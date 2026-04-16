---
name: search
description: "Search the configured Obsidian knowledge base via qmd BM25/vector search. Usage: /obsidian-kb:search <question>"
allowed-tools:
  - Bash
  - Read
---

# obsidian-kb Search

## Step 1 — Load configuration

```bash
source "${CLAUDE_PLUGIN_ROOT}/scripts/load-env.sh"
source "${CLAUDE_PLUGIN_ROOT}/scripts/i18n/load.sh"
```

Extract: `VAULT_DIR`, `QMD_BIN`, `QMD_COLLECTION`, `PLUGIN_LANG`.

## Step 2 — Validate configuration

If `VAULT_DIR` is empty:
```
echo "$ERR_NOT_CONFIGURED"
```
Stop.

## Step 3 — Resolve qmd binary

Effective qmd binary resolution order:
1. `QMD_BIN` from .env (if non-empty and file exists)
2. `command -v qmd` (PATH lookup)
3. `$HOME/.bun/bin/qmd` (bun global)

If none found → print `$ERR_QMD_NOT_FOUND`, then fallback to reading `$VAULT_DIR/wiki/index.md` for manual navigation. Stop.

## Step 4 — Run qmd query (vector search)

```bash
QUERY="$ARGUMENTS"
"$QMD_BIN" query "$QUERY" --collection "$QMD_COLLECTION"
```

If exit code non-zero or output is empty / "No results":
- Print `$MSG_NO_RESULTS`
- Proceed to Step 5 (lex fallback)

Otherwise: synthesize results and answer in language matching `PLUGIN_LANG`.

## Step 5 — Lex fallback

```bash
"$QMD_BIN" query "$QUERY" --collection "$QMD_COLLECTION" --type lex
```

If results found: synthesize and answer.

If still no results:
- Print `$MSG_NO_RESULTS_LEX`
- Read `$VAULT_DIR/wiki/index.md` and use it for manual navigation

## Notes

- `PLUGIN_LANG` determines the response language: `en` → English, `zh-TW` → 繁體中文, `ja` → 日本語
- The qmd collection must be built first via `/kb-ingest` → `qmd update --collection <collection>`
- Cross-directory: this skill works from any working directory
