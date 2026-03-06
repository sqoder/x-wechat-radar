# X WeChat Radar

把你关注的 X 账号动态（文字/图片/视频链接）自动推送到企业微信或飞书。

> 核心目标：不打开 X，也能在消息工具里第一时间看更新。

## 1. 功能概览

- 支持 144+ X 账号监控（通过 RSSHub `twitter/user/<username>`）
- 支持企业微信、飞书推送
- 支持媒体增强：
  - 图片：企业微信直接推图片消息
  - 视频：企业微信推送视频卡片/链接（机器人 API 不支持消息内直接播放）
- 支持调度：
  - 全天增量推送（有人发新帖就提醒）
  - 每天 08:00 固定提醒（当前汇总）
- 支持分组优先推送（AI / Politics / Invest 三路）

## 2. 架构

```text
X (Twitter)
   ↓
RSSHub (twitter/user/:username)
   ↓
TrendRadar (抓取 + 去重 + 调度)
   ↓
企业微信 / 飞书
```

## 3. 目录说明

```text
.
├── config/
│   ├── config.yaml              # 主配置（全量监控）
│   ├── timeline.yaml            # 时间线（8点固定提醒 + 全天增量）
│   └── feed_groups.json         # 分组路由定义（AI/Politics/Invest）
├── overrides/                   # 对上游 TrendRadar 的覆盖（媒体解析与发送增强）
├── scripts/
│   ├── doctor.sh                # 基础自检
│   ├── up.sh                    # 单路启动
│   ├── build_group_configs.py   # 生成分组配置
│   └── up-groups.sh             # 分组三路启动
├── docker-compose.yml
└── .env.example
```

## 4. 快速开始（单路模式）

### 4.1 准备

```bash
cd /Users/wangxinglin/Desktop/x-wechat-radar
cp .env.example .env
```

必填 `.env`：

- `TWITTER_AUTH_TOKEN`：登录 x.com 后 cookie 里的 `auth_token`
- `WEWORK_WEBHOOK_URL` 或 `FEISHU_WEBHOOK_URL`

### 4.2 自检

```bash
./scripts/doctor.sh
```

### 4.3 启动

```bash
./scripts/up.sh
```

查看日志：

```bash
docker logs -f x-trendradar
```

## 5. 分组优先推送（AI / Politics / Invest）

这个模式会启动 3 个 TrendRadar 实例，分别监控不同账号组。

### 5.1 配置 webhook

你可以给每组单独 webhook：

- `WEWORK_WEBHOOK_URL_AI`
- `WEWORK_WEBHOOK_URL_POLITICS`
- `WEWORK_WEBHOOK_URL_INVEST`

或留空，`up-groups.sh` 会自动回退到全局 `WEWORK_WEBHOOK_URL`（飞书同理）。

### 5.2 启动

```bash
./scripts/up-groups.sh
```

日志：

```bash
docker logs -f x-trendradar-ai
docker logs -f x-trendradar-politics
docker logs -f x-trendradar-invest
```

### 5.3 修改分组

编辑 `config/feed_groups.json`，然后重跑：

```bash
python3 scripts/build_group_configs.py
./scripts/up-groups.sh
```

## 6. 时间策略（当前默认）

- 默认时段：`incremental`（全天新帖实时提醒）
- `08:00-08:04`：`current`（只发一次早间汇总）

配置文件：`config/timeline.yaml`

## 7. 常见问题

### Q1: 为什么视频不是直接在微信里播放？

企业微信机器人接口限制，不支持直接发送可播放视频消息。当前是视频卡片/链接方案。

### Q2: 电脑关机后还能推送吗？

不能。本地 Docker 停止后就不会抓取与推送。  
要 24h 稳定运行，建议部署到云服务器。

### Q3: 推送没到？

1. 检查 webhook 是否有效
2. 检查 `TWITTER_AUTH_TOKEN` 是否过期
3. 看容器日志是否报错

## 8. 安全建议

- 不要提交 `.env`、数据库、日志
- webhook/token 泄露后立即重置
- 截图分享时遮挡 key/token

## 9. 关键配置（对应你给的两张图）

### 9.1 获取 X 的 `auth_token`（第一张图）

1. 打开 `x.com` 并保持登录
2. 打开开发者工具 -> `应用`（Application）-> `Cookie` -> `https://x.com`
3. 找到 `auth_token`，复制它的值
4. 填入 `.env`：

```bash
TWITTER_AUTH_TOKEN=你的auth_token
```

### 9.2 获取企业微信机器人 webhook（第二张图）

1. 进入目标群聊 -> 右侧 `聊天信息`
2. 点 `消息推送`（你图里箭头所示）
3. 进入后配置机器人并复制 webhook URL
4. 填入 `.env`：

```bash
WEWORK_WEBHOOK_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

### 9.3 开启中文翻译（当前仓库已默认开启）

本仓库在 `config/config.yaml` 已设置：

- `ai_translation.enabled: true`
- `ai_translation.language: 中文`

你只需要在 `.env` 填 `AI_API_KEY`，然后重启容器：

```bash
docker-compose up -d --force-recreate
```

## 10. 常用命令

```bash
# 单路
./scripts/up.sh

# 分组三路
./scripts/up-groups.sh

# 停止全部
docker-compose down

# 查看容器
docker-compose ps
```
