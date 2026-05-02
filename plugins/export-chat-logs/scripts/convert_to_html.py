#!/usr/bin/env python3
"""
Convert Claude Code JSONL chat logs to standalone HTML format.
Usage: python3 convert_to_html.py <input.jsonl> <output_dir> [--days N]
"""

import sys
import os
import re
import html as _html
sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from common import S, LANG_CODE, CSS_BASE_VARS, safe_format_ts, resolve_display_title, converter_main

# ── CSS ────────────────────────────────────────────────────────────────────────

_CSS = CSS_BASE_VARS + """
:root {
  --user-bg: #eff6ff; --user-border: #60a5fa;
  --assistant-bg: #f0fdf4; --assistant-border: #4ade80;
  --code-bg: #f6f8fa;
}
@media (prefers-color-scheme: dark) {
  :root {
    --user-bg: #1c2a3d; --user-border: #388bfd;
    --assistant-bg: #152320; --assistant-border: #3fb950;
    --code-bg: #161b22;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text);
  background: var(--bg);
}
.container { max-width: 900px; margin: 0 auto; padding: 24px 16px; }
header {
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border);
}
header h1 {
  font-size: 20px;
  font-weight: 600;
  margin-bottom: 10px;
  word-break: break-word;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 20px;
  font-size: 12px;
  color: var(--text-muted);
}
.meta-item b { color: var(--text); font-weight: 500; }
.message {
  margin-bottom: 8px;
  border-radius: 8px;
  border: 1px solid var(--border);
  overflow: hidden;
}
.message.user  { border-left: 3px solid var(--user-border); }
.message.assistant { border-left: 3px solid var(--assistant-border); }
.msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  font-size: 11px;
  background: var(--bg-alt);
  border-bottom: 1px solid var(--border);
}
.message.user .msg-header      { background: var(--user-bg); }
.message.assistant .msg-header { background: var(--assistant-bg); }
.msg-role { font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; }
.msg-time { color: var(--text-muted); margin-left: auto; }
.msg-body { padding: 12px 16px; overflow-x: auto; }
.msg-body p  { margin: 0 0 8px; }
.msg-body p:last-child { margin-bottom: 0; }
.msg-body h1 { font-size: 17px; margin: 12px 0 4px; font-weight: 600; }
.msg-body h2 { font-size: 15px; margin: 10px 0 4px; font-weight: 600; }
.msg-body h3, .msg-body h4, .msg-body h5, .msg-body h6
             { font-size: 14px; margin: 8px 0 4px; font-weight: 600; }
.msg-body ul, .msg-body ol { margin: 4px 0 8px 22px; }
.msg-body li { margin-bottom: 2px; }
.msg-body hr { border: none; border-top: 1px solid var(--border); margin: 10px 0; }
.msg-body pre {
  margin: 8px 0;
  border-radius: 6px;
  overflow-x: auto;
  border: 1px solid var(--border);
}
.msg-body pre code.hljs { border-radius: 6px; font-size: 12px; }
.msg-body code {
  font-family: ui-monospace, "SFMono-Regular", "SF Mono", Menlo, Consolas, monospace;
  font-size: 12px;
  background: var(--code-bg);
  padding: 2px 5px;
  border-radius: 4px;
  border: 1px solid var(--border);
}
.msg-body pre > code { background: transparent; padding: 0; border: none; }
.msg-body a { color: var(--link); text-decoration: none; }
.msg-body a:hover { text-decoration: underline; }
.msg-body strong { font-weight: 600; }
.msg-body em { font-style: italic; }
.msg-body blockquote {
  border-left: 3px solid var(--border);
  padding: 4px 12px;
  color: var(--text-muted);
  margin: 8px 0;
  background: var(--bg-alt);
  border-radius: 0 4px 4px 0;
}
.msg-body blockquote p { margin: 0; }
.msg-body table { border-collapse: collapse; margin: 8px 0; font-size: 13px; }
.msg-body th, .msg-body td { border: 1px solid var(--border); padding: 5px 10px; }
.msg-body th { background: var(--bg-alt); font-weight: 600; }
"""

# ── Markdown → HTML conversion ─────────────────────────────────────────────────

