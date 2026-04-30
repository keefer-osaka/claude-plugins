#!/usr/bin/env python3
"""
normalize_transcripts_tz.py — 將 transcripts/ 內所有 transcript 的時間欄位標準化到 VAULT_TZ。

三個 pass：
1. Pass 1: 掃 transcripts/*.md，必要時改寫 frontmatter 與 body heading 時間，寫入 tz_normalized: true
2. Pass 2: 掃 wiki/**/*.md，重算 sources block 的 date: 欄位
3. Pass 3: 掃 wiki/**/*.md，蒐集跨日 wikilink rot 候選，輸出 _schema/wikilink_rot_candidates.json
   （wikilink 本身不在此修改 — 由 F3.2 repair_filename_mojibake.py 串接消費）

CLI：
  --dry-run            預設，不寫入任何檔案
  --apply              實際寫入；每個被改的檔案會留一份 .bak.<ts> 備份
  --only <author>      只處理指定 author 的 transcript
  --include-unlabeled  body heading 為裸時間時，補上 VAULT_TZ_LABEL（不變更時值）

執行：
  python3 .../normalize_transcripts_tz.py [--apply] [--only keefer] [--include-unlabeled]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# ── wiki_utils import ────────────────────────────────────────────────────────
sys.path.insert(
    0,
    os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")
    ),
)
from wiki_utils import (  # noqa: E402
    VAULT_TZ,
    VAULT_TZ_LABEL,
    VAULT_TZ_OFFSET,
    parse_frontmatter,
    parse_ts_loose,
    resolve_vault_dir,
)

# ── 常數 ─────────────────────────────────────────────────────────────────────

VAULT_DIR = resolve_vault_dir(__file__)
TRANSCRIPTS_DIR = Path(VAULT_DIR) / "transcripts"
WIKI_DIR = Path(VAULT_DIR) / "wiki"
SCHEMA_DIR = Path(VAULT_DIR) / "_schema"

# Match heading lines like:  "## User (2026-04-11 14:19)" or
#                            "## Assistant (2026-04-11 14:19 UTC+9)"
HEADING_RE = re.compile(r"^(##\s+(?:User|Assistant)\s+\()([^)]+)(\))\s*$")

# Wikilink with date prefix: [[YYYY-MM-DD-...]]
DATE_WIKILINK_RE = re.compile(r"\[\[(\d{4}-\d{2}-\d{2}-[^\]]+)\]\]")

# ISO with literal numeric offset (+HH:MM or -HH:MM); excludes "Z"
ISO_WITH_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?[+-]\d{2}:\d{2}$"
)


def iso_with_offset(dt: datetime) -> str:
    """Return ISO with `+HH:MM` (or `-HH:MM`) offset, never `Z`."""
    s = dt.isoformat()
    if s.endswith("+00:00"):
        return s
    return s


def offset_to_label(dt: datetime) -> str:
    """datetime aware → 'UTC+N' / 'UTC-N' label (whole-hour preferred, fallback HH:MM)."""
    off = dt.utcoffset()
    if off is None:
        return ""
    total_minutes = int(off.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    h, m = divmod(total_minutes, 60)
    if m == 0:
        return f"UTC{sign}{h}"
    return f"UTC{sign}{h:02d}:{m:02d}"


# ── Frontmatter 處理（surgical line-edit，避免 lossy round-trip）─────────────

def _replace_fm_value(fm_text: str, key: str, new_value: str) -> tuple[str, bool]:
    """Return (new_fm_text, changed)."""
    pattern = re.compile(rf"^({re.escape(key)}:\s*)(.*)$", re.MULTILINE)
    m = pattern.search(fm_text)
    if not m:
        return fm_text, False
    if m.group(2).strip() == new_value.strip():
        return fm_text, False
    new_fm = pattern.sub(lambda mm: f"{mm.group(1)}{new_value}", fm_text, count=1)
    return new_fm, True


def _has_top_level_key(fm_text: str, key: str) -> bool:
    pattern = re.compile(rf"^{re.escape(key)}:\s", re.MULTILINE)
    return bool(pattern.search(fm_text))


def _append_fm_key(fm_text: str, key: str, value: str) -> str:
    """Append `key: value` to the end of the frontmatter block."""
    if fm_text and not fm_text.endswith("\n"):
        fm_text = fm_text + "\n"
    return f"{fm_text}{key}: {value}"


def _split_frontmatter(text: str) -> tuple[str, str, str] | None:
    """Return (prefix, fm_inner, body) where prefix='---\n' and fm_inner ends without trailing newline.
    Returns None if no frontmatter."""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm_inner = text[3:end]
    if fm_inner.startswith("\n"):
        fm_inner = fm_inner[1:]
    if fm_inner.endswith("\n"):
        fm_inner = fm_inner[:-1]
    body = text[end + 4:]
    if body.startswith("\n"):
        body = body[1:]
    return ("---\n", fm_inner, body)


def _rebuild_with_fm(fm_inner: str, body: str) -> str:
    if fm_inner and not fm_inner.endswith("\n"):
        fm_inner = fm_inner + "\n"
    return f"---\n{fm_inner}---\n{body}"


# ── Atomic write ─────────────────────────────────────────────────────────────

def atomic_write(path: Path, new_content: str, *, backup_ts: str) -> None:
    """Write `new_content` to `path` atomically; preserve original as `<path>.bak.<ts>`."""
    if path.exists():
        backup = path.with_suffix(path.suffix + f".bak.{backup_ts}")
        backup.write_bytes(path.read_bytes())

    tmp_fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(new_content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


# ── Pass 1：transcript normalization ─────────────────────────────────────────

def _detect_first_offset_label(*, fm: dict, body: str) -> str | None:
    """Look for an explicit non-VAULT, non-UTC display TZ marker.

    Source of truth is body headings (display format) — frontmatter timestamps
    are wire format and almost always UTC ('Z'), so tagging every transcript
    with `original_tz: UTC+0` would pollute the audit field.
    """
    for line in body.splitlines():
        m = HEADING_RE.match(line)
        if not m:
            continue
        inner = m.group(2)
        if "UTC" not in inner.upper():
            continue
        dt = parse_ts_loose(inner)
        if dt is None or dt.tzinfo is None:
            continue
        label = offset_to_label(dt)
        if label and label != VAULT_TZ_LABEL:
            return label
    return None


def _heading_needs_rewrite(inner: str, *, include_unlabeled: bool) -> bool:
    """Return True if heading inner string needs to be normalized."""
    has_label = bool(
        "UTC" in inner.upper()
        or inner.endswith("Z")
        or re.search(r"[+-]\d{2}:\d{2}$", inner)
    )
    if not has_label:
        return include_unlabeled

    dt = parse_ts_loose(inner)
    if dt is None:
        return False
    label = offset_to_label(dt)
    return label != VAULT_TZ_LABEL


def _rewrite_heading_inner(inner: str) -> str:
    dt = parse_ts_loose(inner)
    if dt is None:
        return inner
    local = dt.astimezone(VAULT_TZ)
    return f"{local.strftime('%Y-%m-%d %H:%M')} {VAULT_TZ_LABEL}"


def _process_transcript(
    path: Path,
    *,
    apply: bool,
    include_unlabeled: bool,
    only_author: str | None,
    backup_ts: str,
) -> dict:
    """Return a result dict describing the action taken / planned."""
    text = path.read_text(encoding="utf-8")
    split = _split_frontmatter(text)
    if split is None:
        return {"path": str(path), "action": "skip", "reason": "no_frontmatter"}
    prefix, fm_inner, body = split

    fm, _ = parse_frontmatter(text)

    if only_author and str(fm.get("author", "")).strip() != only_author:
        return {"path": str(path), "action": "skip", "reason": "author_filter"}

    if str(fm.get("tz_normalized", "")).strip().lower() == "true":
        return {"path": str(path), "action": "skip", "reason": "already_normalized"}

    # ── Detection ──
    needs_fm_reformat = False
    new_first_ts = None
    new_last_ts = None
    new_date = None
    old_date = str(fm.get("date", "")).strip() or None

    for key, target in (("first_ts", "first"), ("last_ts", "last")):
        raw = str(fm.get(key, "")).strip()
        if not raw:
            continue
        if ISO_WITH_OFFSET_RE.match(raw):
            continue
        dt = parse_ts_loose(raw)
        if dt is None:
            continue
        local = dt.astimezone(VAULT_TZ)
        new_iso = iso_with_offset(local)
        if target == "first":
            new_first_ts = (raw, new_iso)
        else:
            new_last_ts = (raw, new_iso)
        needs_fm_reformat = True

    # New date: derive from new_first_ts (or new_last_ts) in VAULT_TZ.
    src_for_date = None
    for cand in (new_first_ts, new_last_ts):
        if cand is not None:
            src_for_date = cand[1]
            break
    if src_for_date is None:
        # fall back to existing first_ts/last_ts already in VAULT_TZ form
        for key in ("first_ts", "last_ts"):
            raw = str(fm.get(key, "")).strip()
            if raw:
                dt = parse_ts_loose(raw)
                if dt is not None:
                    src_for_date = iso_with_offset(dt.astimezone(VAULT_TZ))
                    break
    if src_for_date is not None:
        derived_date = src_for_date[:10]
        if old_date and derived_date != old_date:
            new_date = derived_date

    # ── Body heading rewrites ──
    body_changed = False
    new_body_lines: list[str] = []
    cross_day_warnings: list[str] = []

    for line in body.splitlines(keepends=False):
        m = HEADING_RE.match(line)
        if not m:
            new_body_lines.append(line)
            continue
        inner = m.group(2)
        if _heading_needs_rewrite(inner, include_unlabeled=include_unlabeled):
            new_inner = _rewrite_heading_inner(inner)
            new_line = f"{m.group(1)}{new_inner}{m.group(3)}"
            if new_line != line:
                body_changed = True
                # cross-day detection
                old_d = inner[:10] if re.match(r"\d{4}-\d{2}-\d{2}", inner) else None
                new_d = new_inner[:10]
                if old_d and old_d != new_d:
                    cross_day_warnings.append(f"{old_d} -> {new_d}: {line.strip()}")
            new_body_lines.append(new_line)
        else:
            new_body_lines.append(line)

    new_body = "\n".join(new_body_lines)
    if body.endswith("\n") and not new_body.endswith("\n"):
        new_body = new_body + "\n"

    # ── Detect original_tz for audit (only meaningful if non-VAULT) ──
    orig_label = _detect_first_offset_label(fm=fm, body=body)

    # ── If nothing actually changed AND already labeled, skip ──
    will_change = (
        needs_fm_reformat
        or body_changed
        or new_date is not None
        or not _has_top_level_key(fm_inner, "tz_normalized")
        or (orig_label and not _has_top_level_key(fm_inner, "original_tz"))
    )
    if not will_change:
        return {"path": str(path), "action": "skip", "reason": "no_change_needed"}

    # ── Apply surgical frontmatter edits ──
    new_fm_inner = fm_inner

    if new_first_ts is not None:
        new_fm_inner, _ = _replace_fm_value(new_fm_inner, "first_ts", new_first_ts[1])
    if new_last_ts is not None:
        new_fm_inner, _ = _replace_fm_value(new_fm_inner, "last_ts", new_last_ts[1])
    if new_date is not None:
        new_fm_inner, _ = _replace_fm_value(new_fm_inner, "date", new_date)

    if not _has_top_level_key(new_fm_inner, "tz_normalized"):
        new_fm_inner = _append_fm_key(new_fm_inner, "tz_normalized", "true")
    else:
        new_fm_inner, _ = _replace_fm_value(new_fm_inner, "tz_normalized", "true")

    if orig_label and not _has_top_level_key(new_fm_inner, "original_tz"):
        new_fm_inner = _append_fm_key(new_fm_inner, "original_tz", orig_label)

    new_text = _rebuild_with_fm(new_fm_inner, new_body)
    if not text.endswith("\n") and new_text.endswith("\n"):
        new_text = new_text.rstrip("\n")

    result: dict = {
        "path": str(path),
        "action": "rewrite",
        "first_ts_changed": new_first_ts is not None,
        "last_ts_changed": new_last_ts is not None,
        "date_changed": new_date is not None,
        "old_date": old_date,
        "new_date": new_date,
        "body_headings_changed": body_changed,
        "original_tz": orig_label,
        "cross_day_warnings": cross_day_warnings,
    }

    if apply:
        atomic_write(path, new_text, backup_ts=backup_ts)
        result["written"] = True
    else:
        result["written"] = False

    if cross_day_warnings:
        msg = f"[WARN] cross-day shift in {path.name}: {len(cross_day_warnings)} heading(s)"
        print(msg, file=sys.stderr)
        if old_date and new_date:
            print(f"       date: {old_date} -> {new_date}", file=sys.stderr)

    return result


# ── Pass 2：wiki sources date 重算 ───────────────────────────────────────────

# Match a sources block entry's date line:  "    date: 2026-04-15"
SOURCE_DATE_RE = re.compile(r"^(\s+date:\s*)(\S+)\s*$")
# Match the start of a source list item:  "  - session: <id>"
SOURCE_ENTRY_RE = re.compile(r"^\s+- session:\s*(\S+)")


def _build_session_date_map(planned_overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Read transcripts/*.md frontmatter to map session_id → date.

    `planned_overrides` (session_id → new_date) lets dry-run see what apply WOULD
    write, so Pass 2's preview reflects Pass 1's planned changes.
    """
    out: dict[str, str] = {}
    for md in TRANSCRIPTS_DIR.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _ = parse_frontmatter(text)
        sid = str(fm.get("session_id", "")).strip()
        date = str(fm.get("date", "")).strip()
        if sid and date:
            out[sid] = date
    if planned_overrides:
        out.update(planned_overrides)
    return out


