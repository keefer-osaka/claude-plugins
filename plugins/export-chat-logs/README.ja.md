# export-chat-logs

Claude Code プラグイン — Claude Code と Cowork のチャットログを収集し、HTML または Markdown に変換、zip に圧縮して Telegram で送信します。

> **注意：** このプラグインは **Claude Code (CLI)** の会話に対応しています。**Claude Cowork** のセッションも含めることができます（オプトイン、macOS のみ）。Claude Desktop Chat および claude.ai ウェブ版の会話はサーバー側に保存されており、ローカルからアクセスできません。

[English](README.md) | [繁體中文](README.zh-TW.md)

## インストール

### 方法 1：`claude --plugin-dir`（ローカル開発 / 動作確認）

```bash
git clone https://github.com/keefer-osaka/devtools-plugins.git /path/to/devtools-plugins
claude --plugin-dir /path/to/devtools-plugins
```

### 方法 2：プラグインマーケットプレイス経由

```
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

インストール後は **Claude Code を再起動**してください。`/export-chat-logs:setup` と `/export-chat-logs:upload` コマンドが表示されます。`/reload-plugins` では新しくインストールしたスキルは読み込まれません。

### アンインストール

```
/plugin uninstall export-chat-logs@devtools-plugins
/reload-plugins
```

マーケットプレイスソースを削除：

```
/plugin marketplace remove devtools-plugins
```

---

## 初期設定

インストール後、以下のコマンドで Telegram Bot Token、chat_id、および環境設定を行います：

```
/export-chat-logs:setup
```

設定ウィザードはクリック可能な UI を使用します。初回起動時はすべての設定を順番に行います。2 回目以降はメニューで変更したい項目を選択できます：

- **Bot Token**：「Other」欄に貼り付け（Telegram の `@BotFather` → `/mybots` → API Token から取得）
- **Chat ID**：「Other」欄に貼り付け（Telegram の `@userinfobot` → メッセージを送信 → `id` をコピーして取得）
- **環境設定**：タイムゾーン、言語、出力形式、Cowork の包含有無 — クリック可能な選択肢から選択

| 設定項目 | 選択肢 | デフォルト |
|---------|--------|-----------|
| タイムゾーン | UTC+8、UTC+9、UTC-5、UTC-8、または「Other」でカスタム入力 | UTC+8 |
| 言語 | English / 繁體中文 / 日本語 | English |
| 出力形式 | HTML（シンタックスハイライト + グラフ）/ Markdown | HTML |
| Cowork を含める | はい / いいえ（macOS のみ） | いいえ |

設定は `~/.config/devtools-plugins/export-chat-logs/.env` に保存されます（パーミッション 600、リポジトリ非管理）。

---

## 使い方

### エクスポート（デフォルト 7 日間）

```
/export-chat-logs:upload
```

### 日数を指定

```
/export-chat-logs:upload 14
```

### 非インタラクティブモード（`claude -p`）

```bash
claude -p "/export-chat-logs:upload" --allowedTools "Bash,Read"
claude -p "/export-chat-logs:upload 14" --allowedTools "Bash,Read"
```

### 毎週の自動エクスポートを設定（launchd）

```
/export-chat-logs:auto
```

セットアップウィザードがスケジュールとエクスポート日数を確認し、macOS の **launchd** エージェントを自動でインストールします。毎週自動的にエクスポートが実行されます。

> **macOS スケジューリングの動作：**
> - **画面ロック** — 通常通り実行されます（ユーザーセッションはアクティブなまま）。
> - **スリープ** — スリープ中はスキップされますが、起動直後に launchd が補完実行します。
> - **シャットダウン** — 次回起動後に missed ジョブは再実行されません。

---

## 関連：obsidian-kb へのインポート

このプラグインでエクスポートしたチャットログ zip は、[obsidian-kb](https://github.com/keefer-osaka/devtools-plugins/tree/main/plugins/obsidian-kb) プラグインの `/kb-import` スキルに直接渡して、共有ナレッジベース wiki を構築できます。

```
/kb-import chat-logs-alice-20250417.zip
```

zip ファイル名の慣例（`chat-logs-<author>-YYYYMMDD.zip`）は vault 内の著者帰属として保持され、UUID デルタ追跡で重複インポートを防ぎます。

> **ヒント：** `.html` と `.md` の両出力フォーマットに対応しており、`.env` の `OUTPUT_FORMAT` を変更する必要はありません。

---

## 関連：組み込み `/insights` コマンド

Claude Code には組み込みの `/insights` コマンド（プラグイン不要）があり、過去 30 日間の使用パターンを AI が質的に分析したレポートを生成します。

```
/insights
```

`~/.claude/usage-data/` のデータを分析し、以下の内容を含む HTML レポートを生成します：

- インタラクションスタイルと使用習慣
- よく行う作業の種類
- Claude Code ワークフローを改善するための提案

> **注意：** `/insights` はこのプラグインと補完関係にあります — AI による質的分析を提供する一方、`export-chat-logs` はトークン使用量、ツール使用量、セッション時間などの定量的な統計とエクスポート可能なチャット履歴を提供します。

---

## 動作環境

- macOS（Linux では `date` コマンドの調整が必要）
- Python 3
- `curl`、`zip`
- Claude Code CLI

---

## エクスポート内容

- Claude Code：`~/.claude/projects/` の JSONL セッションログ
- Claude Cowork（オプション）：`~/Library/Application Support/Claude/` のセッションログ（macOS のみ）
- 各セッションを HTML ファイルに変換（設定によっては Markdown）
- HTML にはシンタックスハイライト（highlight.js）とインタラクティブグラフ（CSS バーチャート）を含む
- 統計レポートを含む（セッション数、モデル使用量、ツール使用量、カテゴリ別内訳）
- zip に圧縮して Telegram に送信

以下のセッションは自動的にスキップされます：

- **実質的な内容なし**：トークン数がゼロ、または AI の出力 < 100 トークンかつ継続時間 < 60 秒
- **スキル実行のみ**：実行したスキルが 1 つだけ（`/exit` などのメタコマンドは除く）で、他のメッセージやインタラクティブな質問応答（`AskUserQuestion`）を含まない

---

## トラブルシューティング

### `git pull` 後にプラグインが更新されない

マーケットプレイスはローカルに特定バージョンをキャッシュします。pull 後も変更が反映されない場合は、キャッシュを削除して再インストールしてください：

```bash
rm -rf ~/.claude/plugins/cache/devtools-plugins
```

Claude Code で再インストール：

```
/plugin marketplace remove devtools-plugins
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

