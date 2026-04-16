#!/usr/bin/env bash
# install-vault-skills.sh - Deploy kb-ingest/kb-lint/kb-stats into <VAULT_DIR>/.claude/skills/
# Usage: bash install-vault-skills.sh <vault_dir> [--force]
#   --force: skip version check and always upgrade (used by upgrade skill)

set -euo pipefail

VAULT_DIR="${1:-}"
VAULT_DIR="${VAULT_DIR/#\~/$HOME}"
FORCE="${2:-}"

if [ -z "$VAULT_DIR" ]; then
  echo "Usage: bash install-vault-skills.sh <vault_dir> [--force]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${SCRIPT_DIR%/*}"

source "$SCRIPT_DIR/i18n/load.sh"
source "$SCRIPT_DIR/plugin-version.sh"

PLUGIN_VERSION=$(plugin_version "$PLUGIN_ROOT")

SKILLS_DIR="$VAULT_DIR/.claude/skills"
VERSION_FILE="$SKILLS_DIR/_version"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="$SKILLS_DIR/.backup-$TIMESTAMP"

HAS_EXISTING=0
for skill in kb-ingest kb-lint kb-stats kb-wiki; do
  if [ -d "$SKILLS_DIR/$skill" ]; then
    HAS_EXISTING=1
    break
  fi
done

OLD_VERSION=""

if [ "$HAS_EXISTING" -eq 1 ]; then
  EXISTING_VERSION=""
  if [ -f "$VERSION_FILE" ]; then
    EXISTING_VERSION=$(tr -d '[:space:]' < "$VERSION_FILE")
  fi
  OLD_VERSION="${EXISTING_VERSION:-unknown}"

  # Same version + no --force → already up to date
  if [ "$FORCE" != "--force" ] && [ "$EXISTING_VERSION" = "$PLUGIN_VERSION" ]; then
    fmt "$MSG_SKILLS_ALREADY_CURRENT" VERSION "$PLUGIN_VERSION"
    exit 0
  fi

  mkdir -p "$BACKUP_DIR"
  for skill in kb-ingest kb-lint kb-stats kb-wiki; do
    mv "$SKILLS_DIR/$skill" "$BACKUP_DIR/" 2>/dev/null || true
  done
  mv "$SKILLS_DIR/_version" "$BACKUP_DIR/" 2>/dev/null || true
  mv "$SKILLS_DIR/_installed-by" "$BACKUP_DIR/" 2>/dev/null || true
fi

mkdir -p "$SKILLS_DIR"
rsync -a "$PLUGIN_ROOT/vault-payload/.claude/skills/" "$SKILLS_DIR/"

mkdir -p "$VAULT_DIR/_schema/templates"
rsync -a "$PLUGIN_ROOT/vault-payload/_schema/templates/" "$VAULT_DIR/_schema/templates/"

find "$SKILLS_DIR" -name "SKILL.md" -exec sed -i '' "s|__VAULT_DIR__|$VAULT_DIR|g" {} +

printf '%s' "$PLUGIN_VERSION" > "$VERSION_FILE"
printf 'obsidian-kb plugin %s installed at %s\n' "$PLUGIN_VERSION" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$SKILLS_DIR/_installed-by"
if [ "$HAS_EXISTING" -eq 1 ]; then
  fmt "$MSG_SKILLS_UPGRADED" OLD_VERSION "$OLD_VERSION" NEW_VERSION "$PLUGIN_VERSION" BACKUP_DIR "$BACKUP_DIR"
else
  fmt "$MSG_SKILLS_INSTALLED" VERSION "$PLUGIN_VERSION" VAULT_DIR "$VAULT_DIR"
fi

echo "$MSG_NEXT_STEPS"
