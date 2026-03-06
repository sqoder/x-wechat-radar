#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' "已创建 .env，请先填入 TWITTER_AUTH_TOKEN 和 webhook（WEWORK_WEBHOOK_URL 或 FEISHU_WEBHOOK_URL）后再重新运行。"
  exit 1
fi

mkdir -p output
"$SCRIPT_DIR/doctor.sh"

if docker compose version >/dev/null 2>&1; then
  docker compose up -d
  docker compose ps
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d
  docker-compose ps
else
  printf '%s\n' "未找到 docker compose / docker-compose。"
  exit 1
fi

printf '\n%s\n' "已启动。查看日志：docker logs -f x-trendradar"
