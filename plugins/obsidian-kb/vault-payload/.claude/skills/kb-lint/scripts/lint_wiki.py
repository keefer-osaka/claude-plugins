#!/usr/bin/env python3
"""
kb-lint: 知識庫健康檢查腳本

檢查項目：
1. canonical_drift         — canonical_files 對照現實漂移
2. broken_links            — wikilink 指向不存在的頁面
3. orphaned_pages          — 無任何 wikilink 指向的頁面
4. missing_sources         — sources 欄位為空
5. contradicted            — status: contradicted 超過 30 天未處理
6. index_missing           — 存在於 wiki/ 但未列入 _index.md
7. stale_pages             — status: stale（超過 90 天未更新）
8. cross_author_conflict   — 跨作者矛盾（contradicted 且多作者，或近 7 天多作者 draft）
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import date, datetime

# ── _lib 共用模組 ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))
from wiki_utils import resolve_vault_dir, parse_frontmatter, WIKILINK_RE, TW_TZ, TOP_LEVEL_SKIP, extract_fm_text, find_duplicate_top_level_keys, parse_source_blocks  # noqa: E402

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
VAULT_DIR = Path(resolve_vault_dir(__file__))
WIKI_DIR = VAULT_DIR / "wiki"
SESSIONS_JSON_PATH = VAULT_DIR / "_schema" / "sessions.json"
REPORT_PATH = WIKI_DIR / "meta" / "lint-report.md"

TODAY = datetime.now(TW_TZ).date()


# ── 頁面收集 ──────────────────────────────────────────────────────────────────

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
            entries.add(_link_target_stem(m))
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


FENCED_CODE_RE = re.compile(r'```.*?```', re.DOTALL)
CODE_SPAN_RE = re.compile(r'``[^`].*?``|`[^`]+`')


def _link_target_stem(link: str) -> str:
    """[[page|alias]] / [[page#Heading]] → page stem（小寫、空格→dash）。"""
    target = link.split("|", 1)[0].split("#", 1)[0]
    return target.lower().replace(" ", "-")


def _collect_wikilinks(text: str) -> set[str]:
    """剝除 code block / code span 後收集 wikilink 目標 stem。"""
    stripped = FENCED_CODE_RE.sub("", text)
    stripped = CODE_SPAN_RE.sub("", stripped)
    return {_link_target_stem(m) for m in WIKILINK_RE.findall(stripped)}


def check_broken_links(parsed_pages):
    """wikilink [[xxx]] 指向不存在的頁面"""
    all_stems = {page.stem.lower() for page, *_ in parsed_pages}
    transcripts_dir = VAULT_DIR / "transcripts"
    if transcripts_dir.exists():
        for p in transcripts_dir.glob("*.md"):
            all_stems.add(p.stem.lower())
    issues = []
    for page, text, *_ in parsed_pages:
        stripped = FENCED_CODE_RE.sub("", text)
        stripped = CODE_SPAN_RE.sub("", stripped)
        for link in WIKILINK_RE.findall(stripped):
            if _link_target_stem(link) not in all_stems:
                issues.append((page, link))
    return issues


def check_orphaned_pages(parsed_pages):
    """無任何 wikilink 指向的頁面"""
    all_links = set()
    for _page, text, *_ in parsed_pages:
        all_links |= _collect_wikilinks(text)
    for special in TOP_LEVEL_SKIP:
        sp = WIKI_DIR / special
        if sp.exists():
            all_links |= _collect_wikilinks(sp.read_text(encoding="utf-8"))
    for idx in WIKI_DIR.rglob("_index.md"):
        all_links |= _collect_wikilinks(idx.read_text(encoding="utf-8"))
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


def check_cross_author_conflict(parsed_pages, recent_days=7):
    """
    第 8 節：跨作者矛盾偵測。

    硬檢查：status=contradicted 且 authors 列表包含 >= 2 位不同作者。
    軟檢查（advisory）：近 recent_days 天內被兩位以上不同作者加過 sources 但 status 仍 draft。

    回傳 list of (page, kind, detail)。
    """
    issues = []
    for page, _text, fm, _body in parsed_pages:
        authors = fm.get("authors", [])
        if isinstance(authors, str):
            authors = [a.strip() for a in authors.split(",") if a.strip()]
        unique_authors = set(a for a in authors if a and a != "__local__")

        status = fm.get("status", "")

        # 硬檢查
        if status == "contradicted" and len(unique_authors) >= 2:
            issues.append((page, "hard", f"contradicted，作者：{', '.join(sorted(unique_authors))}"))
            continue

        # 軟檢查：從 sources 欄位找近 recent_days 天的多作者記錄
        sources = fm.get("sources", [])
        if not isinstance(sources, list):
            continue
        if status != "draft":
            continue
        recent_source_authors = set()
        for src in sources:
            if not isinstance(src, dict):
                continue
            src_author = src.get("author", "")
            src_date_str = src.get("date", "")
            if not src_author or not src_date_str:
                continue
            try:
                src_date = datetime.strptime(src_date_str, "%Y-%m-%d").date()
                if (TODAY - src_date).days <= recent_days:
                    recent_source_authors.add(src_author)
            except ValueError:
                continue
        if len(recent_source_authors) >= 2:
            issues.append((page, "advisory", f"draft，近 {recent_days} 天內多作者更新：{', '.join(sorted(recent_source_authors))}"))

    return issues


def check_duplicate_fm_keys(parsed_pages):
    issues = []
    for page, text, _fm, _body in parsed_pages:
        dupes = find_duplicate_top_level_keys(extract_fm_text(text))
        if dupes:
            issues.append((page, dupes))
    return issues


def load_sessions_manifest() -> dict:
    """讀取 sessions.json；缺檔或解析失敗時回傳空 dict（lint 視為「無 manifest」）。"""
    if not SESSIONS_JSON_PATH.exists():
        return {}
    try:
        data = json.loads(SESSIONS_JSON_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[WARN] lint_wiki load sessions.json: {e}", file=sys.stderr)
        return {}


def check_broken_session_refs(parsed_pages, manifest):
    """
    第 10 節：sources 中 `- session: <sid>` 引用的 sid 不在 manifest 中。

    對每個斷裂引用，嘗試以 prefix-24（前 24 字元，例如 `2026-04-23_18-21-17-554_`）
    找近似匹配，若有則放在 detail 中作為「近似」提示。

    回傳 list of (page, sid, near_sid_or_None)。
    """
    if not manifest:
        return []
    manifest_sids = set(manifest.keys())
    prefix_index: dict[str, list[str]] = {}
    for sid in manifest_sids:
        key = sid[:24]
        prefix_index.setdefault(key, []).append(sid)

    issues = []
    for page, text, _fm, _body in parsed_pages:
        fm_text = extract_fm_text(text)
        for sb in parse_source_blocks(fm_text):
            sid = sb["session"]
            if sid in manifest_sids:
                continue
            near = None
            candidates = prefix_index.get(sid[:24], [])
            if candidates:
                near = candidates[0]
            issues.append((page, sid, near))
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

def _fmt_cross_author_conflict(item):
    page, kind, detail = item
    tag = "⚠️ 硬" if kind == "hard" else "ℹ️ 建議"
    return f"- `{rel(page)}` [{tag}] {detail}"

def _fmt_duplicate_fm_keys(item):
    page, keys = item
    return f"- `{rel(page)}` — 重複 key: {', '.join(keys)}"


def _fmt_broken_session_ref(item):
    page, sid, near = item
    base = f"- `{rel(page)}` — session `{sid}` 不在 sessions.json"
    if near:
        base += f"（近似：`{near}`）"
    return base


REPORT_SECTIONS = [
    ("canonical_drift",       "1. Canonical Drift",  _fmt_canonical_drift),
    ("broken_links",          "2. 斷裂連結",          _fmt_broken_link),
    ("orphaned_pages",        "3. 孤立頁面",          _fmt_page),
    ("missing_sources",       "4. 無來源",            _fmt_page),
    ("contradicted",          "5. 矛盾未解",          _fmt_contradicted),
    ("index_missing",         "6. 索引缺漏",          _fmt_page),
    ("stale_pages",           "7. 過時頁面",          _fmt_page),
    ("cross_author_conflict", "8. 跨作者矛盾",        _fmt_cross_author_conflict),
    ("duplicate_fm_keys",    "9. 重複 frontmatter key", _fmt_duplicate_fm_keys),
    ("broken_session_refs",  "10. 斷裂 session 引用",  _fmt_broken_session_ref),
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

    manifest = load_sessions_manifest()

    results = {
        "canonical_drift":       check_canonical_drift(parsed_pages),
        "broken_links":          check_broken_links(parsed_pages),
        "orphaned_pages":        check_orphaned_pages(parsed_pages),
        "missing_sources":       check_missing_sources(parsed_pages),
        "contradicted":          check_contradicted(parsed_pages),
        "index_missing":         check_index_missing(parsed_pages),
        "stale_pages":           check_stale(parsed_pages),
        "cross_author_conflict": check_cross_author_conflict(parsed_pages),
        "duplicate_fm_keys":     check_duplicate_fm_keys(parsed_pages),
        "broken_session_refs":   check_broken_session_refs(parsed_pages, manifest),
    }

    report = generate_report(results)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    print(report)

    total = sum(len(v) for v in results.values())
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
