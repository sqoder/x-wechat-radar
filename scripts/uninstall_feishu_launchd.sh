#!/usr/bin/env bash
set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.xwechatradar.feishu.bot.plist"

launchctl bootout "gui/$UID/com.xwechatradar.feishu.bot" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$PLIST" >/dev/null 2>&1 || true
rm -f "$PLIST"

echo "Uninstalled: com.xwechatradar.feishu.bot"

