#!/usr/bin/env python3
"""
transcript_utils.py — 共用工具函式，供 backfill_transcripts.py 和 kb-ingest 使用。

提供：
- Slug 生成、檔名生成
- Transcript markdown 渲染
- sessions.json manifest 讀寫
- wiki frontmatter sources 更新（補 transcript: 欄位）
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── _lib 共用模組 ─────────────────────────────────────────────────────────────

_SKILLS_DIR = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(_SKILLS_DIR, "_lib"))
from wiki_utils import resolve_vault_dir, TW_TZ, format_tw_date  # noqa: E402

# ── 路徑常數 ─────────────────────────────────────────────────────────────────

VAULT_DIR = resolve_vault_dir(__file__)
TRANSCRIPTS_DIR = os.path.join(VAULT_DIR, "transcripts")
SESSIONS_JSON_PATH = os.path.join(VAULT_DIR, "_schema", "sessions.json")
WIKI_DIR = os.path.join(VAULT_DIR, "wiki")

# ── Session 掃描常數 ──────────────────────────────────────────────────────────

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
EXCLUDE_DIRS = {"subagents", "memory"}
EXCLUDE_FILES = {"audit.jsonl"}


# ── Slug 與檔名 ───────────────────────────────────────────────────────────────

def make_slug(text: str, max_len: int = 40) -> str:
    """從標題或訊息生成 kebab-case slug。"""
    if not text:
        return "untitled"
    # 移除括號及其內容
    text = re.sub(r'[（(][^）)]*[）)]', '', text)
    # 非字母數字（含中文）轉底線，再壓縮
    text = re.sub(r'[^\w\u4e00-\u9fff\u3400-\u4dbf]+', '-', text.strip())
    text = re.sub(r'-+', '-', text).strip('-').lower()
    return text[:max_len].rstrip('-') or "untitled"


def make_transcript_filename(first_ts: str, session_id: str, title: str) -> str:
    """生成 transcript 檔名：YYYY-MM-DD-<session前8碼>-<slug>.md"""
    date_str = format_tw_date(first_ts) or "0000-00-00"
    short_id = session_id[:8] if session_id else "unknown"
    slug = make_slug(title or session_id)
    return f"{date_str}-{short_id}-{slug}.md"


# ── Transcript Markdown 渲染 ──────────────────────────────────────────────────

def format_message_header(role: str, ts: str) -> str:
    """生成訊息標題行，例如 ## User (2026-04-11 14:32)"""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TW_TZ)
        ts_str = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts_str = ts or "?"
    label = "User" if role == "user" else "Assistant"
    return f"## {label} ({ts_str})"


def render_transcript_md(
    session_id: str,
    title: str,
    cwd: str,
    date: str,
    first_ts: str,
    last_ts: str,
    message_count: int,
    last_processed_msg_uuid: str,
    last_processed_at: str,
    models: list,
    derived_pages: list,
    status: str,
    messages: list,  # [{role, text, timestamp, uuid}]
    author: str = "",
    source: str = "jsonl",
) -> str:
    """渲染完整 transcript markdown（frontmatter + 對話內容）。"""

    # YAML frontmatter
    models_str = json.dumps(models, ensure_ascii=False)
    derived_str = ""
    if derived_pages:
        derived_str = "\nderived_pages:\n" + "".join(f"  - {p}\n" for p in derived_pages)
    else:
        derived_str = "\nderived_pages: []\n"

    # 計算 first/last date display
    first_date = format_tw_date(first_ts) or date
    last_date = format_tw_date(last_ts) or date

    author_line = f"\nauthor: {author}" if author else ""
    source_line = f"\nsource: {source}"

    frontmatter = f"""---
session_id: {session_id}
title: {title}
cwd: {cwd}
date: {date}
first_ts: {first_ts or ''}
last_ts: {last_ts or ''}
message_count: {message_count}
last_processed_msg_uuid: {last_processed_msg_uuid or ''}
last_processed_at: {last_processed_at}
models: {models_str}{derived_str}status: {status}{author_line}{source_line}
---"""

    # 標題與 session 摘要行
    date_range = first_date if first_date == last_date else f"{first_date} → {last_date}"
    header = f"""
# {title}

> Session `{session_id[:8]}`｜{date_range}｜{message_count} messages

"""

    # 對話內容
    body_parts = []
    for msg in messages:
        role = msg.get("role", "")
        text = msg.get("text", "").strip()
        ts = msg.get("timestamp", "")
        if not text:
            continue
        body_parts.append(format_message_header(role, ts))
        body_parts.append("")
        body_parts.append(text)
        body_parts.append("")

    body = "\n".join(body_parts)

    # Delta marker（用於後續 append delta 時的插入點）
    last_uuid = last_processed_msg_uuid or ""
    delta_marker = f"\n---\n\n<!-- delta marker: last_processed_msg_uuid={last_uuid} -->\n"

    return frontmatter + header + body + delta_marker


