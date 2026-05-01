#!/usr/bin/env python3
"""
repair_filename_mojibake.py — crash-safe repair of mojibake transcript filenames
and (optionally) canonicalization of date prefixes from frontmatter `first_ts`.

Two phases (independent flags):
- `--fix-mojibake` (default ON): repair cp437→utf-8 mojibake in session_id /
  transcript filenames. cp437→utf-8 only touches non-ASCII bytes, so the date
  prefix (e.g. `0000-00-00-`) and the SID's leading hex / underscore portion
  stay intact.
- `--canonicalize-date` (default OFF): rebuild filename via
  `make_transcript_filename(first_ts, session_id, title)` (transcript_utils).
  Pre-flight requires every transcript frontmatter to carry `tz_normalized: true`
  (written by `normalize_transcripts_tz.py`); otherwise refuse to run.

State machine — `_schema/repair_manifest.json`:

    {
      "schema_version": 1,
      "manifest_id": "<ISO8601_ts>",
      "wiki_pages": {
        "<rel_path>": {"pre_hash": "...", "post_hash": "...", "status": "pending|done"}
      },
      "<original_sid>": {
        "corrected_sid": "<utf8_sid>",
        "steps": {
          "rename_session_key":              "pending|done",
          "rewrite_md_content":              "pending|done",
          "rename_md_file":                  "pending|done",
          "update_wiki_index":               "pending|done",
          "update_wiki_pages":               "pending|done",
          "update_wikilinks_after_canonicalize": "pending|done"
        },
        "original_transcript_path":  "...",
        "corrected_transcript_path": "..."
      }
    }

Each step follows: apply artefact (with fsync) → atomic update of the manifest
step to "done". Crash anywhere is recoverable via `--resume`; idempotency comes
from "is the artefact already shaped like the target?" probes (filename exists,
session-key already utf-8, etc.).

CLI:
    --dry-run               (default) plan only, no writes
    --apply                 actually mutate
    --include-content       also rewrite mojibake inside transcript .md content
                            (frontmatter session_id, body heading, delta marker
                             if it embeds the SID — body may legitimately differ
                             from filename; default OFF, conservative).
    --fix-mojibake          (default ON; pass `--no-fix-mojibake` to disable)
    --canonicalize-date     (default OFF) rebuild filename from first_ts
    --resume                pick up an interrupted run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── _lib + sibling-script imports ─────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILLS_DIR = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_SKILLS_DIR / "_lib"))
sys.path.insert(0, str(_SCRIPT_DIR))

from wiki_utils import (  # noqa: E402
    parse_frontmatter,
    resolve_vault_dir,
)
from transcript_utils import make_transcript_filename  # noqa: E402

# ── Paths ─────────────────────────────────────────────────────────────────────

VAULT_DIR = Path(resolve_vault_dir(__file__))
TRANSCRIPTS_DIR = VAULT_DIR / "transcripts"
WIKI_DIR = VAULT_DIR / "wiki"
SCHEMA_DIR = VAULT_DIR / "_schema"
SESSIONS_JSON = SCHEMA_DIR / "sessions.json"
WIKI_INDEX_JSON = SCHEMA_DIR / "wiki_index.json"
MANIFEST_PATH = SCHEMA_DIR / "repair_manifest.json"

# ── Regex / constants ─────────────────────────────────────────────────────────

# Latin-1 noise typical of cp437-rendered utf-8 (µ ë ï σ è φ Φ τ Θ etc.)
_LATIN1_NOISE_RE = re.compile(
    r"[µëïσèφΦτΘñ╝╗╣║╠╬╝₧╜╗┐└┴┬├┼─│]+"
)
_CJK_RE = re.compile(r"[㐀-䶿一-鿿]")
_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")

STEP_KEYS = (
    "rename_session_key",
    "rewrite_md_content",
    "rename_md_file",
    "update_wiki_index",
    "update_wiki_pages",
    "update_wikilinks_after_canonicalize",
)


# ── Atomic file utilities ─────────────────────────────────────────────────────

def _atomic_write_text(path: Path, content: str) -> None:
    """Write text to *path* atomically (tmp file + fsync + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_json(path: Path, data) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Mojibake detection / repair ───────────────────────────────────────────────

def _try_repair_cp437(name: str) -> str | None:
    """Three-pronged AND gate. Returns repaired name or None.

    (a) `name.encode('cp437').decode('utf-8')` succeeds without exception
    (b) the result contains ≥1 CJK character
    (c) the original contains Latin-1 noise typical of cp437 renders

    Pure-ASCII names short-circuit None (cp437 round-trip yields the same
    string and contains no CJK).
    """
    if not name:
        return None
    if not _LATIN1_NOISE_RE.search(name):
        return None
    try:
        repaired = name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None
    if repaired == name:
        return None
    if not _CJK_RE.search(repaired):
        return None
    return repaired


# ── Manifest helpers ──────────────────────────────────────────────────────────

def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        bak = path.with_suffix(path.suffix + f".corrupt.{_now_iso()}")
        shutil.copy2(path, bak)
        raise SystemExit(
            f"[FATAL] repair_manifest.json is corrupt: {e}\n"
            f"        a copy was preserved at {bak}\n"
            f"        manual inspection required; refusing auto-resume."
        ) from e


def _save_manifest(manifest: dict) -> None:
    _atomic_write_json(MANIFEST_PATH, manifest)


def _mark_step(manifest: dict, sid: str, step: str) -> None:
    manifest[sid]["steps"][step] = "done"
    _save_manifest(manifest)


def _mark_wiki_page(manifest: dict, rel_path: str, *, post_hash: str) -> None:
    manifest.setdefault("wiki_pages", {})
    page = manifest["wiki_pages"].setdefault(
        rel_path, {"pre_hash": "", "post_hash": "", "status": "pending"}
    )
    page["post_hash"] = post_hash
    page["status"] = "done"
    _save_manifest(manifest)


def _new_manifest_skeleton() -> dict:
    return {
        "schema_version": 1,
        "manifest_id": _now_iso(),
        "wiki_pages": {},
    }


def _is_steps_complete(entry: dict, *, applicable: set[str]) -> bool:
    steps = entry.get("steps", {})
    return all(steps.get(k) == "done" for k in applicable)


# ── Pre-flight: tz_normalized check (canonicalize-date mode only) ─────────────

def _check_tz_normalized() -> list[Path]:
    """Return list of transcripts missing `tz_normalized: true` in frontmatter."""
    missing: list[Path] = []
    if not TRANSCRIPTS_DIR.is_dir():
        return missing
    for md in sorted(TRANSCRIPTS_DIR.glob("*.md")):
        if md.name == "_index.md":
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            missing.append(md)
            continue
        fm, _ = parse_frontmatter(text)
        if str(fm.get("tz_normalized", "")).strip().lower() != "true":
            missing.append(md)
    return missing


# ── Phase 1 — build mojibake rename map ───────────────────────────────────────

def _build_mojibake_map(sessions: dict) -> tuple[dict[str, str], list[str]]:
    """Return ({old_sid → new_sid}, conflicts).

    A SID enters the map iff it passes the three-pronged mojibake gate.
    Cross-author conflicts: if two old SIDs collapse to the same new SID with
    different `author` values in sessions.json, append a human-readable
    description to `conflicts` (caller exits non-zero).
    """
    sid_map: dict[str, str] = {}
    reverse: dict[str, list[tuple[str, str]]] = {}
    conflicts: list[str] = []

    for old_sid, entry in sessions.items():
        new_sid = _try_repair_cp437(old_sid)
        if not new_sid:
            continue
        if new_sid == old_sid:
            continue
        sid_map[old_sid] = new_sid
        author = str(entry.get("author", "")).strip() if isinstance(entry, dict) else ""
        reverse.setdefault(new_sid, []).append((old_sid, author))

    for new_sid, owners in reverse.items():
        authors = {a for _, a in owners if a}
        if len(authors) > 1:
            conflicts.append(
                f"corrected SID {new_sid!r} would collapse rows with conflicting "
                f"authors {sorted(authors)}: " + ", ".join(o for o, _ in owners)
            )

    return sid_map, conflicts


def _build_file_rename_map(
    sid_map: dict[str, str],
    sessions: dict,
) -> dict[Path, Path]:
    """For each repaired SID, plan the .md file rename.

    Strategy:
    1. Look up `sessions[old_sid]['transcript_path']` (relative path) — that is
       the canonical file location for that SID.
    2. Substitute the *exact* old SID substring in the basename with the new
       SID; if the substring is absent, fall back to cp437→utf-8 repairing the
       whole basename (covers cases where the filename embeds different
       mojibake than the SID itself).
    """
    file_map: dict[Path, Path] = {}
    for old_sid, new_sid in sid_map.items():
        entry = sessions.get(old_sid, {})
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("transcript_path", "")).strip()
        if not rel:
            continue
        old_path = VAULT_DIR / rel
        if not old_path.is_file():
            # File missing — leave to summary; do not crash here.
            continue
        old_name = old_path.name
        if old_sid in old_name:
            new_name = old_name.replace(old_sid, new_sid)
        else:
            repaired_name = _try_repair_cp437(old_name)
            new_name = repaired_name or old_name
        if new_name == old_name:
            continue
        new_path = old_path.with_name(new_name)
        file_map[old_path] = new_path
    return file_map


