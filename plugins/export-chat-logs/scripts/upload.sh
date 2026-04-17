#!/usr/bin/env bash
# upload.sh - Export Claude Code chat logs and send to Telegram
# Usage: bash upload.sh [days=7]

set -e

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATS_SCRIPT="$PLUGIN_ROOT/scripts/generate_stats.py"

# Load locale strings
source "$(dirname "$0")/i18n/load.sh"

DAYS="${1:-7}"

# Load configuration (token + chat_id)
DATA_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/devtools-plugins/export-chat-logs"
ENV_FILE="$DATA_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "$ERR_NOT_CONFIGURED"
  exit 1
fi
TELEGRAM_BOT_TOKEN=$(read_env_val TELEGRAM_BOT_TOKEN)
CHAT_ID=$(read_env_val TELEGRAM_CHAT_ID)
OUTPUT_FORMAT=$(read_env_val OUTPUT_FORMAT)
OUTPUT_FORMAT="${OUTPUT_FORMAT:-html}"
INCLUDE_COWORK=$(read_env_val INCLUDE_COWORK)
INCLUDE_COWORK="${INCLUDE_COWORK:-false}"

# Select converter based on output format
if [ "$OUTPUT_FORMAT" = "html" ]; then
  CONVERTER="$PLUGIN_ROOT/scripts/convert_to_html.py"
else
  CONVERTER="$PLUGIN_ROOT/scripts/convert_to_markdown.py"
fi
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
  echo "$ERR_TOKEN_EMPTY"
  exit 1
fi
if [ -z "$CHAT_ID" ]; then
  echo "$ERR_CHATID_EMPTY"
  exit 1
fi

# Create temp directory
EXPORT_DATE=$(date +%Y%m%d)
TMPDIR_PATH="$TMPDIR/chat-export-${EXPORT_DATE}-$$"
rm -rf "$TMPDIR_PATH"
mkdir -p "$TMPDIR_PATH/claude-code"
if [ "$INCLUDE_COWORK" = "true" ]; then
  mkdir -p "$TMPDIR_PATH/claude-cowork"
fi

# Strip home directory prefix from project folder name (e.g. -Users-user-foo-bar → foo-bar)
HOME_ENCODED=$(echo "$HOME" | tr '/' '-')

# Convert Claude Code sessions (parallel)
CC_MARK_DIR="$TMPDIR_PATH/.cc_done"
mkdir -p "$CC_MARK_DIR"

_convert_cc() {
  local f="$1" proj disp out
  proj=$(echo "$f" | sed 's|.*/projects/||' | cut -d'/' -f1)
  disp=$(echo "$proj" | sed "s/^${HOME_ENCODED}-//;s/^${HOME_ENCODED}$//")
  out="$TMPDIR_PATH/claude-code/$disp"
  mkdir -p "$out"
  python3 "$CONVERTER" "$f" "$out" --days "$DAYS" >/dev/null 2>&1 && \
    mktemp "$CC_MARK_DIR/XXXXXXXXXX" >/dev/null || true
}

_cc_pids=()
while IFS= read -r _f; do
  _convert_cc "$_f" &
  _cc_pids+=($!)
  if [ "${#_cc_pids[@]}" -ge 8 ]; then
    wait "${_cc_pids[0]}" 2>/dev/null || true
    _cc_pids=("${_cc_pids[@]:1}")
  fi
done < <(find "$HOME/.claude/projects" -name "*.jsonl" \
  -not -path "*/subagents/*" \
  -not -path "*/memory/*" \
  -mtime -"$DAYS" 2>/dev/null)
wait 2>/dev/null || true