# ── Sessions Manifest ─────────────────────────────────────────────────────────

def read_sessions_json() -> dict:
    """讀取 _schema/sessions.json，若不存在回傳空 dict。"""
    try:
        with open(SESSIONS_JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_sessions_json(data: dict) -> None:
    """寫入 _schema/sessions.json（atomic write via tmp file）。"""
    os.makedirs(os.path.dirname(SESSIONS_JSON_PATH), exist_ok=True)
    tmp_path = SESSIONS_JSON_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SESSIONS_JSON_PATH)


def upsert_session_manifest(
    manifest: dict,
    session_id: str,
    transcript_path: str,
    last_processed_msg_uuid: str,
    last_processed_ts: str,
    message_count: int,
    status: str,
    derived_pages: list,
    author: str = "",
    source: str = "jsonl",
    author_conflict: bool = False,
) -> None:
    """在 manifest dict 中更新或新增 session 條目（in-place）。"""
    existing = manifest.get(session_id, {})
    existing_derived = set(existing.get("derived_pages", []))
    merged_derived = sorted(existing_derived | set(derived_pages))

    # Detect cross-author conflict: same sid previously stored with different author
    existing_author = existing.get("author", "")
    if existing_author and author and existing_author != author:
        author_conflict = True

    entry = {
        "transcript_path": transcript_path,
        "last_processed_msg_uuid": last_processed_msg_uuid,
        "last_processed_ts": last_processed_ts,
        "message_count": message_count,
        "status": status,
        "derived_pages": merged_derived,
    }
    if author:
        entry["author"] = author
    if source:
        entry["source"] = source
    if author_conflict:
        entry["author_conflict"] = True
    manifest[session_id] = entry


# ── Wiki Frontmatter 更新 ─────────────────────────────────────────────────────

def scan_wiki_sources(wiki_dir: str) -> dict:
    """
    掃描 wiki/ 下所有 .md，回傳 {session_id: [wiki_page_rel_path, ...]}。
    rel_path 相對於 vault root。
    """
    result = {}  # session_id → [rel_path, ...]
    vault_root = os.path.dirname(wiki_dir)
    for path in Path(wiki_dir).rglob("*.md"):
        rel_path = os.path.relpath(str(path), vault_root)
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] scan_wiki_sources read {path}: {e}", file=sys.stderr)
            continue
        fm = _parse_frontmatter_sources(content)
        for session_id in fm:
            result.setdefault(session_id, [])
            if rel_path not in result[session_id]:
                result[session_id].append(rel_path)
    return result


def _parse_frontmatter_sources(content: str) -> list:
    """從 markdown frontmatter 提取所有 session ID。"""
    from wiki_utils import extract_fm_text, parse_source_blocks
    return [b["session"] for b in parse_source_blocks(extract_fm_text(content))]