def _extract_tables(text):
    """Extract GFM tables from text, replacing with \x00TB{n}\x00 placeholders.
    Returns (new_text, tables) where tables is a list of rendered <table> HTML strings.
    Falls back silently to (text, []) on any error.
    """
    try:
        import html

        def _render_cell_inline(s):
            s = html.escape(s)
            s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
            s = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', s)
            s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
            s = re.sub(r'\*(.+?)\*', r'<em>\1</em>', s)
            s = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', s)
            s = s.replace('\x00PIPE\x00', '&#124;')
            return s

        def _split_cells(line):
            line = line.replace(r'\|', '\x00PIPE\x00')
            cells = line.split('|')
            # Strip whitespace and filter leading/trailing empty strings from | a | b | format
            cells = [c.strip() for c in cells]
            if cells and cells[0] == '':
                cells = cells[1:]
            if cells and cells[-1] == '':
                cells = cells[:-1]
            return cells

        def _is_separator_cell(cell):
            return bool(re.match(r'^:?-{3,}:?$', cell))

        def _col_align(cell):
            if re.match(r'^:-{3,}:$', cell):
                return 'text-align:center'
            elif re.match(r'^:-{3,}$', cell):
                return 'text-align:left'
            elif re.match(r'^-{3,}:$', cell):
                return 'text-align:right'
            else:
                return 'text-align:left'

        lines = text.split('\n')
        tables = []
        result_lines = []
        i = 0
        while i < len(lines):
            # Check for table: current line is header, next line is separator
            if i + 1 < len(lines):
                header_cells = _split_cells(lines[i])
                sep_cells = _split_cells(lines[i + 1])
                if (header_cells and sep_cells
                        and len(sep_cells) == len(header_cells)
                        and all(_is_separator_cell(c) for c in sep_cells)):
                    # Valid table found
                    aligns = [_col_align(c) for c in sep_cells]
                    col_count = len(header_cells)

                    # Collect body rows
                    body_rows = []
                    j = i + 2
                    while j < len(lines):
                        row_cells = _split_cells(lines[j])
                        # A row must have at least one pipe or be non-empty; stop on blank line
                        if not lines[j].strip() or '|' not in lines[j] and len(row_cells) < 2:
                            break
                        body_rows.append(row_cells)
                        j += 1

                    # Build HTML
                    thead_cells = ''.join(
                        f'<th style="{aligns[ci]}">{_render_cell_inline(header_cells[ci])}</th>'
                        for ci in range(col_count)
                    )
                    tbody_rows_html = []
                    for row in body_rows:
                        # Pad or truncate
                        padded = row[:col_count] + [''] * max(0, col_count - len(row))
                        tbody_rows_html.append(
                            '<tr>' + ''.join(
                                f'<td style="{aligns[ci]}">{_render_cell_inline(padded[ci])}</td>'
                                for ci in range(col_count)
                            ) + '</tr>'
                        )
                    tbody_html = '\n'.join(tbody_rows_html)
                    table_html = (
                        f'<table>\n'
                        f'<thead><tr>{thead_cells}</tr></thead>\n'
                        f'<tbody>\n{tbody_html}\n</tbody>\n'
                        f'</table>'
                    )
                    placeholder = f'\x00TB{len(tables)}\x00'
                    tables.append(table_html)
                    result_lines.append(placeholder)
                    i = j
                    continue
            result_lines.append(lines[i])
            i += 1

        return '\n'.join(result_lines), tables
    except Exception:
        return text, []


def _md_to_html(text):
    """Convert a Markdown subset to HTML. Input is raw (not yet escaped)."""
    # Step 1: Extract triple-backtick code fences before escaping
    code_blocks = []

    def _extract_fence(m):
        lang = (m.group(2) or "").strip()
        code_content = _html.escape(m.group(3))
        lang_attr = f' class="language-{lang}"' if lang else ""
        code_blocks.append(f"<pre><code{lang_attr}>{code_content}</code></pre>")
        return f"\x00CB{len(code_blocks)-1}\x00"

    # Pairs with common.py:clean_string_content — accepts any N-tick fence emitted there (N >= 3).
    text = re.sub(r"(`{3,})(\w*)\n(.*?)\1", _extract_fence, text, flags=re.DOTALL)

    # Step 1.5: Extract GFM tables (after code fence extraction to prevent parsing tables inside code blocks)
    text, tables = _extract_tables(text)

    # Step 2: HTML-escape non-placeholder parts
    parts = re.split(r"(\x00(?:CB|TB)\d+\x00)", text)
    escaped = []
    for p in parts:
        if re.match(r"\x00(?:CB|TB)\d+\x00", p):
            escaped.append(p)
        else:
            escaped.append(_html.escape(p))
    text = "".join(escaped)

    # Step 3: Inline code `...`
    text = re.sub(r"`([^`\n]+)`", lambda m: f"<code>{m.group(1)}</code>", text)

    # Step 4: Bold+italic ***...***  bold **...**  italic *...*
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<strong><em>\1</em></strong>", text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.+?)\*\*",     r"<strong>\1</strong>",         text, flags=re.DOTALL)
    text = re.sub(r"\*([^*\n]+)\*",     r"<em>\1</em>",                 text)

    # Step 5: Links [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )

    # Step 6: Headings (match at line start)
    for n in range(6, 0, -1):
        text = re.sub(
            rf"^{'#' * n} (.+)$",
            rf"<h{n}>\1</h{n}>",
            text,
            flags=re.MULTILINE,
        )

    # Step 7: Horizontal rules (3+ dashes on their own line)
    text = re.sub(r"^-{3,}$", "<hr>", text, flags=re.MULTILINE)

    # Step 8: Unordered lists
    lines = text.split("\n")
    result_lines = []
    in_list = False
    for line in lines:
        lm = re.match(r"^[-*] (.+)$", line)
        if lm:
            if not in_list:
                result_lines.append("<ul>")
                in_list = True
            result_lines.append(f"<li>{lm.group(1)}</li>")
        else:
            if in_list:
                result_lines.append("</ul>")
                in_list = False
            result_lines.append(line)
    if in_list:
        result_lines.append("</ul>")
    text = "\n".join(result_lines)

    # Step 9: Blockquotes  (html.escape turned > into &gt;)
    lines = text.split("\n")
    result_lines = []
    in_bq = False
    for line in lines:
        bm = re.match(r"^&gt; (.+)$", line)
        if bm:
            if not in_bq:
                result_lines.append("<blockquote>")
                in_bq = True
            result_lines.append(f"<p>{bm.group(1)}</p>")
        else:
            if in_bq:
                result_lines.append("</blockquote>")
                in_bq = False
            result_lines.append(line)
    if in_bq:
        result_lines.append("</blockquote>")
    text = "\n".join(result_lines)

    # Step 10: Paragraphs — split on blank lines
    _BLOCK = re.compile(r"^<(h[1-6]|pre|ul|ol|blockquote|hr|div|table)[ >]|^<hr>")
    paragraphs = re.split(r"\n\n+", text)
    result = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        lines_in = para.split("\n")
        if any(_BLOCK.match(l) or l.startswith(("\x00CB", "\x00TB")) for l in lines_in):
            result.append(para)
        else:
            inner = "<br>\n".join(l for l in lines_in)
            if inner.strip():
                result.append(f"<p>{inner}</p>")
    text = "\n".join(result)

    # Step 11: Restore code blocks and tables
    def _restore_placeholder(m):
        kind, idx = m.group(1), int(m.group(2))
        return code_blocks[idx] if kind == "CB" else tables[idx]
    text = re.sub(r"\x00(CB|TB)(\d+)\x00", _restore_placeholder, text)
    return text


