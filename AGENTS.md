# AStock Briefing Manager Codex Memory

## Language And Collaboration

- Default to Chinese when explaining work to the user.
- The user is a programming beginner, so explain changes in small, concrete steps.
- When changing code, explain what changed, why it changed, and how to verify it.

## Submit And Publish Rule

When the user says "提交发布", "提交&发布", "发布", "同步发布", or asks to ship a new app version:

0. First read `fabu.MD` in the project root and follow it as the concrete release checklist for AStock Briefing Manager. If `fabu.MD` and this section differ, stop and explain the difference before publishing.
1. Treat this as a request to commit source changes, push them to GitHub, and publish a distributable zip when appropriate.
2. Verify the current folder is a Git repository with `git rev-parse --show-toplevel`.
3. If the folder is not a Git repository, do not initialize or rewrite Git history automatically. Stop the Git commit/push part and clearly tell the user that `.git` is missing.
4. Configure or verify the preferred identity:
   - `user.name`: `felix1709`
   - `user.email`: `331631382@qq.com`
5. Never commit local secrets, user settings, generated reports, logs, built EXE files, or release zip files.
6. Run fresh verification before committing or publishing:
   - `pytest tests/test_service_manager.py tests/test_daily_briefing_settings.py -q`
   - `ruff check tools/tradingagents_service_manager.py tests/test_service_manager.py`
   - `py_compile tools/tradingagents_service_manager.py`
   - PyInstaller build
   - clean release package generation
   - release EXE smoke test with `--once`
7. Commit only the files related to the current change. Do not use `git add .` when unrelated local edits exist.
8. Push to `https://github.com/felix1709/AAAA-felix-gupiao.git`.
9. Create a GitHub Release tag matching the manager app version, for example `v0.2.0`, and upload `AStockBriefingManager-clean.zip`.
10. Never use `git push --force` unless the user explicitly asks for it.

## Release Update Rule

- A release is not complete if the installed app cannot detect the latest GitHub Release.
- Every release must verify:
  - the GitHub Release tag matches `APP_VERSION` in `tools/tradingagents_service_manager.py`,
  - the clean zip asset is attached to the release,
  - the clean package contains no personal API key, SMTP auth code, email recipients, stock watchlist, holding data, generated reports, or logs,
  - the app can launch in smoke-test mode from the clean package.
- The app checks GitHub Releases from the Settings page. When a newer release has `AStockBriefingManager-clean.zip`, the installed EXE can download and install it automatically while preserving each user's local settings, reports, and logs.

## Local Data Boundary

These files belong to the local user and must not be committed or published:

- `../daily_briefing/data/service_settings.json`
- `../daily_briefing/data/monitor_state.json`
- `../daily_briefing/data/reports/`
- `../daily_briefing/logs/`
- `.env`
- `.venv/`
- `dist/`
- `build/`
- `release/`
- `AStockBriefingManager.exe`
