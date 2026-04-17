#!/usr/bin/env python3
"""
kb-lint: 知識庫健康檢查腳本

檢查項目：
1. canonical_drift  — canonical_files 對照現實漂移
2. broken_links     — wikilink 指向不存在的頁面
3. orphaned_pages   — 無任何 wikilink 指向的頁面
4. missing_sources  — sources 欄位為空
5. contradicted     — status: contradicted 超過 30 天未處理
6. index_missing    — 存在於 wiki/ 但未列入 _index.md
7. stale_pages      — status: stale（超過 90 天未更新）
"""

import os
import re
import sys
from pathlib import Path
from datetime import date, datetime

# ── _lib 共用模組 ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))
from wiki_utils import resolve_vault_dir, parse_frontmatter, WIKILINK_RE, TW_TZ  # noqa: E402

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
VAULT_DIR = Path(resolve_vault_dir(__file__))
WIKI_DIR = VAULT_DIR / "wiki"
REPORT_PATH = WIKI_DIR / "meta" / "lint-report.md"

TODAY = datetime.now(TW_TZ).date()


# ── 頁面收集 ──────────────────────────────────────────────────────────────────

TOP_LEVEL_SKIP = {"hot.md", "index.md", "log.md", "overview.md"}

def find_all_wiki_pages():
    pages = []
    for p in WIKI_DIR.rglob("*.md"):
        if p.name.startswith("_") or p.name in TOP_LEVEL_SKIP:
            continue
        rel_parts = p.relative_to(WIKI_DIR).parts
        if rel_parts[0] == "meta":
            continue
        pages.append(p)
    return pages

def find_all_index_entries():
    """從所有 _index.md 收集已列入的 wiki 連結"""
    entries = set()
    for idx in WIKI_DIR.rglob("_index.md"):
        text = idx.read_text(encoding="utf-8")
        for m in WIKILINK_RE.findall(text):
            entries.add(m.lower().replace(" ", "-"))
        for m in re.findall(r'\[.*?\]\(([^)]+\.md)\)', text):
            entries.add(Path(m).stem.lower())
    return entries


# ── 各項檢查 ──────────────────────────────────────────────────────────────────

def extract_code_values(body):
    """只從 code block 中提取技術值，避免散文說明的假陽性。"""
    candidates = set()
    for block in re.findall(r'```[^\n]*\n(.*?)```', body, re.DOTALL):
        for m in re.findall(r'["\']([^\x00-\x1f"\']{3,60})["\']', block):
            if m.isascii():
                candidates.add(m)
        for m in re.findall(r'v\d+\.\d+(?:\.\d+)?', block):
            candidates.add(m)
        for m in re.findall(r'(?:~|/[\w])[/\w.-]{4,60}', block):
            if m.isascii():
                candidates.add(m)
    for val in re.findall(r'`([^`\n]{3,60})`', body):
        if val.isascii() and not re.search(r'\s{2,}', val):
            candidates.add(val)
    skip = {"0", "1", "true", "false", "null", "yes", "no", "env",
            "json", "yaml", "md", "sh", "py", "bash", "zsh", "cat",
            "grep", "sed", "awk", "echo", "key", "val", "type", "name"}
    return {c for c in candidates if c not in skip}


def check_canonical_drift(parsed_pages):
    """對有 canonical_files 的頁面，從 code block 比對值是否仍在 canonical file 中。"""
    issues = []
    for page, _text, fm, body in parsed_pages:
        if "canonical_drift" in fm.get("lint_ignore", []):
            continue
        canonical_files = fm.get("canonical_files", [])
        if not canonical_files:
            continue

        # 讀取 canonical files（統一展開 ~ 一次）
        missing_cfs = []
        cf_contents = {}
        for cf in canonical_files:
            cf_path = Path(cf).expanduser()
            if not cf_path.exists():
                missing_cfs.append(cf)
            else:
                cf_contents[cf] = cf_path.read_text(encoding="utf-8")

        for cf in missing_cfs:
            issues.append({"page": page, "type": "file_missing",
                           "detail": f"canonical file 不存在：`{cf}`"})

        if not cf_contents:
            continue

        candidates = extract_code_values(body)

        # 過濾 canonical file 路徑本身
        cf_paths_resolved = {Path(cf).expanduser() for cf in canonical_files}
        cf_basenames = {p.name for p in cf_paths_resolved}
        cf_paths_raw = set(canonical_files)
        candidates = {
            c for c in candidates
            if c not in cf_basenames
            and c not in cf_paths_raw
            and not any(c.endswith(p.name) for p in cf_paths_resolved)
        }

        all_cf_content = "\n".join(cf_contents.values())
        drifted = [val for val in sorted(candidates) if val not in all_cf_content]

        if drifted:
            cf_list = ", ".join(f"`{cf}`" for cf in canonical_files)
            issues.append({
                "page": page,
                "type": "value_drift",
                "detail": f"以下值在 wiki code block 中提及，但未出現在 {cf_list} 中：\n"
                          + "\n".join(f"  - `{v}`" for v in drifted[:10])
            })
    return issues


