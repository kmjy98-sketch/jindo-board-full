@echo off
chcp 65001 >nul
rem === Jindo board server (visible window). Keep this window OPEN. ===
cd /d "%~dp0"
set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" board_server_v2.py
echo.
echo [server stopped] press any key to close this window.
pause >nul