# ── Phase 1 — content rewrite (transcript file body) ──────────────────────────

def _rewrite_transcript_content(path: Path, old_sid: str, new_sid: str) -> bool:
    """Replace literal occurrences of old_sid with new_sid in the transcript file.

    Returns True if file was rewritten, False if no change. Atomic write.
    """
    text = path.read_text(encoding="utf-8")
    if old_sid not in text:
        return False
    new_text = text.replace(old_sid, new_sid)
    if new_text == text:
        return False
    _atomic_write_text(path, new_text)
    return True


# ── Phase 1 — sessions.json batch rewrite ─────────────────────────────────────

def _rewrite_sessions_json(
    sessions: dict,
    sid_map: dict[str, str],
    file_renames: dict[Path, Path],
) -> dict:
    """Return a new sessions dict with keys remapped and transcript_path updated."""
    new_sessions: dict = {}
    rel_renames = {
        str(old.relative_to(VAULT_DIR)): str(new.relative_to(VAULT_DIR))
        for old, new in file_renames.items()
    }
    for sid, entry in sessions.items():
        new_sid = sid_map.get(sid, sid)
        new_entry = dict(entry) if isinstance(entry, dict) else entry
        if isinstance(new_entry, dict):
            tp = str(new_entry.get("transcript_path", ""))
            if tp in rel_renames:
                new_entry["transcript_path"] = rel_renames[tp]
        new_sessions[new_sid] = new_entry
    return new_sessions


