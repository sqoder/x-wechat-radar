# GitHub 上传指南（中文）

这份文档用于把本项目安全、完整地上传到 GitHub。

## 1. 上传前检查

```bash
cd /Users/wangxinglin/Desktop/x-wechat-radar
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

如果命令没有输出，说明这些敏感/运行文件未被追踪。

## 2. 本地验证（建议）

```bash
./scripts/doctor.sh
python3 -m unittest discover -s tests -p "test_*.py" -v
docker compose config -q
```

## 3. 提交代码

```bash
git add -A
git commit -m "docs: improve README and onboarding guide"
```

## 4. 推送到 GitHub

查看当前分支：

```bash
git branch --show-current
```

如果是 `main`：

```bash
git push origin main
```

如果是其他分支（例如 `codex/docs-refresh`）：

```bash
git push -u origin codex/docs-refresh
```

然后在 GitHub 上发起 Pull Request 合并到 `main`。

## 5. 推送后检查

在 GitHub 仓库页面确认：
- `README.md` 展示正常
- `docs/GITHUB_UPLOAD_CN.md` 可访问
- 没有 `.env`、token、webhook 泄漏

## 6. 常见问题

### Q1: `remote origin already exists`

说明远程仓库已配置，不需要重复 `git remote add`。

### Q2: `failed to push some refs`

先拉取再推送：

```bash
git pull --rebase origin main
git push origin main
```

### Q3: 误提交了密钥怎么办

1. 立即在平台侧（飞书/企业微信/X）重置 webhook/token  
2. 删除历史敏感提交（重写历史）或新建仓库重新上传  
3. 重新推送并再次检查
