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
  printf '%s\n' "已创建 .env，请先填好必要配置后重试。"
  exit 1
fi

mkdir -p output/shards/shard1 output/shards/shard2 output/shards/shard3 logs
"$SCRIPT_DIR/doctor.sh"
python3 "$SCRIPT_DIR/build_shard_configs.py" --shards 3

compose_profiles="sharded"
set -- rsshub trendradar-shard1 trendradar-shard2 trendradar-shard3
feishu_app_id=$(read_env_value "FEISHU_APP_ID")
feishu_app_secret=$(read_env_value "FEISHU_APP_SECRET")
if [ -n "$feishu_app_id" ] && [ -n "$feishu_app_secret" ]; then
  compose_profiles="sharded,feishu-bot"
  set -- "$@" feishu-command-bot
fi

if docker compose version >/dev/null 2>&1; then
  docker compose stop trendradar >/dev/null 2>&1 || true
  COMPOSE_PROFILES="$compose_profiles" docker compose up -d "$@"
  COMPOSE_PROFILES="$compose_profiles" docker compose ps
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose stop trendradar >/dev/null 2>&1 || true
  COMPOSE_PROFILES="$compose_profiles" docker-compose up -d "$@"
  COMPOSE_PROFILES="$compose_profiles" docker-compose ps
else
  printf '%s\n' "未找到 docker compose / docker-compose。"
  exit 1
fi

printf '\n%s\n' "稳定模式已启动（3分片错峰抓取）。日志示例：docker logs -f x-trendradar-shard1"
if [ "$compose_profiles" = "sharded,feishu-bot" ]; then
  printf '%s\n' "已自动启动飞书应用机器人：docker logs -f x-feishu-command-bot"
  printf '%s\n' "首次私聊机器人一次后，才会建立主动推送收件人。"
fi
