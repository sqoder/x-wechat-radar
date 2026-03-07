# 项目架构说明（中文）

这份文档面向开发者，描述当前这套 `X AI Radar` 的真实运行结构，而不是理想化设计图。

## 1. 系统目标

项目围绕 3 个能力构建：

1. 实时追踪一批指定 X 作者的新帖子
2. 每天固定时间输出一份摘要汇总
3. 在飞书里直接查询某个作者的最新帖子

当前默认关注的是 42 个 AI 相关作者，默认部署形态是 3 分片稳定模式。

## 2. 运行组件

### `rsshub`

职责：

- 把 `twitter/user/:username` 形式的路由转成 RSS
- 为 TrendRadar 和按需查询脚本提供统一入口

在本项目中的角色：

- 本地 Docker 服务
- 服务名固定为 `rsshub`
- 通常映射到 `127.0.0.1:1200`

### `trendradar-shard1/2/3`

职责：

- 定时抓取 RSS
- 对新帖子去重
- 根据 `frequency_words.txt` 做标题过滤
- 生成推送内容
- 通过 webhook 发往飞书或企业微信

为什么要分 3 个分片：

- 42 个账号在单实例高频抓取下容易让 RSSHub 超时
- 三个分片按 `0/1/2` 分钟错峰，能显著降低峰值压力

### `feishu-command-bot`

职责：

- 维护飞书 websocket 长连接
- 解析群聊/私聊命令
- 回退查询最新帖子
- 给用户回消息
- 给私聊收件人做主动实时推送
- 每天 08:00 给私聊收件人发汇总

它和 webhook 通道的关系：

- webhook 通道负责“群推送”
- `feishu-command-bot` 负责“私聊问答 + 私聊主动推送”

两条链路相互独立，可以同时开，也可以只开其中一条。

## 3. 核心脚本

### `scripts/x_latest_post.py`

负责：

- 按账号查询最新帖子
- 数据源回退：RSSHub -> Nitter -> SQLite
- 本地翻译 / 摘要 / 标签
- 单条消息文本排版
- 可选推送到飞书 / 企业微信

这个文件同时服务两类场景：

- 命令行按需查询
- 飞书机器人单条回复与主动推送的消息模板

### `scripts/feishu_command_bot.py`

负责：

- 飞书事件接入
- 命令识别，如 `查看openai最新的动态`
- 收件人注册与持久化
- 主动推送状态管理
- 08:00 汇总调度

### `scripts/feishu_app_support.py`

负责：

- 飞书应用 `tenant_access_token` 获取
- 收件人文件解析与更新
- 向私聊收件人发送文本消息

这是飞书应用机器人模式的基础设施层。

## 4. 数据流

### 4.1 自动推送流（webhook）

1. `supercronic` 触发 `trendradar-shard*`
2. 分片实例从 `rsshub` 拉对应作者的 RSS
3. TrendRadar 做增量判断、过滤、聚合
4. 根据配置决定是否翻译、摘要、打标签
5. 通过飞书 webhook 或企业微信 webhook 发出去

### 4.2 飞书问答流

1. 用户在飞书私聊或群聊发命令
2. `feishu-command-bot` 解析作者名或别名
3. 查询链路按顺序尝试：
   - RSSHub
   - Nitter
   - 本地 SQLite 历史库
4. 生成单条消息文本
5. 回复到飞书会话

### 4.3 飞书私聊主动推送流

1. 用户先私聊机器人一次，建立收件人
2. `feishu-command-bot` 轮询本地 RSS 数据库
3. 去重后只挑尚未发送过的新帖子
4. 通过飞书应用接口发到私聊
5. 每天 08:00 再额外发一条汇总

## 5. 当前消息模板

当前单条消息模板已经统一成下面结构：

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

好处：

- 对用户更像“阅读摘要”，不是日志输出
- 原文与翻译同时保留，便于快速判断
- 链接和媒体信息仍保留，方便点开原帖

## 6. 配置面

### `.env`

决定运行时密钥与推送开关：

- X `auth_token`
- AI 模型地址与 API Key
- webhook
- 飞书应用机器人配置
- 主动推送参数 `FEISHU_APP_PUSH_*`

### `config/config.yaml`

决定：

- RSS feed 列表
- schedule preset
- report mode
- display region
- notification channel

### `config/frequency_words.txt`

决定帖子过滤策略。

当前做法不是把 AI 关键词写得很窄，而是：

- 留一组较宽的 AI 词
- 只过滤 giveaway / promo 这类显性噪音

因为作者池本身已经偏 AI，如果关键词写太窄，容易误杀真正有价值的帖子。

### `config/timeline.yaml`

当前推荐是自定义时间线：

- 全天增量推送
- 08:00 固定汇总

## 7. 存储与状态

主要运行产物位于 `output/`：

- `output/rss/*.db`
  RSS 历史库，飞书问答和主动推送都会读它
- `output/news/*.db`
  TrendRadar 聚合结果
- `output/feishu_app_recipients.json`
  飞书应用机器人收件人注册表
- `output/feishu_app_push_state.json`
  飞书主动推送去重状态

这些文件都不应该提交到 GitHub。

## 8. 扩展点

最常见的改动入口：

- 新增或替换监控作者：`config/config.yaml`
- 调整关键词过滤：`config/frequency_words.txt`
- 调整主动推送格式：`scripts/x_latest_post.py`
- 调整飞书命令识别：`scripts/feishu_command_bot.py`
- 调整上游通知渲染：`overrides/trendradar/notification/*`

## 9. 已知边界

- 企业微信 webhook 只能推送，不能做对话式回复
- 飞书问答依赖应用机器人，不依赖 webhook
- Nitter / RSSHub 都属于外部依赖，存在源级波动
- 视频和图片默认以链接级推送为主，更深内容理解需要额外启用 OCR / ASR 或云多模态

## 10. 开发建议

每次做改动后，至少跑：

```bash
./scripts/doctor.sh
python3 -m unittest discover -s tests -p "test_*.py" -v
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

如果改动涉及 feed 分片，再补：

```bash
python3 scripts/build_shard_configs.py --shards 3
```
