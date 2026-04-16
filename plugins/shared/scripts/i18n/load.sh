#!/usr/bin/env bash
# load.sh - Load shell locale strings based on PLUGIN_LANG in .env
# Usage: source "$(dirname "$0")/i18n/load.sh"

_I18N_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
_PLUGIN_NAME="${_I18N_DIR%/*/*}"
_PLUGIN_NAME="${_PLUGIN_NAME##*/}"
_DATA_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/devtools-plugins/$_PLUGIN_NAME"

_PLUGIN_LANG="en"
if [ -f "$_DATA_DIR/.env" ]; then
  _LANG_VAL=$(grep '^PLUGIN_LANG=' "$_DATA_DIR/.env" | cut -d'=' -f2 | tr -d '"' | tr -d "'" | tr -d ' ')
  [ -n "$_LANG_VAL" ] && _PLUGIN_LANG="$_LANG_VAL"
fi

# Map zh-TW to zh_TW for filename
_LANG_FILE="${_PLUGIN_LANG//-/_}"

if [ -f "$_I18N_DIR/${_LANG_FILE}.sh" ]; then
  source "$_I18N_DIR/${_LANG_FILE}.sh"
else
  source "$_I18N_DIR/en.sh"
fi

# Helper: read a single value from ENV_FILE (must be set by the calling script)
# Usage: read_env_val KEY
read_env_val() { grep "^$1=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'" | tr -d ' '; }

# Helper: resolve optional argument — use arg if non-empty, else read from ENV_FILE, else use default
# Usage: resolve_arg ARG KEY DEFAULT
# ENV_FILE must be set by the calling script.
resolve_arg() {
  if [ -n "$1" ]; then echo "$1"
  elif [ -f "$ENV_FILE" ]; then local _v; _v=$(read_env_val "$2"); echo "${_v:-$3}"
  else echo "$3"; fi
}

# Helper: replace "skip" and "-" with "" in positional args (bash 3.2+)
# Usage: normalize_skip_args "$@"; set -- "${_NORMALIZED_ARGS[@]}"
normalize_skip_args() {
  _NORMALIZED_ARGS=()
  for _a in "$@"; do
    case "$_a" in skip|-) _NORMALIZED_ARGS+=("") ;; *) _NORMALIZED_ARGS+=("$_a") ;; esac
  done
}

# Helper: interpolate %KEY% placeholders in a message string
# Usage: fmt "$MSG_TEMPLATE" KEY1 val1 KEY2 val2 ...
# Note: cannot use ${var//%KEY%/val} — bash treats leading % as end-anchor.
fmt() {
  local _t="$1" _k _v _prefix _suffix; shift
  while [ $# -ge 2 ]; do
    _k="$1" _v="$2"; shift 2
    while true; do
      case "$_t" in
        *"%${_k}%"*)
          _prefix="${_t%%"%${_k}%"*}"
          _suffix="${_t#*"%${_k}%"}"
          _t="${_prefix}${_v}${_suffix}"
          ;;
        *) break ;;
      esac
    done
  done
  printf '%s\n' "$_t"
}
