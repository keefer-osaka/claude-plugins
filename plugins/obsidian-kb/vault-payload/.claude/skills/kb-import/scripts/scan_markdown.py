#!/usr/bin/env python3
"""
scan_markdown.py — 解析 export-chat-logs 產生的 zip（或目錄），輸出與 scan_sessions.py 相容的 JSON。

用法：
  python3 scan_markdown.py <chat-logs-alice-20260417.zip>
  python3 scan_markdown.py --dir <已解壓目錄>
  python3 scan_markdown.py               # 掃描 $KB_IMPORT_INBOX 或 ~/Downloads/kb-inbox
"""

import html as _html
import json
import os
import re
import sys
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone

# ── _lib ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LIB_DIR = os.path.join(SCRIPT_DIR, "..", "..", "_lib")
sys.path.insert(0, LIB_DIR)

# transcript_utils path
INGEST_SCRIPTS = os.path.join(SCRIPT_DIR, "..", "..", "kb-ingest", "scripts")
sys.path.insert(0, INGEST_SCRIPTS)

from message_delta import filter_messages_after_uuid
from transcript_utils import read_sessions_json
from wiki_utils import resolve_vault_dir, format_tw_date

VAULT_DIR = resolve_vault_dir(__file__)

# ── Author 抽取 ───────────────────────────────────────────────────────────────

_ZIP_AUTHOR_RE = re.compile(r'^chat-logs-([^-]+)-\d{8}.*\.zip$')


def author_from_zip_name(zip_path: str) -> str:
    basename = re.sub(r'^[^\w]+', '', os.path.basename(zip_path))
    m = _ZIP_AUTHOR_RE.match(basename)
    return m.group(1) if m else "unknown"


def author_from_dir(dir_path: str) -> str:
    author_file = os.path.join(dir_path, "author.txt")
    if os.path.exists(author_file):
        try:
            return open(author_file).read().strip() or "unknown"
        except Exception:
            pass
    return "unknown"


# ── MD 解析 ───────────────────────────────────────────────────────────────────

_SID_RE = re.compile(r'<!--\s*sid:\s*([^\s>]+)\s*-->')
_GIT_USER_RE = re.compile(r'<!--\s*git_user:\s*([^\s>]+)\s*-->')
_UUID_RE = re.compile(r'<!--\s*uuid:\s*([^\s>]+)\s*-->')
# Matches each message block in HTML files exported by convert_to_html.py.
# Depends on the template structure in convert_to_html.py::format_html.
# If the template changes (class names, DOM order), update this regex too.
_HTML_MSG_RE = re.compile(
    r'<!--\s*uuid:\s*([^\s>]+)\s*-->'
    r'<div class="message\s+(user|assistant)">'
    r'<div class="msg-header">'
    r'<span class="msg-role">[^<]*</span>'
    r'(?:<span class="msg-time">([^<]*)</span>)?'
    r'</div>'
    r'<div class="msg-body">(.*?)</div>'
    r'</div>',
    re.DOTALL,
)
# Match: ### User · 2026-04-17 12:34 UTC+8  or  ### Assistant · ...
_MSG_HEADING_RE = re.compile(
    r'^###\s+(User|Assistant|使用者|助理|ユーザー|アシスタント)\s*(?:[·•]\s*(.+))?$'
)
_ROLE_MAP = {
    "User": "user", "使用者": "user", "ユーザー": "user",
    "Assistant": "assistant", "助理": "assistant", "アシスタント": "assistant",
}


def _ts_from_heading(ts_str: str) -> str:
    """Try to parse a timestamp string from the heading suffix. Return ISO or empty."""
    if not ts_str:
        return ""
    ts_str = ts_str.strip()
    # Try ISO-like patterns: 2026-04-17 12:34 UTC+8
    m = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', ts_str)
    if m:
        return m.group(1)
    return ts_str