def check_broken_links(parsed_pages):
    """wikilink [[xxx]] 指向不存在的頁面"""
    all_stems = {page.stem.lower() for page, *_ in parsed_pages}
    transcripts_dir = VAULT_DIR / "transcripts"
    if transcripts_dir.exists():
        for p in transcripts_dir.glob("*.md"):
            all_stems.add(p.stem.lower())
    FENCED_CODE_RE = re.compile(r'```.*?```', re.DOTALL)
    CODE_SPAN_RE = re.compile(r'``[^`].*?``|`[^`]+`')
    issues = []
    for page, text, *_ in parsed_pages:
        stripped = FENCED_CODE_RE.sub("", text)
        stripped = CODE_SPAN_RE.sub("", stripped)
        for link in WIKILINK_RE.findall(stripped):
            if link.lower().replace(" ", "-") not in all_stems:
                issues.append((page, link))
    return issues


def check_orphaned_pages(parsed_pages):
    """無任何 wikilink 指向的頁面"""
    all_links = set()
    for _page, text, *_ in parsed_pages:
        for link in WIKILINK_RE.findall(text):
            all_links.add(link.lower().replace(" ", "-"))
    for special in ["hot.md", "index.md"]:
        sp = WIKI_DIR / special
        if sp.exists():
            for link in WIKILINK_RE.findall(sp.read_text(encoding="utf-8")):
                all_links.add(link.lower().replace(" ", "-"))
    for idx in WIKI_DIR.rglob("_index.md"):
        for link in WIKILINK_RE.findall(idx.read_text(encoding="utf-8")):
            all_links.add(link.lower().replace(" ", "-"))
    return [page for page, *_ in parsed_pages if page.stem.lower() not in all_links]


def check_missing_sources(parsed_pages):
    return [page for page, _text, fm, _body in parsed_pages if not fm.get("sources")]


def check_contradicted(parsed_pages, threshold_days=30):
    issues = []
    for page, _text, fm, _body in parsed_pages:
        if fm.get("status") != "contradicted":
            continue
        try:
            updated = datetime.strptime(fm.get("updated", ""), "%Y-%m-%d").date()
            delta = (TODAY - updated).days
            if delta >= threshold_days:
                issues.append((page, delta))
        except ValueError:
            issues.append((page, -1))
    return issues


def check_index_missing(parsed_pages):
    index_entries = find_all_index_entries()
    return [page for page, *_ in parsed_pages if page.stem.lower() not in index_entries]


def check_stale(parsed_pages, threshold_days=90):
    issues = []
    for page, _text, fm, _body in parsed_pages:
        if "stale" in fm.get("lint_ignore", []):
            continue
        if fm.get("status") == "stale":
            issues.append(page)
            continue
        try:
            updated = datetime.strptime(fm.get("updated", ""), "%Y-%m-%d").date()
            if (TODAY - updated).days >= threshold_days:
                issues.append(page)
        except ValueError:
            pass
    return issues


# ── 報告輸出 ──────────────────────────────────────────────────────────────────

def rel(path):
    try:
        return str(path.relative_to(VAULT_DIR))
    except ValueError:
        return str(path)


def _fmt_canonical_drift(issue):
    lines = [f"- **{rel(issue['page'])}**"]
    lines.extend(f"  {ln}" for ln in issue["detail"].splitlines())
    return "\n".join(lines)

def _fmt_broken_link(item):
    page, link = item
    return f"- `{rel(page)}` → `[[{link}]]` 不存在"

def _fmt_contradicted(item):
    page, days = item
    day_str = f"{days} 天" if days >= 0 else "日期未知"
    return f"- `{rel(page)}` — 已 {day_str} 未處理"

def _fmt_page(page):
    return f"- `{rel(page)}`"


REPORT_SECTIONS = [
    ("canonical_drift", "1. Canonical Drift",  _fmt_canonical_drift),
    ("broken_links",    "2. 斷裂連結",          _fmt_broken_link),
    ("orphaned_pages",  "3. 孤立頁面",          _fmt_page),
    ("missing_sources", "4. 無來源",            _fmt_page),
    ("contradicted",    "5. 矛盾未解",          _fmt_contradicted),
    ("index_missing",   "6. 索引缺漏",          _fmt_page),
    ("stale_pages",     "7. 過時頁面",          _fmt_page),
]


def generate_report(results):
    total = sum(len(v) for v in results.values())
    lines = [
        "# KB Lint Report",
        f"\n生成時間：{TODAY.isoformat()}\n",
        f"**總計問題：{total}**\n",
        "---\n",
    ]
    for key, title, fmt_fn in REPORT_SECTIONS:
        items = results[key]
        lines.append(f"## {title}（{len(items)} 項）\n")
        if items:
            for item in items:
                lines.append(fmt_fn(item))
        else:
            lines.append("_無問題_")
        lines.append("")
    return "\n".join(lines)


def main():
    pages = find_all_wiki_pages()

    # 一次讀取並解析所有頁面（避免重複 I/O）
    parsed_pages = []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(text)
        parsed_pages.append((p, text, fm, body))

    results = {
        "canonical_drift": check_canonical_drift(parsed_pages),
        "broken_links":    check_broken_links(parsed_pages),
        "orphaned_pages":  check_orphaned_pages(parsed_pages),
        "missing_sources": check_missing_sources(parsed_pages),
        "contradicted":    check_contradicted(parsed_pages),
        "index_missing":   check_index_missing(parsed_pages),
        "stale_pages":     check_stale(parsed_pages),
    }

    report = generate_report(results)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(report)

    total = sum(len(v) for v in results.values())
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
