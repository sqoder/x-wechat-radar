# X AI Radar

只监控 AI 圈 X 账号，并把新帖推送到企业微信/飞书。  
默认策略：`实时增量提醒 + 每天 08:00 汇总`，翻译默认开启（可关闭）。

## 项目架构

- TrendRadar：调度、去重、推送
- RSSHub：X 用户 RSS（`twitter/user/:username`）
- Docker Compose：一键运行
- `overrides/trendradar/*`：本仓库定制逻辑

数据流：`X -> RSSHub -> TrendRadar -> 企业微信/飞书`

## 当前默认配置

- 账号范围：AI-only（42 个）
- 轮询频率：`CRON_SCHEDULE=*/3 * * * *`（稳定模式建议）
- 汇总时间：每天 `08:00`
- 翻译功能：默认开启（`config/config.yaml` 里 `ai_translation.enabled: true`）
- 帖子增强：自动提取 `标签 + 摘要 + 图片/视频链接`

## 你会收到什么

- 实时新帖：有人发新帖就推送
- 每日汇总：每天 08:00 一条“当前汇总”
- 文本增强：每条附带 `标签` 和 `摘要`
- 媒体增强：图片直发；视频卡片/链接推送（企业微信接口限制）
- 中文能力：打开 `ai_translation` 后可自动中文翻译

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

稳定抓取推荐（42 账号）：

```bash
./scripts/up-stable.sh
```

说明：`up-stable.sh` 会自动做 3 分片错峰抓取，显著降低 RSSHub 超时与 503。

如果你想关闭翻译，把 `config/config.yaml` 里的 `ai_translation.enabled` 改成 `false`，再重启容器。

## 开源翻译模型（推荐）

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

### 4) 检查翻译开关（默认已开）

确认 `config/config.yaml` 为：

```yaml
ai_translation:
  enabled: true
```

### 5) 重启生效

```bash
docker-compose up -d --force-recreate trendradar
```

## 推送内容说明

- 默认推送字段：标题 + 原帖链接 + 标签 + 摘要
- 图片：直接推图
- 视频：以链接/卡片推送（平台接口限制）
- 开启翻译后：以上内容都会按目标语言翻译（链接、@用户名、#标签会保留原样）

## 按需查询任意账号（随时查特朗普等）

支持手动查询任意 X 用户最新帖子，并直接推到你的微信（企业微信机器人）。

```bash
# 查询并推送
./scripts/x-latest.sh realDonaldTrump

# 只看终端结果，不推送
./scripts/x-latest.sh realDonaldTrump --no-push
```

可选增强：

```bash
# 图片 OCR（免费本地，需安装 paddleocr）
./scripts/x-latest.sh realDonaldTrump --with-ocr

# 视频语音转写（免费本地，需安装 faster-whisper + ffmpeg）
./scripts/x-latest.sh realDonaldTrump --with-asr
```

说明：
- 这是“主动查询”能力，适合你临时想看某个人最新帖。
- 脚本会自动按顺序回退：`RSSHub -> Nitter RSS -> 本地SQLite历史库`。
- 如果是“纯视频/纯图片且几乎无正文”的帖子，会给出稳定说明，不会胡乱编造翻译。
- 企业微信 webhook 是单向推送，不支持在群里@机器人后让它回你。要做“聊天问答式”需要企业微信回调服务（单独开发）。

## 飞书聊天指令机器人（0 元本地）

如果你要“在飞书里直接发命令，机器人自动回最新帖子”，用这个：

### 1) 在飞书开发者后台创建应用

- 开启机器人能力
- 开启事件订阅并选择“长连接模式”（不需要公网回调 URL）
- 订阅事件：`im.message.receive_v1`
- 给应用权限（至少）：
  - 读取消息内容相关权限
  - 发送消息相关权限
- 把机器人加到你的群里

### 2) 填写 `.env`

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BOT_RSS_BASE=http://127.0.0.1:1200
FEISHU_BOT_ENABLE_TRANSLATE=true
```

### 3) 安装依赖并启动

```bash
python3 -m pip install --user lark-oapi
./scripts/feishu-bot.sh
```

Docker 常驻模式（可选）：

```bash
COMPOSE_PROFILES=feishu-bot docker-compose up -d feishu-command-bot
docker logs -f x-feishu-command-bot
```

macOS launchd 常驻模式（可选）：

```bash
./scripts/install_feishu_launchd.sh
launchctl print gui/$UID/com.xwechatradar.feishu.bot
```

### 4) 在飞书群里发命令

- `查 elonmusk 最新帖子`
- `查看 @realDonaldTrump 最新推特`
- `我要看马斯克最新帖子`

本地自测（不连飞书）：

```bash
./scripts/feishu-bot.sh --self-test "我要看马斯克最新推特"
```

## 0 元本地 OCR/ASR（可选）

本项目可做到纯本地免费运行（不调用云 API）。你只需按需安装本地依赖：

```bash
brew install ffmpeg
python3 -m pip install --user paddleocr paddlepaddle faster-whisper
```

然后配合 `./scripts/x-latest.sh` 的 `--with-ocr` / `--with-asr` 即可启用。

## 最小测试集

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

## 常用命令

```bash
./scripts/up.sh
./scripts/up-stable.sh
docker-compose down
docker-compose ps
docker logs -f x-trendradar
docker logs -f x-trendradar-shard1
./scripts/x-latest.sh realDonaldTrump
./scripts/feishu-bot.sh
./scripts/install_feishu_launchd.sh
./scripts/uninstall_feishu_launchd.sh
```
