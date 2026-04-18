# export-chat-logs

Claude Code plugin — 收集 Claude Code 與 Cowork 聊天記錄，轉換為 HTML 或 Markdown 格式，打包成 zip，並透過 Telegram 傳送。

> **注意：** 本 plugin 支援 **Claude Code (CLI)** 對話紀錄。**Claude Cowork** 的對話也可選擇性包含（需手動開啟，僅限 macOS）。Claude Desktop Chat 和 claude.ai 網頁版的對話存放於 Anthropic 伺服器端，無法透過本地檔案取得。

[English](README.md) | [日本語](README.ja.md)

## 安裝

### 方式一：`claude --plugin-dir`（本機開發 / 快速測試）

```bash
git clone https://github.com/keefer-osaka/devtools-plugins.git /path/to/devtools-plugins
claude --plugin-dir /path/to/devtools-plugins
```

### 方式二：透過 plugin marketplace

```
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

安裝後請**重新啟動 Claude Code**，才能看到 `/export-chat-logs:setup` 和 `/export-chat-logs:upload` 指令。`/reload-plugins` 無法載入新安裝的 skill。

### 解除安裝

```
/plugin uninstall export-chat-logs@devtools-plugins
/reload-plugins
```

移除 marketplace 來源：

```
/plugin marketplace remove devtools-plugins
```

---

## 初始設定

安裝後，執行以下指令設定 Telegram Bot Token、chat_id 和偏好設定：

```
/export-chat-logs:setup
```

設定精靈使用可點選的 UI 介面。首次執行會引導你完成所有設定；之後再執行時，選單讓你選擇要修改的項目：

- **Bot Token**：在「Other」欄位貼上（從 Telegram `@BotFather` → `/mybots` → API Token 取得）
- **Chat ID**：在「Other」欄位貼上（從 Telegram `@userinfobot` → 傳送任意訊息 → 複製 `id` 取得）
- **偏好設定**：時區、語言、輸出格式、Cowork 包含與否——從可點選的選項中選擇

| 設定項目 | 選項 | 預設值 |
|---------|------|--------|
| 時區 | UTC+8、UTC+9、UTC-5、UTC-8，或透過「Other」自訂 | UTC+8 |
| 語言 | English / 繁體中文 / 日本語 | English |
| 輸出格式 | HTML（語法高亮 + 互動式圖表）/ Markdown | HTML |
| 包含 Cowork | 是 / 否（僅限 macOS） | 否 |

設定儲存於 `~/.config/devtools-plugins/export-chat-logs/.env`（權限 600，不納入 repo）。

---

## 使用方式

### 匯出（預設 7 天）

```
/export-chat-logs:upload
```

### 指定天數

```
/export-chat-logs:upload 14
```

### 非互動模式（`claude -p`）

```bash
claude -p "/export-chat-logs:upload" --allowedTools "Bash,Read"
claude -p "/export-chat-logs:upload 14" --allowedTools "Bash,Read"
```

### 自動每週匯出（launchd）

```
/export-chat-logs:auto
```

設定精靈會詢問排程時間與匯出天數，並自動安裝 macOS **launchd** 排程代理，每週自動執行匯出。

> **macOS 排程行為說明：**
> - **螢幕鎖定** — 正常執行；使用者 session 仍處於活躍狀態。
> - **休眠（Sleep）** — 休眠期間略過，但喚醒後 launchd 會立即補執行一次。
> - **完全關機** — 略過的排程不會在下次開機後補執行。

---

## 相關：匯入 obsidian-kb

本 plugin 匯出的對話記錄 zip 可直接供 [obsidian-kb](https://github.com/keefer-osaka/devtools-plugins/tree/main/plugins/obsidian-kb) plugin 的 `/kb-import` skill 使用，以填充共享知識庫 wiki。

```
/kb-import chat-logs-alice-20250417.zip
```

zip 檔名慣例（`chat-logs-<author>-YYYYMMDD.zip`）會以作者歸因形式保存在 vault 中，UUID 增量追蹤可防止重複匯入。

> **提示：** `.html` 與 `.md` 兩種輸出格式均支援，無需修改 `.env` 中的 `OUTPUT_FORMAT`。

---

## 相關：內建 `/insights` 指令

Claude Code 內建 `/insights` 指令（不需安裝任何 plugin），可對過去 30 天的使用模式產生 AI 質性分析報告。

```
/insights
```

資料來源為 `~/.claude/usage-data/`，產出 HTML 報告，內容涵蓋：

- 互動風格與使用習慣
- 常見的工作類型
- 改善 Claude Code 工作流程的建議

> **備註：** `/insights` 與本 plugin 功能互補——它提供 AI 質性分析，而 `export-chat-logs` 提供量化統計（token 用量、工具用量、對話時長等）並可匯出完整對話記錄。

---

## 環境需求

- macOS（Linux 需調整 `date` 指令）
- Python 3
- `curl`、`zip`
- Claude Code CLI

---

## 匯出內容

- Claude Code：來自 `~/.claude/projects/` 的 JSONL 對話記錄
- Claude Cowork（選擇性）：來自 `~/Library/Application Support/Claude/` 的對話記錄（僅限 macOS）
- 每個對話轉換為一個 HTML 檔案（或 Markdown，依設定而定）
- HTML 包含語法高亮（highlight.js）與互動式圖表（CSS bar chart）
- 包含統計報告（對話數、模型用量、工具用量、分類統計）
- 打包成 zip 並傳送至 Telegram

以下對話會自動略過，不列入匯出：

- **無實質內容**：token 數為零，或 AI 輸出 < 100 tokens 且持續時間 < 60 秒
- **純技能執行**：只執行了 1 個 skill（`/exit` 等 meta command 不計），且無其他訊息或互動式問答（`AskUserQuestion`）

---

## 疑難排解

### `git pull` 後 plugin 沒有更新

marketplace 會在本機快取特定版本。若拉取後變更未反映，請清除快取並重新安裝：

```bash
rm -rf ~/.claude/plugins/cache/devtools-plugins
```

在 Claude Code 中重新安裝：

```
/plugin marketplace remove devtools-plugins
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

重新安裝後重啟 Claude Code。

---

## 檔案結構

```
.claude-plugin/
└── plugin.json             # Plugin 元資料
skills/
├── upload/SKILL.md         # /export-chat-logs:upload
├── setup/
│   ├── SKILL.md            # /export-chat-logs:setup
│   └── questions/          # 設定精靈問題定義
│       ├── en.json
│       ├── zh-TW.json
│       └── ja.json
└── auto/
    ├── SKILL.md            # /export-chat-logs:auto
    └── questions/          # 自動匯出精靈問題定義
        ├── en.json
        ├── zh-TW.json
        └── ja.json
scripts/
├── common.py               # 共用邏輯（JSONL 解析、i18n/tz 載入）
├── upload.sh               # 主匯出流程
├── save-config.sh          # 寫入 token + chat_id + 時區 + 語言 + 格式 + Cowork
├── install-launchd.sh      # 產生 plist、載入 launchd agent、寫入摘要（由 /auto 呼叫）
├── convert_to_html.py      # JSONL → HTML（語法高亮 + 圖表）
├── convert_to_markdown.py  # JSONL → Markdown
├── generate_stats.py       # 統計報告（HTML 或 Markdown）
└── i18n/                   # 多語言字串
    ├── load.sh                 # i18n 載入器（載入對應語言檔）
    ├── en.sh / en.py           # 英文
    ├── zh_TW.sh / zh_TW.py    # 繁體中文
    └── ja.sh / ja.py           # 日文
```