CC_COUNT=$(find "$CC_MARK_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')

# Convert Claude Cowork sessions (opt-in, macOS only)
CW_COUNT=0
COWORK_PATHS=()
if [ "$INCLUDE_COWORK" = "true" ]; then
  COWORK_PATHS=(
    "$HOME/Library/Application Support/Claude/local-agent-mode-sessions"
    "$HOME/Library/Application Support/Claude/claude-code-sessions"
  )

  CW_MARK_DIR="$TMPDIR_PATH/.cw_done"
  mkdir -p "$CW_MARK_DIR"

  _convert_cw() {
    local f="$1" proj out
    proj=$(python3 "$PLUGIN_ROOT/scripts/common.py" --extract-cwd "$f" 2>/dev/null)
    proj="${proj:-unknown}"
    out="$TMPDIR_PATH/claude-cowork/$proj"
    mkdir -p "$out"
    python3 "$CONVERTER" "$f" "$out" --days "$DAYS" --source-label cowork >/dev/null 2>&1 && \
      mktemp "$CW_MARK_DIR/XXXXXXXXXX" >/dev/null || true
  }

  _cw_pids=()
  while IFS= read -r _f; do
    _convert_cw "$_f" &
    _cw_pids+=($!)
    if [ "${#_cw_pids[@]}" -ge 8 ]; then
      wait "${_cw_pids[0]}" 2>/dev/null || true
      _cw_pids=("${_cw_pids[@]:1}")
    fi
  done < <({
    for COWORK_BASE in "${COWORK_PATHS[@]}"; do
      [ -d "$COWORK_BASE" ] || continue
      find "$COWORK_BASE" -name "*.jsonl" \
        -not -path "*/subagents/*" \
        -not -path "*/memory/*" \
        -not -name "audit.jsonl" \
        -mtime -"$DAYS" 2>/dev/null
    done
  })
  wait 2>/dev/null || true

  CW_COUNT=$(find "$CW_MARK_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d ' ')
fi

# Exit early if no sessions found
if [ "$CC_COUNT" -eq 0 ] && [ "$CW_COUNT" -eq 0 ]; then
  fmt "$WARN_NO_SESSIONS" DAYS "$DAYS"
  rm -rf "$TMPDIR_PATH"
  exit 0
fi

# Generate stats report
STATS_DATE=$(date +%Y-%m-%d_%H-%M)
STATS_EXT=$( [ "$OUTPUT_FORMAT" = "html" ] && echo "html" || echo "md" )

# Claude Code stats
CC_STATS_FILE="$TMPDIR_PATH/${STATS_DATE}_${STATS_REPORT_SLUG}.${STATS_EXT}"
python3 "$STATS_SCRIPT" \
  --projects "$HOME/.claude/projects" \
  --days "$DAYS" \
  --format "$OUTPUT_FORMAT" \
  --out "$CC_STATS_FILE" \
  --conv-base "$TMPDIR_PATH/claude-code" >/dev/null 2>&1

# Claude Cowork stats (only when there are Cowork sessions)
if [ "$INCLUDE_COWORK" = "true" ] && [ "$CW_COUNT" -gt 0 ]; then
  CW_STATS_FILE="$TMPDIR_PATH/${STATS_DATE}_${STATS_REPORT_SLUG_COWORK}.${STATS_EXT}"
  CW_STATS_CMD=(python3 "$STATS_SCRIPT"
    --days "$DAYS"
    --format "$OUTPUT_FORMAT"
    --out "$CW_STATS_FILE"
    --conv-base "$TMPDIR_PATH/claude-cowork"
    --source-label cowork
  )
  for COWORK_BASE in "${COWORK_PATHS[@]}"; do
    [ -d "$COWORK_BASE" ] && CW_STATS_CMD+=(--projects "$COWORK_BASE")
  done
  "${CW_STATS_CMD[@]}" >/dev/null 2>&1
fi

CC_SESSIONS=$(grep '^\*\*Sessions:\*\*' "$CC_STATS_FILE" 2>/dev/null | grep -o '[0-9]*' | head -1)
CC_SESSIONS="${CC_SESSIONS:-$CC_COUNT}"

# Package as zip
GIT_USER_NAME=$(git config --global user.name 2>/dev/null | tr ' ' '_')
GIT_USER_NAME="${GIT_USER_NAME:-$(whoami)}"
ZIPNAME="$TMPDIR/chat-logs-${GIT_USER_NAME}-${EXPORT_DATE}.zip"
rm -f "$ZIPNAME"
cd "$TMPDIR_PATH" && zip -r "$ZIPNAME" . -x "*.DS_Store" -x ".cc_done/*" -x ".cw_done/*" > /dev/null
ZIP_SIZE=$(du -sh "$ZIPNAME" | cut -f1)
ZIP_BYTES=$(stat -f%z "$ZIPNAME" 2>/dev/null || stat -c%s "$ZIPNAME" 2>/dev/null)

# Send to Telegram
START_DATE=$(date -v-${DAYS}d +%Y-%m-%d 2>/dev/null || date -d "-${DAYS} days" +%Y-%m-%d 2>/dev/null)
TODAY=$(date +%Y-%m-%d)
GIT_USER_EMAIL=$(git config --global user.email 2>/dev/null)
GIT_USER_DISPLAY=$(echo "$GIT_USER_NAME" | tr '_' ' ')
if [ -n "$GIT_USER_EMAIL" ]; then
  GIT_USER="${GIT_USER_DISPLAY} <${GIT_USER_EMAIL}>"
else
  GIT_USER="$GIT_USER_DISPLAY"
fi
_s1=$(fmt "$SUMMARY_USER" GIT_USER "$GIT_USER")
_s2=$(fmt "$SUMMARY_PERIOD" START_DATE "$START_DATE" TODAY "$TODAY" DAYS "$DAYS")
if [ "$INCLUDE_COWORK" = "true" ] && [ "$CW_COUNT" -gt 0 ]; then
  _s3=$(fmt "$SUMMARY_STATS_COWORK" CC_SESSIONS "$CC_SESSIONS" CW_SESSIONS "$CW_COUNT")
else
  _s3=$(fmt "$SUMMARY_STATS" CC_SESSIONS "$CC_SESSIONS")
fi
_s4=$(fmt "$SUMMARY_SIZE" ZIP_SIZE "$ZIP_SIZE")
if [ "$OUTPUT_FORMAT" = "html" ]; then
  _s5="$SUMMARY_FORMAT_HTML"
else
  _s5="$SUMMARY_FORMAT_MD"
fi
SUMMARY_TEXT="$SUMMARY_HEADER
$_s1
$_s2
$_s3
$_s4
$_s5"

SUMMARY_TEXT="${SUMMARY_TEXT:0:4000}"

# Send text summary first
curl -s -o /dev/null -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d chat_id="$CHAT_ID" \
  --data-urlencode text="$SUMMARY_TEXT"

# Then send the file
if [ "$ZIP_BYTES" -le 52428800 ]; then
  curl -s -o /dev/null -X POST \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
    -F chat_id="$CHAT_ID" \
    -F document=@"$ZIPNAME"
else
  split -b 45m "$ZIPNAME" "${ZIPNAME}.part"
  PART_NUM=1
  PART_TOTAL=$(ls "${ZIPNAME}.part"* | wc -l | tr -d ' ')
  for part in "${ZIPNAME}.part"*; do
    curl -s -o /dev/null -X POST \
      "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendDocument" \
      -F chat_id="$CHAT_ID" \
      -F document=@"$part" \
      -F caption="[${PART_NUM}/${PART_TOTAL}] $(basename "$part")"
    PART_NUM=$((PART_NUM + 1))
  done
  rm -f "${ZIPNAME}.part"*
fi

# Clean up temp directory
rm -rf "$TMPDIR_PATH"
if [ "$INCLUDE_COWORK" = "true" ] && [ "$CW_COUNT" -gt 0 ]; then
  fmt "$MSG_DONE_COWORK" CC_SESSIONS "$CC_SESSIONS" CW_SESSIONS "$CW_COUNT" ZIP_SIZE "$ZIP_SIZE"
else
  fmt "$MSG_DONE" CC_SESSIONS "$CC_SESSIONS" ZIP_SIZE "$ZIP_SIZE"
fi
