#!/usr/bin/env python3
"""
backfill_transcripts.py — 一次性回填歷史 session transcripts。

執行步驟：
1. 掃描 ~/.claude/projects/**/*.jsonl 所有 session
2. 對每個 non-trivial session 生成 transcript markdown → transcripts/
3. 掃描 wiki/**/*.md 反查哪些 session 被哪些 wiki 頁面引用（derived_pages）
4. 更新 wiki 頁面的 sources frontmatter，補 transcript: 欄位
5. 建立 _schema/sessions.json manifest
6. 重建 transcripts/_index.md

用法：
  python3 backfill_transcripts.py              # 正式執行
  python3 backfill_transcripts.py --dry-run    # 乾跑：只輸出統計，不寫檔
  python3 backfill_transcripts.py --limit N    # 只處理前 N 個 session（測試用）
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 引入共用工具
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from transcript_utils import (
    VAULT_DIR, TRANSCRIPTS_DIR, WIKI_DIR, TW_TZ,
    make_transcript_filename, render_transcript_md,
    read_sessions_json, write_sessions_json, upsert_session_manifest,
    scan_wiki_sources, add_transcript_to_wiki_sources, backfill_wiki_transcripts,
    rebuild_transcripts_index,
    find_jsonl_files, get_last_message_uuid,
)
# transcript_utils 已將 _lib 加入 sys.path，可直接 import
from wiki_utils import format_tw_date, extract_fm_text, parse_source_blocks

# 引入 scan_sessions 的解析工具（避免重複程式碼）
from scan_sessions import parse_session, compute_active_duration, is_skill_only_session


def main():
    dry_run = "--dry-run" in sys.argv
    limit = None
    for flag in ("--limit", "-n"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv):
                try:
                    limit = int(sys.argv[idx + 1])
                except ValueError:
                    pass

    mode_str = "[DRY RUN] " if dry_run else ""
    print(f"{mode_str}backfill_transcripts.py 開始")
    print(f"  Vault: {VAULT_DIR}")
    print(f"  Transcripts: {TRANSCRIPTS_DIR}")

    # 1. 確認目錄存在
    if not dry_run:
        os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)

    # 2. 掃描所有 JSONL session
    all_files = find_jsonl_files()
    all_files.sort(key=lambda f: os.path.getmtime(f))
    if limit:
        all_files = all_files[:limit]

    print(f"\n找到 {len(all_files)} 個 JSONL 檔案")

    # 3. 讀取現有 sessions.json（可能是空 dict）
    manifest = read_sessions_json()
    print(f"已有 manifest 條目：{len(manifest)} 個")

    # 4. 掃描 wiki/ 取得 session → derived_pages 的反查表
    print("\n掃描 wiki/ 建立反查表...")
    session_to_wiki_pages = scan_wiki_sources(WIKI_DIR)
    print(f"  找到 {len(session_to_wiki_pages)} 個被 wiki 引用的 session")

    # 5. 逐 session 處理
    stats = {
        "total": 0, "trivial_skip": 0, "skill_only_skip": 0,
        "parse_error": 0, "new": 0, "already_exists": 0, "wiki_updated": 0,
    }

    # session_id → transcript_rel_path（用於後續更新 wiki frontmatter）
    session_to_transcript_path = {}

    for filepath in all_files:
        session_id = os.path.splitext(os.path.basename(filepath))[0]
        stats["total"] += 1

        # 如果 manifest 中已存在且 transcript 檔案也存在，記錄路徑後略過生成
        if session_id in manifest:
            existing_tp = manifest[session_id].get("transcript_path", "")
            full_tp = os.path.join(VAULT_DIR, existing_tp) if existing_tp else ""
            if existing_tp and os.path.exists(full_tp):
                session_to_transcript_path[session_id] = existing_tp
                stats["already_exists"] += 1
                continue

        # 解析 session
        data, err = parse_session(filepath)
        if err or data is None:
            stats["parse_error"] += 1
            continue

        # Trivial 過濾
        total_tokens = data["input_tokens"] + data["output_tokens"]
        tss = data["msg_timestamps"]
        duration = compute_active_duration(tss) if len(tss) >= 2 else None
        if total_tokens == 0 or (data["output_tokens"] < 100 and (duration is None or duration < 60)):
            stats["trivial_skip"] += 1
            continue

        if is_skill_only_session(data["messages"], data["tool_counts"]):
            stats["skill_only_skip"] += 1
            continue

        # 準備 transcript 資料
        title = data["title"] or data["first_user_message"][:60] or session_id
        first_ts = data["first_ts"] or ""
        last_ts = data["last_ts"] or ""

        date_str = format_tw_date(first_ts) or "0000-00-00"

        fname = make_transcript_filename(first_ts, session_id, title)
        transcript_rel_path = os.path.join("transcripts", fname)
        transcript_abs_path = os.path.join(TRANSCRIPTS_DIR, fname)

        session_to_transcript_path[session_id] = transcript_rel_path

        # 取最後一則訊息的 uuid 作為 last_processed_msg_uuid
        # parse_session 目前不輸出 uuid，需直接從 JSONL 讀最後一條 message 的 uuid
        last_uuid = get_last_message_uuid(filepath)

        # derived_pages（從反查表取）
        derived_pages = sorted(session_to_wiki_pages.get(session_id, []))

        # 格式化訊息
        messages_formatted = []
        for role, text, ts in data["messages"]:
            messages_formatted.append({"role": role, "text": text, "timestamp": ts})

        now_ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

        if not dry_run:
            md_content = render_transcript_md(
                session_id=session_id,
                title=title,
                cwd=data["cwd"],
                date=date_str,
                first_ts=first_ts,
                last_ts=last_ts,
                message_count=len(messages_formatted),
                last_processed_msg_uuid=last_uuid,
                last_processed_at=now_ts,
                models=data["models"],
                derived_pages=derived_pages,
                status="processed",
                messages=messages_formatted,
            )
            Path(transcript_abs_path).write_text(md_content, encoding="utf-8")

            # 更新 manifest
            upsert_session_manifest(
                manifest=manifest,
                session_id=session_id,
                transcript_path=transcript_rel_path,
                last_processed_msg_uuid=last_uuid,
                last_processed_ts=now_ts,
                message_count=len(messages_formatted),
                status="processed",
                derived_pages=derived_pages,
            )

        stats["new"] += 1
        if stats["new"] % 20 == 0:
            print(f"  ... 已生成 {stats['new']} 個 transcripts")

    print(f"\n=== Transcript 生成完成 ===")
    print(f"  總計掃描：{stats['total']}")
    print(f"  新生成：  {stats['new']}")
    print(f"  已存在：  {stats['already_exists']}")
    print(f"  瑣碎跳過：{stats['trivial_skip']}")
    print(f"  Skill-only：{stats['skill_only_skip']}")
    print(f"  解析錯誤：{stats['parse_error']}")

    # 6. 更新 wiki 頁面的 sources frontmatter（補 transcript:）
    print(f"\n{'[DRY RUN] ' if dry_run else ''}更新 wiki 頁面 sources frontmatter...")
    if not dry_run:
        wiki_updated = backfill_wiki_transcripts(manifest, WIKI_DIR)
    else:
        # dry-run: 只讀取確認哪些需要更新
        wiki_updated = 0
        for wiki_path in Path(WIKI_DIR).rglob("*.md"):
            if wiki_path.name == "_index.md":
                continue
            content = wiki_path.read_text(encoding="utf-8")
            for block in parse_source_blocks(extract_fm_text(content)):
                if block["session"] in session_to_transcript_path:
                    wiki_updated += 1
                    break
    print(f"  {'會更新' if dry_run else '已更新'} {wiki_updated} 個 wiki 頁面")
    stats["wiki_updated"] = wiki_updated

    # 7. 寫入 sessions.json
    if not dry_run:
        write_sessions_json(manifest)
        print(f"\n已寫入 _schema/sessions.json（{len(manifest)} 個條目）")
    else:
        print(f"\n[DRY RUN] 會寫入 _schema/sessions.json（約 {len(manifest) + stats['new']} 個條目）")

    # 8. 重建 transcripts/_index.md
    if not dry_run:
        rebuild_transcripts_index(TRANSCRIPTS_DIR)
        transcript_count = len(list(Path(TRANSCRIPTS_DIR).glob("*.md"))) - 1  # 扣掉 _index.md
        print(f"已重建 transcripts/_index.md（{transcript_count} 個 transcripts）")

    print(f"\n{mode_str}完成！")


if __name__ == "__main__":
    main()
