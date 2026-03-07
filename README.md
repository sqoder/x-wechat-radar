# X AI Radar

只监控 AI 圈 X 账号，并把新帖推送到企业微信/飞书。  
默认策略：`实时增量提醒 + 每天 08:00 汇总`，翻译默认关闭。

## 项目架构

- TrendRadar：调度、去重、推送
- RSSHub：X 用户 RSS（`twitter/user/:username`）
- Docker Compose：一键运行
- `overrides/trendradar/*`：本仓库定制逻辑

数据流：`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 当前默认配置

- 账号范围：AI-only（42 个）
- 轮询频率：`CRON_SCHEDULE=*/1 * * * *`
- 汇总时间：每天 `08:00`
- 翻译功能：默认关闭（`config/config.yaml` 里 `ai_translation.enabled: false`）

## 小白上手

### 1) 初始化

```bash
cp .env.example .env
```

`.env` 至少填这两项：

- `TWITTER_AUTH_TOKEN`
- `WEWORK_WEBHOOK_URL` 或 `FEISHU_WEBHOOK_URL`

### 2) 获取 X 的 `auth_token`

1. 登录 `x.com`
2. 打开开发者工具 -> Application -> Cookies -> `https://x.com`
3. 找到 `auth_token` 并复制
4. 填到 `.env`

![X auth_token Cookie screenshot](./5ba9aeb751faa9bd7f973ce330d1c77d.png)

```env
TWITTER_AUTH_TOKEN=your_auth_token
```

### 3) 配置企业微信 webhook

1. 目标群 -> 聊天信息
2. 点击 `消息推送`
3. 配置机器人并复制 webhook
4. 填到 `.env`

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

## 开源翻译模型（可选，默认不启用）

如果你想用免费本地翻译，需要自己下载并运行本地模型，再改配置。

推荐开源模型（示例）：

- `qwen2.5:1.5b`（轻量，先跑通最稳）
- `qwen2.5:7b`（质量更高，更吃资源）
- `HY-MT1.5-7B`（需你自己导入到本地推理服务后使用）

推荐接法：Ollama（OpenAI 兼容接口）。

### 1) 安装并启动 Ollama

```bash
brew install ollama
brew services start ollama
```

### 2) 下载翻译模型（示例）

```bash
ollama pull qwen2.5:1.5b
ollama list
```

### 3) 修改 `.env`（按你的本地模型名）

```env
AI_API_KEY=local_dummy_key
AI_API_BASE=http://host.docker.internal:11434/v1
AI_MODEL=openai/qwen2.5:1.5b
```

说明：模型名规则是 `AI_MODEL=openai/<ollama中的模型名>`。

### 4) 打开翻译开关

编辑 `config/config.yaml`，把：

```yaml
ai_translation:
  enabled: false
```

改为：

```yaml
ai_translation:
  enabled: true
```

### 5) 重启生效

```bash
docker compose up -d --force-recreate trendradar
```

## 推送内容说明

- 新帖提醒：有新增就推
- 每日汇总：08:00 固定一条
- 图片：直接推图
- 视频：以链接/卡片推送（平台接口限制）

## 常用命令

```bash
./scripts/up.sh
docker compose down
docker compose ps
docker logs -f x-trendradar
```
