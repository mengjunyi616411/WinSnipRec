@echo off
chcp 65001 >nul
rem ============================================================
rem  截图工具 WinSnipRec - 一键安装到本机
rem  复制到 %LOCALAPPDATA%\Programs\WinSnipRec 并创建快捷方式
rem ============================================================
setlocal
cd /d "%~dp0"

if /i "%~1"=="uninstall" goto uninstall

if not exist "%~dp0dist\截图工具\截图工具.exe" (
    echo.
    echo  还没有打包好的程序，请先运行：
    echo      powershell -ExecutionPolicy Bypass -File build_exe.ps1
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install.ps1"
pause
exit /b 0

:uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install.ps1" -Uninstall
pause
exit /b 0
