# GitHub 上传指南（中文）

这份文档描述当前仓库的推荐上传流程。

注意：

- 本地目录名是 `x-wechat-feishu-radar`
- 当前远程仓库名仍然是 `sqoder/x-wechat-radar`

这两者不需要强行一致，Git 只认 remote 配置。

## 1. 上传前检查

```bash
cd /path/to/x-wechat-feishu-radar
git status --short
```

确认以下文件不会被提交：

- `.env`
- `output/`
- `logs/`

快速验证：

```bash
git ls-files | rg '^\\.env$|^output/|^logs/'
```

如果没有输出，说明这些敏感或运行时文件没有被追踪。

## 2. 本地验证

推荐至少执行：

```bash
./scripts/doctor.sh
python3 -m unittest discover -s tests -p "test_*.py" -v
./scripts/feishu-bot.sh --self-test "查看openai最新的动态"
```

如果本机支持 `docker compose`：

```bash
docker compose config -q
```

如果本机只有 `docker-compose`：

```bash
docker-compose config -q
```

## 3. 提交代码

```bash
git add README.md docs/ARCHITECTURE_CN.md docs/GITHUB_UPLOAD_CN.md \
  .env.example config/frequency_words.txt scripts tests
git commit -m "docs: refresh developer docs and Feishu bot workflow"
```

如果还有其他本次改动需要一并上传，可以改成：

```bash
git add -A
git commit -m "feat: refine Feishu bot workflow and refresh docs"
```

## 4. 推送到 GitHub

查看当前分支：

```bash
git branch --show-current
```

如果当前就是 `main`：

```bash
git push origin main
```

如果是其他分支，例如 `codex/docs-refresh`：

```bash
git push -u origin codex/docs-refresh
```

然后在 GitHub 上发起 Pull Request 合并回 `main`。

## 5. 推送后检查

到 GitHub 仓库页面确认：

- `README.md` 展示正常
- `docs/ARCHITECTURE_CN.md` 可访问
- `docs/GITHUB_UPLOAD_CN.md` 可访问
- 没有 `.env`、token、webhook、运行产物泄漏

## 6. 常见问题

### Q1. `remote origin already exists`

说明远程仓库已经配置好，不需要再次执行 `git remote add`。

### Q2. `failed to push some refs`

先同步远端再推：

```bash
git pull --rebase origin main
git push origin main
```

### Q3. 误提交了密钥怎么办

1. 立即在飞书、企业微信、X 等平台侧重置 webhook / token
2. 停止继续推送包含敏感信息的提交
3. 视情况重写历史，或新建干净仓库重新上传

### Q4. 本机只有 `docker-compose` 没有 `docker compose`

这是兼容场景，不是错误。当前项目脚本已经同时兼容这两种命令。
