# A 股每日邮件简报

每天自动生成 3 封邮件，并在交易时段监控你的持仓。

## 三封邮件

| 时间 | 内容 |
| --- | --- |
| 09:35 盘前简报 | 外盘、宏观日历、昨晚公告、新股、解禁、早评、持仓 |
| 11:45 午间简报 | 上午盘面、板块轮动、财联社实时快讯、持仓异动 |
| 18:00 收盘总结 | 收盘核心数据、两市大宗交易汇总、当日龙虎榜完整榜单、持仓盈亏总结 |

盘中监控：交易时段每 5 分钟检查持仓和指数，触发异动时额外发送提醒邮件。

盘中额外提醒做了防打扰限制：只对“重要异动”发信，且每小时最多 1 封、全天最多 3 封；普通风险线提示只出现在三封固定简报里。

## 首次使用

1. 打开 `daily_briefing/.env`，确认邮箱和 DeepSeek Key 已填写。
2. 手动生成一封测试邮件：

```powershell
python daily_briefing\run_briefing.py --mode premarket --no-send
```

3. 确认 `daily_briefing\data\reports\` 下有 HTML 报告后，再执行：

```powershell
python daily_briefing\run_briefing.py --mode premarket
```

## 注册 Windows 定时任务

在 PowerShell 中执行一次即可：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File daily_briefing\setup_tasks.ps1
```

以后可在“任务计划程序”中看到：

- A股盘前简报
- A股午间简报
- A股收盘总结
- A股盘中监控

## QQ 邮箱发送失败怎么办

如果日志出现 `535 Login fail`，通常是邮箱没有开启 SMTP 服务。请按以下步骤操作：

1. 登录 QQ 邮箱网页版。
2. 进入“设置 → 账户”。
3. 找到“POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务”，开启 SMTP 服务。
4. 按提示发送短信，生成一个 16 位授权码。
5. 把新的授权码填到 `daily_briefing/.env` 的 `QQ_SMTP_AUTH_CODE=` 后面，注意不要有空格。
6. 重新执行：

```powershell
python daily_briefing\test_mail.py
```

如果收到测试邮件，说明配置成功。

## 常用命令

```powershell
# 生成盘前简报，不发送
python daily_briefing\run_briefing.py --mode premarket --no-send

# 生成午间简报并发送
python daily_briefing\run_briefing.py --mode midday

# 生成收盘总结并发送
python daily_briefing\run_briefing.py --mode close

# 手动执行一次盘中监控
python daily_briefing\run_briefing.py --mode monitor --no-send
```

> 所有邮件正文都包含“不构成投资建议”。本系统只做信息提醒，不执行任何自动交易。

## 可视化小工具

优先双击 EXE 打开：

```powershell
C:\Users\admin\Documents\ChatGPT\A沪深\AAA.exe
```

如果需要用源码调试，再双击：

```powershell
C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\start_service_manager.bat
```

小工具可以：

- 查看 `TradingAgents` / 每日简报当前是否有运行进程。
- 查看、启用、停用 4 个 Windows 定时任务。
- 添加或删除收件邮箱。
- 添加或删除关注股票，并填写股数、成本、风险线、清仓线。
- 手动生成盘前、午间、收盘、盘中监控预览；也可以确认后手动发送一次。

收件邮箱和关注股票会保存到：

```powershell
C:\Users\admin\Documents\ChatGPT\A沪深\daily_briefing\data\service_settings.json
```

这个文件不保存邮箱授权码；授权码仍在 `daily_briefing\.env`。