# ── Phase 1 — wiki_index.json rewrite ─────────────────────────────────────────

def _rewrite_wiki_index(wiki_index: dict, sid_map: dict[str, str]) -> dict:
    """Remap session_to_wiki keys via sid_map (values untouched in phase 1)."""
    new_index = dict(wiki_index)
    s2w = wiki_index.get("session_to_wiki", {})
    new_s2w: dict = {}
    for sid, paths in s2w.items():
        new_sid = sid_map.get(sid, sid)
        if new_sid in new_s2w:
            existing = list(new_s2w[new_sid])
            for p in paths:
                if p not in existing:
                    existing.append(p)
            new_s2w[new_sid] = existing
        else:
            new_s2w[new_sid] = list(paths)
    new_index["session_to_wiki"] = new_s2w
    return new_index


# ── Phase 1 — wiki page rewrite (sources block + transcripts list) ────────────

def _rewrite_wiki_pages(
    sid_map: dict[str, str],
    stem_map: dict[str, str],
    *,
    apply: bool,
    manifest: dict,
) -> list[dict]:
    """For each wiki/*.md, replace literal `[[old_stem]]` and `- session: <old>`.

    Idempotency contract:
    - SID literal substitution uses anchored line match `^(\\s+- session:\\s*)<old>$`
      so unrelated text isn't touched.
    - wikilink substitution matches `[[<old_stem>]]` exactly and refuses to run
      if any new_stem is a strict prefix of an existing old_stem in stem_map
      (would cause cascading rewrites).
    """
    # Prefix-conflict guard
    for old, new in stem_map.items():
        for other in stem_map:
            if other != old and other.startswith(new):
                raise SystemExit(
                    f"[FATAL] new stem {new!r} is a prefix of another old stem "
                    f"{other!r}; refusing to rewrite wikilinks."
                )

    results: list[dict] = []
    if not WIKI_DIR.is_dir():
        return results
    for md in sorted(WIKI_DIR.rglob("*.md")):
        try:
            original = md.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] read {md}: {e}", file=sys.stderr)
            continue
        new_text = original
        # SID substitution (sources block lines)
        for old_sid, new_sid in sid_map.items():
            new_text = re.sub(
                rf"^(\s+- session:\s*){re.escape(old_sid)}\s*$",
                rf"\g<1>{new_sid}",
                new_text,
                flags=re.MULTILINE,
            )
        # Stem substitution (wikilinks)
        for old_stem, new_stem in stem_map.items():
            new_text = new_text.replace(f"[[{old_stem}]]", f"[[{new_stem}]]")

        if new_text == original:
            continue

        rel = str(md.relative_to(VAULT_DIR))
        pre_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
        post_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
        results.append(
            {
                "wiki_file": rel,
                "pre_hash": pre_hash,
                "post_hash": post_hash,
            }
        )

        if apply:
            manifest.setdefault("wiki_pages", {})[rel] = {
                "pre_hash": pre_hash,
                "post_hash": post_hash,
                "status": "pending",
            }
            _save_manifest(manifest)
            _atomic_write_text(md, new_text)
            _mark_wiki_page(manifest, rel, post_hash=post_hash)
    return results