def _process_wiki_dates(
    *, apply: bool, backup_ts: str, session_dates: dict[str, str]
) -> list[dict]:
    """Pass 2: rewrite `date:` inside source blocks when transcript's date differs."""
    results: list[dict] = []
    for md in WIKI_DIR.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        split = _split_frontmatter(text)
        if split is None:
            continue
        prefix, fm_inner, body = split

        # Walk fm_inner line by line; track current source's session id.
        lines = fm_inner.splitlines(keepends=False)
        new_lines: list[str] = []
        current_session: str | None = None
        changed = False
        per_file_changes: list[tuple[str, str, str]] = []  # (session, old_date, new_date)

        for line in lines:
            m_session = SOURCE_ENTRY_RE.match(line)
            if m_session:
                current_session = m_session.group(1)
                new_lines.append(line)
                continue

            m_date = SOURCE_DATE_RE.match(line)
            if m_date and current_session:
                old_d = m_date.group(2)
                new_d = session_dates.get(current_session)
                if new_d and new_d != old_d:
                    new_lines.append(f"{m_date.group(1)}{new_d}")
                    changed = True
                    per_file_changes.append((current_session, old_d, new_d))
                    continue
            new_lines.append(line)

        if not changed:
            continue

        new_fm_inner = "\n".join(new_lines)
        new_text = _rebuild_with_fm(new_fm_inner, body)
        if not text.endswith("\n") and new_text.endswith("\n"):
            new_text = new_text.rstrip("\n")

        results.append(
            {"path": str(md), "changes": per_file_changes, "written": apply}
        )
        if apply:
            atomic_write(md, new_text, backup_ts=backup_ts)

    return results


