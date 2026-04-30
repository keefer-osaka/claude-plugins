#!/usr/bin/env python3
"""
backfill_wiki_links: 為 wiki 頁面補回缺失的 transcript: 連結

來源：`_schema/sessions.json`（session → transcript_path）
動作：對每個 wiki 頁面 frontmatter 內的 `sources: - session: <sid>`，
      若該 session 在 manifest 中且有 transcript_path 卻尚未在 wiki 補 transcript:，則補上。

CLI:
  --dry-run        （default）只列出將更新的條目，不寫檔
  --apply          實際寫檔
  --filter-author  只處理 manifest 中 author == <slug> 的 session
  --limit N        最多處理 N 個 wiki 檔
  --json           以 JSON 格式輸出彙總（給上層工具消費）
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))

from transcript_utils import (  # noqa: E402
    WIKI_DIR,
    add_transcript_to_wiki_sources,
    read_sessions_json,
)


def parse_args():
    p = argparse.ArgumentParser(description="Backfill missing transcript: links into wiki frontmatter sources.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="預覽變更（default）")
    mode.add_argument("--apply", dest="apply", action="store_true", help="實際寫檔")
    p.add_argument("--filter-author", default=None, help="只處理 manifest 中 author 等於此 slug 的 session")
    p.add_argument("--limit", type=int, default=None, help="最多處理 N 個 wiki 檔")
    p.add_argument("--json", dest="as_json", action="store_true", help="以 JSON 輸出")
    args = p.parse_args()
    if not args.apply:
        args.dry_run = True
    return args


def build_session_to_transcript(manifest: dict, filter_author: str | None) -> dict:
    s2t: dict[str, str] = {}
    for sid, entry in manifest.items():
        if not isinstance(entry, dict):
            continue
        tp = entry.get("transcript_path")
        if not tp:
            continue
        if filter_author and entry.get("author") != filter_author:
            continue
        s2t[sid] = tp
    return s2t


def render(summary: dict, args) -> None:
    if args.as_json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"backfill_wiki_links [{mode}]")
    print(f"  manifest sessions with transcript_path: {summary['s2t_count']}")
    if args.filter_author:
        print(f"  filter-author: {args.filter_author}")
    print(f"  wiki files scanned: {summary['scanned']}")
    print()

    updated = summary["updated"]
    if updated:
        verb = "已更新" if args.apply else "將更新"
        print(f"{verb}（{len(updated)} 檔）：")
        for path, added in updated:
            print(f"  - {path}")
            for sid, wikilink in added:
                print(f"      + session `{sid}` → {wikilink}")
    else:
        print("（無 wiki 檔需要更新）")

    print()
    print("Summary:")
    print(f"  updated:           {len(updated)}")
    print(f"  already linked:    {summary['already_linked']}")
    print(f"  no manifest match: {summary['no_match']}")


def main() -> int:
    args = parse_args()

    manifest = read_sessions_json()
    s2t = build_session_to_transcript(manifest, args.filter_author)

    wiki_files = sorted(Path(WIKI_DIR).rglob("*.md"))
    if args.limit is not None:
        wiki_files = wiki_files[: args.limit]

    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "filter_author": args.filter_author,
        "s2t_count": len(s2t),
        "scanned": 0,
        "updated": [],          # [(path, [(sid, wikilink), ...])]
        "already_linked": 0,    # source 條目已有 transcript:
        "no_match": 0,          # source 條目缺 transcript: 且 sid 不在 s2t
    }

    # 為了給人類可讀的 summary，我們需要在呼叫 add_... 前先掃描 frontmatter
    # 統計 already_linked / no_match。否則 add_... 不修改、不回報略過原因。
    from wiki_utils import extract_fm_text, parse_source_blocks  # noqa: E402

    for path in wiki_files:
        if path.name == "_index.md":
            continue
        summary["scanned"] += 1

        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] read {path}: {e}", file=sys.stderr)
            continue

        for sb in parse_source_blocks(extract_fm_text(text)):
            if sb.get("has_transcript"):
                summary["already_linked"] += 1
            elif sb["session"] not in s2t:
                summary["no_match"] += 1

        result = add_transcript_to_wiki_sources(str(path), s2t, dry_run=not args.apply)
        if result["added"]:
            summary["updated"].append((str(path), result["added"]))

    render(summary, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
