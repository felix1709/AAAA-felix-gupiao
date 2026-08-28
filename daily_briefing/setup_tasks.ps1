param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Runner = ""
)

# 注册 A 股每日简报的 Windows 定时任务（当前用户，无需管理员）。
# 优先使用同目录的 AStockBriefingManager.exe；没有 EXE 时回退到本机 Python。
$ErrorActionPreference = "Stop"

$Script = Join-Path $Root "daily_briefing\run_briefing.py"
$Exe = Join-Path $Root "AStockBriefingManager.exe"

if ([string]::IsNullOrWhiteSpace($Runner)) {
    if (Test-Path $Exe) {
        $Runner = $Exe
    } else {
        $Runner = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
        if ([string]::IsNullOrWhiteSpace($Runner)) {
            $Runner = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
        }
    }
}

if ([string]::IsNullOrWhiteSpace($Runner)) {
    throw "没有找到 AStockBriefingManager.exe 或 python.exe，无法注册定时任务。"
}

function New-BriefingTask {
    param(
        [string]$Name,
        [string]$Mode,
        [object[]]$Triggers,
        [string]$Description
    )
    if ((Split-Path -Leaf $Runner).ToLowerInvariant() -eq "astockbriefingmanager.exe") {
        $Argument = "--run-briefing --mode " + $Mode
    } else {
        $Argument = '"' + $Script + '" --mode ' + $Mode
    }
    $Action = New-ScheduledTaskAction -Execute $Runner -Argument $Argument -WorkingDirectory $Root
    $Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $Name -Trigger $Triggers -Action $Action -Settings $Settings -Description $Description -Force | Out-Null
    Write-Host "已注册任务：$Name"
}

$PremarketTrigger = New-ScheduledTaskTrigger -Daily -At 09:35
New-BriefingTask -Name "A股盘前简报" -Mode "premarket" -Triggers @($PremarketTrigger) -Description "每个A股交易日 09:35 生成并发送盘前简报"

$MiddayTrigger = New-ScheduledTaskTrigger -Daily -At 11:45
New-BriefingTask -Name "A股午间简报" -Mode "midday" -Triggers @($MiddayTrigger) -Description "每个A股交易日 11:45 生成并发送午间简报"

$CloseTrigger = New-ScheduledTaskTrigger -Daily -At 18:00
New-BriefingTask -Name "A股收盘总结" -Mode "close" -Triggers @($CloseTrigger) -Description "每个A股交易日 18:00 生成并发送收盘总结（含龙虎榜、大宗交易）"

# 盘中监控：上午 09:35-11:30，下午 13:05-15:00，每 5 分钟运行一次。
$MorningRepetition = (New-ScheduledTaskTrigger -Once -At 09:35 -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Minutes 115)).Repetition
$MorningMonitor = New-ScheduledTaskTrigger -Daily -At 09:35
$MorningMonitor.Repetition = $MorningRepetition
$AfternoonRepetition = (New-ScheduledTaskTrigger -Once -At 13:05 -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Minutes 115)).Repetition
$AfternoonMonitor = New-ScheduledTaskTrigger -Daily -At 13:05
$AfternoonMonitor.Repetition = $AfternoonRepetition
New-BriefingTask -Name "A股盘中监控" -Mode "monitor" -Triggers @($MorningMonitor, $AfternoonMonitor) -Description "交易时段每 5 分钟检查持仓与指数异动，触发后发送提醒"

Write-Host "全部任务注册完成。可在“任务计划程序”中查看。"
