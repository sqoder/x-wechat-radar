# X AI Radar

把你关注的 X（Twitter）账号自动抓取下来，翻译/总结后推送到飞书或企业微信。

默认策略：
- 实时增量推送（有新帖就推）
- 每天 08:00 固定汇总

适合场景：
- 不想频繁刷 X，只看消息推送
- 重点关注 AI 圈账号动态
- 需要“私聊机器人查询某人最新帖”

## 项目能做什么

- 监控 42 个 AI 账号（默认配置）
- 定时抓取：RSSHub + TrendRadar（去重/调度/推送）
- 推送通道：飞书 webhook、企业微信 webhook
- 飞书机器人对话：私聊/群聊里发命令查询最新帖
- 文本增强：中文翻译、摘要、标签
- 媒体支持：图片/视频链接推送；可选 OCR/ASR（本地）或云端媒体总结

## 架构说明

主链路（自动推送）：
`X -> RSSHub -> TrendRadar -> Feishu/WeCom webhook`

对话链路（飞书机器人）：
`飞书消息 -> feishu_command_bot -> RSSHub/Nitter/SQLite回退 -> 飞书回复`

组件职责：
- `rsshub`：把 X 账号转成 RSS 源
- `trendradar`：拉取 RSS、去重、调度、渲染、推送
- `feishu-command-bot`：处理“查看xxx最新动态”这类聊天命令
- `overrides/trendradar/*`：项目自定义逻辑（翻译、渲染、推送增强）

详细版本见：
- [docs/ARCHITECTURE_CN.md](./docs/ARCHITECTURE_CN.md)

## 3 分钟上手（给克隆用户）

### 1) 环境要求

- Docker / Docker Compose
- Python 3.10+（用于脚本与测试）

### 2) 初始化配置

```bash
cd x-wechat-radar
cp .env.example .env
```

至少填写：
- `TWITTER_AUTH_TOKEN`
- `FEISHU_WEBHOOK_URL` 或 `WEWORK_WEBHOOK_URL`（至少一个）

如果要用飞书“私聊机器人对话”，还要填：
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

### 3) 启动前体检

```bash
./scripts/doctor.sh
```

### 4) 推荐启动方式（42 账号稳定模式）

```bash
./scripts/up-stable.sh
COMPOSE_PROFILES=feishu-bot docker compose up -d feishu-command-bot
```

查看日志：

```bash
docker logs -f x-trendradar-shard1
docker logs -f x-feishu-command-bot
```

## 关键配置（.env）

必填项：
- `TWITTER_AUTH_TOKEN`：X 登录 cookie 的 `auth_token`
- `AI_API_KEY`：当 `ai_translation.enabled=true` 时必填

推送相关：
- `FEISHU_WEBHOOK_URL`：飞书群机器人 webhook（自动推送）
- `WEWORK_WEBHOOK_URL`：企业微信群机器人 webhook（自动推送）
- `FEISHU_WEBHOOK_SECRET`：飞书 webhook 开启签名校验时填写

飞书对话机器人：
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_BOT_ENABLE_TRANSLATE=true|false`

调度相关（建议值）：
- `CRON_SCHEDULE=*/5 * * * *`
- `SHARD_CRON_SCHEDULE_1=0-59/5 * * * *`
- `SHARD_CRON_SCHEDULE_2=1-59/5 * * * *`
- `SHARD_CRON_SCHEDULE_3=2-59/5 * * * *`

## 两种使用方式

### A. 自动推送（不用聊天）

只依赖 webhook（飞书群或企微群）：

```bash
./scripts/up-stable.sh
```

系统会自动：
- 实时推送新增帖子
- 每天 08:00 推送一次当前汇总

### B. 飞书私聊机器人（可以直接问）

```bash
COMPOSE_PROFILES=feishu-bot docker compose up -d feishu-command-bot
```

私聊或群聊命令示例：
- `查看openai最新的动态`
- `我要看马斯克最新帖子`
- `查看 @realDonaldTrump 最新推特`

本地自测（不连飞书）：

```bash
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

## 按需查询脚本（命令行）

```bash
# 只查不推送
./scripts/x-latest.sh OpenAI --no-push

# 推送目标自动选择（优先飞书，其次企微）
./scripts/x-latest.sh OpenAI

# 强制推送到飞书
./scripts/x-latest.sh OpenAI --push-target feishu

# 同时推送到飞书和企业微信
./scripts/x-latest.sh OpenAI --push-target both
```

可选增强：

```bash
# 图片 OCR
./scripts/x-latest.sh OpenAI --with-ocr

# 视频 ASR
./scripts/x-latest.sh OpenAI --with-asr
```

## 推送内容说明

默认字段：
- 标题
- 摘要
- 标签
- 原帖链接
- 图片/视频链接（如有）

翻译开关：
- 在 `config/config.yaml` 中控制 `ai_translation.enabled`

## 项目结构

```text
x-wechat-radar/
├── config/                         # 主配置（账号、时间线、提示词）
├── overrides/trendradar/           # 对上游 TrendRadar 的定制补丁
├── scripts/                        # 启动/体检/分片/查询/机器人脚本
├── tests/                          # 单元测试
├── docker-compose.yml              # 服务编排
├── .env.example                    # 环境变量模板
├── output/                         # 运行产物（数据库/HTML报告）
└── logs/                           # 机器人日志
```

## 故障排查 Top 5

1. 飞书报 `Bot Not Enabled`  
说明你填的不是“群自定义机器人 webhook”，或机器人未启用。

2. 没收到“实时推送”  
先看日志是否有新增条目：`docker logs -f x-trendradar-shard1`。

3. RSSHub 超时/503  
使用 `./scripts/up-stable.sh` 分片模式，避免单实例过载。

4. 翻译失败回退原文  
检查 `.env` 的 `AI_API_KEY / AI_API_BASE / AI_MODEL` 是否可用。

5. 飞书私聊机器人不回消息  
检查 `FEISHU_APP_ID/FEISHU_APP_SECRET`，并看 `docker logs -f x-feishu-command-bot`。

## 测试与 CI

本地最小验证：

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
docker compose config -q
```

CI 文件：`/.github/workflows/ci.yml`  
已覆盖 shell/python 语法、YAML 校验、compose 校验、单测。

## 安全建议

- `.env` 不要提交到 GitHub（已在 `.gitignore` 忽略）
- 定期轮换 webhook/token
- 公开仓库只保留 `.env.example`

## 发布到 GitHub

完整步骤见：
- [docs/GITHUB_UPLOAD_CN.md](./docs/GITHUB_UPLOAD_CN.md)

## 下一步建议（可选）

- 增加“每日 08:05 健康报告”（抓取数/推送数/失败数）
- 给翻译结果加缓存（按 status_id 去重）
- 企业微信“私聊机器人回调模式”（复杂度高于 webhook）
