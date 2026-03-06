# X Radar: X(Twitter) -> 企业微信/飞书推送

把你关注的 X 账号动态自动推送到微信/飞书，减少手动刷 X 的时间。

数据链路：

`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 功能

- 支持多 X 账号订阅（RSSHub `twitter/user/<username>`）
- 支持企业微信与飞书推送
- 支持媒体补发：
  - 图片：企业微信会直接推图片消息
  - 视频：企业微信会推送视频卡片/链接（机器人接口不支持消息内直接播放视频）
- 调度支持：
  - 全天增量提醒（有新帖就推）
  - 每天早上 08:00 固定提醒一次（当前汇总）

## 目录结构

```text
.
├── config/                    # TrendRadar 主配置与时间线
├── overrides/                 # 对上游 TrendRadar 的本地覆盖
├── scripts/                   # 启动与自检脚本
├── docker-compose.yml         # 一键启动
├── .env.example               # 环境变量模板
└── README.md
```

## 快速开始

1. 准备环境变量

```bash
cd /Users/wangxinglin/Desktop/x-wechat-radar
cp .env.example .env
```

填写 `.env`：

- `TWITTER_AUTH_TOKEN`：登录 x.com 后 Cookie 里的 `auth_token`
- `WEWORK_WEBHOOK_URL`：企业微信机器人 webhook（或配置 `FEISHU_WEBHOOK_URL`）
- `AI_API_KEY`：可选，仅开启翻译/AI 分析时需要

2. 配置要追踪的账号

编辑 `config/config.yaml` 的 `rss.feeds`。

```yaml
- id: "x-openai"
  name: "X / OpenAI"
  url: "http://rsshub:1200/twitter/user/OpenAI"
```

3. 自检

```bash
./scripts/doctor.sh
```

4. 启动

```bash
./scripts/up.sh
```

5. 查看日志

```bash
docker logs -f x-trendradar
```

## 当前默认策略（已配置）

已在 `config/timeline.yaml` 里设置：

- 默认：`incremental`，全天有新增就推送
- `08:00-08:04`：固定提醒窗口，`current` 汇总，仅推送一次

## 安全说明

- `.env` 与 `output/` 不应提交到 GitHub
- 如果 webhook 或 token 泄露，请立即重置
- 不要在 issue/日志/截图中暴露 webhook 完整 URL

## 云端部署建议

本地部署时，电脑关机/睡眠后不会推送。要 24 小时稳定推送，建议部署到云服务器（Docker 常驻）。

最小方案：

1. 准备 Linux 云主机（2C2G 即可）
2. 安装 Docker / Docker Compose
3. 拉取本仓库并配置 `.env`
4. `docker compose up -d`
5. 配置开机自启（如 systemd）

## 常见问题

1. 企业微信只看到链接没有图片？
- 先确认你使用的是本仓库当前覆盖版（`overrides/trendradar/notification/senders.py` 已挂载）。

2. 没有收到推送？
- 检查 webhook 是否可用
- 检查 `docker logs -f x-trendradar`
- 检查 `.env` 的 `TWITTER_AUTH_TOKEN` 是否过期

3. 为什么视频不是直接播放？
- 企业微信机器人 API 本身不支持直接发送可播放视频消息，当前为卡片/链接方案。

## 停止服务

```bash
docker-compose down
```
