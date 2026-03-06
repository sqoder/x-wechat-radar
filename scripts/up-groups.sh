#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  printf '%s\n' "已创建 .env，请先填写 TWITTER_AUTH_TOKEN 和 webhook 后再运行。"
  exit 1
fi

"$SCRIPT_DIR/doctor.sh"
python3 "$SCRIPT_DIR/build_group_configs.py"

mkdir -p output/groups/ai output/groups/politics output/groups/invest

read_env_value() {
  key=$1
  line=$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 || true)
  if [ -z "$line" ]; then
    printf ''
    return 0
  fi
  printf '%s' "${line#*=}"
}

env_or_file() {
  key=$1
  value=$(printenv "$key" 2>/dev/null || true)
  if [ -n "$value" ]; then
    printf '%s' "$value"
    return 0
  fi
  read_env_value "$key"
}

WEWORK_WEBHOOK_URL_GLOBAL=$(env_or_file "WEWORK_WEBHOOK_URL")
FEISHU_WEBHOOK_URL_GLOBAL=$(env_or_file "FEISHU_WEBHOOK_URL")

WEWORK_WEBHOOK_URL_AI_VALUE=$(env_or_file "WEWORK_WEBHOOK_URL_AI")
WEWORK_WEBHOOK_URL_POLITICS_VALUE=$(env_or_file "WEWORK_WEBHOOK_URL_POLITICS")
WEWORK_WEBHOOK_URL_INVEST_VALUE=$(env_or_file "WEWORK_WEBHOOK_URL_INVEST")

FEISHU_WEBHOOK_URL_AI_VALUE=$(env_or_file "FEISHU_WEBHOOK_URL_AI")
FEISHU_WEBHOOK_URL_POLITICS_VALUE=$(env_or_file "FEISHU_WEBHOOK_URL_POLITICS")
FEISHU_WEBHOOK_URL_INVEST_VALUE=$(env_or_file "FEISHU_WEBHOOK_URL_INVEST")

# group webhook fallback:
# if group-specific webhook is empty, fallback to global webhook
if [ -z "${WEWORK_WEBHOOK_URL_AI_VALUE}" ]; then
  WEWORK_WEBHOOK_URL_AI_VALUE="${WEWORK_WEBHOOK_URL_GLOBAL}"
fi
if [ -z "${WEWORK_WEBHOOK_URL_POLITICS_VALUE}" ]; then
  WEWORK_WEBHOOK_URL_POLITICS_VALUE="${WEWORK_WEBHOOK_URL_GLOBAL}"
fi
if [ -z "${WEWORK_WEBHOOK_URL_INVEST_VALUE}" ]; then
  WEWORK_WEBHOOK_URL_INVEST_VALUE="${WEWORK_WEBHOOK_URL_GLOBAL}"
fi

if [ -z "${FEISHU_WEBHOOK_URL_AI_VALUE}" ]; then
  FEISHU_WEBHOOK_URL_AI_VALUE="${FEISHU_WEBHOOK_URL_GLOBAL}"
fi
if [ -z "${FEISHU_WEBHOOK_URL_POLITICS_VALUE}" ]; then
  FEISHU_WEBHOOK_URL_POLITICS_VALUE="${FEISHU_WEBHOOK_URL_GLOBAL}"
fi
if [ -z "${FEISHU_WEBHOOK_URL_INVEST_VALUE}" ]; then
  FEISHU_WEBHOOK_URL_INVEST_VALUE="${FEISHU_WEBHOOK_URL_GLOBAL}"
fi

export WEWORK_WEBHOOK_URL_AI="${WEWORK_WEBHOOK_URL_AI_VALUE}"
export WEWORK_WEBHOOK_URL_POLITICS="${WEWORK_WEBHOOK_URL_POLITICS_VALUE}"
export WEWORK_WEBHOOK_URL_INVEST="${WEWORK_WEBHOOK_URL_INVEST_VALUE}"
export FEISHU_WEBHOOK_URL_AI="${FEISHU_WEBHOOK_URL_AI_VALUE}"
export FEISHU_WEBHOOK_URL_POLITICS="${FEISHU_WEBHOOK_URL_POLITICS_VALUE}"
export FEISHU_WEBHOOK_URL_INVEST="${FEISHU_WEBHOOK_URL_INVEST_VALUE}"

missing=0
check_group_channel() {
  group_name=$1
  ww=$2
  fs=$3
  if [ -z "$ww" ] && [ -z "$fs" ]; then
    printf '%s\n' "FAIL: ${group_name} 组未配置 webhook（企业微信或飞书至少一个）"
    missing=1
  else
    printf '%s\n' "OK:   ${group_name} 组 webhook 已就绪"
  fi
}

check_group_channel "AI" "${WEWORK_WEBHOOK_URL_AI}" "${FEISHU_WEBHOOK_URL_AI}"
check_group_channel "Politics" "${WEWORK_WEBHOOK_URL_POLITICS}" "${FEISHU_WEBHOOK_URL_POLITICS}"
check_group_channel "Invest" "${WEWORK_WEBHOOK_URL_INVEST}" "${FEISHU_WEBHOOK_URL_INVEST}"

if [ "$missing" -ne 0 ]; then
  printf '\n%s\n' "请先在 .env 中填写分组 webhook，再运行 ./scripts/up-groups.sh"
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_PROFILES=grouped docker compose up -d rsshub trendradar-ai trendradar-politics trendradar-invest
  COMPOSE_PROFILES=grouped docker compose ps
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_PROFILES=grouped docker-compose up -d rsshub trendradar-ai trendradar-politics trendradar-invest
  COMPOSE_PROFILES=grouped docker-compose ps
else
  printf '%s\n' "未找到 docker compose / docker-compose。"
  exit 1
fi

printf '\n%s\n' "分组推送已启动。日志："
printf '%s\n' "  docker logs -f x-trendradar-ai"
printf '%s\n' "  docker logs -f x-trendradar-politics"
printf '%s\n' "  docker logs -f x-trendradar-invest"
