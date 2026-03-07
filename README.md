# x-wechat-feishu-radar

一个面向 AI 信息追踪的 X 监控项目。

它做的事情很简单：持续抓取一组 AI 相关作者的 X 帖子，整理成适合在飞书里阅读的消息，然后用两种方式给你：

- 实时推送新帖子
- 每天 08:00 发一份汇总

除了被动接收，你还可以直接在飞书里问：

- `查看openai最新的动态`
- `查看karpathy最新的动态`
- `我要看马斯克最新帖子`

## 这套项目当前已经实现了什么

- 默认监控 42 个 AI 相关作者
- 3 分片错峰抓取，降低 RSSHub 压力
- 飞书应用机器人支持：
  - 私聊问答
  - 私聊实时主动推送
  - 每天 08:00 私聊汇总
- 群机器人 / 企业微信 webhook 仍可继续作为群推送通道
- 单条消息统一排版为：
  - 标题
  - 作者 + 时间
  - 核心内容
  - 标签
  - 原帖链接
- 核心内容里同时保留原文和中文翻译

## 项目怎么工作

自动推送主链路：

`X -> RSSHub -> TrendRadar(shard1/2/3) -> 飞书/企业微信`

飞书问答链路：

`飞书消息 -> feishu_command_bot -> RSSHub / Nitter / SQLite -> 飞书回复`

如果你关心内部组件和扩展点，直接看：

- [docs/ARCHITECTURE_CN.md](./docs/ARCHITECTURE_CN.md)

## 快速启动

### 1. 准备环境

- Docker 或 Docker Compose
- Python 3.10+
- 一个可用的 X `auth_token`

### 2. 初始化配置

```bash
cp .env.example .env
```

至少填这些：

- `TWITTER_AUTH_TOKEN`
- `AI_API_KEY`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

如果你还想保留群机器人推送，再额外填：

- `FEISHU_WEBHOOK_URL`

或者企业微信：

- `WEWORK_WEBHOOK_URL`

### 3. 启动前检查

```bash
./scripts/doctor.sh
```

### 4. 启动

```bash
./scripts/up-stable.sh
```

这会启动：

- `x-rsshub`
- `x-trendradar-shard1`
- `x-trendradar-shard2`
- `x-trendradar-shard3`
- `x-feishu-command-bot`（当 `.env` 已配置飞书应用机器人时）

### 5. 首次激活飞书私聊推送

第一次需要先私聊机器人发一句话，建立收件人。

之后你会同时得到：

- 实时新帖推送
- 每天 08:00 汇总
- 私聊查询作者最新帖子

## 最常用的命令

启动稳定模式：

```bash
./scripts/up-stable.sh
```

查看体检结果：

```bash
./scripts/doctor.sh
```

本地自测飞书问答：

```bash
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

按命令行查询某个作者最新帖子：

```bash
./scripts/x-latest.sh OpenAI --no-push
./scripts/x-latest.sh karpathy --push-target feishu
```

查看服务日志：

```bash
docker logs -f x-trendradar-shard1
docker logs -f x-trendradar-shard2
docker logs -f x-trendradar-shard3
docker logs -f x-feishu-command-bot
```

## 配置从哪里改

### `.env`

这里放运行时密钥和推送开关。

最重要的是：

- `TWITTER_AUTH_TOKEN`
- `AI_API_KEY / AI_API_BASE / AI_MODEL`
- `FEISHU_APP_ID / FEISHU_APP_SECRET`
- `FEISHU_APP_PUSH_*`
- `FEISHU_WEBHOOK_URL`
- `WEWORK_WEBHOOK_URL`

模板见 [.env.example](./.env.example)。

### `config/config.yaml`

这里决定：

- 监控哪些作者
- 抓取模式
- 调度方式
- 推送区域

你最常改的是：

- `rss.feeds`
- `schedule`
- `report`

### `config/frequency_words.txt`

这里决定过滤规则。

当前默认是：

- 用一组较宽的 AI 关键词保留 AI 相关帖子
- 用全局过滤词压掉 giveaway、promo 这类噪音

### `config/timeline.yaml`

这里决定时间线。

当前策略是：

- 全天实时增量
- 08:00 固定汇总

## 飞书里实际收到的消息格式

```text
🧠 标题
作者 / @账号 | 时间

核心内容：
总结：...
原文：...
翻译：...

标签：
#标签1 #标签2

原帖：
https://x.com/...
```

如果帖子带图片或视频，消息里会追加媒体链接。

## 开发时最该看的文件

- [scripts/feishu_command_bot.py](./scripts/feishu_command_bot.py)
  飞书长连接、命令识别、主动推送、08:00 汇总都在这里
- [scripts/feishu_app_support.py](./scripts/feishu_app_support.py)
  飞书应用消息发送、收件人注册、token 获取
- [scripts/x_latest_post.py](./scripts/x_latest_post.py)
  按需查询、翻译、摘要、消息模板
- [scripts/build_shard_configs.py](./scripts/build_shard_configs.py)
  把主配置拆成 3 个分片
- [overrides/trendradar/](./overrides/trendradar)
  对上游 TrendRadar 的定制层

## 改动后怎么验证

至少跑这三条：

```bash
./scripts/doctor.sh
python3 -m unittest discover -s tests -p "test_*.py" -v
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

如果你改了作者列表，再补一次：

```bash
python3 scripts/build_shard_configs.py --shards 3
```

## 常见问题

### 飞书机器人不回消息

看这里：

```bash
docker logs -f x-feishu-command-bot
```

重点确认：

- `FEISHU_APP_ID / FEISHU_APP_SECRET` 是否正确
- websocket 是否已经连上
- 是否已经先私聊过机器人一次

### 一直收到旧消息

检查：

- `FEISHU_APP_PUSH_BOOTSTRAP_SKIP_EXISTING=true`
- `output/feishu_app_push_state.json` 是否异常

### 没收到实时推送

先区分链路：

- 群机器人 / 企业微信群推送：看 `x-trendradar-shard*`
- 飞书私聊主动推送：看 `x-feishu-command-bot`

### RSSHub 超时或 503

不要把所有作者塞进单实例高频抓取。这个项目默认的 3 分片稳定模式就是为了解决这个问题。

## 安全

- 不要提交 `.env`
- 不要提交 `output/` 和 `logs/`
- webhook、token、cookie 泄露后立即重置

## License

见 [LICENSE](./LICENSE)
