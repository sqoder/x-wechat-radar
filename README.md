# X AI Radar

目标：只监控 AI 圈 X 账号，做到两件事：

- 有新帖就尽快推送到企业微信/飞书（1 分钟轮询）
- 每天早上 08:00 固定推一条汇总

并且支持本地免费翻译（Ollama，不走云 API 计费）。

## 项目来源

这个项目是开源组件组合方案：

- `TrendRadar`：抓取、去重、调度、推送
- `RSSHub`：提供 X 用户 RSS（`twitter/user/:username`）
- `Docker Compose`：一键编排运行
- `overrides/trendradar/*`：本仓库对推送与媒体处理的定制

数据流：`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 当前默认策略

- 监控范围：AI-only（42 个账号）
- 推送节奏：`CRON_SCHEDULE=*/1 * * * *`
- 汇总时间：每天 `08:00`
- 翻译：默认开启（走本地 Ollama OpenAI 接口）

## 小白快速上手

### 1) 初始化

```bash
cp .env.example .env
```

`.env` 至少填写：

- `TWITTER_AUTH_TOKEN`
- `WEWORK_WEBHOOK_URL` 或 `FEISHU_WEBHOOK_URL`

### 2) 获取 X 的 `auth_token`

1. 登录 `x.com`
2. 开发者工具 -> Application -> Cookies -> `https://x.com`
3. 找到 `auth_token`，复制值写入 `.env`

![X auth_token Cookie screenshot](./5ba9aeb751faa9bd7f973ce330d1c77d.png)

```env
TWITTER_AUTH_TOKEN=your_auth_token
```

### 3) 配置企业微信 webhook

1. 企业微信群 -> 聊天信息
2. 点击 `消息推送`
3. 配置机器人并复制 webhook
4. 写入 `.env`

![WeCom webhook setup screenshot](./ScreenShot_2026-03-07_044844_909.png)

```env
WEWORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

### 4) 启动

```bash
./scripts/doctor.sh
./scripts/up.sh
```

查看日志：

```bash
docker logs -f x-trendradar
```

## 本地免费翻译（Ollama）

### 1) 安装并启动 Ollama

macOS 可用：

```bash
brew install ollama
ollama serve
```

说明：`ollama serve` 需要常驻运行（可开新终端窗口）。

### 2) 准备翻译模型

你要用 HY 的话，关键是最终在 `ollama list` 里能看到一个模型名，比如：

- `hy-mt1.5-7b`

如果你先只想测试链路，可先拉一个轻量模型：

```bash
ollama pull qwen2.5:1.5b
```

查看本地模型：

```bash
ollama list
```

### 3) 对齐 `.env`（已在 `.env.example` 预置）

```env
AI_API_KEY=local_dummy_key
AI_API_BASE=http://host.docker.internal:11434/v1
AI_MODEL=openai/HY-MT1.5-7B
```

如果你在 Ollama 里实际模型名是 `hy-mt1.5-7b`，建议把 `AI_MODEL` 改为：

```env
AI_MODEL=openai/hy-mt1.5-7b
```

规则：`AI_MODEL=openai/<ollama中的模型名>`

### 4) 重启生效

```bash
docker compose up -d --force-recreate trendradar
```

## 你会收到的消息形态

- 新帖提醒：按增量推送（有新增就发）
- 早上 08:00：固定一条当前汇总
- 图片：可直接推图
- 视频：以链接/卡片推送（企业微信接口限制）

注：同一分钟内如果多位博主同时发帖，可能会在同一轮一起发出，但不会显示“第1批/第2批”标题。

## 常用命令

```bash
# 启动
./scripts/up.sh

# 停止
docker compose down

# 查看容器状态
docker compose ps

# 查看主服务日志
docker logs -f x-trendradar
```

## 目录

```text
.
├── config/
│   ├── config.yaml
│   ├── timeline.yaml
│   └── feed_groups.json
├── overrides/
├── scripts/
│   ├── doctor.sh
│   ├── up.sh
│   ├── up-groups.sh
│   └── build_group_configs.py
└── docker-compose.yml
```
