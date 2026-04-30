---
name: kb-ingest
description: "從 Claude Code JSONL 歷史紀錄擷取知識，更新 wiki/ 知識庫。用法：/kb-ingest（預設 10 筆）、/kb-ingest -a（批次處理所有歷史）。支援 -n N 調整每批數量"
context: fork
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

你是知識庫維護 agent。任務是從 Claude Code 對話歷史中提取有價值的知識，寫入 Obsidian wiki。

## Vault 路徑

Vault 根目錄：`__VAULT_DIR__`
Wiki 目錄：`__VAULT_DIR__/wiki`
Skill 腳本：`__VAULT_DIR__/.claude/skills/kb-ingest/scripts`

## 掃描 Sessions

執行掃描腳本，取得待處理的 sessions：

```bash
# 一般模式（只處理水位線之後的新 sessions）
python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/scan_sessions.py

# -a 模式（處理所有歷史，預設每批 10 筆）
python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/scan_sessions.py -a

# 自訂每批數量（-n N，長格式 --limit N 亦可）
python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/scan_sessions.py -a -n 20
```

如果 `$ARGUMENTS` 包含 `--all`，使用 `--all --limit 10` 模式。如果 `$ARGUMENTS` 包含 `--limit N`，將該值傳入腳本。

輸出是 JSON，其中 `sessions` 陣列包含每個 session 的完整對話內容。

> **`--all` 模式注意**：`scan_sessions.py` 執行時已自動推進 `.all_watermark` 游標，無需手動呼叫 `update_all_watermark.py`。

## 逐 Session 分析

每個 session 輸出中現在包含 `delta` 和 `base_transcript` 欄位：

- `"delta": false` — 新 session，全部訊息，正常處理
- `"delta": true` — 已有 transcript，`messages` 只含新增訊息，`base_transcript` 是現有 transcript 路徑

**Delta session 的處理規則：**
1. 先 Read `base_transcript` 的 frontmatter（取 `derived_pages` 清單，了解已建立的 wiki 頁面）
2. 只對 `messages` 中的新訊息做知識分類判斷
3. 若 delta 觸發既有 wiki 頁面更新 → 正常走『寫入 Wiki 頁面』節的矛盾偵測
4. 若 delta 產生新 wiki 頁面 → 正常建立，並在『更新 Transcript 與 Sessions Manifest』節更新 transcript 的 `derived_pages`
5. 把 delta 訊息 append 到 transcript（『更新 Transcript 與 Sessions Manifest』節的任務）
6. 更新 `_schema/sessions.json` 條目

**⚠️ Transcript wikilink（新 session 與 delta session 均適用）**：
一律使用 scan 輸出中的 `transcript_stem` 欄位，**嚴禁**從 `title` 自行生成 slug。
- Delta session：`transcript_stem` = 現有 transcript 檔名去 `.md`（session 可能被 `/rename`，title 已變但檔名不變）
- 新 session：`transcript_stem` = Python 預先計算好的檔名 stem（與 `upsert_transcripts.py` 建立的實際檔名一致）

正確寫法：`[[<transcript_stem 欄位的值>]]`

對每個 session 分析其 `messages` 欄位，判斷包含哪些有價值的知識。
**分類標準**：Read `__VAULT_DIR__/.claude/skills/kb-ingest/references/classification.md`

## 讀取現有 Wiki

在寫入前，先讀取相關的現有頁面：

```bash
# 讀取主索引，了解現有內容
# Read wiki/index.md
# Read wiki/entities/_index.md（如果要寫 entity）
# Glob wiki/entities/*.md 確認現有實體
```

## 寫入 Wiki 頁面

**Wiki 頁面寫入規則**（frontmatter、衝突偵測、更新策略）：
Read `__VAULT_DIR__/.claude/skills/kb-ingest/references/wiki-rules.md`

新頁面放置路徑：
```
wiki/entities/<名稱>.md
wiki/concepts/<名稱>.md
wiki/decisions/<決策名稱>.md
wiki/troubleshooting/<問題名稱>.md
wiki/sources/<YYYY-MM-DD>-<主題>.md
```

## 更新 Transcript 與 Sessions Manifest

所有 wiki 頁面寫入完成後，將本批次處理的 sessions 整理成 JSON，透過 stdin 傳給腳本：

```bash
echo '<sessions_json>' | python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/upsert_transcripts.py
```

輸入格式（JSON 陣列，每個元素包含）：
- `session_id`, `delta` (bool), `title`, `cwd`, `date`, `first_ts`, `last_ts`
- `models`, `messages`, `jsonl_path`
- `base_transcript`（delta 專用：現有 transcript 的 vault-relative 路徑）
- `new_derived_pages`（本次新建或更新的 wiki 頁面路徑清單）
- `author`（作者 slug，例如 `keefer`；scan_sessions.py 自動填入）
- `source`（來源類型：`"jsonl"` 或 `"md-import"`）

> **md-import 兼容性**：當 `source: "md-import"` 且 `jsonl_path: ""` 時，upsert 仍正常建立 transcript 並回填 wiki source。本地 JSONL 不存在不影響任何功能。

腳本自動處理：建立/更新 transcript、更新 sessions manifest、重建 transcripts 索引。
詳細欄位說明：`python3 .../upsert_transcripts.py --help`

## 更新索引檔

**索引格式規範**（_index.md / hot.md / log.md）：
Read `__VAULT_DIR__/.claude/skills/kb-ingest/references/index-formats.md`

## 更新 overview.md

```bash
python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/update_overview.py
```

腳本輸出統計 JSON（`page_count`、`last_ingest`、`sessions_count`）並就地更新 `## 狀態` 機械段。

敘事段更新規則（LLM 判斷）：
- 若本批 ingest 出現新的重要 entity/concept 或主題轉向 → Edit `wiki/overview.md` 的 `## 主要主題` 段
- `## 近期重點`：append 一條，格式 `- YYYY-MM-DD：<本批 ingest 重點>`，保留最近 3–5 條

## 更新水位線

所有頁面寫入完成後：

```bash
# 必做（所有模式）：更新 .watermark（記錄到當前時間）
python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/update_watermark.py
```

> **`--all` 模式**：`.all_watermark` 已由 `scan_sessions.py` 自動推進，此處無需額外呼叫 `update_all_watermark.py`。

## 刷新 qmd 索引

所有頁面寫入完成後，刷新 qmd 搜尋索引讓新頁面立即可被查詢：

```bash
qmd update --collection obsidian-wiki
```

若命令失敗（例如 qmd 未安裝），略過此步驟，不影響 ingest 結果。

> **注意**：`qmd embed`（向量化）因 Metal GPU 初始化問題暫不執行。BM25 搜尋（`lex` 查詢）不受影響。待 node-llama-cpp 修好相容性後再加回。

## 完成回報

最後輸出簡潔摘要：
- 本次處理了多少 sessions
- 新增/更新了哪些頁面
- 有沒有矛盾標記
- 水位線更新結果

## 注意事項

- **品質重於數量**：一個 session 通常只產生 1-3 個有價值的知識頁面，不要強行分類
- **繁體中文**：所有 wiki 頁面使用繁體中文（台灣）
- **保持簡潔**：entity/concept 頁面 < 500 字，source 頁面只保留精華
- **不要記錄工具呼叫細節**：只記錄對話中的實質知識，忽略 tool_use 的機械性操作
- **--all 模式**：批次限制 15 個 sessions，避免 context 爆炸。若還有更多，告知用戶再次執行
