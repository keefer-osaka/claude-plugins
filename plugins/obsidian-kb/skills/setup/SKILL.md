---
name: setup
description: "Configure the obsidian-kb plugin: set vault directory, qmd binary, collection, and language. On first install, also deploys kb-ingest/kb-lint/kb-stats into the vault."
allowed-tools:
  - Bash
  - Read
  - AskUserQuestion
disable-model-invocation: true
---

# obsidian-kb Setup

> Execute each step silently. Do not print step names, detected values, intermediate status, or any text between tool calls. After the final step, output nothing.

## Step 1 — Read current configuration

Read `~/.config/devtools-plugins/obsidian-kb/.env` (try `$HOME/.config/devtools-plugins/obsidian-kb/.env` if `~` fails). If missing: first-time setup.

Extract: `CURRENT_VAULT_DIR`, `CURRENT_LANG` (default `en`), `CURRENT_QMD_BIN`, `CURRENT_QMD_COLLECTION` (default `obsidian-wiki`).

---

## Step 2 — Language (first-time only)

**Reconfigure** (`.env` exists): set `SETUP_LANG = CURRENT_LANG` internally. Skip to Step 3.

**First-time**: ask AskUserQuestion with the JSON below. Map answer → `SETUP_LANG`.

```json
{
  "questions": [{
    "question": "Select language / 選擇語言 / 言語を選択",
    "header": "Language",
    "multiSelect": false,
    "options": [
      { "label": "English", "description": "All output in English" },
      { "label": "繁體中文", "description": "所有輸出使用繁體中文" },
      { "label": "日本語", "description": "すべての出力を日本語で表示" }
    ]
  }]
}
```

---

## Step 3 — Load Q

Read `"${CLAUDE_PLUGIN_ROOT}/skills/setup/questions/<SETUP_LANG>.json"` → store as `Q`.

---

## Step 4 — Menu (reconfigure only)

**First-time**: skip to Step 5.

**Reconfigure**: ask `Q["menu"]` substituting `<CURRENT_*>` placeholders. Store selected option labels as `SELECTED`.

If `"Language"` / `"語言"` / `"言語"` is in `SELECTED`: ask `Q["language"]` as a separate AskUserQuestion. Map answer → `SETUP_LANG`. Reload Q with the new language.

Normalize `SELECTED` → `SELECTED_TOKENS` (use in Steps 5–8):

| Label in SELECTED | Token |
|-------------------|-------|
| `"Vault Directory"`, `"Vault 路徑"`, `"Vault ディレクトリ"` | `vault` |
| `"Qmd Binary"`, `"qmd Binary"` | `qmd_bin` |
| `"Qmd Collection"`, `"qmd Collection"` | `qmd_collection` |
| `"Language"`, `"語言"`, `"言語"` | `lang` |

---

## Step 5 — Detect defaults

**Reconfigure**: skip to Step 6 if neither `vault` nor `qmd_bin` is in `SELECTED_TOKENS`. Set `DETECTED_VAULT=""`, `DETECTED_QMD=""`.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/detect-defaults.sh"
```

Parse output silently: `DETECTED_VAULT`, `DETECTED_QMD`.

---

## Step 6 — Settings

Take `Q["all_settings"]`. Substitute `<DETECTED_VAULT>` and `<DETECTED_QMD>` in all option labels and descriptions.

- **First-time**: ask AskUserQuestion with all three sub-questions.
- **Reconfigure**: ask AskUserQuestion with only the sub-questions whose `header` is in `SELECTED`, excluding `lang` (already handled in Step 4). Omit others; pass `skip` for their values in Step 8. If no sub-questions remain, skip this step.

From the answers, set `VAULT_PATH` (vault dir answer or text field), `QMD_BIN_VAL`, `QMD_COLLECTION_VAL`.

---

## Step 7 — Validate vault (if Vault Directory was answered)

**Skip** if `vault` is not in `SELECTED_TOKENS` (reconfigure only). Set `NEED_INIT=0` and `VAULT_STATUS=existing`.

Otherwise:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/validate-vault.sh" "$VAULT_PATH"
```

Parse output silently: `VAULT_STATUS`, `NEED_INIT`.

**If `VAULT_STATUS=partial`**: Output the following error based on `SETUP_LANG` and stop — do not proceed to Step 8:

| SETUP_LANG | Message |
|------------|---------|
| `en` | ⚠️ `<VAULT_PATH>` has an incomplete structure — only one of `wiki/` or `_schema/` exists. Remove the partial directory and re-run `/obsidian-kb:setup` to start fresh. |
| `zh-TW` | ⚠️ `<VAULT_PATH>` 的 vault 結構不完整 — `wiki/` 與 `_schema/` 只存在其中一個。請移除該目錄後重新執行 `/obsidian-kb:setup`。 |
| `ja` | ⚠️ `<VAULT_PATH>` の vault 構造が不完全です — `wiki/` と `_schema/` の一方しか存在しません。ディレクトリを削除してから `/obsidian-kb:setup` を再実行してください。 |

---

## Step 8 — Save and install

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/save-config.sh" "<VAULT_PATH or skip>" "<SETUP_LANG if first-time or lang in SELECTED_TOKENS, else skip>" "<QMD_BIN_VAL or skip>" "<QMD_COLLECTION_VAL or skip>"
```

If `NEED_INIT=1`: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/init-vault.sh" "$VAULT_PATH"`

If first-time OR `NEED_INIT=1`: `bash "${CLAUDE_PLUGIN_ROOT}/scripts/install-vault-skills.sh" "$VAULT_PATH"`

Stop. Output nothing further.

---

## Answer mapping

| Answer | Value |
|--------|-------|
| Not selected / skipped | `skip` |
| `"English"` | `en` |
| `"繁體中文"` | `zh-TW` |
| `"日本語"` | `ja` |
| Label equal to `DETECTED_VAULT` | `DETECTED_VAULT` |
| `"Use detected path"` / `"使用偵測到的路徑"` / `"検出されたパスを使用"` | `DETECTED_QMD` |
| `"Skip / disable search"` / `"停用搜尋功能"` / `"スキップ / 検索を無効化"` | `""` |
| `"Keep default (obsidian-wiki)"` / `"保留預設（obsidian-wiki）"` / `"デフォルトを維持（obsidian-wiki）"` | `obsidian-wiki` |
| Text field input | as-is |
