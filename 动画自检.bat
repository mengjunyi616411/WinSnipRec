@echo off
rem ============================================================
rem  Minimize-animation self-check
rem
rem  Reports this machine's animation capabilities and then really
rem  minimizes a window to show whether the native Windows animation
rem  or the self-drawn fallback was used.
rem
rem  NOTE: keep this file ASCII-only. cmd parses a .bat with the code
rem  page that was active when it started, so UTF-8 Chinese comments
rem  get executed as commands. All Chinese output comes from Python.
rem ============================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo.
echo Running self-check, please wait...
echo (a window will appear briefly and get minimized)
echo.
"%PY%" -u "%~dp0app.py" --selftest-minimize

echo.
echo Done.
pause
endlocal
