# devtools-plugins

[English](README.md) | [繁體中文](README.zh-TW.md)

開発者ワークフロー向け [Claude Code](https://claude.ai/code) プラグイン集。

## プラグイン一覧

| プラグイン | 説明 |
|-----------|------|
| [obsidian-kb](plugins/obsidian-kb/README.ja.md) | Obsidian ナレッジベース vault の構築と運用。kb-ingest / kb-lint / kb-stats / kb-import スキル、マルチコントリビューター対応、qmd ベースの検索を内蔵 |
| [export-chat-logs](plugins/export-chat-logs/README.ja.md) | Claude Code と Cowork のチャットログを HTML または Markdown に変換し、zip に圧縮して Telegram で送信 |
| [protoc-java-gen](plugins/protoc-java-gen/README.ja.md) | 指定バージョンの protoc を使って `.proto` ファイルから Java を生成し、各サブプロジェクトに自動コピー |

## インストール

このマーケットプレイスを Claude Code に追加：

```
/plugin marketplace add keefer-osaka/devtools-plugins
```

個別プラグインをインストール：

```
/plugin install obsidian-kb@devtools-plugins
/plugin install export-chat-logs@devtools-plugins
/plugin install protoc-java-gen@devtools-plugins
```

## ライセンス

MIT
