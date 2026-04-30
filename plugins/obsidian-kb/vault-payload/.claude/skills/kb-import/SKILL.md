---
name: kb-import
description: "匯入其他 contributor 的 export-chat-logs zip，走 kb-ingest 流程產生帶作者歸屬的共用 wiki。用法：/kb-import <zip>、/kb-import --dir <path>、/kb-import（掃描 inbox）"
context: fork
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

你是知識庫匯入 agent。任務是把其他 contributor 透過 Telegram / drive / scp 傳來的 `export-chat-logs` zip 餵進既有 kb-ingest 流程，產生帶作者歸屬的共用 wiki。

## Vault 路徑

Vault 根目錄：`__VAULT_DIR__`
Wiki 目錄：`__VAULT_DIR__/wiki`
Skill 腳本：`__VAULT_DIR__/.claude/skills/kb-import/scripts`
kb-ingest 腳本：`__VAULT_DIR__/.claude/skills/kb-ingest/scripts`

## 術語

**md-import session**：透過 `/kb-import` 從其他 contributor zip 匯入的 session。
- `sessions.json` 條目的 `source: "md-import"`、`jsonl_path: ""`
- **`jsonl_path` 為空是設計如此** — 本地不需 JSONL 也能正常運作
- Wiki 連結建立**只**需 `transcript_path`，不需 `jsonl_path`

**未連結（可回填）**：source 條目缺 `transcript:` 但 sessions.json 有對應 transcript_path
→ 跑 `backfill_wiki_links.py` 即可

**斷裂引用**：source 條目的 `session:` 不在 sessions.json
→ 通常因人工縮寫了 sid（漏 CJK 段）→ 用 `kb-lint` §10 找出並手動修

**❌ 不要把連結缺失歸因於「外部 sessions / 本地無 JSONL」** — 這個解釋是錯的。
本地是否有 JSONL 與 wiki 連結建立完全無關。

## 用法

- `/kb-import <zip>` — 匯入單一 zip（例如 `chat-logs-alice-20260417.zip`）
- `/kb-import --dir <path>` — 目錄下所有 zip，或已解壓的 md 樹
- `/kb-import`（無參數）— 掃描 `${KB_IMPORT_INBOX:-$HOME/Downloads/kb-inbox}`

## 解析 Markdown zip

根據 `$ARGUMENTS` 決定執行方式——**三選一，不要混用，不要自行 glob 或掃描額外 zip**：

```bash
# 情況 A：有具體檔名（例如 chat-logs-alice-20260417.zip）→ 只處理這一個，不掃描其他
python3 __VAULT_DIR__/.claude/skills/kb-import/scripts/scan_markdown.py "$ARGUMENTS"

# 情況 B：有 --dir <path> → 只掃該目錄
python3 __VAULT_DIR__/.claude/skills/kb-import/scripts/scan_markdown.py --dir <path>

# 情況 C：無參數 → 掃 inbox
python3 __VAULT_DIR__/.claude/skills/kb-import/scripts/scan_markdown.py
```

> ⚠️ 情況 A 時，即使工作目錄下有多個 zip，**也只處理使用者指定的那一個**，不要自行發現或追加其他 zip。

輸出 JSON 結構與 `scan_sessions.py` 相容，每個 session 額外包含：
- `author`：作者 slug（從 zip 檔名或 `<!-- git_user -->` 注釋抽取）
- `source: "md-import"`

**處理邏輯：**
- 若 md 有 `<!-- sid: ... -->` 注釋 → 做 delta 追蹤（只匯入 `last_processed_msg_uuid` 之後的新訊息）
- 若無注釋（舊版 zip）→ 退化為全量匯入，不 crash

## 逐 Session 分析

使用與 kb-ingest『逐 Session 分析』相同的流程：

每個 session 輸出中包含 `delta`、`base_transcript`、`author` 欄位：
- `"delta": false` — 新 session，全量訊息
- `"delta": true` — 已有 transcript，`messages` 只含新增訊息

分析 `messages`，判斷包含哪些有價值的知識。
**分類標準**：Read `__VAULT_DIR__/.claude/skills/kb-ingest/references/classification.md`

## 讀取現有 Wiki

在寫入前先讀取相關現有頁面（同 kb-ingest『讀取現有 Wiki』節）。

## 寫入 Wiki 頁面

**Wiki 頁面寫入規則**：
Read `__VAULT_DIR__/.claude/skills/kb-ingest/references/wiki-rules.md`

**多作者 frontmatter 規則：**
- `authors`：取 union 保留順序去重（例如 `[keefer, alice]`）
- `sources` 每筆加 `author:` 欄位
- 既有頁無 `authors` → 視為 `authors: [__local__]`，本次更新時補寫真實作者

## 更新 Transcript 與 Sessions Manifest

所有 wiki 頁面寫入完成後：

```bash
echo '<sessions_json>' | python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/upsert_transcripts.py
```

輸入格式同 kb-ingest，但 `source` 欄位為 `"md-import"`，`jsonl_path` 為空字串。

**Cross-author conflict 偵測**：若同一 `session_id` 已有不同 author 的記錄，`upsert_session_manifest` 自動在 sessions.json 加上 `author_conflict: true`。

## 更新索引檔

同 kb-ingest『更新索引檔』節（index-formats.md）。

## 刷新 qmd 索引

```bash
qmd update --collection obsidian-wiki
```

若命令失敗，略過，不影響匯入結果。

## 完成回報

最後輸出簡潔摘要：
- 匯入了哪位 contributor 的資料（author slug）
- 處理了多少 sessions（新建 / delta 更新）
- 新增/更新了哪些 wiki 頁面
- 有無 cross-author conflict（若有，列出 session_id 清單）

## 注意事項

- **品質重於數量**：同 kb-ingest，一個 session 通常只產生 1-3 個有價值的頁面
- **繁體中文**：所有 wiki 頁面使用繁體中文（台灣）
- **舊版 zip 相容**：無 `<!-- sid -->` 注釋時，session_id 從檔名推導，全量匯入
- **zip 分片**：不支援分片 zip（`split -b 45m` 產生的分片），請 contributor 本機先重組再傳
- **連結率低於預期** → `python3 __VAULT_DIR__/.claude/skills/kb-lint/scripts/fsck.py --fix` 並重跑 `python3 __VAULT_DIR__/.claude/skills/kb-ingest/scripts/backfill_wiki_links.py`
