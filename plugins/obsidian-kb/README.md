# obsidian-kb

[繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

Persistent knowledge base for Claude Code, built on Obsidian. Extracts knowledge from your Claude Code conversation history, stores it in a structured wiki, and makes it searchable from any working directory.

## Overview

- **`/obsidian-kb:setup`** — Configure vault path, qmd binary, and language. Deploys maintenance skills into the vault on first install.
- **`/obsidian-kb:search <question>`** — Semantic search across your knowledge base (BM25 via qmd). Works from any directory.
- **`/obsidian-kb:upgrade`** — Sync the latest maintenance scripts into your vault after upgrading the plugin.

After setup, these skills become available **inside your vault directory**:
- `/kb-ingest` — Extract knowledge from Claude Code JSONL history
- `/kb-lint` — Check knowledge base health (broken links, orphaned pages, etc.)
- `/kb-stats` — Statistics and coverage report
- `/kb-import` — Import chat-log zips exported by `export-chat-logs` (`.html` or `.md`) into `transcripts/`, with author attribution and UUID-based delta (no duplicates)

## Installation

```
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install obsidian-kb@devtools-plugins
/obsidian-kb:setup
```

## Requirements

- Python 3.x (for ingest scripts)
- [qmd](https://github.com/toblu/qmd) (optional, for semantic search): `bun install -g @tobilu/qmd`

## Architecture

```
~/.claude/projects/**/*.jsonl     chat-log-<author>.zip
         ↓  /kb-ingest                 ↓  /kb-import
         └──────────────┬──────────────┘
                        ↓
transcripts/                   (L1.5: cleaned conversation archive)
         ↓
wiki/                          (L2: structured knowledge wiki)
         ↓  @wiki/hot.md
CLAUDE.md                      (L3: session injection)
```

Knowledge pages are organized into: entities, concepts, decisions, troubleshooting, sources.

## Multi-contributor workflow

Teammates running `export-chat-logs` send their session zips to Telegram (or share the file directly). Each zip filename encodes the author: `chat-logs-<author>-YYYYMMDD.zip`.

Run `/kb-import <zip>` inside the vault to ingest their sessions. Author attribution is preserved in every transcript, and UUID-based delta tracking prevents duplicates if the same zip is imported twice.

## After Plugin Upgrade

Run `/obsidian-kb:upgrade` to sync the latest maintenance scripts into your vault.

## Languages

Supports English, 繁體中文 (Traditional Chinese), and 日本語.