def add_transcript_to_wiki_sources(wiki_path: str, session_to_transcript: dict) -> bool:
    """
    讀取 wiki 頁面，對 sources 中每個 session 補 transcript: 欄位（巢狀），
    並同步維護頂層 transcripts: list（供 Obsidian Properties 面板渲染可點擊連結）。
    只在該條目尚無 transcript: 時才補。
    回傳 True 若有實際修改。
    """
    try:
        content = Path(wiki_path).read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] add_transcript_to_wiki_sources read {wiki_path}: {e}", file=sys.stderr)
        return False

    fm_match = re.match(r'^(---\s*\n)(.*?)(\n---\s*\n)(.*)', content, re.DOTALL)
    if not fm_match:
        return False

    fm_open, fm_body, fm_close, body_rest = fm_match.groups()

    new_fm_lines = []
    lines = fm_body.split("\n")
    i = 0
    modified = False
    # 追蹤本次新增的 transcript wikilinks（供更新頂層 transcripts: list）
    new_transcripts = []

    while i < len(lines):
        line = lines[i]
        new_fm_lines.append(line)

        # 偵測 `  - session: <uuid>` 行
        m = re.match(r'^(\s+)- session:\s*(\S+)\s*$', line)
        if m:
            indent = m.group(1)
            session_id = m.group(2)
            # 收集這個 source 塊的後續行（date:, project:, transcript: 等）
            block_lines = []
            j = i + 1
            while j < len(lines):
                next_line = lines[j]
                # 如果下一行是新的 source item 或 frontmatter 頂層 key，停止
                if re.match(r'^\s+- ', next_line) or re.match(r'^\w', next_line):
                    break
                block_lines.append(next_line)
                j += 1

            # 把 block_lines 先加進去
            new_fm_lines.extend(block_lines)
            i = j

            # 判斷是否已有 transcript:
            has_transcript = any('transcript:' in bl for bl in block_lines)
            if not has_transcript and session_id in session_to_transcript:
                transcript_path = session_to_transcript[session_id]
                fname = os.path.splitext(os.path.basename(transcript_path))[0]
                wikilink = f"[[{fname}]]"
                new_fm_lines.append(f'{indent}  transcript: "{wikilink}"')
                new_transcripts.append(wikilink)
                modified = True
            continue

        i += 1

    if not modified:
        return False

    new_fm_text = "\n".join(new_fm_lines)

    # 同步更新頂層 transcripts: list
    if new_transcripts:
        # 讀取現有 transcripts: list（若有）
        existing = []
        top_match = re.search(r'^transcripts:\n((?:  - .+\n?)+)', new_fm_text, re.MULTILINE)
        if top_match:
            for entry in re.finditer(r'^\s+- "?(\[\[.+?\]\])"?', top_match.group(1), re.MULTILINE):
                existing.append(entry.group(1))

        # 合併（去重保序）
        seen = set(existing)
        merged = list(existing)
        for t in new_transcripts:
            if t not in seen:
                merged.append(t)
                seen.add(t)

        transcripts_block = "transcripts:\n" + "".join(f'  - "{t}"\n' for t in merged)

        if top_match:
            # 替換既有區塊
            new_fm_text = new_fm_text[:top_match.start()] + transcripts_block.rstrip('\n') + '\n' + new_fm_text[top_match.end():]
        else:
            # 插入到 created: 前，或追加到結尾
            created_m = re.search(r'^created:', new_fm_text, re.MULTILINE)
            if created_m:
                insert_pos = created_m.start()
                new_fm_text = new_fm_text[:insert_pos] + transcripts_block + new_fm_text[insert_pos:]
            else:
                new_fm_text = new_fm_text.rstrip('\n') + '\n' + transcripts_block.rstrip('\n')

    new_content = fm_open + new_fm_text + fm_close + body_rest
    Path(wiki_path).write_text(new_content, encoding="utf-8")
    return True


def backfill_wiki_transcripts(manifest: dict, wiki_dir: str) -> int:
    """
    For every wiki page, fill in missing transcript: fields for sessions that
    now have a transcript. Returns count of wiki files actually modified.
    """
    session_to_transcript = {
        sid: entry["transcript_path"]
        for sid, entry in manifest.items()
        if entry.get("transcript_path")
    }
    updated = 0
    for wiki_path in Path(wiki_dir).rglob("*.md"):
        if wiki_path.name == "_index.md":
            continue
        if add_transcript_to_wiki_sources(str(wiki_path), session_to_transcript):
            updated += 1
    return updated


# ── Transcript Append Delta ───────────────────────────────────────────────────