再インストール後は Claude Code を再起動してください。

---

## ファイル構成

```
.claude-plugin/
└── plugin.json             # プラグインメタデータ
skills/
├── upload/SKILL.md         # /export-chat-logs:upload
├── setup/
│   ├── SKILL.md            # /export-chat-logs:setup
│   └── questions/          # 設定ウィザードの質問定義
│       ├── en.json
│       ├── zh-TW.json
│       └── ja.json
└── auto/
    ├── SKILL.md            # /export-chat-logs:auto
    └── questions/          # 自動エクスポートウィザードの質問定義
        ├── en.json
        ├── zh-TW.json
        └── ja.json
scripts/
├── common.py               # 共有ロジック（JSONL パース、i18n/tz 読み込み）
├── upload.sh               # メインエクスポートフロー
├── save-config.sh          # token + chat_id + タイムゾーン + 言語 + 形式 + Cowork の書き込み
├── install-launchd.sh      # plist 生成・launchd エージェント読み込み・サマリー書き込み（/auto から呼び出し）
├── convert_to_html.py      # JSONL → HTML（シンタックスハイライト + グラフ）
├── convert_to_markdown.py  # JSONL → Markdown
├── generate_stats.py       # 統計レポート（HTML または Markdown）
└── i18n/                   # ロケール文字列
    ├── load.sh                 # i18n ローダー（対応するロケールファイルを読み込む）
    ├── en.sh / en.py           # 英語
    ├── zh_TW.sh / zh_TW.py    # 繁体字中国語
    └── ja.sh / ja.py           # 日本語
```