# ── Phase 2 — canonicalize date ───────────────────────────────────────────────

def _build_canonical_rename_map(sessions: dict) -> dict[Path, Path]:
    """For each transcript, compute the canonical filename from frontmatter.

    Uses `make_transcript_filename(first_ts, session_id, title)`. Skips files
    whose current basename already matches the canonical form, or whose
    frontmatter lacks `first_ts`.
    """
    file_map: dict[Path, Path] = {}
    for old_sid, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        rel = str(entry.get("transcript_path", "")).strip()
        if not rel:
            continue
        path = VAULT_DIR / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, _ = parse_frontmatter(text)
        first_ts = str(fm.get("first_ts", "")).strip()
        title = str(fm.get("title", "")).strip()
        if not first_ts:
            continue
        canonical = make_transcript_filename(first_ts, old_sid, title)
        if not canonical or canonical == path.name:
            continue
        file_map[path] = path.with_name(canonical)
    return file_map


def _apply_wikilink_rot_candidates(*, apply: bool, manifest: dict) -> int:
    """Consume `_schema/wikilink_rot_candidates.json` (Pass 3 from
    normalize_transcripts_tz). Returns count of substitutions written.
    """
    rot_path = SCHEMA_DIR / "wikilink_rot_candidates.json"
    if not rot_path.is_file():
        print(
            "[INFO] _schema/wikilink_rot_candidates.json not found; "
            "skipping update_wikilinks_after_canonicalize."
        )
        return 0
    try:
        rot = json.loads(rot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[WARN] wikilink_rot_candidates.json corrupt ({e}); skipping.")
        return 0
    if not rot:
        return 0

    # Group by file
    by_file: dict[str, list[tuple[str, str]]] = {}
    for cand in rot:
        wf = cand.get("wiki_file")
        old_link = cand.get("old_link")
        new_link = cand.get("new_link")
        if not (wf and old_link and new_link):
            continue
        by_file.setdefault(wf, []).append((old_link, new_link))

    written = 0
    for rel, pairs in by_file.items():
        path = VAULT_DIR / rel
        if not path.is_file():
            print(f"[WARN] rot candidate file missing: {rel}", file=sys.stderr)
            continue
        original = path.read_text(encoding="utf-8")
        new_text = original
        for old, new in pairs:
            # Prefix conflict guard within this file's local map.
            for o2, _ in pairs:
                if o2 != old and o2.startswith(new):
                    raise SystemExit(
                        f"[FATAL] new wikilink {new!r} is a prefix of {o2!r} "
                        f"in {rel}; refusing partial rewrite."
                    )
            new_text = new_text.replace(old, new)
        if new_text == original:
            continue
        if apply:
            pre_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()
            post_hash = hashlib.sha256(new_text.encode("utf-8")).hexdigest()
            manifest.setdefault("wiki_pages", {})[rel] = {
                "pre_hash": pre_hash,
                "post_hash": post_hash,
                "status": "pending",
            }
            _save_manifest(manifest)
            _atomic_write_text(path, new_text)
            _mark_wiki_page(manifest, rel, post_hash=post_hash)
        written += sum(1 for old, _ in pairs if old in original)
    return written


# ── Orchestration ─────────────────────────────────────────────────────────────

def _build_stem_map(file_map: dict[Path, Path]) -> dict[str, str]:
    return {old.stem: new.stem for old, new in file_map.items() if old.stem != new.stem}


def _backup(path: Path, ts: str) -> Path | None:
    if not path.is_file():
        return None
    bak = path.with_suffix(path.suffix + f".bak.{ts}")
    shutil.copy2(path, bak)
    return bak


def _ensure_manifest(args, manifest_exists: bool) -> dict:
    if manifest_exists:
        manifest = _load_manifest(MANIFEST_PATH)
        if not args.resume:
            raise SystemExit(
                f"[FATAL] {MANIFEST_PATH} exists (manifest_id="
                f"{manifest.get('manifest_id', '?')!r}). Pass --resume to "
                f"continue, or rename it to <name>.done.<ts> if completed."
            )
        return manifest
    if args.resume:
        raise SystemExit(
            f"[FATAL] --resume requested but no manifest at {MANIFEST_PATH}."
        )
    return _new_manifest_skeleton()


def _populate_phase1_entries(
    manifest: dict,
    sid_map: dict[str, str],
    file_map: dict[Path, Path],
) -> None:
    """Seed manifest with per-SID rows for phase 1 (mojibake)."""
    for old_sid, new_sid in sid_map.items():
        if old_sid in manifest:
            continue  # resume: keep existing per-SID state
        old_path = next(
            (p for p in file_map if p.name and old_sid in str(p)),
            None,
        )
        # Fall back to sessions.json transcript_path if direct probe failed
        original_rel = str(old_path.relative_to(VAULT_DIR)) if old_path else ""
        new_rel = (
            str(file_map[old_path].relative_to(VAULT_DIR)) if old_path else ""
        )
        manifest[old_sid] = {
            "corrected_sid": new_sid,
            "steps": {k: "pending" for k in STEP_KEYS},
            "original_transcript_path": original_rel,
            "corrected_transcript_path": new_rel,
        }


def _run(args) -> int:
    if not args.fix_mojibake and not args.canonicalize_date:
        print("[FATAL] nothing to do: pass --fix-mojibake and/or --canonicalize-date.")
        return 2

    if args.canonicalize_date:
        missing = _check_tz_normalized()
        if missing:
            print(
                f"[FATAL] --canonicalize-date requires every transcript to have "
                f"`tz_normalized: true` in frontmatter. {len(missing)} missing.",
                file=sys.stderr,
            )
            for p in missing[:5]:
                print(f"  - {p.relative_to(VAULT_DIR)}", file=sys.stderr)
            print("Run normalize_transcripts_tz.py --apply first.", file=sys.stderr)
            return 3

    # --skip-if-clean: detect mojibake before touching the manifest.
    # NOTE: `sessions` is loaded after _ensure_manifest below, so we must
    # inline-load here to avoid NameError.
    if getattr(args, "skip_if_clean", False):
        _sessions_tmp = (
            json.loads(SESSIONS_JSON.read_text(encoding="utf-8"))
            if SESSIONS_JSON.is_file() else {}
        )
        _sid_map_tmp, _ = _build_mojibake_map(_sessions_tmp)
        if not _sid_map_tmp:
            print(json.dumps(
                {"mode": "skip-clean", "phase1_sid_renames": 0},
                ensure_ascii=False,
            ))
            return 2  # nothing-to-do; do NOT touch manifest
        # Has mojibake — fall through to normal flow

    manifest_exists = MANIFEST_PATH.is_file()
    manifest = _ensure_manifest(args, manifest_exists)
    apply = bool(args.apply)
    ts = manifest.get("manifest_id") or _now_iso()
    manifest.setdefault("manifest_id", ts)
    manifest.setdefault("schema_version", 1)
    manifest.setdefault("wiki_pages", {})

    if apply and not manifest_exists:
        # Step 1: persist skeleton before any artefact write
        _save_manifest(manifest)
        # Step 2: backup snapshots
        _backup(SESSIONS_JSON, ts)
        _backup(WIKI_INDEX_JSON, ts)

    # Load current snapshots
    sessions = json.loads(SESSIONS_JSON.read_text(encoding="utf-8")) if SESSIONS_JSON.is_file() else {}
    wiki_index = (
        json.loads(WIKI_INDEX_JSON.read_text(encoding="utf-8"))
        if WIKI_INDEX_JSON.is_file()
        else {"schema_version": 1, "session_to_wiki": {}}
    )

    summary: dict = {
        "mode": "apply" if apply else "dry-run",
        "manifest_id": ts,
        "fix_mojibake": bool(args.fix_mojibake),
        "canonicalize_date": bool(args.canonicalize_date),
        "include_content": bool(args.include_content),
        "phase1_sid_renames": 0,
        "phase1_file_renames": 0,
        "phase1_wiki_pages_changed": 0,
        "phase2_file_renames": 0,
        "phase2_wikilink_substitutions": 0,
        "conflicts": [],
        "warnings": [],
    }

    # ── Phase 1: --fix-mojibake ───────────────────────────────────────────────
    if args.fix_mojibake:
        sid_map, conflicts = _build_mojibake_map(sessions)
        if conflicts:
            summary["conflicts"] = conflicts
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            print(
                "[FATAL] cross-author conflicts detected; refusing to repair.",
                file=sys.stderr,
            )
            return 4
        file_map = _build_file_rename_map(sid_map, sessions)
        stem_map = _build_stem_map(file_map)

        # Surface SIDs whose filename can't be repaired by cp437 round-trip
        # (commonly truncated mid-multibyte). Filename rebuild is the job of
        # --canonicalize-date, not --fix-mojibake.
        for old_sid, new_sid in sid_map.items():
            sess_entry = sessions.get(old_sid, {})
            if not isinstance(sess_entry, dict):
                continue
            rel = str(sess_entry.get("transcript_path", "")).strip()
            old_path = VAULT_DIR / rel if rel else None
            if old_path and old_path in file_map:
                continue
            summary["warnings"].append(
                {
                    "sid": old_sid,
                    "corrected_sid": new_sid,
                    "original_path": rel,
                    "reason": (
                        "filename mojibake unrecoverable via cp437→utf-8 "
                        "(likely truncated mid-multibyte); defer rename to "
                        "--canonicalize-date after normalize_transcripts_tz"
                    ),
                }
            )

        summary["phase1_sid_renames"] = len(sid_map)
        summary["phase1_file_renames"] = len(file_map)
        summary["phase1_filename_unrecoverable"] = len(sid_map) - len(file_map)

        if apply:
            _populate_phase1_entries(manifest, sid_map, file_map)
            _save_manifest(manifest)

            # Step 3: rewrite transcript content + rename file
            for old_sid, new_sid in sid_map.items():
                entry = manifest.get(old_sid, {})
                old_rel = entry.get("original_transcript_path", "")
                new_rel = entry.get("corrected_transcript_path", "")
                if not old_rel or not new_rel:
                    continue
                old_path = VAULT_DIR / old_rel
                new_path = VAULT_DIR / new_rel

                steps = entry["steps"]

                # rewrite_md_content (idempotent: only changes if old_sid in body)
                if steps.get("rewrite_md_content") != "done":
                    if args.include_content and old_path.is_file():
                        _rewrite_transcript_content(old_path, old_sid, new_sid)
                    _mark_step(manifest, old_sid, "rewrite_md_content")

                # rename_md_file (idempotent)
                if steps.get("rename_md_file") != "done":
                    if new_path.exists() and not old_path.exists():
                        # already renamed
                        pass
                    elif old_path.is_file():
                        new_path.parent.mkdir(parents=True, exist_ok=True)
                        os.rename(old_path, new_path)
                    _mark_step(manifest, old_sid, "rename_md_file")

            # Step 4: sessions.json batch rewrite
            new_sessions = _rewrite_sessions_json(sessions, sid_map, file_map)
            _atomic_write_json(SESSIONS_JSON, new_sessions)
            sessions = new_sessions
            for old_sid in sid_map:
                _mark_step(manifest, old_sid, "rename_session_key")

            # Step 5: wiki_index.json rewrite
            new_wiki_index = _rewrite_wiki_index(wiki_index, sid_map)
            _atomic_write_json(WIKI_INDEX_JSON, new_wiki_index)
            wiki_index = new_wiki_index
            for old_sid in sid_map:
                _mark_step(manifest, old_sid, "update_wiki_index")

            # Step 6: wiki page rewrite
            wiki_changes = _rewrite_wiki_pages(sid_map, stem_map, apply=True, manifest=manifest)
            for old_sid in sid_map:
                _mark_step(manifest, old_sid, "update_wiki_pages")
            summary["phase1_wiki_pages_changed"] = len(wiki_changes)
        else:
            wiki_changes = _rewrite_wiki_pages(sid_map, stem_map, apply=False, manifest=manifest)
            summary["phase1_wiki_pages_changed"] = len(wiki_changes)

    # ── Phase 2: --canonicalize-date ──────────────────────────────────────────
    if args.canonicalize_date:
        canon_map = _build_canonical_rename_map(sessions)
        summary["phase2_file_renames"] = len(canon_map)

        if apply and canon_map:
            for old_path, new_path in canon_map.items():
                if new_path.exists() and not old_path.exists():
                    continue
                if old_path.is_file():
                    new_path.parent.mkdir(parents=True, exist_ok=True)
                    os.rename(old_path, new_path)
            # patch sessions.json transcript_path
            rel_renames = {
                str(old.relative_to(VAULT_DIR)): str(new.relative_to(VAULT_DIR))
                for old, new in canon_map.items()
            }
            patched = False
            for sid, entry in sessions.items():
                if not isinstance(entry, dict):
                    continue
                tp = str(entry.get("transcript_path", ""))
                if tp in rel_renames:
                    entry["transcript_path"] = rel_renames[tp]
                    patched = True
            if patched:
                _atomic_write_json(SESSIONS_JSON, sessions)

        # Always (apply or not) attempt wikilink_rot consumption — even in
        # dry-run we want a count for the summary.
        subs = _apply_wikilink_rot_candidates(apply=apply, manifest=manifest)
        summary["phase2_wikilink_substitutions"] = subs
        if apply:
            for old_sid in list(manifest.keys()):
                if not isinstance(manifest[old_sid], dict):
                    continue
                if "steps" not in manifest[old_sid]:
                    continue
                _mark_step(manifest, old_sid, "update_wikilinks_after_canonicalize")

    # ── Finalize ──────────────────────────────────────────────────────────────
    if apply and MANIFEST_PATH.is_file():
        done_path = MANIFEST_PATH.with_suffix(MANIFEST_PATH.suffix + f".done.{ts}")
        os.rename(MANIFEST_PATH, done_path)
        summary["manifest_finalized"] = str(done_path.relative_to(VAULT_DIR))

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Crash-safe repair of mojibake transcript filenames.",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--apply", action="store_true")

    p.add_argument("--include-content", action="store_true",
                   help="also rewrite mojibake inside transcript .md content")
    p.add_argument("--fix-mojibake", dest="fix_mojibake", action="store_true",
                   default=True)
    p.add_argument("--no-fix-mojibake", dest="fix_mojibake", action="store_false")
    p.add_argument("--canonicalize-date", action="store_true",
                   help="rebuild filename from frontmatter first_ts")
    p.add_argument("--resume", action="store_true",
                   help="continue from an existing repair_manifest.json")
    p.add_argument(
        "--skip-if-clean",
        dest="skip_if_clean",
        action="store_true",
        help="若 sessions.json 中無 mojibake key，直接 exit 2 不觸碰 manifest。",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.apply:
        args.dry_run = False
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
