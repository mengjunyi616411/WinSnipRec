@echo off
chcp 65001 >nul
rem ============================================================
rem  WinSnipRec / 截图工具  -  launcher
rem  Prefers a local .venv, then a venv in the parent folder,
rem  then the system Python.
rem ============================================================
setlocal
cd /d "%~dp0"

set "PYW="
if exist "%~dp0.venv\Scripts\pythonw.exe" set "PYW=%~dp0.venv\Scripts\pythonw.exe"
if not defined PYW if exist "%~dp0..\.venv\Scripts\pythonw.exe" set "PYW=%~dp0..\.venv\Scripts\pythonw.exe"
if not defined PYW if exist "%~dp0venv\Scripts\pythonw.exe" set "PYW=%~dp0venv\Scripts\pythonw.exe"

if defined PYW (
    start "" "%PYW%" "%~dp0app.py" %*
    exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 "%~dp0app.py" %*
    exit /b 0
)

where python >nul 2>nul
if %errorlevel%==0 (
    start "" python "%~dp0app.py" %*
    exit /b 0
)

echo.
echo  没有找到 Python 运行环境。
echo  请先执行： py -3 -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
echo  或直接运行打包好的 dist\截图工具.exe
echo.
pause
exit /b 1
