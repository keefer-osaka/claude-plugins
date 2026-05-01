#!/usr/bin/env python3
"""Shared utilities for devtools-plugins scripts."""

import json
import re
import os
import sys
import importlib.util
from datetime import datetime, timezone, timedelta


def _load_env():
    env_path = os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "devtools-plugins", "export-chat-logs", ".env"
    )
    lang = "en"
    offset = 8
    try:
        with open(env_path) as f:
            for line in f:
                if line.startswith("PLUGIN_LANG="):
                    lang = line.split("=", 1)[1].strip().strip("'\"")
                elif line.startswith("TIMEZONE_OFFSET="):
                    try:
                        offset = int(line.split("=", 1)[1].strip())
                    except Exception:
                        pass
    except Exception:
        pass
    lang_file = lang.replace("-", "_")
    i18n_dir = os.path.join(os.path.dirname(__file__), "i18n")
    locale_path = os.path.join(i18n_dir, f"{lang_file}.py")
    if not os.path.exists(locale_path):
        locale_path = os.path.join(i18n_dir, "en.py")
    spec = importlib.util.spec_from_file_location("_locale", locale_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tz = timezone(timedelta(hours=offset))
    return mod.S, lang, tz, offset


S, LANG_CODE, TZ_LOCAL, TZ_OFFSET = _load_env()
TZ_LABEL = f"UTC{TZ_OFFSET:+d}"

# Shared CSS custom properties (base palette + dark mode) used by HTML output scripts
CSS_BASE_VARS = """\
:root {
  --bg: #ffffff; --bg-alt: #f6f8fa; --border: #d0d7de;
  --text: #1f2328; --text-muted: #656d76; --link: #0969da;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --bg-alt: #161b22; --border: #30363d;
    --text: #e6edf3; --text-muted: #8b949e; --link: #388bfd;
  }
}"""


def parse_ts(ts_str: str) -> datetime:
    """Parse a Claude timestamp string to a timezone-aware datetime."""
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def format_local_ts(ts_str: str) -> str:
    """Format a Claude timestamp as local time with timezone label."""
    return parse_ts(ts_str).astimezone(TZ_LOCAL).strftime("%Y-%m-%d %H:%M") + f" {TZ_LABEL}"


def safe_format_ts(ts_str: str, fallback=None) -> str:
    """Format a Claude timestamp; on error returns ts_str itself (or fallback if given)."""
    try:
        return format_local_ts(ts_str)
    except Exception:
        return ts_str if fallback is None else fallback


def compute_active_duration(timestamps) -> float:
    """Return active session time in seconds (sum of consecutive gaps <= 30 min)."""
    dts = [parse_ts(t) for t in timestamps]
    return sum(
        (dts[i] - dts[i - 1]).total_seconds()
        for i in range(1, len(dts))
        if (dts[i] - dts[i - 1]).total_seconds() <= 1800
    )


def _make_preview(text, max_len=40):
    """Return a short preview of text (first line, truncated). Empty string if nothing useful."""
    if not text:
        return ""
    first_line = text.split("\n")[0].strip()
    if not first_line:
        return ""
    if len(first_line) > max_len:
        return first_line[:max_len] + "…"
    return first_line


def resolve_display_title(title, cwd, source_label, first_user_message=""):
    """Return (display_title, source_display) based on session source."""
    preview = _make_preview(first_user_message)
    if source_label == "cowork":
        fallback = cwd.rstrip("/").split("/")[-1] if cwd else "Claude Cowork"
        return title or preview or fallback, S["source_name_cowork"]
    return title or preview or "Claude Code", S["source_name"]


def clean_string_content(text):
    """Clean string message content: strip control characters, simplify slash command XML."""
    text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text).strip()

    if re.match(r'<local-command-stdout>', text):
        return ''

    # Fence length must exceed max inner backtick run; see convert_to_html.py:_md_to_html
    # for the matching regex (must accept any N-tick fence with N >= 3).
    if re.match(r'<command-name>', text) or re.match(r'<command-message>', text):
        msg_m = re.search(r'<command-message>(.*?)</command-message>', text, re.DOTALL)
        name_m = re.search(r'<command-name>(.*?)</command-name>', text, re.DOTALL)
        args_m = re.search(r'<command-args>(.*?)</command-args>', text, re.DOTALL)

        head = ''
        if msg_m:
            msg = msg_m.group(1).strip()
            if msg:
                head = f"/{msg}"
        if not head and name_m:
            head = name_m.group(1).strip()

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
    """Extract only text-type blocks from a content array."""
    if isinstance(content, str):
        return clean_string_content(content)
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        t = block.get("type", "")
        if t == "text":
            text = clean_string_content(block.get("text", ""))
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def parse_session(filepath):
    """Parse a Claude Code session JSONL file. Returns comprehensive session data."""
    messages = []
    title = None
    cwd = None
    first_ts = None
    last_ts = None
    models_seen = []
    msg_timestamps = []
    input_tokens = 0
    output_tokens = 0
    cache_read = 0
    cache_creation = 0
    tool_counts = {}
    first_user_message = ""
    session_id = None

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

            if session_id is None:
                sid = obj.get("sessionId", "")
                if sid:
                    session_id = sid

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
                cache_read += usage.get("cache_read_input_tokens", 0)
                cache_creation += usage.get("cache_creation_input_tokens", 0)

            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if name:
                            tool_counts[name] = tool_counts.get(name, 0) + 1

            if role not in ("user", "assistant"):
                continue

            text = extract_text_blocks(content)
            if text.strip():
                messages.append((role, text.strip(), ts, uuid))
                if role == "user" and not first_user_message:
                    first_user_message = text.strip()

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
        "cache_read": cache_read,
        "cache_creation": cache_creation,
        "tool_counts": tool_counts,
        "first_user_message": first_user_message,
        "session_id": session_id or "",
    }


