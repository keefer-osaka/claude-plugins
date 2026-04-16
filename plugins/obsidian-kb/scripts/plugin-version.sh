#!/usr/bin/env bash
# plugin_version <plugin_root> — Print version from .claude-plugin/plugin.json
# Usage: source plugin-version.sh; PLUGIN_VERSION=$(plugin_version "$PLUGIN_ROOT")
plugin_version() {
  local pj="$1/.claude-plugin/plugin.json"
  grep -o '"version"[[:space:]]*:[[:space:]]*"[^"]*"' "$pj" \
    | head -1 | sed 's/.*"\([^"]*\)"$/\1/'
}
