@echo off
rem ============================================================
rem  Restart WinSnipRec: stop any old instance, then start the
rem  freshly installed build.
rem
rem  The app has a single-instance guard. If an old copy is still
rem  running, launching again only shows "already running" and you
rem  keep clicking in the OLD window -- so changes look like they
rem  did nothing.
rem
rem  NOTE: keep this file ASCII-only. cmd parses a .bat with the
rem  code page active when it started, so any non-ASCII byte here
rem  (even inside a path) gets executed as a command. The exe name
rem  is non-ASCII, so it is resolved through a wildcard at runtime
rem  instead of being written into this file.
rem ============================================================
chcp 65001 >nul
setlocal

set "DIR=%LOCALAPPDATA%\Programs\WinSnipRec"
set "APP="
for %%F in ("%DIR%\*.exe") do set "APP=%%~fF"

echo.
echo Stopping any running copy...
powershell -NoProfile -Command "Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*\WinSnipRec\*.exe' } | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1
timeout /t 1 /nobreak >nul

if not defined APP (
    echo Installed build not found under:
    echo   %DIR%
    echo.
    pause
    exit /b 1
)

for %%F in ("%APP%") do echo Starting build dated %%~tF
start "" "%APP%"
echo.
echo Started. Look for the tray icon.
timeout /t 2 /nobreak >nul
endlocal
