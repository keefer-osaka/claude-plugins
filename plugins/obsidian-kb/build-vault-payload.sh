#!/usr/bin/env bash
# build-vault-payload.sh - Dev-time tool: sync skills from the live vault into vault-payload/
# and template-ize hardcoded paths to __VAULT_DIR__.
#
# Usage: bash build-vault-payload.sh [<vault_dir>]
#   Default vault_dir: $HOME/claude-code/Obsidian
#
# Run this whenever kb-ingest/kb-lint/kb-stats SKILL.md or scripts are updated in the vault.

set -euo pipefail

VAULT_DIR="${1:-$HOME/claude-code/Obsidian}"
SCRIPT_DIR="$(cd "${0%/*}" && pwd)"
PAYLOAD_SKILLS="$SCRIPT_DIR/vault-payload/.claude/skills"
PAYLOAD_TEMPLATES="$SCRIPT_DIR/vault-payload/_schema/templates"

echo "=== build-vault-payload.sh ==="
echo "Source vault: $VAULT_DIR"
echo "Target:       $SCRIPT_DIR/vault-payload/"
echo ""

# Verify source exists
for skill in kb-ingest kb-lint kb-stats; do
  if [ ! -d "$VAULT_DIR/.claude/skills/$skill" ]; then
    echo "❌ Missing: $VAULT_DIR/.claude/skills/$skill" >&2
    exit 1
  fi
done

# Create destination directories
mkdir -p \
  "$PAYLOAD_SKILLS/kb-ingest" \
  "$PAYLOAD_SKILLS/kb-lint" \
  "$PAYLOAD_SKILLS/kb-stats" \
  "$PAYLOAD_TEMPLATES"

# Sync kb-ingest, kb-lint, kb-stats in parallel (SKILL.md + scripts/ per skill)
_pids=()
for _skill in kb-ingest kb-lint kb-stats; do
  (
    echo "→ Syncing ${_skill}..."
    rsync -a --delete \
      --include='SKILL.md' --include='scripts/' --include='scripts/**' --exclude='*' \
      "$VAULT_DIR/.claude/skills/${_skill}/" \
      "$PAYLOAD_SKILLS/${_skill}/"
  ) &
  _pids+=($!)
  if [ "${#_pids[@]}" -ge 8 ]; then
    wait "${_pids[0]}" 2>/dev/null || true
    _pids=("${_pids[@]:1}")
  fi
done
wait "${_pids[@]}" 2>/dev/null || true

# ── Templates ──────────────────────────────────────────────────────────────
echo "→ Syncing templates..."
rsync -a --delete \
  "$VAULT_DIR/_schema/templates/" \
  "$PAYLOAD_TEMPLATES/"

# ── Template-ize hardcoded vault path in SKILL.md files ───────────────────
echo "→ Replacing '$VAULT_DIR' → '__VAULT_DIR__' in SKILL.md files..."
find "$PAYLOAD_SKILLS" -name "SKILL.md" -exec sed -i '' "s|$VAULT_DIR|__VAULT_DIR__|g" {} +

# ── Write _version file ────────────────────────────────────────────────────
source "$SCRIPT_DIR/scripts/plugin-version.sh"
PLUGIN_VERSION=$(plugin_version "$SCRIPT_DIR")
printf '%s' "$PLUGIN_VERSION" > "$PAYLOAD_SKILLS/_version"
echo "→ _version = $PLUGIN_VERSION"

# ── Verify: no absolute paths should remain in SKILL.md ───────────────────
echo ""
echo "=== Verification ==="
LEAKED=$(grep -r "$VAULT_DIR" "$PAYLOAD_SKILLS" --include="*.md" -l 2>/dev/null || true)
if [ -n "$LEAKED" ]; then
  echo "❌ Found leaked absolute paths in:" >&2
  echo "$LEAKED" >&2
  exit 1
fi

# Also check Python scripts don't reference VAULT_DIR directly
# (they should use __file__ dirname resolution — not hardcoded paths)
PY_HARDCODED=$(grep -r "claude-code/Obsidian" "$PAYLOAD_SKILLS" --include="*.py" -l 2>/dev/null || true)
if [ -n "$PY_HARDCODED" ]; then
  echo "⚠️  Python scripts with hardcoded Obsidian path (verify these use __file__ dirname):" >&2
  echo "$PY_HARDCODED" >&2
fi

echo "✅ vault-payload/ is clean — no hardcoded vault paths in SKILL.md files"
echo ""
echo "Files in vault-payload/.claude/skills/:"
find "$PAYLOAD_SKILLS" -type f | sort
