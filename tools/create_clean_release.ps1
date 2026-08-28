param(
    [string]$ReleaseName = "AStockBriefingManager-clean"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$WorkspaceRoot = (Resolve-Path (Join-Path $ProjectRoot "..")).Path
$ReleaseRoot = Join-Path $WorkspaceRoot "release"
$PackageRoot = Join-Path $ReleaseRoot $ReleaseName
$ExeSource = Join-Path $WorkspaceRoot "AStockBriefingManager.exe"
$ZipPath = Join-Path $ReleaseRoot "$ReleaseName.zip"

if (!(Test-Path $ExeSource)) {
    throw "Missing EXE: $ExeSource. Build AStockBriefingManager.exe first."
}

$releaseRootFull = [System.IO.Path]::GetFullPath($ReleaseRoot)
$packageRootFull = [System.IO.Path]::GetFullPath($PackageRoot)
if (!$packageRootFull.StartsWith($releaseRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean outside release directory: $packageRootFull"
}

if (Test-Path $PackageRoot) {
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $PackageRoot | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageRoot "daily_briefing\data") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageRoot "daily_briefing\logs") | Out-Null

Copy-Item -LiteralPath $ExeSource -Destination (Join-Path $PackageRoot "AStockBriefingManager.exe")

$settings = [ordered]@{
    version = 1
    recipients = @()
    smtp = [ordered]@{
        host = "smtp.qq.com"
        port = 465
        user = ""
        auth_code = ""
    }
    llm_api = [ordered]@{
        base_url = ""
        api_key = ""
        model = ""
    }
    stocks = @()
}
$settingsJson = $settings | ConvertTo-Json -Depth 8
Set-Content -LiteralPath (Join-Path $PackageRoot "daily_briefing\data\service_settings.json") -Value $settingsJson -Encoding UTF8

$envExample = @'
# Optional advanced environment variables.
# Most users can configure API, email, recipients, and stocks in the app UI.

QQ_SMTP_HOST=smtp.qq.com
QQ_SMTP_PORT=465
QQ_SMTP_USER=
QQ_SMTP_AUTH_CODE=
QQ_SMTP_TO=

OPENAI_COMPATIBLE_BASE_URL=
OPENAI_COMPATIBLE_API_KEY=
OPENAI_COMPATIBLE_MODEL=
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "daily_briefing\.env.example") -Value $envExample -Encoding UTF8

$startBat = @'
@echo off
cd /d "%~dp0"
start "" "%~dp0AStockBriefingManager.exe"
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "StartManager.bat") -Value $startBat -Encoding ASCII

$installBat = @'
@echo off
cd /d "%~dp0"
"%~dp0AStockBriefingManager.exe" --install-tasks
if errorlevel 1 pause
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "InstallScheduledTasks.bat") -Value $installBat -Encoding ASCII

$readme = @'
AStockBriefingManager clean release

First use:
1. Double-click AStockBriefingManager.exe, or StartManager.bat.
2. Open Settings, fill your OpenAI-compatible Base URL and API Key, then test connection.
3. Choose a model from the model dropdown after connection succeeds.
4. Open recipients/email settings, fill SMTP sender settings and recipient addresses.
5. Open stocks, add your own stocks or holdings.
6. Use Schedule to manually preview/send reports.
7. Use Settings to check whether a newer release is available.
8. Use Service Status to install or enable scheduled tasks.

Notes:
- This package includes the Python runtime inside the EXE. Codex is not required.
- User settings are stored in daily_briefing\data\service_settings.json.
- Generated reports are stored in daily_briefing\data\reports.
- Logs are stored in daily_briefing\logs.
- This clean package contains no personal API key, email, recipients, or stock holdings.
- The reports are for research only and are not investment advice.
'@
Set-Content -LiteralPath (Join-Path $PackageRoot "README_FIRST_USE.txt") -Value $readme -Encoding UTF8

if (Test-Path $ZipPath) {
    Remove-Item -LiteralPath $ZipPath -Force
}
Compress-Archive -LiteralPath $PackageRoot -DestinationPath $ZipPath -Force

Write-Host "Clean release folder: $PackageRoot"
Write-Host "Clean release zip: $ZipPath"