# ── HTML formatter ─────────────────────────────────────────────────────────────

def format_html(messages, first_ts, cwd=None, title=None, models=None, source_label=None, first_user_message="", session_id=""):
    display_title_raw, source_display = resolve_display_title(title, cwd, source_label, first_user_message)
    display_title = _html.escape(display_title_raw)
    lang_attr = LANG_CODE
    git_user = os.environ.get("GIT_USER_NAME", "")

    date_str = safe_format_ts(first_ts) if first_ts else ""

    # Build meta items
    meta_items = []
    if date_str:
        meta_items.append(f'<span class="meta-item">{_html.escape(S["label_date"])}: <b>{_html.escape(date_str)}</b></span>')
    if cwd:
        folder_name = _html.escape(Path(cwd).name or cwd)
        meta_items.append(f'<span class="meta-item">{_html.escape(S["label_project"])}: <b>{folder_name}</b></span>')
    meta_items.append(f'<span class="meta-item">{_html.escape(S["label_source"])}: <b>{_html.escape(source_display)}</b></span>')
    if models:
        meta_items.append(f'<span class="meta-item">{_html.escape(S["label_model"])}: <b>{_html.escape(", ".join(models))}</b></span>')
    meta_items.append(f'<span class="meta-item">{_html.escape(S["label_messages"])}: <b>{len(messages)}</b></span>')

    # Build message HTML
    msgs_html_parts = []
    if not messages:
        msgs_html_parts.append(f'<p class="no-messages">{_html.escape(S["no_messages"])}</p>')
    else:
        for role, text, ts, uuid in messages:
            ts_str = safe_format_ts(ts, fallback="") if ts else ""
            role_label = S["role_user"] if role == "user" else S["role_assistant"]
            body_html = _md_to_html(text)
            msgs_html_parts.append(
                f'<!-- uuid: {uuid} -->'
                f'<div class="message {_html.escape(role)}">'
                f'<div class="msg-header">'
                f'<span class="msg-role">{_html.escape(role_label)}</span>'
                + (f'<span class="msg-time">{_html.escape(ts_str)}</span>' if ts_str else "")
                + f'</div>'
                f'<div class="msg-body">{body_html}</div>'
                f'</div>'
            )

    meta_html = "\n    ".join(meta_items)
    msgs_html = "\n    ".join(msgs_html_parts)

    return f"""<!DOCTYPE html>
<html lang="{lang_attr}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{display_title}</title>
  <link rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css"
    media="(prefers-color-scheme: light)">
  <link rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css"
    media="(prefers-color-scheme: dark)">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
  <style>{_CSS}</style>
</head>
<body><!-- sid: {session_id} --><!-- git_user: {git_user} -->
  <div class="container">
    <header>
      <h1>{display_title}</h1>
      <div class="meta">
    {meta_html}
      </div>
    </header>
    <div class="messages">
    {msgs_html}
    </div>
  </div>
  <script>document.addEventListener("DOMContentLoaded", () => hljs.highlightAll());</script>
</body>
</html>"""


if __name__ == "__main__":
    converter_main(format_html, ".html")
