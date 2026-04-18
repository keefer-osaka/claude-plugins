#!/usr/bin/env bash
# generate.sh - Generate Java from a .proto file and copy to matching subprojects
# Usage: bash generate.sh [file.proto]
#   No argument: list available .proto files
set -euo pipefail

DATA_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/devtools-plugins/protoc-java-gen"
ENV_FILE="$DATA_DIR/.env"

source "$(dirname "$0")/i18n/load.sh"

# --- Load config ---
if [ ! -f "$ENV_FILE" ]; then
  echo "$ERR_NOT_CONFIGURED"
  exit 1
fi

PROTOC_PATH=$(read_env_val PROTOC_PATH)
PROJECT_ROOT=$(read_env_val PROJECT_ROOT)
PROTO_DIR_REL=$(read_env_val PROTO_DIR)
PROTO_DIR_REL="${PROTO_DIR_REL:-proto}"
PROTO_DIR="$PROJECT_ROOT/$PROTO_DIR_REL"

# --- Validate ---
if [ ! -x "$PROTOC_PATH" ]; then
  fmt "$ERR_PROTOC_NOT_FOUND" PROTOC_PATH "$PROTOC_PATH"
  exit 1
fi

if [ ! -d "$PROTO_DIR" ]; then
  fmt "$ERR_PROTO_DIR_NOT_FOUND" PROTO_DIR "$PROTO_DIR"
  exit 1
fi

# --- No argument: list available protos ---
if [ $# -eq 0 ] || [ -z "${1:-}" ]; then
  echo "$MSG_AVAILABLE_PROTOS"
  find "$PROTO_DIR" -maxdepth 1 -name '*.proto' | sort | while read -r f; do
    echo "  $(basename "$f")"
  done
  exit 0
fi

PROTO_FILE="${1:-}"
# Auto-append .proto extension if missing
[[ "$PROTO_FILE" != *.proto ]] && PROTO_FILE="${PROTO_FILE}.proto"
PROTO_PATH="$PROTO_DIR/$PROTO_FILE"

if [ ! -f "$PROTO_PATH" ]; then
  PROTO_PATH="$PROTO_FILE"
  if [ ! -f "$PROTO_PATH" ]; then
    fmt "$ERR_PROTO_FILE_NOT_FOUND" PROTO_FILE "$PROTO_FILE"
    exit 1
  fi
fi

extract_proto_option() {
  local key=$1
  grep -v '^\s*//' "$PROTO_PATH" \
    | grep -oE "option[[:space:]]+${key}[[:space:]]*=[[:space:]]*\"[^\"]*\"" \
    | grep -o '"[^"]*"' | tr -d '"' | head -1 || true
}

# --- Extract java_outer_classname ---
JAVA_CLASS=$(extract_proto_option "java_outer_classname")
if [ -z "$JAVA_CLASS" ]; then
  fmt "$ERR_NO_CLASSNAME" PROTO_FILE "$(basename "$PROTO_PATH")"
  exit 1
fi
JAVA_FILE="${JAVA_CLASS}.java"

fmt "$MSG_GENERATING" PROTO_FILE "$(basename "$PROTO_PATH")" JAVA_FILE "$JAVA_FILE"

# --- Run protoc ---
WORK_DIR=$(mktemp -d)
trap 'rm -rf "$WORK_DIR"' EXIT

PROTOC_EXIT=0
(cd "$PROTO_DIR" && "$PROTOC_PATH" --java_out="$WORK_DIR" --proto_path=. "$(basename "$PROTO_PATH")") \
  || PROTOC_EXIT=$?
if [ $PROTOC_EXIT -ne 0 ]; then
  fmt "$ERR_PROTOC_FAILED" EXIT_CODE "$PROTOC_EXIT" >&2
  exit 1
fi

# Locate generated file: parse java_package / package from proto to derive subdir
JAVA_PKG=$(extract_proto_option "java_package")
if [ -z "$JAVA_PKG" ]; then
  JAVA_PKG=$(grep -v '^\s*//' "$PROTO_PATH" | grep -m1 '^package ' | awk '{print $2}' | tr -d ';' || true)
fi
PKG_PATH="${JAVA_PKG//.//}"
GENERATED="$WORK_DIR/$PKG_PATH/$JAVA_FILE"
if [ ! -f "$GENERATED" ]; then
  MATCH_COUNT=$(find "$WORK_DIR" -name "$JAVA_FILE" -print | wc -l | tr -d ' ')
  if [ "$MATCH_COUNT" -eq 1 ]; then
    GENERATED=$(find "$WORK_DIR" -name "$JAVA_FILE" -print -quit)
  elif [ "$MATCH_COUNT" -gt 1 ]; then
    fmt "$ERR_PROTO_MULTIPLE_MATCH" JAVA_FILE "$JAVA_FILE" >&2
    exit 1
  fi
fi

if [ -z "$GENERATED" ] || [ ! -f "$GENERATED" ]; then
  fmt "$ERR_PROTO_GENERATED_NOT_FOUND" JAVA_FILE "$JAVA_FILE"
  exit 1
fi

# --- Find targets in subprojects ---
TARGETS=()
while IFS= read -r line; do
  TARGETS+=("$line")
done < <(find "$PROJECT_ROOT" -path "*/src/main/java/$PKG_PATH/$JAVA_FILE" 2>/dev/null)

if [ ${#TARGETS[@]} -eq 0 ]; then
  fmt "$ERR_NO_TARGETS" JAVA_FILE "$JAVA_FILE"
  exit 1
fi

# --- Diff and overwrite ---
UPDATED=0
SUBPROJECTS=()
for TARGET in "${TARGETS[@]}"; do
  if diff -q "$GENERATED" "$TARGET" > /dev/null 2>&1; then
    fmt "$MSG_SKIPPED" TARGET "$TARGET"
  else
    cp "$GENERATED" "$TARGET"
    fmt "$MSG_UPDATED" TARGET "$TARGET"
    UPDATED=$((UPDATED + 1))
    SUBPROJECT="${TARGET%/src/main/java/*}"
    SUBPROJECTS+=("$SUBPROJECT")
  fi
done

TOTAL=${#TARGETS[@]}

if [ "$UPDATED" -eq 0 ]; then
  fmt "$MSG_NO_CHANGES" TOTAL "$TOTAL"
else
  UNIQUE_SUBPROJECTS=$(printf '%s\n' "${SUBPROJECTS[@]}" | sort -u | wc -l | tr -d ' ')
  fmt "$MSG_SUMMARY" UPDATED "$UPDATED" TOTAL "$TOTAL" SUBPROJECTS "$UNIQUE_SUBPROJECTS"
fi
