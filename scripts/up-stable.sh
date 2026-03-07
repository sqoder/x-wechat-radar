#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' "已创建 .env，请先填好必要配置后重试。"
  exit 1
fi

mkdir -p output/shards/shard1 output/shards/shard2 output/shards/shard3 logs
"$SCRIPT_DIR/doctor.sh"
python3 "$SCRIPT_DIR/build_shard_configs.py" --shards 3

if docker compose version >/dev/null 2>&1; then
  docker compose stop trendradar >/dev/null 2>&1 || true
  COMPOSE_PROFILES=sharded docker compose up -d rsshub trendradar-shard1 trendradar-shard2 trendradar-shard3
  COMPOSE_PROFILES=sharded docker compose ps
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose stop trendradar >/dev/null 2>&1 || true
  COMPOSE_PROFILES=sharded docker-compose up -d rsshub trendradar-shard1 trendradar-shard2 trendradar-shard3
  COMPOSE_PROFILES=sharded docker-compose ps
else
  printf '%s\n' "未找到 docker compose / docker-compose。"
  exit 1
fi

printf '\n%s\n' "稳定模式已启动（3分片错峰抓取）。日志示例：docker logs -f x-trendradar-shard1"

