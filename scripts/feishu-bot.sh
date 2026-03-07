#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

# Some networks inject custom cert chains; force a stable CA bundle when available.
if [ -z "${SSL_CERT_FILE:-}" ]; then
  CERTIFI_PATH=$(python3 -c "import certifi; print(certifi.where())" 2>/dev/null || true)
  if [ -n "$CERTIFI_PATH" ]; then
    export SSL_CERT_FILE="$CERTIFI_PATH"
  fi
fi

python3 "$SCRIPT_DIR/feishu_command_bot.py" "$@"
