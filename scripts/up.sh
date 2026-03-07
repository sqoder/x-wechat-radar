#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

read_env_value() {
  key=$1
  line=$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 || true)
  if [ -z "$line" ]; then
    printf ''
    return 0
  fi

  printf '%s' "${line#*=}"
}

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' "已创建 .env，请先填入 TWITTER_AUTH_TOKEN，以及推送方式（企业微信 webhook、飞书 webhook，或飞书应用机器人 FEISHU_APP_ID/FEISHU_APP_SECRET）后再重新运行。"
  exit 1
fi

mkdir -p output
"$SCRIPT_DIR/doctor.sh"

compose_profiles=""
feishu_app_id=$(read_env_value "FEISHU_APP_ID")
feishu_app_secret=$(read_env_value "FEISHU_APP_SECRET")
if [ -n "$feishu_app_id" ] && [ -n "$feishu_app_secret" ]; then
  compose_profiles="feishu-bot"
fi

if docker compose version >/dev/null 2>&1; then
  if [ -n "$compose_profiles" ]; then
    COMPOSE_PROFILES="$compose_profiles" docker compose up -d
    COMPOSE_PROFILES="$compose_profiles" docker compose ps
  else
    docker compose up -d
    docker compose ps
  fi
elif command -v docker-compose >/dev/null 2>&1; then
  if [ -n "$compose_profiles" ]; then
    COMPOSE_PROFILES="$compose_profiles" docker-compose up -d
    COMPOSE_PROFILES="$compose_profiles" docker-compose ps
  else
    docker-compose up -d
    docker-compose ps
  fi
else
  printf '%s\n' "未找到 docker compose / docker-compose。"
  exit 1
fi

printf '\n%s\n' "已启动。查看日志：docker logs -f x-trendradar"
if [ -n "$compose_profiles" ]; then
  printf '%s\n' "已自动启动飞书应用机器人：docker logs -f x-feishu-command-bot"
  printf '%s\n' "首次私聊机器人一次后，才会建立主动推送收件人。"
fi