def is_trivial_stats(output_tokens, total_tokens, duration):
    """Check if pre-extracted session stats indicate a trivial (skippable) session."""
    if total_tokens == 0:
        return True
    if output_tokens >= 100:
        return False
    return duration is None or duration < 60


_META_COMMANDS = frozenset({
    "/exit", "/compact", "/clear", "/help", "/init", "/login", "/logout",
    "/config", "/cost", "/doctor", "/memory", "/permissions", "/review",
    "/status", "/terminal-setup", "/vim", "/fast", "/slow",
})


def is_skill_only_session(messages, tool_counts=None):
    """Check if session is a single slash-command invocation with no real discussion."""
    if tool_counts and "AskUserQuestion" in tool_counts:
        return False
    user_msgs = [text for role, text, *_ in messages if role == "user"]
    if not user_msgs:
        return True
    if not all(re.match(r"^/\S+\s*$", m) for m in user_msgs):
        return False
    skills = [m for m in user_msgs if m.strip() not in _META_COMMANDS]
    return len(skills) <= 1


def make_output_path(out_dir, first_ts, title, ext=".md"):
    """Generate output filename based on date and title."""
    if first_ts:
        try:
            dt = parse_ts(first_ts).astimezone(TZ_LOCAL)
            date_str = f"{dt.strftime('%Y-%m-%d_%H-%M-%S')}-{dt.microsecond // 1000:03d}"
        except Exception:
            date_str = "unknown"
    else:
        date_str = "unknown"

    if title:
        title_safe = re.sub(r'[^\w\-]', '_', title)[:60].strip('_')
        filename = f"{date_str}_{title_safe}{ext}"
    else:
        filename = f"{date_str}{ext}"
    return os.path.join(out_dir, filename)


def converter_main(format_fn, ext):
    """Shared main() logic for JSONL → file converters."""
    if len(sys.argv) < 3:
        print("Usage: python3 <script> <input.jsonl> <output_dir> [--days N] [--source-label LABEL]")
        sys.exit(1)
    input_path = sys.argv[1]
    out_dir = sys.argv[2]
    days_filter = None
    source_label = None
    if "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            try:
                days_filter = int(sys.argv[idx + 1])
            except ValueError:
                pass
    if "--source-label" in sys.argv:
        idx = sys.argv.index("--source-label")
        if idx + 1 < len(sys.argv):
            source_label = sys.argv[idx + 1]
    session = parse_session(input_path)
    messages = session["messages"]
    first_ts = session["first_ts"]
    last_ts = session["last_ts"]
    title = session["title"]
    cwd = session["cwd"]
    models = session["models"]
    first_user_message = session.get("first_user_message", "")
    if not first_ts:
        mtime = os.path.getmtime(input_path)
        first_ts = datetime.fromtimestamp(mtime, tz=TZ_LOCAL).isoformat()
    # Skip trivial sessions (no meaningful interaction)
    total_tokens = session["input_tokens"] + session["output_tokens"]
    tss = session["msg_timestamps"]
    duration = compute_active_duration(tss) if len(tss) >= 2 else None
    if is_trivial_stats(session["output_tokens"], total_tokens, duration):
        sys.exit(2)
    if is_skill_only_session(messages, session["tool_counts"]):
        sys.exit(2)
    active_ts = last_ts or first_ts
    if days_filter is not None and active_ts:
        try:
            dt_check = parse_ts(active_ts).astimezone(timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_filter)
            if dt_check < cutoff:
                sys.exit(3)
        except Exception:
            pass
    content = format_fn(messages, active_ts, cwd=cwd, title=title, models=models, source_label=source_label, first_user_message=first_user_message, session_id=session.get("session_id", ""))
    os.makedirs(out_dir, exist_ok=True)
    output_path = make_output_path(out_dir, active_ts, title, ext=ext)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(S["msg_done_convert"].format(n=len(messages), path=output_path))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--extract-cwd":
        with open(sys.argv[2], encoding="utf-8", errors="ignore") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _obj = json.loads(_line)
                    _cwd = _obj.get("cwd", "")
                    if _cwd:
                        print(_cwd.rstrip("/").split("/")[-1])
                        break
                except Exception:
                    pass
