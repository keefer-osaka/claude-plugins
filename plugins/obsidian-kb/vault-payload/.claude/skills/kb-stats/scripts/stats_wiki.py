#!/usr/bin/env python3
"""
kb-stats: 知識庫統計報告腳本

統計項目：
1. 頁面分佈（各類型數量）
2. 狀態分佈（draft/verified/stale/contradicted）
3. 信心度分佈（high/medium/low）
4. TL;DR 覆蓋率
5. 來源覆蓋率
6. Transcript 連結率
7. 新鮮度（30/60/90 天）
8. Transcripts 層狀態
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

# ── _lib 共用模組 ─────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_lib")))
from wiki_utils import resolve_vault_dir, parse_frontmatter, TW_TZ, parse_source_blocks, extract_fm_text, TOP_LEVEL_SKIP  # noqa: E402

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
VAULT_DIR = Path(resolve_vault_dir(__file__))
WIKI_DIR = VAULT_DIR / "wiki"
TRANSCRIPTS_DIR = VAULT_DIR / "transcripts"
SESSIONS_JSON_PATH = VAULT_DIR / "_schema" / "sessions.json"
REPORT_PATH = WIKI_DIR / "meta" / "stats-report.md"

TODAY = datetime.now(TW_TZ).date()

# 子目錄內跳過
SUBDIR_SKIP = {"_index.md"}


# ── 收集 wiki 內容頁面 ────────────────────────────────────────────────────────

def collect_content_pages() -> list[dict]:
    """掃描 wiki/ 收集所有「內容頁面」（排除 _index.md、頂層工具檔）。"""
    pages = []
    for md_path in WIKI_DIR.rglob("*.md"):
        rel = md_path.relative_to(WIKI_DIR)
        parts = rel.parts
        # 頂層工具檔
        if len(parts) == 1 and parts[0] in TOP_LEVEL_SKIP:
            continue
        # _index.md
        if parts[-1] in SUBDIR_SKIP:
            continue
        # meta/ 目錄
        if parts[0] == "meta":
            continue

        try:
            text = md_path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[WARN] stats_wiki read {md_path}: {e}", file=sys.stderr)
            continue

        fm, body = parse_frontmatter(text)
        fm_text = extract_fm_text(text)

        # 日期解析
        updated_str = fm.get("updated", fm.get("created", ""))
        updated_date = None
        if updated_str:
            try:
                updated_date = date.fromisoformat(str(updated_str).strip())
            except ValueError:
                pass

        # TL;DR 偵測
        has_tldrs = bool(re.search(r'^##\s+TL;DR', body, re.MULTILINE))

        # sources 解析
        source_blocks = parse_source_blocks(fm_text)

        pages.append({
            "path": str(rel),
            "type": fm.get("type", "unknown"),
            "status": fm.get("status", "draft"),
            "confidence": fm.get("confidence", ""),
            "updated": updated_date,
            "has_tldr": has_tldrs,
            "source_count": len(source_blocks),
            "source_blocks": source_blocks,
        })
    return pages


# ── 統計計算 ──────────────────────────────────────────────────────────────────

def pct(n: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{n * 100 // total}%"


def bar(n: int, total: int, width: int = 20) -> str:
    if total == 0:
        return " " * width
    filled = int(n * width / total)
    return "█" * filled + "░" * (width - filled)


def compute_stats(pages: list[dict]) -> dict:
    total = len(pages)

    # 類型 / 狀態 / 信心度分佈
    types = dict(Counter(p["type"] for p in pages))
    statuses = dict(Counter(p["status"] for p in pages))
    confidences = dict(Counter(p["confidence"] for p in pages if p["confidence"]))

    # TL;DR 覆蓋
    tldr_count = sum(1 for p in pages if p["has_tldr"])

    # 來源覆蓋
    has_source = sum(1 for p in pages if p["source_count"] > 0)
    total_source_refs = sum(p["source_count"] for p in pages)
    avg_sources = total_source_refs / total if total > 0 else 0

    # Transcript 連結率
    transcript_linked = sum(
        sum(1 for sb in p["source_blocks"] if sb["has_transcript"])
        for p in pages
    )
    unlinked_sources = [
        (p["path"], sb["session"])
        for p in pages
        for sb in p["source_blocks"]
        if not sb["has_transcript"]
    ]

    # 新鮮度
    updated_pages = [p for p in pages if p["updated"]]
    fresh_30 = sum(1 for p in updated_pages if (TODAY - p["updated"]).days <= 30)
    fresh_60 = sum(1 for p in updated_pages if (TODAY - p["updated"]).days <= 60)
    fresh_90 = sum(1 for p in updated_pages if (TODAY - p["updated"]).days <= 90)
    oldest = None
    if updated_pages:
        oldest_p = min(updated_pages, key=lambda p: p["updated"])
        oldest = (oldest_p["path"], oldest_p["updated"])

    return {
        "total": total,
        "types": types,
        "statuses": statuses,
        "confidences": confidences,
        "tldr_count": tldr_count,
        "has_source": has_source,
        "total_source_refs": total_source_refs,
        "avg_sources": avg_sources,
        "transcript_linked": transcript_linked,
        "unlinked_sources": unlinked_sources,
        "fresh_30": fresh_30,
        "fresh_60": fresh_60,
        "fresh_90": fresh_90,
        "oldest": oldest,
        "no_updated_field": total - len(updated_pages),
    }


def load_transcripts_stats() -> dict:
    disk_files = set()
    if TRANSCRIPTS_DIR.exists():
        disk_files = {p.name for p in TRANSCRIPTS_DIR.glob("*.md") if p.name != "_index.md"}
    transcript_count = len(disk_files)

    sessions_count = 0
    manifest_paths = set()
    if SESSIONS_JSON_PATH.exists():
        try:
            data = json.loads(SESSIONS_JSON_PATH.read_text(encoding="utf-8"))
            sessions_count = len(data)
            manifest_paths = {
                os.path.basename(v["transcript_path"])
                for v in data.values()
                if v.get("transcript_path")
            }
        except Exception as e:
            print(f"[WARN] stats_wiki load sessions.json: {e}", file=sys.stderr)

    orphan_files = sorted(disk_files - manifest_paths)
    missing_files = sorted(manifest_paths - disk_files)
    return {
        "transcripts": transcript_count,
        "sessions": sessions_count,
        "orphan_files": orphan_files,
        "missing_files": missing_files,
    }


# ── 報告渲染 ──────────────────────────────────────────────────────────────────

def render_report(stats: dict, ts_stats: dict) -> str:
    total = stats["total"]
    now_tw = datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 知識庫統計報告",
        "",
        f"> 生成時間：{now_tw}　｜　工具：`/kb-stats`",
        "",
        "---",
        "",
        "## 1. 頁面分佈",
        "",
        f"**總計：{total} 個內容頁面**",
        "",
        "| 類型 | 數量 | 佔比 | 進度 |",
        "|------|------|------|------|",
    ]
    type_order = ["entity", "concept", "decision", "troubleshooting", "source", "unknown"]
    for t in type_order:
        n = stats["types"].get(t, 0)
        if n == 0:
            continue
        lines.append(f"| {t} | {n} | {pct(n, total)} | `{bar(n, total, 15)}` |")

    lines += [
        "",
        "## 2. 狀態分佈",
        "",
        "| 狀態 | 數量 | 佔比 |",
        "|------|------|------|",
    ]
    status_order = ["verified", "draft", "stale", "contradicted"]
    for s in status_order:
        n = stats["statuses"].get(s, 0)
        if n == 0:
            continue
        lines.append(f"| {s} | {n} | {pct(n, total)} |")
    # unknown statuses
    for s, n in stats["statuses"].items():
        if s not in status_order:
            lines.append(f"| {s}（非標準） | {n} | {pct(n, total)} |")

    lines += [
        "",
        "## 3. 信心度分佈",
        "",
        "| 信心度 | 數量 | 佔比 |",
        "|--------|------|------|",
    ]
    conf_order = ["high", "medium", "low"]
    for c in conf_order:
        n = stats["confidences"].get(c, 0)
        if n:
            lines.append(f"| {c} | {n} | {pct(n, total)} |")
    no_conf = total - sum(stats["confidences"].values())
    if no_conf:
        lines.append(f"| （未設定） | {no_conf} | {pct(no_conf, total)} |")

    tldr = stats["tldr_count"]
    lines += [
        "",
        "## 4. TL;DR 覆蓋率",
        "",
        f"- 有 `## TL;DR`：**{tldr} / {total}**（{pct(tldr, total)}）",
        f"- 缺少 `## TL;DR`：{total - tldr} 個",
    ]

    has_src = stats["has_source"]
    avg = stats["avg_sources"]
    lines += [
        "",
        "## 5. 來源覆蓋率",
        "",
        f"- 有 sources：**{has_src} / {total}**（{pct(has_src, total)}）",
        f"- 無 sources：{total - has_src} 個",
        f"- 平均來源數：{avg:.1f} 個 / 頁面",
        f"- Sources 條目總計：{stats['total_source_refs']}",
    ]

    tl = stats["transcript_linked"]
    tb = stats["total_source_refs"]
    lines += [
        "",
        "## 6. Transcript 連結率",
        "",
        f"- Sources 條目有 transcript: 欄位：**{tl} / {tb}**（{pct(tl, tb)}）",
        f"- 尚未連結：{tb - tl} 個",
    ]
    if tb - tl > 0:
        for page_path, sid in stats.get("unlinked_sources", []):
            lines.append(f"  - `{page_path}` ← session `{sid}`")

    lines += [
        "",
        "## 7. 新鮮度",
        "",
        f"| 區間 | 數量 | 佔比 |",
        f"|------|------|------|",
        f"| 30 天內更新 | {stats['fresh_30']} | {pct(stats['fresh_30'], total)} |",
        f"| 60 天內更新 | {stats['fresh_60']} | {pct(stats['fresh_60'], total)} |",
        f"| 90 天內更新 | {stats['fresh_90']} | {pct(stats['fresh_90'], total)} |",
    ]
    if stats["no_updated_field"]:
        lines.append(f"| （無 updated 欄位） | {stats['no_updated_field']} | {pct(stats['no_updated_field'], total)} |")
    if stats["oldest"]:
        path, dt = stats["oldest"]
        age = (TODAY - dt).days
        lines += ["", f"- 最舊頁面：`{path}`（{dt}，{age} 天前）"]

    lines += [
        "",
        "## 8. Transcripts 層（L1.5）",
        "",
        f"- Transcripts 檔案：**{ts_stats['transcripts']} 個**",
        f"- sessions.json 條目：**{ts_stats['sessions']} 個**",
    ]
    if ts_stats["sessions"] > 0 and ts_stats["transcripts"] > 0:
        diff = ts_stats["sessions"] - ts_stats["transcripts"]
        if diff == 0:
            lines.append("- 兩者一致")
        else:
            lines.append(f"- 差異：{abs(diff)} 個（{'sessions.json 多' if diff > 0 else 'transcripts 多'}）")
    for fname in ts_stats.get("orphan_files", []):
        lines.append(f"  - orphan: `transcripts/{fname}`（sessions.json 無對應）")
    for fname in ts_stats.get("missing_files", []):
        lines.append(f"  - missing: `transcripts/{fname}`（檔案不存在）")

    lines += ["", "---", "", f"_由 `/kb-stats` 自動生成於 {now_tw}_", ""]
    return "\n".join(lines)


# ── 主程式 ────────────────────────────────────────────────────────────────────

def main():
    print("kb-stats 開始掃描...")
    pages = collect_content_pages()
    print(f"  掃描到 {len(pages)} 個內容頁面")

    stats = compute_stats(pages)
    ts_stats = load_transcripts_stats()

    report = render_report(stats, ts_stats)

    # 寫入報告
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"  報告寫入：{REPORT_PATH}")
    print()
    print(report)


if __name__ == "__main__":
    main()