# ── Pass 3：wikilink rot 候選蒐集 ────────────────────────────────────────────

def _process_wikilink_rot(
    *, transcript_date_map: dict[str, tuple[str, str]]
) -> list[dict]:
    """transcript_date_map: session_id → (old_date, new_date) for cross-day shifts.

    Pass 3 ONLY emits the JSON candidate list. F3.2 is responsible for actually
    rewriting wikilinks (post-rename), so we never mutate wiki/ markdown here.
    """
    if not transcript_date_map:
        return []

    # Build {old_link_stem -> new_link_stem} by inspecting transcript files.
    stem_map: dict[str, str] = {}
    for md in TRANSCRIPTS_DIR.glob("*.md"):
        stem = md.stem
        if not re.match(r"\d{4}-\d{2}-\d{2}-", stem):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _ = parse_frontmatter(text)
        sid = str(fm.get("session_id", "")).strip()
        if not sid or sid not in transcript_date_map:
            continue
        old_date, new_date = transcript_date_map[sid]
        if old_date == new_date:
            continue
        # Only consider this stem if its current prefix matches the OLD date
        # (no rename has happened yet — the transcript file still uses old prefix).
        if stem.startswith(old_date + "-"):
            new_stem = new_date + stem[len(old_date):]
            stem_map[stem] = new_stem

    if not stem_map:
        return []

    candidates: list[dict] = []
    for md in WIKI_DIR.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in DATE_WIKILINK_RE.finditer(line):
                target = m.group(1)
                if target in stem_map:
                    candidates.append(
                        {
                            "old_link": f"[[{target}]]",
                            "new_link": f"[[{stem_map[target]}]]",
                            "wiki_file": str(md.relative_to(VAULT_DIR)),
                            "line_no": lineno,
                        }
                    )
    return candidates


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually write changes (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit dry-run (default behavior)")
    ap.add_argument("--only", metavar="AUTHOR", help="restrict to transcripts whose author matches")
    ap.add_argument("--include-unlabeled", action="store_true",
                    help="also rewrite body headings that lack a TZ label (adds VAULT_TZ_LABEL)")
    args = ap.parse_args()

    apply = bool(args.apply) and not args.dry_run
    backup_ts = datetime.now(VAULT_TZ).strftime("%Y%m%d-%H%M%S")

    if not TRANSCRIPTS_DIR.is_dir():
        print(f"[ERR] transcripts dir not found: {TRANSCRIPTS_DIR}", file=sys.stderr)
        return 1

    # ── Pass 1 ──
    pass1_results: list[dict] = []
    cross_day_session_map: dict[str, tuple[str, str]] = {}
    planned_date_overrides: dict[str, str] = {}
    for md in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        try:
            r = _process_transcript(
                md,
                apply=apply,
                include_unlabeled=args.include_unlabeled,
                only_author=args.only,
                backup_ts=backup_ts,
            )
        except Exception as e:
            print(f"[ERR] {md}: {e}", file=sys.stderr)
            continue
        pass1_results.append(r)
        if r.get("date_changed"):
            try:
                fm, _ = parse_frontmatter(md.read_text(encoding="utf-8"))
                sid = str(fm.get("session_id", "")).strip()
                if sid and r.get("old_date") and r.get("new_date"):
                    cross_day_session_map[sid] = (r["old_date"], r["new_date"])
                    planned_date_overrides[sid] = r["new_date"]
            except Exception:
                pass

    # ── Pass 2 ── (wiki sources date) — uses planned overrides so dry-run mirrors apply
    session_dates = _build_session_date_map(planned_overrides=planned_date_overrides)
    pass2_results = _process_wiki_dates(
        apply=apply, backup_ts=backup_ts, session_dates=session_dates
    )

    # ── Pass 3 ── (wikilink rot candidates → JSON; never mutates wiki/)
    rot_candidates = _process_wikilink_rot(transcript_date_map=cross_day_session_map)
    if rot_candidates:
        SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = SCHEMA_DIR / "wikilink_rot_candidates.json"
        # Always emit JSON (both dry-run and apply): F3.2 reads this regardless.
        out_path.write_text(
            json.dumps(rot_candidates, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    # ── Summary ──
    summary = {
        "mode": "apply" if apply else "dry-run",
        "vault_tz_label": VAULT_TZ_LABEL,
        "vault_tz_offset": VAULT_TZ_OFFSET,
        "include_unlabeled": bool(args.include_unlabeled),
        "only_author": args.only,
        "transcripts": {
            "total": len(pass1_results),
            "rewrite": sum(1 for r in pass1_results if r.get("action") == "rewrite"),
            "skip_already_normalized": sum(
                1 for r in pass1_results if r.get("reason") == "already_normalized"
            ),
            "skip_no_change": sum(
                1 for r in pass1_results if r.get("reason") == "no_change_needed"
            ),
            "skip_author_filter": sum(
                1 for r in pass1_results if r.get("reason") == "author_filter"
            ),
            "cross_day_shifts": len(cross_day_session_map),
        },
        "wiki_sources_date": {
            "files_changed": len(pass2_results),
            "total_date_edits": sum(len(r["changes"]) for r in pass2_results),
        },
        "wikilink_rot_candidates": len(rot_candidates),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
