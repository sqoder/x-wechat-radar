#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT_DIR/launchd/com.xwechatradar.feishu.bot.plist.template"
PLIST="$HOME/Library/LaunchAgents/com.xwechatradar.feishu.bot.plist"

mkdir -p "$ROOT_DIR/logs" "$HOME/Library/LaunchAgents"

sed -e "s|__ROOT_DIR__|$ROOT_DIR|g" "$TEMPLATE" > "$PLIST"

launchctl bootout "gui/$UID/com.xwechatradar.feishu.bot" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true

launchctl bootstrap "gui/$UID" "$PLIST"
launchctl enable "gui/$UID/com.xwechatradar.feishu.bot"
launchctl kickstart -k "gui/$UID/com.xwechatradar.feishu.bot"

echo "Installed: $PLIST"
echo "Check: launchctl print gui/$UID/com.xwechatradar.feishu.bot"

