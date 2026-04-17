#!/usr/bin/env bash
# install-launchd.sh — Write plist, load launchd agent, write summary file
# Usage: bash install-launchd.sh <weekday> <hour> <minute> <days> <project_dir|skip> <plugin_dir_path|skip> <lang>
#   weekday:          0-7 (launchd: 0 or 7 = Sunday, 1 = Monday, ..., 6 = Saturday)
#   hour:             0-23 (local time)
#   minute:           0-59
#   days:             number of days to cover per export
#   project_dir:      absolute path to working directory, or "skip"
#   plugin_dir_path:  absolute path to plugin dir (local dev / git clone), or "skip"
#   lang:             en | zh-TW | ja

set -uo pipefail

WEEKDAY="${1:?weekday required}"
HOUR="${2:?hour required}"
MINUTE="${3:?minute required}"
DAYS="${4:?days required}"
PROJECT_DIR="${5:-skip}"
PLUGIN_DIR_PATH="${6:-skip}"
SETUP_LANG="${7:-en}"

# Normalize "skip"
[ "$PROJECT_DIR"    = "skip" ] && PROJECT_DIR=""
[ "$PLUGIN_DIR_PATH" = "skip" ] && PLUGIN_DIR_PATH=""

# Source locale strings (and fmt() from shared)
source "$(cd "${BASH_SOURCE[0]%/*}" && pwd)/i18n/load.sh"

# Day name via indirect reference (LAUNCHD_DAY_0 … LAUNCHD_DAY_7)
_DAY_VAR="LAUNCHD_DAY_${WEEKDAY}"
DAY_NAME="${!_DAY_VAR:-Day${WEEKDAY}}"

# Zero-padded time display
HH_MM="$(printf '%02d:%02d' "$HOUR" "$MINUTE")"

# Detect paths
CLAUDE_PATH="$(which claude 2>/dev/null || echo "claude")"
HOME_PATH="$HOME"
CLAUDE_DIR="$(dirname "$CLAUDE_PATH")"

# Plist constants
PLIST_LABEL="com.devtools-plugins.export-chat-logs"
PLIST_FILE="${HOME_PATH}/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_FILE="${HOME_PATH}/.config/devtools-plugins/export-chat-logs/launchd.log"

# Ensure directories exist
mkdir -p "${HOME_PATH}/Library/LaunchAgents"
mkdir -p "$(dirname "$LOG_FILE")"

# ── Build conditional plist fragments ────────────────────────────────────────

# Optional --plugin-dir entries (with trailing newline so the next line aligns)
if [ -n "$PLUGIN_DIR_PATH" ]; then
  _PLUGIN_DIR_ENTRIES="        <string>--plugin-dir</string>
        <string>${PLUGIN_DIR_PATH}</string>
"
else
  _PLUGIN_DIR_ENTRIES=""
fi

# Optional WorkingDirectory block (with trailing newline)
if [ -n "$PROJECT_DIR" ]; then
  _WORKING_DIR_BLOCK="    <key>WorkingDirectory</key>
    <string>${PROJECT_DIR}</string>
"
else
  _WORKING_DIR_BLOCK=""
fi

# ── Write plist ───────────────────────────────────────────────────────────────

cat > "$PLIST_FILE" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${CLAUDE_PATH}</string>
${_PLUGIN_DIR_ENTRIES}        <string>-p</string>
        <string>/export-chat-logs:upload ${DAYS}</string>
        <string>--allowedTools</string>
        <string>Bash,Read</string>
    </array>

    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>${WEEKDAY}</integer>
        <key>Hour</key>
        <integer>${HOUR}</integer>
        <key>Minute</key>
        <integer>${MINUTE}</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>${LOG_FILE}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_FILE}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>${HOME_PATH}</string>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:${CLAUDE_DIR}</string>
    </dict>

${_WORKING_DIR_BLOCK}    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
PLIST_EOF

# ── Load launchd agent ────────────────────────────────────────────────────────

launchctl unload "$PLIST_FILE" 2>/dev/null || true
launchctl load "$PLIST_FILE"
launchctl list | grep devtools-plugins || true

# ── Write summary markdown file ───────────────────────────────────────────────

CWD_PATH="$(pwd)"
SUMMARY_FILE="${CWD_PATH}/export-chat-logs-auto.md"

_SCHED_VAL="$(fmt "$LAUNCHD_MD_SCHEDULE_VAL" DAY_NAME "$DAY_NAME" HH_MM "$HH_MM")"
_TB='```'

cat > "$SUMMARY_FILE" << SUMMARY_EOF
${LAUNCHD_MD_TITLE}

- **${LAUNCHD_MD_SCHEDULE}:** ${_SCHED_VAL}
- **Plist:** \`${PLIST_FILE}\`
- **${LAUNCHD_MD_LOG}:** \`${LOG_FILE}\`

${LAUNCHD_MD_COMMANDS}

${LAUNCHD_MD_TEST}
${_TB}bash
launchctl start ${PLIST_LABEL}
${_TB}

${LAUNCHD_MD_REMOVE}
${_TB}bash
launchctl unload ${PLIST_FILE}
rm ${PLIST_FILE}
${_TB}
SUMMARY_EOF

# ── Print success message ─────────────────────────────────────────────────────

echo ""
echo "$MSG_LAUNCHD_INSTALLED"
echo ""
fmt "$MSG_LAUNCHD_SCHEDULE" DAY_NAME "$DAY_NAME" HH_MM "$HH_MM"
fmt "$MSG_LAUNCHD_PLIST" PLIST_FILE "$PLIST_FILE"
fmt "$MSG_LAUNCHD_LOG" LOG_FILE "$LOG_FILE"
echo ""
echo "$MSG_LAUNCHD_TEST"
echo "  launchctl start ${PLIST_LABEL}"
echo ""
echo "$MSG_LAUNCHD_REMOVE"
echo "  launchctl unload ${PLIST_FILE}"
echo "  rm ${PLIST_FILE}"
echo ""
fmt "$MSG_LAUNCHD_SUMMARY_SAVED" SUMMARY_FILE "$SUMMARY_FILE"
