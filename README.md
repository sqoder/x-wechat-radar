# X AI Radar

你关注的 AI 圈 X 账号，只要有新帖就推送到微信/飞书；每天早上 08:00 再给一条汇总。

当前默认策略：

- 监控范围：仅 AI 方向账号（42 个）
- 实时提醒：每 1 分钟轮询一次，有新增就推
- 固定汇总：每天 08:00 推送当前汇总
- 翻译功能：默认关闭（需要时可开启）

## 项目是怎么来的

这个项目是基于开源组件组合出来的，不是从零重写：

- `TrendRadar`：负责抓取结果整理、去重、调度和推送
- `RSSHub`：提供 X 用户时间线 RSS 路由（`twitter/user/:username`）
- `Docker Compose`：把整套服务一键启动
- `overrides/trendradar/*`：本仓库的定制逻辑（媒体处理、推送优化）

数据流：`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 小白 10 分钟上手

### 1. 准备环境

- 安装并启动 Docker Desktop
- 能正常访问 `x.com`
- 已有企业微信机器人 webhook 或飞书机器人 webhook

### 2. 初始化配置

```bash
cp .env.example .env
```

### 3. 必填 `.env`

至少填写：

- `TWITTER_AUTH_TOKEN`
- `WEWORK_WEBHOOK_URL` 或 `FEISHU_WEBHOOK_URL`

翻译暂时不用填（默认关闭）：

- `AI_API_KEY`（可留空）

### 4. 获取 `TWITTER_AUTH_TOKEN`

1. 登录 `x.com`
2. 打开开发者工具 -> Application -> Cookies -> `https://x.com`
3. 复制 `auth_token` 的值
4. 写入 `.env`

![X auth_token Cookie screenshot](./5ba9aeb751faa9bd7f973ce330d1c77d.png)

```env
TWITTER_AUTH_TOKEN=your_auth_token
```

### 5. 配置企业微信 webhook

1. 进入目标群 -> 聊天信息
2. 点击 `消息推送`
3. 配置机器人并复制 webhook
4. 写入 `.env`

![WeCom webhook setup screenshot](./ScreenShot_2026-03-07_044844_909.png)

```env
WEWORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

### 6. 自检并启动

```bash
./scripts/doctor.sh
./scripts/up.sh
```

### 7. 看日志确认是否正常

```bash
docker logs -f x-trendradar
```

看到下面类似日志说明已正常运行：

- `生成的crontab内容: */1 * * * * ...`
- `[RSS] 开始抓取 42 个 RSS 源`

## 你现在会收到什么推送

- 某个 AI 账号发新帖：尽快推送（按 1 分钟轮询）
- 每天 08:00：固定推一条当前汇总
- 图片：可直接推送图片消息
- 视频：以链接/卡片方式推送（平台接口限制）

说明：如果同一分钟内有多条新帖，可能会在一轮里一起发出，但不会显示“第1批/第2批”这种批次标题。

## 推送节奏与延迟说明

- 轮询频率：`CRON_SCHEDULE=*/1 * * * *`
- 启动即跑：`IMMEDIATE_RUN=true`
- 早 8 汇总：`config/timeline.yaml` 的 `custom.morning_digest`

可能影响时效的因素：

- X/RSSHub 接口超时或限流
- 本机网络波动
- 推送平台通道限速

## 开启翻译（可选）

1. `.env` 填入 `AI_API_KEY`
2. 把 `config/config.yaml` 中 `ai_translation.enabled` 改为 `true`
3. 重启：

```bash
docker compose up -d --force-recreate trendradar
```

## 常用命令

```bash
# 启动
./scripts/up.sh

# 停止
docker compose down

# 查看状态
docker compose ps

# 查看日志
docker logs -f x-trendradar
```

## 目录说明

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
