#!/usr/bin/env python3
"""
upsert_transcripts.py — 更新 transcript 與 sessions manifest。

從 stdin 讀取 JSON（本批次處理過的 sessions 清單），
對每個 session 建立或更新 transcript，並更新 _schema/sessions.json。

輸入 JSON 格式（stdin，JSON 陣列）：
[
  {
    "session_id": "...",
    "delta": false,            # true = delta session，false = 新 session
    "title": "...",
    "cwd": "...",
    "date": "YYYY-MM-DD",
    "first_ts": "...",
    "last_ts": "...",
    "models": [...],
    "messages": [{"role": "...", "text": "...", "timestamp": "...", "uuid": "..."}],
    "jsonl_path": "...",        # 用於取得 last_processed_msg_uuid
    "base_transcript": "...",  # delta 用：現有 transcript 的 vault-relative 路徑
    "new_derived_pages": [...]  # 本次新建或更新的 wiki 頁面路徑清單
  },
  ...
]

輸出 JSON（stdout）：
{
  "created": N,    # 新建立的 transcript 數
  "updated": N,    # 更新的 transcript 數
  "errors": [...]  # 若有錯誤
}
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from transcript_utils import (
    VAULT_DIR, TRANSCRIPTS_DIR, WIKI_DIR,
    render_transcript_md, append_delta_to_transcript,
    read_sessions_json, write_sessions_json, upsert_session_manifest,
    rebuild_transcripts_index, make_transcript_filename,
    get_last_message_uuid, backfill_wiki_transcripts,
)


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)

    try:
        sessions = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON from stdin: {e}"}))
        sys.exit(1)

    if not isinstance(sessions, list):
        print(json.dumps({"error": "Input must be a JSON array of session objects"}))
        sys.exit(1)

    manifest = read_sessions_json()
    now_ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    Path(TRANSCRIPTS_DIR).mkdir(exist_ok=True)

    created = 0
    updated = 0
    errors = []

    for session in sessions:
        session_id = session.get("session_id", "")
        if not session_id:
            errors.append("Missing session_id in entry")
            continue

        jsonl_path = session.get("jsonl_path", "")
        new_derived_pages = session.get("new_derived_pages", [])

        try:
            if session.get("delta"):
                # Delta session：append 新訊息到現有 transcript
                base_transcript_rel = session.get("base_transcript", "")
                transcript_abs = os.path.join(VAULT_DIR, base_transcript_rel)
                new_last_uuid = get_last_message_uuid(jsonl_path) if jsonl_path else ""

                ok = append_delta_to_transcript(
                    transcript_abs, session.get("messages", []), new_last_uuid
                )
                if not ok:
                    errors.append(f"{session_id}: delta append failed, manifest not advanced")
                    continue

                entry = manifest.get(session_id, {})
                upsert_session_manifest(
                    manifest, session_id,
                    transcript_path=base_transcript_rel,
                    last_processed_msg_uuid=new_last_uuid,
                    last_processed_ts=now_ts,
                    message_count=entry.get("message_count", 0) + sum(1 for m in session.get("messages", []) if m.get("text", "").strip()),
                    status="processed",
                    derived_pages=new_derived_pages,
                    author=session.get("author", ""),
                    source=session.get("source", "jsonl"),
                )
                updated += 1
            else:
                # 新 session：建立 transcript
                messages = session.get("messages", [])
                if not messages:
                    print(f"[skip] empty session {session_id[:8]}... (no messages)", file=sys.stderr)
                    continue
                fname = make_transcript_filename(
                    session.get("first_ts", ""),
                    session_id,
                    session.get("title", ""),
                )
                transcript_rel = os.path.join("transcripts", fname)
                transcript_abs = os.path.join(TRANSCRIPTS_DIR, fname)
                last_uuid = get_last_message_uuid(jsonl_path) if jsonl_path else ""
                old_tp = manifest.get(session_id, {}).get("transcript_path", "")
                if old_tp and old_tp != transcript_rel:
                    old_abs = os.path.join(VAULT_DIR, old_tp)
                    if os.path.exists(old_abs):
                        os.remove(old_abs)
                        print(f"[cleanup] removed stale transcript {old_tp}", file=sys.stderr)

                md = render_transcript_md(
                    session_id=session_id,
                    title=session.get("title", ""),
                    cwd=session.get("cwd", ""),
                    date=session.get("date", ""),
                    first_ts=session.get("first_ts", ""),
                    last_ts=session.get("last_ts", ""),
                    message_count=len(messages),
                    last_processed_msg_uuid=last_uuid,
                    last_processed_at=now_ts,
                    models=session.get("models", []),
                    derived_pages=new_derived_pages,
                    status="processed",
                    messages=messages,
                    author=session.get("author", ""),
                    source=session.get("source", "jsonl"),
                )
                Path(transcript_abs).write_text(md, encoding="utf-8")
                upsert_session_manifest(
                    manifest, session_id,
                    transcript_path=transcript_rel,
                    last_processed_msg_uuid=last_uuid,
                    last_processed_ts=now_ts,
                    message_count=len(messages),
                    status="processed",
                    derived_pages=new_derived_pages,
                    author=session.get("author", ""),
                    source=session.get("source", "jsonl"),
                )
                created += 1

        except Exception as e:
            errors.append(f"{session_id}: {e}")

    write_sessions_json(manifest)
    wiki_linked = backfill_wiki_transcripts(manifest, WIKI_DIR)
    rebuild_transcripts_index(TRANSCRIPTS_DIR)

    result = {"created": created, "updated": updated, "wiki_linked": wiki_linked}
    if errors:
        result["errors"] = errors
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
