# X AI Radar

一个面向 AI 信息追踪的 X（Twitter）监控项目。

它把你关注的 X 账号转成可抓取 RSS，经过去重、翻译、摘要和标签整理后，发到飞书或企业微信。当前默认配置已经收敛成一套能直接跑的方案：

- 监控 42 个 AI 相关作者
- 实时增量推送新帖
- 每天 08:00 发送一次汇总
- 支持飞书应用机器人私聊问答
- 单条消息统一使用「标题 / 作者+时间 / 核心内容 / 标签 / 原帖链接」排版

## 适合什么场景

- 不想频繁刷 X，只想接收关键动态
- 重点追踪 AI 公司、研究员、产品负责人和独立开发者
- 想在飞书里直接问“某个作者最新发了什么”

## 当前默认行为

- 数据源：`RSSHub -> Nitter 回退 -> 本地 SQLite 历史库回退`
- 推送策略：实时增量 + 08:00 固定汇总
- 默认账号池：42 个 AI 作者
- 默认关键词：一组较宽的 AI 词，用于过滤明显噪音
- 默认对话能力：飞书应用机器人

## 核心链路

自动推送链路：

`X -> RSSHub -> TrendRadar(shard1/2/3) -> 飞书/企业微信`

飞书问答链路：

`飞书消息 -> feishu_command_bot -> RSSHub/Nitter/SQLite -> 飞书回复`

更详细的开发视角说明见：

- [docs/ARCHITECTURE_CN.md](./docs/ARCHITECTURE_CN.md)

## 快速启动

### 1. 环境要求

- Docker / Docker Compose
- Python 3.10+
- 一个可用的 X `auth_token`

### 2. 初始化配置

```bash
cd x-wechat-feishu-radar
cp .env.example .env
```

至少填写：

- `TWITTER_AUTH_TOKEN`
- `AI_API_KEY`
- `FEISHU_WEBHOOK_URL` 或 `WEWORK_WEBHOOK_URL` 二选一

如果你要启用飞书应用机器人私聊问答和单聊主动推送，还要填写：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

### 3. 启动前体检

```bash
./scripts/doctor.sh
```

### 4. 推荐启动方式

```bash
./scripts/up-stable.sh
```

这条命令会做两件事：

- 启动 `rsshub + 3 个 TrendRadar 分片`
- 如果 `.env` 已填写 `FEISHU_APP_ID / FEISHU_APP_SECRET`，自动启动 `feishu-command-bot`

### 5. 首次使用飞书应用机器人

如果你走的是“飞书应用机器人私聊主动推送”模式，第一次需要先私聊机器人发一句话，建立主动推送收件人。

完成后你会得到：

- 实时新帖推送
- 每天 08:00 汇总
- 私聊直接查询指定作者最新帖子

## 常用命令

启动稳定模式：

```bash
./scripts/up-stable.sh
```

只做本地体检：

```bash
./scripts/doctor.sh
```

重建 3 分片配置：

```bash
python3 scripts/build_shard_configs.py --shards 3
```

本地自测飞书问答，不连接飞书：

```bash
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

按需查询某个账号最新帖子：

```bash
./scripts/x-latest.sh OpenAI --no-push
./scripts/x-latest.sh karpathy --push-target feishu
```

查看日志：

```bash
docker logs -f x-trendradar-shard1
docker logs -f x-trendradar-shard2
docker logs -f x-trendradar-shard3
docker logs -f x-feishu-command-bot
```

## 配置入口

### `.env`

主要放运行时密钥和开关：

- `TWITTER_AUTH_TOKEN`
- `AI_API_KEY / AI_API_BASE / AI_MODEL`
- `FEISHU_WEBHOOK_URL / FEISHU_WEBHOOK_SECRET`
- `WEWORK_WEBHOOK_URL`
- `FEISHU_APP_ID / FEISHU_APP_SECRET`
- `FEISHU_APP_PUSH_*`

模板见：

- [.env.example](./.env.example)

### `config/config.yaml`

主配置，决定：

- 监控哪些 RSS feed
- 使用什么调度 preset
- 以什么报告模式推送
- 各推送区域是否显示

关键位置：

- `rss.feeds`
- `schedule`
- `report`
- `display`
- `notification`

### `config/frequency_words.txt`

决定帖子过滤逻辑。

当前策略是：

- 一组较宽的 AI 关键词，尽量保留 AI 相关内容
- 一组全局噪音过滤词，压掉 giveaway / promo 这类帖子

### `config/timeline.yaml`

控制调度时间线。当前推荐用自定义方案：

- 全天实时增量
- 08:00 固定汇总

## 开发者关注的文件

- [scripts/feishu_command_bot.py](./scripts/feishu_command_bot.py)
  负责飞书长连接、命令解析、主动推送、08:00 汇总
- [scripts/feishu_app_support.py](./scripts/feishu_app_support.py)
  负责飞书应用消息发送、收件人注册、tenant token 获取
- [scripts/x_latest_post.py](./scripts/x_latest_post.py)
  负责按需查询、翻译、摘要、消息排版、推送脚本
- [scripts/build_shard_configs.py](./scripts/build_shard_configs.py)
  负责把主配置拆成 3 个分片
- [overrides/trendradar/](./overrides/trendradar)
  对上游 TrendRadar 的定制覆盖层

## 当前消息排版

实时推送和飞书问答已经统一成单条文本模板：

```text
🧠 标题
作者 / @账号 | 时间

核心内容：
总结：...
原文：...
翻译：...
图片：...
视频：...

标签：
#标签1 #标签2

原帖：
https://x.com/...
```

这套模板主要由：

- [scripts/x_latest_post.py](./scripts/x_latest_post.py)
- [scripts/feishu_command_bot.py](./scripts/feishu_command_bot.py)

共同驱动。

## 验证与回归

建议每次改动后至少执行：

```bash
./scripts/doctor.sh
python3 -m unittest discover -s tests -p "test_*.py" -v
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

如果你修改了分片配置，再补一次：

```bash
python3 scripts/build_shard_configs.py --shards 3
```

## 常见问题

### 1. 飞书应用机器人不回消息

先看：

```bash
docker logs -f x-feishu-command-bot
```

重点确认：

- `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确
- websocket 是否连接成功
- 是否已经先私聊过机器人一次

### 2. 没收到实时推送

先区分是哪条链路：

- 飞书群机器人 / 企业微信群机器人：看 `x-trendradar-shard*`
- 飞书应用机器人单聊主动推送：看 `x-feishu-command-bot`

### 3. 一直推旧消息

检查：

- `FEISHU_APP_PUSH_BOOTSTRAP_SKIP_EXISTING=true`
- `output/feishu_app_push_state.json` 是否异常

### 4. RSSHub 超时或 503

优先使用：

```bash
./scripts/up-stable.sh
```

不要把 42 个账号堆在单实例里高频抓取。

## 上传到 GitHub

上传步骤见：

- [docs/GITHUB_UPLOAD_CN.md](./docs/GITHUB_UPLOAD_CN.md)

## 许可

见 [LICENSE](./LICENSE)
