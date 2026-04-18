# export-chat-logs

Claude Code plugin — collects Claude Code and Cowork chat logs, converts them to HTML or Markdown, packages as a zip, and sends via Telegram.

> **Note:** This plugin works with **Claude Code (CLI)** conversations. **Claude Cowork** sessions can also be included (opt-in, macOS only). Claude Desktop Chat and claude.ai web conversations are stored server-side and cannot be accessed locally.

[繁體中文](README.zh-TW.md) | [日本語](README.ja.md)

## Installation

### Method 1: `claude --plugin-dir` (local development / quick test)

```bash
git clone https://github.com/keefer-osaka/devtools-plugins.git /path/to/devtools-plugins
claude --plugin-dir /path/to/devtools-plugins
```

### Method 2: Via plugin marketplace

```
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

After installation, **restart Claude Code** to see the `/export-chat-logs:setup` and `/export-chat-logs:upload` commands. `/reload-plugins` will not load newly installed skills.

### Uninstall

```
/plugin uninstall export-chat-logs@devtools-plugins
/reload-plugins
```

Remove marketplace source:

```
/plugin marketplace remove devtools-plugins
```

---

## Initial Setup

After installation, run the following command to configure your Telegram Bot Token, chat_id, and preferences:

```
/export-chat-logs:setup
```

The setup wizard uses a clickable UI. On first run, it walks through all settings. On subsequent runs, a menu lets you pick which settings to change:

- **Bot Token**: Paste in the "Other" field (get it from Telegram `@BotFather` → `/mybots` → API Token)
- **Chat ID**: Paste in the "Other" field (get it from Telegram `@userinfobot` → send any message → copy `id`)
- **Preferences**: Timezone, Language, Output Format, and Cowork inclusion — select from clickable options

| Setting | Options | Default |
|---------|---------|---------|
| Timezone | UTC+8, UTC+9, UTC-5, UTC-8, or custom via "Other" | UTC+8 |
| Language | English / 繁體中文 / 日本語 | English |
| Output format | HTML (syntax highlighting + charts) / Markdown | HTML |
| Include Cowork | Yes / No (macOS only) | No |

Settings are saved to `~/.config/devtools-plugins/export-chat-logs/.env` (permissions 600, not in repo).

---

## Usage

### Export (default 7 days)

```
/export-chat-logs:upload
```

### Specify number of days

```
/export-chat-logs:upload 14
```

### Non-interactive mode (`claude -p`)

```bash
claude -p "/export-chat-logs:upload" --allowedTools "Bash,Read"
claude -p "/export-chat-logs:upload 14" --allowedTools "Bash,Read"
```

### Automate weekly exports (launchd)

```
/export-chat-logs:auto
```

The setup wizard asks for your preferred schedule and export range, then installs a macOS **launchd** agent that runs automatically every week.

> **macOS scheduling behavior:**
> - **Screen locked** — job runs normally; the user session remains active.
> - **Asleep** — job is skipped during sleep, but launchd fires a compensatory run immediately on wake.
> - **Shut down** — missed jobs are not re-run after the next boot.

---

## Related: Ingest into obsidian-kb

Chat-log zips exported by this plugin can be fed directly into the [obsidian-kb](https://github.com/keefer-osaka/devtools-plugins/tree/main/plugins/obsidian-kb) plugin's `/kb-import` skill to populate a shared knowledge-base wiki.

```
/kb-import chat-logs-alice-20250417.zip
```

The zip filename convention (`chat-logs-<author>-YYYYMMDD.zip`) is preserved as author attribution inside the vault, and UUID-based delta tracking prevents duplicate ingestion if the same zip is imported twice.

> **Tip:** Both `.html` and `.md` output formats are accepted — no need to change `OUTPUT_FORMAT` in `.env`.

---

## Related: Built-in `/insights` Command

Claude Code has a built-in `/insights` command (no plugin required) that generates an AI-powered qualitative analysis report of your usage patterns over the past 30 days.

```
/insights
```

It analyzes data from `~/.claude/usage-data/` and produces an HTML report covering:

- Interaction style and habits
- Types of tasks you commonly work on
- Suggestions for improving your Claude Code workflow

> **Note:** `/insights` is complementary to this plugin — it provides qualitative AI analysis, while `export-chat-logs` provides quantitative statistics (token usage, tool usage, session duration, etc.) with exportable chat history.

---

## Requirements

- macOS (Linux requires minor adjustments to the `date` command)
- Python 3
- `curl`, `zip`
- Claude Code CLI

---

## Exported Content

- Claude Code: JSONL session logs from `~/.claude/projects/`
- Claude Cowork (opt-in): session logs from `~/Library/Application Support/Claude/` (macOS only)
- Each session is converted to an HTML file (or Markdown if configured)
- HTML includes syntax highlighting (highlight.js) and interactive charts (CSS bar charts)
- Includes a statistics report (session count, model usage, tool usage, category breakdown)
- Packaged as a zip and sent to Telegram

The following sessions are automatically skipped:

- **No meaningful content**: zero tokens, or AI output < 100 tokens and duration < 60 seconds
- **Skill-only execution**: only one real skill was invoked (meta commands like `/exit` don't count), with no other messages and no interactive prompts (`AskUserQuestion`)

---

## Troubleshooting

### Plugin not updating after `git pull`

The marketplace caches a specific version locally. If changes are not reflected after pulling, clear the cache and reinstall:

```bash
rm -rf ~/.claude/plugins/cache/devtools-plugins
```

Then reinstall in Claude Code:

```
/plugin marketplace remove devtools-plugins
/plugin marketplace add keefer-osaka/devtools-plugins
/plugin install export-chat-logs@devtools-plugins
```

Restart Claude Code after reinstalling.

---

## File Structure

```
.claude-plugin/
└── plugin.json             # Plugin metadata
skills/
├── upload/SKILL.md         # /export-chat-logs:upload
├── setup/
│   ├── SKILL.md            # /export-chat-logs:setup
│   └── questions/          # Setup wizard question definitions
│       ├── en.json
│       ├── zh-TW.json
│       └── ja.json
└── auto/
    ├── SKILL.md            # /export-chat-logs:auto
    └── questions/          # Auto export wizard question definitions
        ├── en.json
        ├── zh-TW.json
        └── ja.json
scripts/
├── common.py               # Shared logic (JSONL parsing, i18n/tz loading)
├── upload.sh               # Main export flow
├── save-config.sh          # Write token + chat_id + timezone + language + format + cowork
├── install-launchd.sh      # Generate plist, load launchd agent, write summary (used by /auto)
├── convert_to_html.py      # JSONL → HTML (syntax highlighting + charts)
├── convert_to_markdown.py  # JSONL → Markdown
├── generate_stats.py       # Statistics report (HTML or Markdown)
└── i18n/                   # Locale strings
    ├── load.sh                 # i18n loader (sources correct locale file)
    ├── en.sh / en.py           # English
    ├── zh_TW.sh / zh_TW.py    # Traditional Chinese
    └── ja.sh / ja.py           # Japanese
```
