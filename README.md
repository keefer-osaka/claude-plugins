# devtools-plugins

[繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

A collection of [Claude Code](https://claude.ai/code) plugins for developer workflows.

## Plugins

| Plugin | Description |
|--------|-------------|
| [obsidian-kb](plugins/obsidian-kb/) | Bootstrap and maintain an Obsidian knowledge-base vault with kb-ingest / kb-lint / kb-stats / kb-import skills, multi-contributor support, and qmd-backed search |
| [export-chat-logs](plugins/export-chat-logs/) | Export Claude Code and Cowork chat logs as HTML or Markdown, zip them, and send via Telegram |
| [protoc-java-gen](plugins/protoc-java-gen/) | Generate Java from `.proto` files using a specific protoc version and auto-copy to subprojects |

## Installation

Add this marketplace to Claude Code:

```
/plugin marketplace add keefer-osaka/devtools-plugins
```

Then install individual plugins:

```
/plugin install obsidian-kb@devtools-plugins
/plugin install export-chat-logs@devtools-plugins
/plugin install protoc-java-gen@devtools-plugins
```

## License

MIT
