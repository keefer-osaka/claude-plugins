#!/usr/bin/env python3
"""
scan_sessions.py — 掃描 ~/.claude/projects/**/*.jsonl，輸出待處理 sessions 的結構化 JSON。

用法：
  python3 scan_sessions.py              # 只處理水位線之後的新 sessions
  python3 scan_sessions.py --all        # 忽略水位線，處理所有 sessions
  python3 scan_sessions.py --limit N    # 限制輸出 N 個 sessions（預設 20）
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

# ── 共用模組（transcript_utils → _lib/wiki_utils）────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "..", "..", "_lib")
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, LIB_DIR)
from transcript_utils import (
    read_sessions_json, find_jsonl_files,
    make_transcript_filename,
    PROJECTS_DIR, EXCLUDE_DIRS, EXCLUDE_FILES,
)
from wiki_utils import resolve_vault_dir, format_tw_date
from message_delta import filter_messages_after_uuid

# ── 設定 ──────────────────────────────────────────────────────────────────────

VAULT_DIR = resolve_vault_dir(__file__)
WATERMARK_PATH = os.path.join(VAULT_DIR, "_schema", ".watermark")
ALL_WATERMARK_PATH = os.path.join(VAULT_DIR, "_schema", ".all_watermark")

MAX_MSG_LEN = 3000
DEFAULT_LIMIT = 10

import subprocess as _subprocess
def _git_author_slug():
    try:
        name = _subprocess.check_output(
            ["git", "config", "user.name"], stderr=_subprocess.DEVNULL
        ).decode().strip()
        return name.replace(" ", "_") or "unknown"
    except Exception:
        return "unknown"

_LOCAL_AUTHOR = _git_author_slug()

# ── 解析工具 ──────────────────────────────────────────────────────────────────

def parse_ts(ts_str):
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def compute_active_duration(timestamps):
    dts = [parse_ts(t) for t in timestamps]
    return sum(
        (dts[i] - dts[i - 1]).total_seconds()
        for i in range(1, len(dts))
        if (dts[i] - dts[i - 1]).total_seconds() <= 1800
    )


def truncate(text, max_len=MAX_MSG_LEN):
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"\n\n[截斷：省略 {len(text) - max_len} 字元]"


# Keep in sync with plugins/export-chat-logs/scripts/common.py:clean_string_content
def clean_string_content(text):
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text).strip()
    if re.match(r'<local-command-stdout>', text):
        return ''
    if re.match(r'<command-name>', text) or re.match(r'<command-message>', text):
        msg_m = re.search(r'<command-message>(.*?)</command-message>', text, re.DOTALL)
        args_m = re.search(r'<command-args>(.*?)</command-args>', text, re.DOTALL)

        head = ''
        if msg_m:
            msg = msg_m.group(1).strip()
            if msg:
                head = f"/{msg}"

        args = args_m.group(1).strip() if args_m else ''
        if head and args:
            runs = re.findall(r'`+', args)
            max_run = max((len(r) for r in runs), default=0)
            fence_len = max(3, max_run + 1)
            fence = '`' * fence_len
            return f"{head}\n\n{fence}\n{args}\n{fence}"
        return head or ''
    return text


def extract_text_blocks(content):
    if isinstance(content, str):
        return clean_string_content(content)
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text = clean_string_content(block.get("text", ""))
            if text:
                parts.append(text)
    return "\n\n".join(parts)


_META_COMMANDS = frozenset({
    "/exit", "/compact", "/clear", "/help", "/init", "/login", "/logout",
    "/config", "/cost", "/doctor", "/memory", "/permissions", "/review",
    "/status", "/terminal-setup", "/vim", "/fast", "/slow",
})


def is_skill_only_session(messages, tool_counts=None):
    if tool_counts and "AskUserQuestion" in tool_counts:
        return False
    user_msgs = [text for role, text, *_ in messages if role == "user"]
    if not user_msgs:
        return True
    if not all(re.match(r"^/\S+\s*$", m) for m in user_msgs):
        return False
    skills = [m for m in user_msgs if m.strip() not in _META_COMMANDS]
    return len(skills) <= 1


def _fused_parse_jsonl(filepath):
    """單次掃描 JSONL，同時收集 metadata、messages（含 uuid）、last_msg_uuid。

    Returns:
        tuple[dict | None, str | None]: (data, error_str)
        data keys:
            messages: list of {uuid, role, text, timestamp}
            title, cwd, first_ts, last_ts, models, msg_timestamps,
            input_tokens, output_tokens, tool_counts, first_user_message,
            last_msg_uuid  — uuid of last user/assistant message (may be "")
    """
    messages = []
    title = None
    cwd = None
    first_ts = None
    last_ts = None
    models_seen = []
    msg_timestamps = []
    input_tokens = 0
    output_tokens = 0
    tool_counts = {}
    first_user_message = ""
    last_msg_uuid = ""

    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if obj.get("isCompactSummary"):
                    continue

                if obj.get("type") == "custom-title":
                    t = obj.get("customTitle", "").strip()
                    if t:
                        title = t

                if cwd is None:
                    c = obj.get("cwd", "")
                    if c:
                        cwd = c

                if obj.get("isMeta"):
                    continue

                msg = obj.get("message", {})
                role = msg.get("role", "")
                ts = obj.get("timestamp", "")
                uuid = obj.get("uuid", "")

                if ts and first_ts is None:
                    first_ts = ts
                if ts and role in ("user", "assistant"):
                    last_ts = ts
                    msg_timestamps.append(ts)

                if role == "assistant":
                    model = msg.get("model", "")
                    if model and model not in models_seen:
                        models_seen.append(model)

                content = msg.get("content", "")
                usage = msg.get("usage", {})
                if usage:
                    input_tokens += usage.get("input_tokens", 0)
                    output_tokens += usage.get("output_tokens", 0)

                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if name:
                                tool_counts[name] = tool_counts.get(name, 0) + 1

                if role not in ("user", "assistant"):
                    continue

                # Track last uuid for all user/assistant messages (matches get_last_message_uuid behavior)
                if uuid:
                    last_msg_uuid = uuid

                text = extract_text_blocks(content)
                if text.strip():
                    t_str = truncate(text.strip())
                    messages.append({
                        "uuid": uuid,
                        "role": role,
                        "text": t_str,
                        "timestamp": ts,
                    })
                    if role == "user" and not first_user_message:
                        first_user_message = text.strip()

    except Exception as e:
        return None, f"parse error: {e}"

    return {
        "messages": messages,
        "title": title,
        "cwd": cwd or "",
        "first_ts": first_ts,
        "last_ts": last_ts,
        "models": models_seen,
        "msg_timestamps": msg_timestamps,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tool_counts": tool_counts,
        "first_user_message": first_user_message,
        "last_msg_uuid": last_msg_uuid,
    }, None


def parse_session(filepath):
    """Backward-compat wrapper around _fused_parse_jsonl; returns tuple-style messages."""
    data, err = _fused_parse_jsonl(filepath)
    if data is None:
        return None, err
    tuple_messages = [(m["role"], m["text"], m["timestamp"]) for m in data["messages"]]
    return {
        "messages": tuple_messages,
        "title": data["title"],
        "cwd": data["cwd"],
        "first_ts": data["first_ts"],
        "last_ts": data["last_ts"],
        "models": data["models"],
        "msg_timestamps": data["msg_timestamps"],
        "input_tokens": data["input_tokens"],
        "output_tokens": data["output_tokens"],
        "tool_counts": data["tool_counts"],
        "first_user_message": data["first_user_message"],
    }, None


def _read_jsonl_messages(filepath):
    """Backward-compat wrapper; returns [{uuid, role, text, timestamp}] or None."""
    data, _ = _fused_parse_jsonl(filepath)
    if data is None:
        return None
    return data["messages"]


def get_messages_after_uuid(filepath, after_uuid):
    """Read JSONL, return (messages_list, found_pivot) for messages after after_uuid."""
    raw = _read_jsonl_messages(filepath)
    if raw is None:
        return [], False
    filtered, found = filter_messages_after_uuid(raw, after_uuid)
    result = [{"role": m["role"], "text": m["text"], "timestamp": m["timestamp"]} for m in filtered]
    return result, found


# ── 主邏輯 ────────────────────────────────────────────────────────────────────

def read_watermark():
    try:
        with open(WATERMARK_PATH) as f:
            content = f.read().strip()
            if content:
                return parse_ts(content)
    except Exception:
        pass
    return None


def read_all_watermark():
    """讀取 --all 模式的游標（Unix timestamp），0 = 從頭開始。"""
    try:
        with open(ALL_WATERMARK_PATH) as f:
            content = f.read().strip()
            if content:
                return float(content)
    except Exception:
        pass
    return 0.0


def main():
    all_mode = "--all" in sys.argv or "-a" in sys.argv
    limit = DEFAULT_LIMIT
    for flag in ("--limit", "-n"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv):
                try:
                    limit = int(sys.argv[idx + 1])
                except ValueError:
                    pass
            break

    all_files = find_jsonl_files()

    if all_mode:
        # --all 模式：使用獨立游標 .all_watermark，由舊到新逐批推進
        all_cursor = read_all_watermark()
        candidates = [f for f in all_files if os.path.getmtime(f) > all_cursor]
        candidates.sort(key=lambda f: os.path.getmtime(f))  # 升序：最舊的優先
        watermark = None  # 輸出中顯示用
    else:
        watermark = read_watermark()
        if watermark:
            cutoff_ts = watermark.timestamp()
            candidates = [f for f in all_files if os.path.getmtime(f) > cutoff_ts]
        else:
            candidates = all_files
        candidates.sort(key=lambda f: os.path.getmtime(f), reverse=True)  # 降序

    total_candidates = len(candidates)

    # 限制數量
    candidates = candidates[:limit]

    # 記錄本批次最大 mtime（供 update_all_watermark.py 使用）
    max_mtime = max((os.path.getmtime(f) for f in candidates), default=0.0)

    results = []
    skipped = []

    # 載入 sessions.json manifest（用於 delta 偵測）
    manifest = read_sessions_json()

    for filepath in candidates:
        session_id = os.path.splitext(os.path.basename(filepath))[0]
        project_dir = os.path.basename(os.path.dirname(filepath))

        # 查詢 manifest，決定是 delta 還是新 session
        manifest_entry = manifest.get(session_id)
        last_processed_uuid = (manifest_entry or {}).get("last_processed_msg_uuid", "")
        base_transcript = (manifest_entry or {}).get("transcript_path", "")

        data = None  # 若 delta 分支已解析，可供 fallthrough 重用（避免二次讀取）

        if last_processed_uuid:
            # Delta 模式：單次 _fused_parse_jsonl，再用 filter_messages_after_uuid 切取新訊息
            data, err = _fused_parse_jsonl(filepath)
            if err or data is None:
                skipped.append({"path": filepath, "reason": err or "parse failed"})
                continue

            filtered, found_pivot = filter_messages_after_uuid(data["messages"], last_processed_uuid)

            if not found_pivot:
                # Pivot UUID 不在 JSONL 中（可能 session 被重寫），fallthrough 到一般解析
                # data 已可用，不需再讀檔案
                last_processed_uuid = ""
            elif not filtered:
                # 無新訊息
                skipped.append({"path": filepath, "reason": "already processed, no delta"})
                continue
            else:
                # 有 delta
                delta_messages = [
                    {"role": m["role"], "text": m["text"], "timestamp": m["timestamp"]}
                    for m in filtered
                ]
                date_str = format_tw_date(data["first_ts"]) if data["first_ts"] else ""
                results.append({
                    "session_id": session_id,
                    "project_dir": project_dir,
                    "jsonl_path": filepath,
                    "title": data["title"] or data["first_user_message"][:60] or session_id,
                    "cwd": data["cwd"],
                    "date": date_str,
                    "first_ts": data["first_ts"],
                    "last_ts": data["last_ts"],
                    "output_tokens": data["output_tokens"],
                    "duration_seconds": None,
                    "models": data["models"],
                    "message_count": len(delta_messages),
                    "messages": delta_messages,
                    "delta": True,
                    "base_transcript": base_transcript,
                    "transcript_stem": os.path.splitext(os.path.basename(base_transcript))[0] if base_transcript else None,
                    "author": _LOCAL_AUTHOR,
                    "source": "jsonl",
                    "last_processed_msg_uuid": data["last_msg_uuid"],
                })
                continue

        # 一般模式（新 session，或 delta fallthrough 時重用已解析的 data）
        if data is None:
            data, err = _fused_parse_jsonl(filepath)
            if err or data is None:
                skipped.append({"path": filepath, "reason": err or "parse failed"})
                continue

        # 判斷 trivial
        total_tokens = data["input_tokens"] + data["output_tokens"]
        tss = data["msg_timestamps"]
        duration = compute_active_duration(tss) if len(tss) >= 2 else None

        if total_tokens == 0 or (data["output_tokens"] < 100 and (duration is None or duration < 60)):
            skipped.append({"path": filepath, "reason": "trivial (low tokens/duration)"})
            continue

        # is_skill_only_session 需要 tuple-style messages
        messages_as_tuples = [(m["role"], m["text"], m["timestamp"]) for m in data["messages"]]
        if is_skill_only_session(messages_as_tuples, data["tool_counts"]):
            skipped.append({"path": filepath, "reason": "skill-only session"})
            continue

        formatted_messages = [
            {"role": m["role"], "text": m["text"], "timestamp": m["timestamp"]}
            for m in data["messages"]
            if m["text"].strip()
        ]

        # 計算日期
        date_str = format_tw_date(data["first_ts"]) if data["first_ts"] else ""

        title = data["title"] or data["first_user_message"][:60] or session_id
        results.append({
            "session_id": session_id,
            "project_dir": project_dir,
            "jsonl_path": filepath,
            "title": title,
            "cwd": data["cwd"],
            "date": date_str,
            "first_ts": data["first_ts"],
            "last_ts": data["last_ts"],
            "output_tokens": data["output_tokens"],
            "duration_seconds": duration,
            "models": data["models"],
            "message_count": len(formatted_messages),
            "messages": formatted_messages,
            "delta": False,
            "base_transcript": "",
            "transcript_stem": os.path.splitext(
                make_transcript_filename(data["first_ts"], session_id, title)
            )[0],
            "author": _LOCAL_AUTHOR,
            "source": "jsonl",
            "last_processed_msg_uuid": data["last_msg_uuid"],
        })

    output = {
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "watermark": watermark.isoformat() if watermark else None,
        "all_mode": all_mode,
        "total_found": len(all_files),
        "total_candidates": total_candidates,
        "candidates": len(candidates),
        "max_candidate_mtime": max_mtime,  # --all 模式用：更新 .all_watermark 的依據
        "sessions": results,
        "skipped_count": len(skipped),
        "skipped": skipped[:10],  # 只輸出前 10 個跳過記錄
    }

    # --all 模式：掃完就自動推進游標，不依賴 skill 手動呼叫 update_all_watermark.py
    if all_mode and max_mtime > 0:
        with open(ALL_WATERMARK_PATH, "w", encoding="utf-8") as f:
            f.write(str(max_mtime) + "\n")
        output["all_watermark_updated"] = max_mtime

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
