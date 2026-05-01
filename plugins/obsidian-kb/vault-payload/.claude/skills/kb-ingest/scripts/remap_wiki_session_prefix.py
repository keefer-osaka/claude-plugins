#!/usr/bin/env python3
"""
remap_wiki_session_prefix.py — wiki source 短前綴改寫為 sessions.json 完整 key。

當 LLM 寫 wiki frontmatter 時，將 mojibake 完整 session_id 自動截斷為乾淨 ASCII
前綴，造成 backfill_wiki_links 無法精確比對。本腳本掃描 wiki/**/*.md，對每個
`- session: <prefix>` 行，依 sessions.json 中的完整 key 做 prefix→full_key 改寫。

四條規則：
  R1 unique-match  : 唯一 candidate 且 != prefix → rewrite
  R2 idempotent    : 唯一 candidate 且 == prefix → unchanged（已是 full key）
  R3 collision     : len(candidates) >= 2 → fail loud（exit 1）
  R4 zero-match    : len(candidates) == 0 → log SKIP（--strict 時 fail loud）

CLI:
  --dry-run   （default）只列計畫，不寫檔
  --apply     實際寫檔（每個 wiki .md 寫前先 backup）
  --json      JSON 輸出（供工具消費）
  --vault PATH  指定 vault root（預設 cwd）
  --strict    R4 zero-match 時 fail loud（pre-apply sanity check 用）
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


_SESSION_LINE_RE = re.compile(r'^(\s+)- session:\s*(\S+)\s*$')


def rewrite_session_line(text: str, prefix: str, full_key: str) -> tuple[str, int]:
    """Replace exactly `- session: <prefix>` lines (with trailing whitespace only).

    Trailing whitespace is matched as `[ \\t]*` (NOT `\\s*`) so that the line
    terminator is preserved across the substitution. `re.MULTILINE` makes `$`
    line-anchored — combined with the `[ \\t]*$` tail this rejects extended
    prefixes (e.g. `<prefix>-extra`) without eating the trailing newline.

    Returns (new_text, n_replacements).
    """
    pattern = rf"^(\s+- session:\s*){re.escape(prefix)}([ \t]*)$"
    new_text, n = re.subn(
        pattern,
        rf"\g<1>{full_key}\g<2>",
        text,
        flags=re.MULTILINE,
    )
    return new_text, n


def find_session_prefixes(text: str) -> list[str]:
    """Return all session prefixes appearing on `- session: <token>` lines (frontmatter only)."""
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end == -1:
        return []
    fm = text[3:end]
    prefixes = []
    for line in fm.splitlines():
        m = _SESSION_LINE_RE.match(line)
        if m:
            prefixes.append(m.group(2))
    return prefixes


def classify(prefix: str, full_keys: list[str], sessions_set: set[str]) -> tuple[str, list[str]]:
    """Return (rule, candidates) for a given prefix.

    Rules: 'R1', 'R2', 'R3', 'R4'.
    """
    if prefix in sessions_set:
        return ("R2", [prefix])
    candidates = [k for k in full_keys if k.startswith(prefix)]
    if len(candidates) == 0:
        return ("R4", [])
    if len(candidates) == 1:
        return ("R1", candidates)
    return ("R3", candidates)


def _iso_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _backup_path(p: Path, ts: str) -> Path:
    return p.with_name(f"{p.name}.bak.{ts}")


def process_vault(
    vault: Path,
    *,
    apply: bool,
    strict: bool,
    backup_ts: str | None = None,
) -> dict:
    """Scan vault, classify, and (optionally) rewrite. Returns summary dict.

    On collision (R3): aborts via SystemExit(1) before any write.
    """
    sessions_path = vault / "_schema" / "sessions.json"
    wiki_dir = vault / "wiki"

    if not sessions_path.is_file():
        print(f"[ERROR] sessions.json not found: {sessions_path}", file=sys.stderr)
        sys.exit(1)
    if not wiki_dir.is_dir():
        print(f"[ERROR] wiki/ not found: {wiki_dir}", file=sys.stderr)
        sys.exit(1)

    with open(sessions_path, encoding="utf-8") as f:
        sessions = json.load(f)
    full_keys = list(sessions.keys())
    sessions_set = set(full_keys)

    rewrites: list[dict] = []
    unchanged: list[dict] = []
    no_match: list[dict] = []
    collisions: list[dict] = []

    plan: dict[Path, list[tuple[str, str]]] = {}

    for md in sorted(wiki_dir.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] read {md}: {e}", file=sys.stderr)
            continue

        rel = str(md.relative_to(vault))
        for prefix in find_session_prefixes(text):
            rule, candidates = classify(prefix, full_keys, sessions_set)
            if rule == "R1":
                full_key = candidates[0]
                rewrites.append({"file": rel, "prefix": prefix, "full_key": full_key})
                plan.setdefault(md, []).append((prefix, full_key))
            elif rule == "R2":
                unchanged.append({"file": rel, "key": prefix})
            elif rule == "R3":
                collisions.append({
                    "file": rel,
                    "prefix": prefix,
                    "candidates": candidates,
                })
            elif rule == "R4":
                no_match.append({"file": rel, "prefix": prefix})
                print(
                    f"[SKIP] session: {prefix} — no match in sessions.json ({rel})",
                    file=sys.stderr,
                )

    if collisions:
        print("[FATAL] collision detected — multiple full keys share the same prefix:", file=sys.stderr)
        for c in collisions:
            print(f"  {c['file']}: prefix={c['prefix']}", file=sys.stderr)
            for cand in c["candidates"]:
                print(f"    -> {cand}", file=sys.stderr)
        print("Resolve manually by editing the wiki source line, then re-run.", file=sys.stderr)
        sys.exit(1)

    if strict and no_match:
        print(f"[FATAL] --strict: {len(no_match)} zero-match prefix(es) found", file=sys.stderr)
        sys.exit(1)

    if apply and plan:
        ts = backup_ts or _iso_ts()
        for md, replacements in plan.items():
            text = md.read_text(encoding="utf-8")
            new_text = text
            for prefix, full_key in replacements:
                new_text, _n = rewrite_session_line(new_text, prefix, full_key)
            if new_text != text:
                bak = _backup_path(md, ts)
                bak.write_text(text, encoding="utf-8")
                tmp = md.with_name(md.name + ".tmp")
                tmp.write_text(new_text, encoding="utf-8")
                os.replace(tmp, md)

    summary = {
        "rewrites": rewrites,
        "unchanged": unchanged,
        "no_match": no_match,
        "collisions": collisions,
        "summary": {
            "rewrite": len(rewrites),
            "unchanged": len(unchanged),
            "no_match": len(no_match),
            "collision": len(collisions),
        },
    }
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Remap wiki source `- session: <prefix>` to full sessions.json key."
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="預覽變更（default）")
    mode.add_argument("--apply", dest="apply", action="store_true", help="實際寫檔（含 backup）")
    p.add_argument("--json", dest="as_json", action="store_true", help="JSON 輸出")
    p.add_argument("--vault", default=None, help="vault root path（預設 cwd）")
    p.add_argument("--strict", dest="strict", action="store_true",
                   help="R4 zero-match 時 fail loud（pre-apply sanity check）")
    args = p.parse_args(argv)
    if not args.apply:
        args.dry_run = True
    return args


def render_human(summary: dict, *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    s = summary["summary"]
    print(f"remap_wiki_session_prefix [{mode}]")
    print(f"  rewrite:   {s['rewrite']}")
    print(f"  unchanged: {s['unchanged']}")
    print(f"  no_match:  {s['no_match']}")
    print(f"  collision: {s['collision']}")
    if summary["rewrites"]:
        print()
        verb = "已改寫" if apply else "將改寫"
        print(f"{verb}（{len(summary['rewrites'])} 條目）：")
        for r in summary["rewrites"]:
            print(f"  - {r['file']}: {r['prefix']}\n      -> {r['full_key']}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    vault = Path(args.vault).resolve() if args.vault else Path.cwd().resolve()
    summary = process_vault(vault, apply=args.apply, strict=args.strict)
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        render_human(summary, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
