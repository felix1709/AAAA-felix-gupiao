# AStock Briefing Manager Sync And Release Workflow

## Purpose

This document is the standard workflow for updating, syncing, packaging, and publishing the Windows AStock Briefing Manager.

The goal is to keep source code versioned in GitHub while never publishing local user secrets, stock holdings, generated reports, logs, or build artifacts.

## Repository

- GitHub repository: `https://github.com/felix1709/AAAA-felix-gupiao.git`
- Primary source directory: `TradingAgents`
- Runtime sibling directory: `daily_briefing`
- Clean release output: `release/AStockBriefingManager-clean`
- Clean release zip: `release/AStockBriefingManager-clean.zip`

## Never Commit

Do not commit these items:

- `.env`
- `.venv/`
- `build/`
- `dist/`
- `release/`
- `AStockBriefingManager.exe`
- `daily_briefing/data/service_settings.json`
- `daily_briefing/data/reports/`
- `daily_briefing/logs/`
- personal stock analysis markdown files
- any API key, SMTP auth code, email recipient list, or holding data

## Update Flow

1. Edit source code and docs.
2. Add or update tests before production code when behavior changes.
3. Run verification:

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m pytest tests/test_service_manager.py tests/test_daily_briefing_settings.py -q
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m ruff check tools/tradingagents_service_manager.py tests/test_service_manager.py
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\python.exe' -m py_compile tools/tradingagents_service_manager.py
```

4. Build the Windows EXE with the project virtual environment:

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\.venv\Scripts\pyinstaller.exe' --noconfirm --clean --distpath 'C:\Users\admin\Documents\ChatGPT\A沪深' 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\AStockBriefingManager.spec'
```

5. Create the clean distributable folder and zip:

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\TradingAgents\tools\create_clean_release.ps1'
```

6. Smoke test the release EXE:

```powershell
& 'C:\Users\admin\Documents\ChatGPT\A沪深\release\AStockBriefingManager-clean\AStockBriefingManager.exe' --once
```

7. Review the Git diff and staged files. Confirm no private data is staged.
8. Commit source and docs.
9. Push to GitHub.
10. Publish the zip as the release asset when making a public version.

## Release Package Rules

The clean release package must contain:

- `AStockBriefingManager.exe`
- `StartManager.bat`
- `InstallScheduledTasks.bat`
- `README_FIRST_USE.txt`
- `daily_briefing/.env.example`
- `daily_briefing/data/service_settings.json` with empty recipients, empty API key, empty SMTP user, empty holdings
- empty log/report folders only

Each user must configure their own API, email, recipients, and stocks from the app UI.

## Update Check Behavior

The Settings page includes a manual update check. It checks the GitHub repository for the latest release tag and reads the release assets.

When a newer release includes `AStockBriefingManager-clean.zip`, the installed EXE enables `下载并安装`. The app downloads the zip, extracts it to a temporary folder, writes an updater PowerShell script, closes the current window, copies only safe package files, and relaunches the EXE. The updater must not overwrite `daily_briefing/data`, `daily_briefing/logs`, or `.env`, so each user's API key, email settings, recipients, watchlist, holdings, reports, and logs stay local.
