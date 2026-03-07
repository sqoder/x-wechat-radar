# 项目架构说明（中文）

## 1. 目标

这个项目的核心目标是：
- 自动抓取指定 X 账号的新帖子
- 在飞书/企业微信里接收推送
- 支持中文翻译、摘要、标签提取
- 支持飞书私聊/群聊命令式查询

## 2. 核心组件

### RSSHub
- 将 `twitter/user/:username` 路由输出为 RSS。
- 项目里通过 Docker 本地运行，服务名是 `rsshub`。

### TrendRadar（主流程）
- 定时任务入口（cron）
- 拉取 RSS
- 去重、过滤、聚合
- 调用翻译/总结逻辑
- 发送到 webhook 渠道

### Feishu Command Bot（对话流程）
- 使用飞书长连接模式接收消息事件
- 解析命令（如“查看openai最新动态”）
- 数据源回退：
  1. RSSHub
  2. Nitter RSS
  3. 本地 SQLite 历史库
- 生成回复并回发消息

### 自定义覆盖层（overrides）
- `overrides/trendradar/*` 是对上游 TrendRadar 的行为扩展。
- 主要扩展点：
  - RSS 解析与回退
  - 通知渲染
  - 发送器增强（飞书签名、媒体总结）

## 3. 数据流

自动推送流：
1. cron 触发 TrendRadar
2. TrendRadar 从 RSSHub 拉数据
3. 过滤与去重后生成增量报告
4. 调用翻译/标签/摘要（按配置）
5. 推送到飞书/企业微信 webhook

命令查询流（飞书）：
1. 用户在飞书私聊或群聊发命令
2. `feishu_command_bot.py` 解析用户名
3. 按回退链路取最新帖子
4. 输出“标题/总结/标签/正文/媒体链接/原帖”
5. 机器人回复

## 4. 调度策略

默认建议：
- 5 分钟节奏
- 3 分片错峰（0/1/2 分钟起步）

原因：
- 42 账号场景下，3 分钟节奏容易出现任务重叠
- 5 分钟错峰能显著降低 RSSHub timeout/503

## 5. 存储

- 运行产物在 `output/`：
  - `output/rss/*.db`：RSS 历史库
  - `output/news/*.db`：新闻聚合库
  - `output/html/*`：HTML 报告

这些目录不应提交到 GitHub。

## 6. 可扩展点

- 新增监控账号：`config/config.yaml -> rss.feeds`
- 调整时间策略：`config/timeline.yaml`
- 变更推送逻辑：`overrides/trendradar/notification/*`
- 增强命令能力：`scripts/feishu_command_bot.py`

## 7. 已知边界

- 企业微信 webhook 是单向推送，不支持对话式回复
- 飞书对话能力依赖应用机器人，不依赖 webhook
- 视频/图片“内容理解”默认是链接级；更深媒体总结需开启 OCR/ASR 或云多模态
