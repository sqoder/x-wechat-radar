#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$ROOT_DIR"

status=0

say() {
  printf '%s\n' "$1"
}

fail() {
  say "FAIL: $1"
  status=1
}

pass() {
  say "OK:   $1"
}

warn() {
  say "WARN: $1"
}

read_env_value() {
  key=$1
  line=$(grep -E "^${key}=" .env 2>/dev/null | tail -n 1 || true)
  if [ -z "$line" ]; then
    printf ''
    return 0
  fi

  printf '%s' "${line#*=}"
}

env_is_true() {
  value=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    1|true|yes|y|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

cron_is_aggressive() {
  value=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')
  case "$value" in
    "* * * * *"|"*/1 * * * *"|"*/2 * * * *"|"*/3 * * * *"|\
    "0-59/1 * * * *"|"1-59/1 * * * *"|"2-59/1 * * * *"|\
    "0-59/2 * * * *"|"1-59/2 * * * *"|"2-59/2 * * * *"|\
    "0-59/3 * * * *"|"1-59/3 * * * *"|"2-59/3 * * * *")
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

config_section_enabled() {
  section=$1
  awk -v target="${section}" '
    $0 ~ ("^" target ":") { in_section=1; next }
    in_section && /^[^[:space:]]/ { exit(found ? 0 : 1) }
    in_section && /^  enabled: true/ { found=1 }
    END { exit(found ? 0 : 1) }
  ' config/config.yaml
}

translation_enabled=0
analysis_enabled=0
if config_section_enabled "ai_translation"; then
  translation_enabled=1
fi
if config_section_enabled "ai_analysis"; then
  analysis_enabled=1
fi

if [ ! -f .env ]; then
  fail ".env 不存在。先运行: cp .env.example .env"
else
  pass ".env 已存在"

  twitter_token=$(read_env_value "TWITTER_AUTH_TOKEN")
  if [ -n "$twitter_token" ]; then
    pass "TWITTER_AUTH_TOKEN 已填写"
  else
    fail "TWITTER_AUTH_TOKEN 为空"
  fi

  feishu_webhook=$(read_env_value "FEISHU_WEBHOOK_URL")
  wework_webhook=$(read_env_value "WEWORK_WEBHOOK_URL")
  if [ -n "$feishu_webhook" ]; then
    pass "FEISHU_WEBHOOK_URL 已填写"
  else
    pass "FEISHU_WEBHOOK_URL 未填写"
  fi
  if [ -n "$wework_webhook" ]; then
    pass "WEWORK_WEBHOOK_URL 已填写"
  else
    pass "WEWORK_WEBHOOK_URL 未填写"
  fi

  feishu_app_id=$(read_env_value "FEISHU_APP_ID")
  feishu_app_secret=$(read_env_value "FEISHU_APP_SECRET")
  feishu_app_enabled=0
  if [ -n "$feishu_app_id" ] || [ -n "$feishu_app_secret" ]; then
    if [ -n "$feishu_app_id" ] && [ -n "$feishu_app_secret" ]; then
      feishu_app_enabled=1
      pass "FEISHU_APP_ID / FEISHU_APP_SECRET 已填写（飞书应用机器人可用）"
    else
      fail "FEISHU_APP_ID 和 FEISHU_APP_SECRET 需要成对填写"
    fi
  else
    pass "FEISHU_APP_ID / FEISHU_APP_SECRET 未填写"
  fi

  if [ -z "$feishu_webhook" ] && [ -z "$wework_webhook" ] && [ "$feishu_app_enabled" -ne 1 ]; then
    fail "未配置推送通道：至少填写 FEISHU_WEBHOOK_URL、WEWORK_WEBHOOK_URL，或 FEISHU_APP_ID/FEISHU_APP_SECRET"
  fi

  if [ "$feishu_app_enabled" -eq 1 ]; then
    recipients_file=$(read_env_value "FEISHU_APP_RECIPIENTS_FILE")
    if [ -z "$recipients_file" ]; then
      recipients_file="output/feishu_app_recipients.json"
    fi
    if [ -f "$recipients_file" ]; then
      pass "飞书应用机器人收件人文件已存在：${recipients_file}"
    else
      warn "飞书应用机器人首次使用前，需要先私聊机器人一次以建立主动推送收件人（${recipients_file}）"
    fi
  fi

  if [ "$translation_enabled" -eq 1 ] || [ "$analysis_enabled" -eq 1 ]; then
    value=$(read_env_value "AI_API_KEY")
    if [ -n "$value" ]; then
      pass "AI_API_KEY 已填写（AI 功能已启用）"
    else
      fail "AI_API_KEY 为空（当前已启用 ai_translation 或 ai_analysis）"
    fi
  else
    pass "AI_API_KEY 非必填（当前 AI 功能均关闭）"
  fi

  media_summary_enabled=$(read_env_value "AI_MEDIA_SUMMARY_ENABLED")
  if env_is_true "$media_summary_enabled"; then
    media_summary_key=$(read_env_value "AI_MEDIA_SUMMARY_API_KEY")
    if [ -n "$media_summary_key" ]; then
      pass "AI_MEDIA_SUMMARY_API_KEY 已填写（云端媒体总结已启用）"
    else
      fail "AI_MEDIA_SUMMARY_ENABLED=true 但 AI_MEDIA_SUMMARY_API_KEY 为空"
    fi
  else
    pass "云端媒体总结未启用（AI_MEDIA_SUMMARY_ENABLED=false）"
  fi

  cron_value=$(read_env_value CRON_SCHEDULE)
  if [ -n "$cron_value" ]; then
    pass "CRON_SCHEDULE=${cron_value}"
  else
    pass "CRON_SCHEDULE 未显式设置，将使用 5 分钟默认值"
  fi
fi

feed_count=$(grep -Ec 'url: "http://rsshub:1200/twitter/user/' config/config.yaml || true)
if [ "${feed_count}" -gt 0 ]; then
  pass "已配置 ${feed_count} 个 X 账号 RSS feed"
else
  fail "config/config.yaml 里没有配置 X 账号 feed"
fi

if [ "${feed_count}" -gt 30 ]; then
  cron_value=$(read_env_value CRON_SCHEDULE)
  if [ -n "$cron_value" ] && cron_is_aggressive "$cron_value"; then
    warn "当前 feed 数较多且 CRON_SCHEDULE=${cron_value}，容易超时。建议使用 */5，并通过 ./scripts/up-stable.sh 分片抓取。"
  fi

  shard1=$(read_env_value SHARD_CRON_SCHEDULE_1)
  shard2=$(read_env_value SHARD_CRON_SCHEDULE_2)
  shard3=$(read_env_value SHARD_CRON_SCHEDULE_3)

  if [ -n "$shard1" ] && cron_is_aggressive "$shard1"; then
    warn "SHARD_CRON_SCHEDULE_1=${shard1} 偏快，建议使用 0-59/5 * * * *"
  fi
  if [ -n "$shard2" ] && cron_is_aggressive "$shard2"; then
    warn "SHARD_CRON_SCHEDULE_2=${shard2} 偏快，建议使用 1-59/5 * * * *"
  fi
  if [ -n "$shard3" ] && cron_is_aggressive "$shard3"; then
    warn "SHARD_CRON_SCHEDULE_3=${shard3} 偏快，建议使用 2-59/5 * * * *"
  fi
fi

if [ "$translation_enabled" -eq 1 ]; then
  pass "ai_translation 已启用"
else
  pass "ai_translation 已关闭（测试模式）"
fi

if command -v docker >/dev/null 2>&1; then
  pass "docker 命令可用"

  compose_source=""
  if docker compose version >/dev/null 2>&1; then
    compose_source="docker compose"
  elif command -v docker-compose >/dev/null 2>&1; then
    compose_source="docker-compose"
  fi

  if [ -n "$compose_source" ]; then
    pass "Compose 命令可用 (${compose_source})"
  else
    fail "未找到 docker compose / docker-compose"
  fi

  if docker info >/dev/null 2>&1; then
    pass "Docker daemon 已启动"
  else
    fail "Docker daemon 未启动"
  fi

  if [ -n "$compose_source" ]; then
    if [ "$compose_source" = "docker compose" ]; then
      if docker compose config >/dev/null 2>&1; then
        pass "docker-compose.yml 语法有效"
      else
        fail "docker compose 配置解析失败"
      fi
    else
      if docker-compose config >/dev/null 2>&1; then
        pass "docker-compose.yml 语法有效"
      else
        fail "docker-compose 配置解析失败"
      fi
    fi
  fi
else
  fail "当前机器未安装 docker"
fi

if [ "$status" -ne 0 ]; then
  say ""
  say "修复上述 FAIL 后，再运行 ./scripts/up.sh"
  exit "$status"
fi

say ""
say "环境检查通过，可以启动。"