def _html_to_md(html_str: str) -> str:
    """Reverse convert_to_html.py::_md_to_html for msg-body content."""
    code_blocks = []

    def _extract_fence(m):
        lang_class = m.group(1) or ""
        lang = re.sub(r'^language-', '', lang_class)
        body = _html.unescape(m.group(2))
        code_blocks.append(f"```{lang}\n{body}\n```")
        return f"\x00CB{len(code_blocks)-1}\x00"

    # Step 1: protect fenced code blocks (with or without language class)
    html_str = re.sub(
        r'<pre><code(?:\s+class="([^"]*)")?>(.*?)</code></pre>',
        _extract_fence, html_str, flags=re.DOTALL,
    )
    # Step 2: inline code
    html_str = re.sub(r'<code>([^<]*)</code>', r'`\1`', html_str)
    # Step 3: bold+italic (combined first, then individual)
    html_str = re.sub(r'<strong><em>(.*?)</em></strong>', r'***\1***', html_str, flags=re.DOTALL)
    html_str = re.sub(r'<strong>(.*?)</strong>', r'**\1**', html_str, flags=re.DOTALL)
    html_str = re.sub(r'<em>(.*?)</em>', r'*\1*', html_str, flags=re.DOTALL)
    # Step 4: links
    html_str = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', html_str, flags=re.DOTALL)
    # Step 5: headings h6→h1 (longest first to avoid partial match)
    for n in range(6, 0, -1):
        html_str = re.sub(
            rf'<h{n}>(.*?)</h{n}>',
            lambda m, n=n: '#' * n + ' ' + m.group(1),
            html_str, flags=re.DOTALL,
        )
    # Step 6: horizontal rule
    html_str = html_str.replace('<hr>', '---')
    # Step 7: list items then ul wrapper
    html_str = re.sub(r'<li>(.*?)</li>', r'- \1', html_str, flags=re.DOTALL)
    html_str = re.sub(r'<ul>(.*?)</ul>', lambda m: m.group(1).strip(), html_str, flags=re.DOTALL)
    # Step 8: blockquotes (strip inner <p> tags then prefix lines with '> ')
    def _bq(m):
        inner = re.sub(r'<p>(.*?)</p>', r'\1', m.group(1), flags=re.DOTALL).strip()
        return '\n'.join('> ' + line for line in inner.split('\n'))
    html_str = re.sub(r'<blockquote>(.*?)</blockquote>', _bq, html_str, flags=re.DOTALL)
    # Step 9: paragraphs (after blockquote already stripped its inner <p> tags)
    html_str = re.sub(r'<p>(.*?)</p>', r'\1\n\n', html_str, flags=re.DOTALL)
    # Step 10: line breaks
    html_str = re.sub(r'<br\s*/?>', '\n', html_str)
    # Step 11: restore code blocks
    html_str = re.sub(r'\x00CB(\d+)\x00', lambda m: code_blocks[int(m.group(1))], html_str)
    # Step 12: unescape HTML entities (must be last)
    return _html.unescape(html_str).strip()


