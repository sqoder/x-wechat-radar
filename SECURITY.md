# Security Policy

## Supported Versions

当前仓库以 `main` 分支为准，建议始终使用最新提交。

## Reporting a Vulnerability

如果发现安全问题（例如 webhook 泄露风险、敏感信息暴露、依赖漏洞）：

- 不要在公开 issue 贴出可利用细节和密钥
- 通过私信或私有渠道联系维护者
- 提供复现步骤、影响范围、建议修复方案

## Secret Handling

- 不要提交 `.env`、数据库文件、日志文件
- webhook/token 泄露后应立即重置
- 发布截图前应遮挡 webhook key 与 cookie 值