def append_delta_to_transcript(transcript_path: str, new_messages: list, new_last_uuid: str) -> bool:
    """
    把新 messages 追加到 transcript 的 delta marker 前，並更新 frontmatter。
    回傳 True 若成功。
    """
    try:
        content = Path(transcript_path).read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] append_delta_to_transcript read {transcript_path}: {e}", file=sys.stderr)
        return False

    # 找 delta marker
    marker_pattern = r'\n---\n\n<!-- delta marker: last_processed_msg_uuid=([^\s]+) -->\n'
    marker_match = re.search(marker_pattern, content)
    if not marker_match:
        return False

    marker_start = marker_match.start()
    new_msgs_md_parts = []
    for msg in new_messages:
        role = msg.get("role", "")
        text = msg.get("text", "").strip()
        ts = msg.get("timestamp", "")
        if not text:
            continue
        new_msgs_md_parts.append(format_message_header(role, ts))
        new_msgs_md_parts.append("")
        new_msgs_md_parts.append(text)
        new_msgs_md_parts.append("")

    if not new_msgs_md_parts:
        return False

    new_block = "\n" + "\n".join(new_msgs_md_parts)
    new_marker = f"\n---\n\n<!-- delta marker: last_processed_msg_uuid={new_last_uuid} -->\n"

    new_content = content[:marker_start] + new_block + new_marker + content[marker_match.end():]

    # 更新 frontmatter 的 last_processed_msg_uuid 和 message_count
    def update_fm_field(text, key, value):
        return re.sub(rf'^({key}:\s*).*$', rf'\g<1>{value}', text, flags=re.MULTILINE)

    fm_match = re.match(r'^(---\s*\n)(.*?)(\n---\s*\n)(.*)', new_content, re.DOTALL)
    if fm_match:
        fm_open, fm_body, fm_close, body_rest = fm_match.groups()
        fm_body = update_fm_field(fm_body, 'last_processed_msg_uuid', new_last_uuid)
        now_ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        fm_body = update_fm_field(fm_body, 'last_processed_at', now_ts)
        # message_count: 更新（增加 delta 數量）
        total_new = len([m for m in new_messages if m.get('text', '').strip()])
        old_count_m = re.search(r'^message_count:\s*(\d+)', fm_body, re.MULTILINE)
        if old_count_m:
            old_count = int(old_count_m.group(1))
            fm_body = update_fm_field(fm_body, 'message_count', str(old_count + total_new))
        fm_body = update_fm_field(fm_body, 'status', 'processed')
        new_content = fm_open + fm_body + fm_close + body_rest

    Path(transcript_path).write_text(new_content, encoding="utf-8")
    return True


# ── Transcripts Index ─────────────────────────────────────────────────────────

def rebuild_transcripts_index(transcripts_dir: str) -> None:
    """重建 transcripts/_index.md（按日期倒序）。"""
    entries = []
    for p in Path(transcripts_dir).glob("*.md"):
        if p.name == "_index.md":
            continue
        try:
            content = p.read_text(encoding="utf-8")
            fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if not fm_match:
                continue
            fm = fm_match.group(1)
            title_m = re.search(r'^title:\s*(.+)$', fm, re.MULTILINE)
            date_m = re.search(r'^date:\s*(.+)$', fm, re.MULTILINE)
            session_m = re.search(r'^session_id:\s*(.+)$', fm, re.MULTILINE)
            status_m = re.search(r'^status:\s*(.+)$', fm, re.MULTILINE)
            title = title_m.group(1).strip() if title_m else p.stem
            date = date_m.group(1).strip() if date_m else "?"
            session = session_m.group(1).strip()[:8] if session_m else "?"
            status = status_m.group(1).strip() if status_m else "?"
            entries.append((date, title, session, status, p.name))
        except Exception as e:
            print(f"[WARN] rebuild_transcripts_index parse {p.name}: {e}", file=sys.stderr)
            continue

    entries.sort(key=lambda x: x[0], reverse=True)

    lines = [
        "# Transcripts Index",
        "",
        "> 所有 session 的清理後完整對話歸檔。按日期倒序排列。",
        f"> 最後更新：{datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}",
        f"> 總計：{len(entries)} 個 transcripts",
        "",
        "| 日期 | 標題 | Session | 狀態 |",
        "|------|------|---------|------|",
    ]
    for date, title, session, status, fname in entries:
        lines.append(f"| {date} | [{title}]({fname}) | `{session}` | {status} |")

    index_path = os.path.join(transcripts_dir, "_index.md")
    Path(index_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Session JSONL 掃描工具 ────────────────────────────────────────────────────

def find_jsonl_files() -> list:
    """找出所有 ~/.claude/projects/**/*.jsonl，排除特定目錄和檔案。"""
    files = []
    for jsonl_path in glob.glob(os.path.join(PROJECTS_DIR, "**", "*.jsonl"), recursive=True):
        parts = os.path.normpath(jsonl_path).split(os.sep)
        if any(d in EXCLUDE_DIRS for d in parts):
            continue
        if os.path.basename(jsonl_path) in EXCLUDE_FILES:
            continue
        files.append(jsonl_path)
    return files


def get_last_message_uuid(filepath: str) -> str:
    """讀取 JSONL 檔案，取得最後一則 user/assistant message 的 uuid。"""
    last_uuid = ""
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("isMeta"):
                        continue
                    msg = obj.get("message", {})
                    role = msg.get("role", "")
                    if role in ("user", "assistant"):
                        uuid = obj.get("uuid", "")
                        if uuid:
                            last_uuid = uuid
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"[WARN] get_last_message_uuid {filepath}: {e}", file=sys.stderr)
    return last_uuid