def parse_html_file(html_path: str) -> dict | None:
    """Parse a single session .html file exported by convert_to_html.py."""
    try:
        content = open(html_path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None

    # sid and git_user are in the <body> opening tag (~first 2000 chars)
    head = content[:2000]
    session_id = ""
    git_user = ""
    m = _SID_RE.search(head)
    if m:
        session_id = m.group(1)
    m = _GIT_USER_RE.search(head)
    if m:
        git_user = m.group(1)

    messages = []
    for m in _HTML_MSG_RE.finditer(content):
        uuid_val = m.group(1)
        role     = m.group(2)           # "user" or "assistant"
        ts_str   = (m.group(3) or "").strip()
        body_html = m.group(4)
        text = _html_to_md(body_html)
        if text:
            messages.append({
                "uuid": uuid_val,
                "role": role,
                "text": text,
                "timestamp": ts_str,
            })

    return {
        "session_id": session_id,
        "git_user": git_user,
        "messages": messages,
        "md_path": html_path,
    }


def parse_md_file(md_path: str) -> dict | None:
    """Parse a single session .md file. Returns session dict or None on failure."""
    try:
        content = open(md_path, encoding="utf-8", errors="ignore").read()
    except Exception:
        return None

    lines = content.splitlines()

    # Extract top-level annotations
    session_id = ""
    git_user = ""
    for line in lines[:20]:
        if not session_id:
            m = _SID_RE.search(line)
            if m:
                session_id = m.group(1)
        if not git_user:
            m = _GIT_USER_RE.search(line)
            if m:
                git_user = m.group(1)
        if session_id and git_user:
            break

    # Parse messages
    messages = []
    pending_uuid = ""
    current_role = None
    current_ts = ""
    current_lines = []

    def _flush():
        if current_role is None:
            return
        text = "\n".join(current_lines).strip()
        if text:
            messages.append({
                "uuid": pending_uuid,
                "role": current_role,
                "text": text,
                "timestamp": current_ts,
            })

    for line in lines:
        uuid_m = _UUID_RE.match(line.strip())
        if uuid_m:
            pending_uuid = uuid_m.group(1)
            continue

        hdg_m = _MSG_HEADING_RE.match(line)
        if hdg_m:
            _flush()
            current_lines = []
            role_raw = hdg_m.group(1)
            current_role = _ROLE_MAP.get(role_raw, "user")
            current_ts = _ts_from_heading(hdg_m.group(2) or "")
            continue

        if current_role is not None:
            # Skip horizontal rules between messages
            if line.strip() == "---":
                continue
            current_lines.append(line)

    _flush()

    return {
        "session_id": session_id,
        "git_user": git_user,
        "messages": messages,
        "md_path": md_path,
    }


# ── 主邏輯 ────────────────────────────────────────────────────────────────────

def scan_dir(scan_path: str, author: str) -> list:
    """Walk scan_path for .md files and return session results list."""
    manifest = read_sessions_json()
    results = []
    skipped = []

    for root, _dirs, files in os.walk(scan_path):
        for fname in sorted(files):
            if fname.endswith(".md"):
                parser = parse_md_file
            elif fname.endswith(".html"):
                parser = parse_html_file
            else:
                continue
            # Skip index/stats files (not per-session)
            if fname.startswith("_") or fname in ("index.md", "index.html"):
                continue

            md_path = os.path.join(root, fname)
            parsed = parser(md_path)
            if not parsed:
                skipped.append({"path": md_path, "reason": "parse failed"})
                continue

            session_id = parsed["session_id"]
            effective_author = parsed["git_user"] or author

            if not session_id:
                # Old-format zip without <!-- sid --> — full import, derive id from filename
                session_id = os.path.splitext(fname)[0]
                delta = False
                last_uuid = ""
                messages = parsed["messages"]
            else:
                manifest_entry = manifest.get(session_id, {})
                existing_tp = manifest_entry.get("transcript_path", "")
                if existing_tp and os.path.exists(os.path.join(VAULT_DIR, existing_tp)):
                    existing_fname = os.path.basename(existing_tp)
                    is_stub = existing_fname.startswith("0000-00-00-")
                    if not is_stub:
                        skipped.append({"path": md_path, "reason": "session_id already ingested"})
                        continue
                    # stub → fall through to allow re-import (upsert_transcripts will clean old file)
                last_uuid = manifest_entry.get("last_processed_msg_uuid", "")
                base_transcript = manifest_entry.get("transcript_path", "")

                if last_uuid:
                    filtered, found = filter_messages_after_uuid(parsed["messages"], last_uuid)
                    if not found:
                        # Pivot not found — full import
                        messages = parsed["messages"]
                        delta = False
                        last_uuid = ""
                    elif not filtered:
                        skipped.append({"path": md_path, "reason": "no delta messages"})
                        continue
                    else:
                        messages = filtered
                        delta = True
                else:
                    messages = parsed["messages"]
                    delta = False
                    base_transcript = ""

            if not messages:
                skipped.append({"path": md_path, "reason": "no messages"})
                continue

            date_str = ""
            if messages:
                ts = messages[0].get("timestamp", "")
                if ts:
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        date_str = dt.strftime("%Y-%m-%d")
                    except Exception:
                        date_str = ts[:10] if len(ts) >= 10 else ""

            # Strip uuid from output messages (scan_sessions.py compat)
            out_messages = [
                {"role": m["role"], "text": m["text"], "timestamp": m["timestamp"]}
                for m in messages
            ]

            entry = {
                "session_id": session_id,
                "project_dir": effective_author,
                "jsonl_path": "",
                "title": session_id[:60],
                "cwd": "",
                "date": date_str,
                "first_ts": messages[0].get("timestamp", "") if messages else "",
                "last_ts": messages[-1].get("timestamp", "") if messages else "",
                "output_tokens": 0,
                "duration_seconds": None,
                "models": [],
                "message_count": len(out_messages),
                "messages": out_messages,
                "delta": delta,
                "base_transcript": base_transcript if delta else "",
                "transcript_stem": (
                    os.path.splitext(os.path.basename(base_transcript))[0]
                    if delta and base_transcript else None
                ),
                "author": effective_author,
                "source": "md-import",
            }
            results.append(entry)

    return results, skipped


def main():
    args = sys.argv[1:]
    zip_path = None
    scan_dir_path = None

    if "--dir" in args:
        idx = args.index("--dir")
        if idx + 1 < len(args):
            scan_dir_path = args[idx + 1]
    elif args and not args[0].startswith("-"):
        zip_path = args[0]
    else:
        inbox = os.environ.get("KB_IMPORT_INBOX", os.path.expanduser("~/Downloads/kb-inbox"))
        scan_dir_path = inbox

    tmpdir = None
    author = "unknown"

    try:
        if zip_path:
            author = author_from_zip_name(zip_path)
            tmpdir = tempfile.mkdtemp(prefix="kb-import-")
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmpdir)
            scan_dir_path = tmpdir

        elif scan_dir_path:
            if not os.path.isdir(scan_dir_path):
                print(json.dumps({"error": f"Directory not found: {scan_dir_path}"}))
                sys.exit(1)
            author = author_from_dir(scan_dir_path)

        results, skipped = scan_dir(scan_dir_path, author)

        output = {
            "scan_time": datetime.now(timezone.utc).isoformat(),
            "source": "md-import",
            "author": author,
            "total_candidates": len(results) + len(skipped),
            "candidates": len(results),
            "sessions": results,
            "skipped_count": len(skipped),
            "skipped": skipped[:10],
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))

    finally:
        if tmpdir and os.path.exists(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    main()
