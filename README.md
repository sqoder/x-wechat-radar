# X AI Radar

把你关注的 AI 圈 X 账号动态，自动推送到企业微信或飞书。默认只监控 AI 账号，默认关闭翻译，开箱即可先跑通。

## 项目来源（基于什么开源）

这个仓库不是从零重造，核心是把现成开源方案组合并做了定制：

- 抓取与推送主程序：TrendRadar（镜像：`wantcat/trendradar`）
- X 数据入口：RSSHub 的 `twitter/user/:username` 路由（镜像：`diygod/rsshub`）
- 本仓库定制层：`overrides/trendradar/*`（媒体渲染、发送行为优化）
- 编排方式：Docker Compose（一个命令启动整套链路）

数据流：`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 现在这套能做什么

- 监控范围：AI 圈账号（`config/config.yaml` 当前 42 个）
- 推送内容：文字、图片、视频链接（企业微信机器人不支持消息内直接播放视频）
- 推送策略：
  - 有新帖就推送（增量）
  - 每天 08:00 固定提醒一条（当前汇总）
- 翻译能力：支持中文翻译，默认关闭；需要时再开启

## 小白上手（10 分钟）

### 1) 准备环境

- 电脑已安装并启动 Docker Desktop
- 能访问 GitHub、x.com、企业微信或飞书

### 2) 初始化配置

```bash
cp .env.example .env
```

`.env` 至少填这两项：

- `TWITTER_AUTH_TOKEN`
- `WEWORK_WEBHOOK_URL` 或 `FEISHU_WEBHOOK_URL`（二选一或都填）

### 3) 获取 X 的 `auth_token`

1. 登录 `x.com`
2. 打开开发者工具 -> Application -> Cookies -> `https://x.com`
3. 找到 `auth_token` 并复制值
4. 写入 `.env`

![X auth_token Cookie screenshot](./5ba9aeb751faa9bd7f973ce330d1c77d.png)

```env
TWITTER_AUTH_TOKEN=your_auth_token
```

### 4) 配置企业微信机器人 webhook

1. 企业微信群 -> 聊天信息
2. 点击 `消息推送`
3. 配置机器人并复制 webhook
4. 写入 `.env`

![WeCom webhook setup screenshot](./ScreenShot_2026-03-07_044844_909.png)

```env
WEWORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

### 5) 一键检查 + 启动

```bash
./scripts/doctor.sh
./scripts/up.sh
```

### 6) 看运行日志

```bash
docker logs -f x-trendradar
```

如果你看到 `开始抓取 42 个 RSS 源`，说明主流程已经跑起来了。

## 推送时效与延迟说明

- 默认轮询频率：每 5 分钟一次（`CRON_SCHEDULE=*/5 * * * *`）
- 默认启动即执行：容器启动后会先立即跑一次（`IMMEDIATE_RUN=true`）
- 08:00 固定提醒：由 `config/timeline.yaml` 的时间线控制
- 常见延迟来源：
  - X 或 RSSHub 限流/超时
  - 网络波动
  - 企业微信/飞书通道限速

## 如何开启翻译（默认关闭）

1. 在 `.env` 填写 `AI_API_KEY`
2. 把 `config/config.yaml` 中 `ai_translation.enabled` 改为 `true`
3. 重启容器：

```bash
docker compose up -d --force-recreate trendradar
```

## 目录说明

```text
.
├── config/
│   ├── config.yaml          # 主配置（账号列表、翻译开关等）
│   ├── timeline.yaml        # 时间线（08:00 固定提醒）
│   └── feed_groups.json     # 分组配置（当前仅 ai）
├── overrides/               # 对 TrendRadar 的功能覆盖
├── scripts/
│   ├── doctor.sh            # 启动前体检
│   ├── up.sh                # 单实例启动
│   ├── build_group_configs.py
│   └── up-groups.sh
└── docker-compose.yml
```

## 常用命令

```bash
# 启动
./scripts/up.sh

# 停止
docker compose down

# 看容器状态
docker compose ps

# 只看主服务日志
docker logs -f x-trendradar
```
