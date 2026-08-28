@echo off
setlocal
cd /d "%~dp0"

where python.exe >nul 2>nul
if %errorlevel%==0 (
    python.exe "%~dp0tools\tradingagents_service_manager.py"
) else (
    where py.exe >nul 2>nul
    if %errorlevel%==0 (
        py.exe -3 "%~dp0tools\tradingagents_service_manager.py"
    ) else (
        echo Python was not found. Please install Python, then run this file again.
        pause
        exit /b 1
    )
)

if errorlevel 1 pause
