# AStock Briefing Manager 提交发布流程

本文档是 AStock Briefing Manager 的固定发布手册。以后用户说“提交发布”、“提交&发布”、“同步发布”或“发布”时，先读本文件，再按这里执行。

## 0. 先确认当前目录是 Git 仓库

Git 仓库就是带有 `.git` 隐藏目录的项目文件夹。`.git` 保存提交历史、分支、远程仓库地址等信息。

在项目根目录执行：

```powershell
git rev-parse --show-toplevel
git status --short
git remote -v
gh auth status -h github.com
```

如果不是 Git 仓库，停止提交、推送和 GitHub Release 发布。不要自动运行 `git init`，也不要自动改写历史。

## 1. 发布目标

发布包含三件事：

1. 提交代码和文档到 Git 仓库。
2. 构建干净的 Windows 可分发包。
3. 创建 GitHub Release 并上传 zip，让用户可以下载安装，也让已安装的新版客户端可以一键下载并安装后续更新。

## 2. 固定项目信息

- 项目目录：`C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents`
- GitHub 仓库：`https://github.com/felix1709/AAAA-felix-gupiao.git`
- Git 远程名：`felix`
- Git 用户名：`felix1709`
- Git 邮箱：`331631382@qq.com`
- 管理器版本来源：`tools\tradingagents_service_manager.py` 里的 `APP_VERSION`
- 干净发布目录：`C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean`
- 干净发布 zip：`C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean.zip`

## 3. 隐私和安全边界

绝对不要提交或发布这些内容：

- `.env`
- `.venv/`
- `build/`
- `dist/`
- `release/`
- `AStockBriefingManager.exe`
- `daily_briefing\data\service_settings.json`
- `daily_briefing\data\monitor_state.json`
- `daily_briefing\data\reports\`
- `daily_briefing\logs\`
- API key
- SMTP 授权码
- 邮件收件人列表
- 用户自选股票、持仓数据
- 个人股票分析 markdown 文件

发布包里的 `daily_briefing\data\service_settings.json` 必须是空白模板：无 API key、无邮箱账号、无收件人、无股票、无持仓。

## 4. Git 身份

每次发布前确认：

```powershell
git config user.name "felix1709"
git config user.email "331631382@qq.com"
git config user.name
git config user.email
```

## 5. 版本号规则

管理器界面、更新检查和一键更新使用：

```powershell
Select-String -Path tools\tradingagents_service_manager.py -Pattern 'APP_VERSION'
```

发布 tag 必须使用 `vAPP_VERSION`，例如 `APP_VERSION = "0.2.1"` 对应 GitHub Release tag `v0.2.1`。

注意：`pyproject.toml` 是原 TradingAgents Python 包版本，不一定等于当前 Windows 管理器版本。发布 Windows 管理器时，以 `APP_VERSION` 为准。

## 6. 发布前验证

每次发布都必须重新运行，不能只相信旧结果：

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m pytest tests/test_service_manager.py tests/test_daily_briefing_settings.py -q
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m ruff check tools/tradingagents_service_manager.py tests/test_service_manager.py
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m py_compile tools/tradingagents_service_manager.py
```

任何一步失败都停止发布，先修复问题。

## 7. 构建 EXE

使用项目虚拟环境里的 PyInstaller：

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\pyinstaller.exe' --noconfirm --clean --distpath 'C:\Users\admin\Documents\ChatGPT\A沪深' 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\AStockBriefingManager.spec'
```

构建后确认：

```powershell
Test-Path 'C:\Users\admin\Documents\ChatGPT\A沪深\AStockBriefingManager.exe'
```

## 8. 生成干净发布包

执行：

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\tools\create_clean_release.ps1'
```

然后检查 zip 和目录：

```powershell
Get-Item 'C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean.zip'
Get-ChildItem 'C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean'
```

## 9. 发布包冒烟测试

冒烟测试是最小启动检查，用来确认 EXE 能打开自身逻辑，不依赖 Codex：

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean\AStockBriefingManager.exe' --once
```

如果失败，停止发布并先修复。

## 10. 提交代码

先查看改动：

```powershell
git status --short
```

只添加本次相关文件。不要用 `git add .`，因为工作区可能有用户自己的未提交改动。

示例：

```powershell
git add AGENTS.md fabu.MD docs/ASTOCK_MANAGER_RELEASE_WORKFLOW.md tools/tradingagents_service_manager.py tests/test_service_manager.py
git commit -m "chore: update astock manager release workflow"
```

如果没有新增提交，跳过 commit。

## 11. 推送

推送到用户仓库：

```powershell
git push felix main
```

禁止使用：

```powershell
git push --force
```

除非用户明确要求强推。

## 12. 创建 GitHub Release

tag 格式固定为 `vAPP_VERSION`，例如 `v0.2.1`。

如果 Release 不存在：

```powershell
gh release create v0.2.2 `
  --repo felix1709/AAAA-felix-gupiao `
  --target main `
  --title "AStock Briefing Manager v0.2.2" `
  --notes "本版本包含 AStock Briefing Manager Windows 可视化管理器、定时服务控制、设置页、更新检测/一键安装更新和干净可分发包。" `
  'C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean.zip'
```

如果 Release 已存在，不要默认覆盖。除非用户明确要求覆盖资产，否则升级版本号再发布。

## 13. 发布后验证

发布后检查：

```powershell
gh release view v0.2.2 --repo felix1709/AAAA-felix-gupiao
```

必须确认：

- Release tag 存在。
- 资产里有 `AStockBriefingManager-clean.zip`。
- zip 是干净发布包。
- 设置页“检测更新”可以读到 GitHub 最新 Release，并能识别 `AStockBriefingManager-clean.zip` 作为可自动安装资产。
- 一键更新逻辑不会覆盖 `daily_briefing\data`、`daily_briefing\logs` 或 `.env`。

## 14. 最终回复用户

发布完成后，用中文告诉用户：

1. 推送到哪个 GitHub 仓库。
2. 发布的版本号。
3. Release 地址。
4. 安装包资产名。
5. 本地 zip 路径。
6. 还有哪些本地未提交文件没有动。
