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
from wiki_utils import resolve_vault_dir, parse_frontmatter, TW_TZ, parse_source_blocks, extract_fm_text, TOP_LEVEL_SKIP, collect_content_pages  # noqa: E402

# ── 路徑設定 ──────────────────────────────────────────────────────────────────
VAULT_DIR = Path(resolve_vault_dir(__file__))
WIKI_DIR = VAULT_DIR / "wiki"
TRANSCRIPTS_DIR = VAULT_DIR / "transcripts"
SESSIONS_JSON_PATH = VAULT_DIR / "_schema" / "sessions.json"
REPORT_PATH = WIKI_DIR / "meta" / "stats-report.md"

TODAY = datetime.now(TW_TZ).date()


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


def compute_stats(pages: list[dict], manifest: dict | None = None) -> dict:
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

    # Transcript 三分類：linked / backfillable / broken
    # - linked: source 條目已含 transcript: 欄位
    # - backfillable: 未含 transcript: 但 sid 在 manifest 中且該 manifest 條目有 transcript_path
    # - broken: 未含 transcript: 且 sid 不在 manifest 中（或 manifest=None 全歸此類，保守 default）
    sid_has_transcript: set[str] = set()
    if manifest:
        sid_has_transcript = {
            sid for sid, e in manifest.items()
            if isinstance(e, dict) and e.get("transcript_path")
        }

    linked: list[tuple[str, str]] = []
    backfillable: list[tuple[str, str]] = []
    broken: list[tuple[str, str]] = []
    for p in pages:
        for sb in p["source_blocks"]:
            sid = sb["session"]
            entry = (p["path"], sid)
            if sb.get("has_transcript"):
                linked.append(entry)
            elif manifest is not None and sid in sid_has_transcript:
                backfillable.append(entry)
            else:
                broken.append(entry)

    transcript_linked = len(linked)

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
        "backfillable_sources": backfillable,
        "broken_sources": broken,
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
    backfillable = stats.get("backfillable_sources", [])
    broken = stats.get("broken_sources", [])
    lines += [
        "",
        "## 6. Transcript 連結率",
        "",
        f"- Sources 條目有 transcript: 欄位：**{tl} / {tb}**（{pct(tl, tb)}）",
        f"- 可回填（manifest 有對應 transcript）：{len(backfillable)} 個",
        f"- 斷裂引用（manifest 無對應）：{len(broken)} 個",
        "",
        f"### 6.1 可回填（{len(backfillable)} 個）",
        "",
    ]
    if backfillable:
        lines.append("修復指令：`python3 .claude/skills/kb-ingest/scripts/backfill_wiki_links.py`")
        lines.append("")
        for page_path, sid in backfillable[:20]:
            lines.append(f"- `{page_path}` ← session `{sid}`")
        extra = len(backfillable) - 20
        if extra > 0:
            lines.append(f"- _+ {extra} more_")
    else:
        lines.append("_無_")

    lines += [
        "",
        f"### 6.2 斷裂引用（{len(broken)} 個）",
        "",
    ]
    if broken:
        for page_path, sid in broken:
            lines.append(f"- `{page_path}` ← session `{sid}`（manifest 無對應）")
    else:
        lines.append("_無_")

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

def load_manifest() -> dict | None:
    """讀取 sessions.json 作為 transcript manifest。失敗回傳 None（保守 default）。"""
    if not SESSIONS_JSON_PATH.exists():
        return None
    try:
        return json.loads(SESSIONS_JSON_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] stats_wiki load manifest: {e}", file=sys.stderr)
        return None


def main():
    print("kb-stats 開始掃描...")
    pages = collect_content_pages(WIKI_DIR)
    print(f"  掃描到 {len(pages)} 個內容頁面")

    manifest = load_manifest()
    stats = compute_stats(pages, manifest=manifest)
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
