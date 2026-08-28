# AStock Briefing Manager Banana Console Design

## Goal

Upgrade the Windows manager into a compact dark console for ordinary users who need to run daily A-share briefing, email, stock-watch, API, and schedule controls without opening Codex.

## Visual System

- Window background: `#0f1117`
- Panel background: `#171a21`
- Card background: `#1f2430`
- Primary accent: banana yellow `#ffd84d`
- Success: neon green `#2ee59d`
- Warning: amber `#ffb020`
- Danger: red-orange `#ff5c5c`
- Text: off-white `#f5f7fb`
- Muted text: cool gray `#98a2b3`

The interface should feel like a compact monitoring console rather than a marketing page. It should remain practical: readable tables, clear buttons, stable layouts, and obvious status labels.

## Required UI Changes

- Fix the Overview page by using a scrollable body and a two-column status-card grid.
- Keep the setup checklist and recent logs as full-width panels below the cards.
- Rename the `API` navigation item to `设置`.
- Make Settings compact: Base URL, API Key, Model, save/test actions, API status, and update check in one dense page.
- Add a manual `检测更新` action that checks the GitHub latest release and reports whether a newer version exists.
- Keep the close-window behavior: when background service is active, ask whether to minimize to taskbar, stop service and exit, or cancel.

## Data Safety

The UI and release package must not expose or bundle local personal data. API keys, SMTP auth codes, recipients, holdings, reports, and logs stay local to each user.

## Verification

Before release:

- Run unit tests.
- Run ruff for touched Python files.
- Compile the manager file.
- Build the EXE from the project `.venv`.
- Regenerate the clean release folder and zip.
- Smoke test the release EXE with `--once`.
