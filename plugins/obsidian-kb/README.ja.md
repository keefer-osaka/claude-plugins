# obsidian-kb

[English](README.md) | [繁體中文](README.zh-TW.md)

Obsidian をストレージとして使用する Claude Code の永続記憶ナレッジベース。会話履歴から知識を自動抽出し、構造化された wiki に整理し、任意のディレクトリからセマンティック検索を可能にします。

## 機能

- **`/obsidian-kb:setup`** — vault パス、qmd バイナリ、言語を設定。初回インストール時はメンテナンススキルを vault にデプロイ。
- **`/obsidian-kb:search <質問>`** — ナレッジベースをセマンティック検索（qmd BM25）。任意のディレクトリから使用可能。
- **`/obsidian-kb:upgrade`** — プラグインアップグレード後、最新のメンテナンススクリプトを vault に同期。

セットアップ完了後、**vault ディレクトリで Claude Code を起動**すると利用可能：
- `/kb-ingest` — Claude Code の JSONL 履歴から知識を抽出
- `/kb-lint` — ナレッジベースのヘルスチェック（リンク切れ、孤立ページなど）
- `/kb-stats` — 統計とカバレッジレポート
- `/kb-import` — `export-chat-logs` でエクスポートしたチャットログ zip（`.html` または `.md`）を `transcripts/` にインポート。著者帰属と UUID デルタ追跡（重複なし）対応

## インストール

```
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install obsidian-kb@devtools-plugins
/obsidian-kb:setup
```

## 必要要件

- Python 3.x（インジェストスクリプト用）
- [qmd](https://github.com/toblu/qmd)（任意、セマンティック検索用）：`bun install -g @tobilu/qmd`

## アーキテクチャ

```
~/.claude/projects/**/*.jsonl     chat-log-<author>.zip
         ↓  /kb-ingest                 ↓  /kb-import
         └──────────────┬──────────────┘
                        ↓
transcripts/                   (L1.5: クリーン済みアーカイブ)
         ↓
wiki/                          (L2: 構造化ナレッジページ)
         ↓  @wiki/hot.md
CLAUDE.md                      (L3: セッション起動時注入)
```

ページカテゴリ：entities（エンティティ）、concepts（概念）、decisions（決定）、troubleshooting（トラブルシューティング）、sources（ソースまとめ）。

## マルチコントリビューター ワークフロー

チームメンバーが `export-chat-logs` でセッション zip を Telegram に送信（または直接共有）します。zip ファイル名に著者情報が含まれます：`chat-logs-<author>-YYYYMMDD.zip`。

vault 内で `/kb-import <zip>` を実行するとインポートされます。各 transcript に著者帰属が保持され、UUID デルタ追跡で重複インポートを防ぎます。

## プラグインアップグレード後

`/obsidian-kb:upgrade` を実行して最新のメンテナンススクリプトを vault に同期してください。

## 言語サポート

English、繁體中文（台湾）、日本語をサポート。
