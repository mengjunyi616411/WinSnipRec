# ============================================================================
#  WinSnipRec / 截图工具  -  安装到本机
#
#  把 dist\截图工具 复制到 %LOCALAPPDATA%\Programs\WinSnipRec，
#  并在桌面和开始菜单创建快捷方式（无需管理员权限）。
#
#  用法：powershell -ExecutionPolicy Bypass -File tools\install.ps1
# ============================================================================
[CmdletBinding()]
param(
    [string]$Source,
    [switch]$Uninstall,
    [switch]$NoShortcuts,
    [switch]$Autostart
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

$target = Join-Path $env:LOCALAPPDATA 'Programs\WinSnipRec'
$exeName = '截图工具.exe'
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')
$shortcutName = '截图工具 WinSnipRec.lnk'

function Remove-Shortcuts {
    foreach ($dir in @($desktop, $programs)) {
        $path = Join-Path $dir $shortcutName
        if (Test-Path $path) { Remove-Item $path -Force; Write-Host "已删除 $path" }
    }
}

function Remove-Autostart {
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    $value = (Get-ItemProperty -Path $runKey -Name 'WinSnipRec' -ErrorAction SilentlyContinue).WinSnipRec
    if ($value) {
        Remove-ItemProperty -Path $runKey -Name 'WinSnipRec' -ErrorAction SilentlyContinue
        Write-Host "已移除开机自启项：$value"
    }
}

if ($Uninstall) {
    Step '卸载'
    Remove-Shortcuts
    Remove-Autostart
    if (Test-Path $target) { Remove-Item $target -Recurse -Force; Write-Host "已删除 $target" }
    Write-Host '卸载完成（用户配置保留在 %APPDATA%\WinSnipRec）' -ForegroundColor Green
    exit 0
}

if (-not $Source) { $Source = Join-Path $root 'dist\截图工具' }
if (-not (Test-Path (Join-Path $Source $exeName))) {
    throw "找不到 $exeName。请先执行： powershell -ExecutionPolicy Bypass -File build_exe.ps1"
}

Step "复制到 $target"
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item -Path (Join-Path $Source '*') -Destination $target -Recurse -Force
Write-Host '复制完成'

$exe = Join-Path $target $exeName

if (-not $NoShortcuts) {
    Step '创建快捷方式'
    $shell = New-Object -ComObject WScript.Shell
    foreach ($dir in @($desktop, $programs)) {
        if (-not (Test-Path $dir)) { continue }
        $link = Join-Path $dir $shortcutName
        $shortcut = $shell.CreateShortcut($link)
        $shortcut.TargetPath = $exe
        $shortcut.WorkingDirectory = $target
        $shortcut.IconLocation = "$exe,0"
        $shortcut.Description = '在 Windows 10 上使用 Windows 11 截图工具同款界面录屏'
        $shortcut.Save()
        Write-Host "已创建 $link"
    }
}

if ($Autostart) {
    Step '注册开机自动启动'
    $runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (-not (Test-Path $runKey)) { New-Item -Path $runKey -Force | Out-Null }
    Set-ItemProperty -Path $runKey -Name 'WinSnipRec' -Value "`"$exe`" --tray"
    Write-Host "已注册：`"$exe`" --tray" -ForegroundColor Green
}

Step '启动测试'
$proc = Start-Process -FilePath $exe -ArgumentList '--tray' -PassThru
Start-Sleep -Seconds 5
if ($proc.HasExited) {
    Write-Warning "程序提前退出（退出码 $($proc.ExitCode)），请查看 %APPDATA%\WinSnipRec\app.log"
} else {
    Write-Host '程序已启动并驻留在通知区域' -ForegroundColor Green
    $proc | Stop-Process -Force
    Get-Process -Name '截图工具' -ErrorAction SilentlyContinue | Stop-Process -Force
}

Write-Host "`n安装完成：$exe" -ForegroundColor Green
Write-Host '卸载： powershell -ExecutionPolicy Bypass -File tools\install.ps1 -Uninstall'
