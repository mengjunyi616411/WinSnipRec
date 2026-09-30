# ============================================================================
#  WinSnipRec / 截图工具  -  PyInstaller 打包脚本
#
#  用法：
#     powershell -ExecutionPolicy Bypass -File build_exe.ps1            # 目录版（启动快）
#     powershell -ExecutionPolicy Bypass -File build_exe.ps1 -OneFile   # 单文件版
#
#  产物：dist\截图工具\截图工具.exe   或   dist\截图工具.exe
# ============================================================================
[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$SkipSmokeTest
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# ---- 1. 解释器 -------------------------------------------------------------
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    $venvPython = Join-Path (Split-Path $root -Parent) '.venv\Scripts\python.exe'
}
if (-not (Test-Path $venvPython)) {
    throw "找不到虚拟环境解释器（.venv\Scripts\python.exe）。请先: py -3 -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
}
Write-Host "Python: $venvPython"

# ---- 2. 依赖检查 -----------------------------------------------------------
Step '检查依赖'
& $venvPython -c "import PySide6, mss, imageio_ffmpeg, numpy, PyInstaller; print('deps ok')"
if ($LASTEXITCODE -ne 0) { throw '依赖不完整，请先 pip install -r requirements.txt' }

# ---- 3. 图标 ---------------------------------------------------------------
Step '生成应用图标'
& $venvPython tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw '图标生成失败' }
if (-not (Test-Path 'assets\app.ico')) { throw 'assets\app.ico 缺失' }

# ---- 4. ffmpeg -------------------------------------------------------------
Step '定位 ffmpeg'
$ffmpeg = (& $venvPython -c "import imageio_ffmpeg,sys; sys.stdout.write(imageio_ffmpeg.get_ffmpeg_exe())").Trim()
if (-not (Test-Path $ffmpeg)) {
    # PowerShell wraps long native-command output at the console width, which
    # corrupts paths containing spaces; fall back to reading it from a file.
    $ffTmp = Join-Path $env:TEMP 'winsnip_ffmpeg_path.txt'
    & $venvPython -c "import sys, imageio_ffmpeg; open(sys.argv[1], 'w', encoding='utf-8').write(imageio_ffmpeg.get_ffmpeg_exe())" $ffTmp
    $ffmpeg = (Get-Content -Raw -Encoding UTF8 $ffTmp).Trim()
}
if (-not (Test-Path $ffmpeg)) { throw "找不到 ffmpeg: $ffmpeg" }
Write-Host "ffmpeg: $ffmpeg"

# ---- 5. 自测 ---------------------------------------------------------------
if (-not $SkipSmokeTest) {
    Step '运行内核自测'
    & $venvPython tests\selftest_core.py
    if ($LASTEXITCODE -ne 0) { Write-Warning '内核自测未全部通过，仍继续打包' }
}

# ---- 6. PyInstaller --------------------------------------------------------
Step 'PyInstaller 打包'
$mode = if ($OneFile) { '--onefile' } else { '--onedir' }

$args = @(
    '--noconfirm', '--clean',
    '--name', '截图工具',
    '--icon', 'assets\app.ico',
    '--noconsole',
    $mode,
    '--add-data', 'assets;assets',
    # ffmpeg already comes in through pyinstaller-hooks-contrib's imageio_ffmpeg
    # hook; adding it again here would ship a second 84 MB copy.
    '--collect-submodules', 'winsnip',
    '--hidden-import', 'PySide6.QtSvg',
    '--exclude-module', 'tkinter',
    '--exclude-module', 'pandas',
    '--exclude-module', 'matplotlib',
    'app.py'
)
& $venvPython -m PyInstaller @args
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 失败' }

# ---- 7. 收尾 ---------------------------------------------------------------
Step '整理产物'
$exeDir = Join-Path $root 'dist\截图工具'
$exe    = Join-Path $exeDir '截图工具.exe'
if ($OneFile) {
    $exe = Join-Path $root 'dist\截图工具.exe'
}
if (-not (Test-Path $exe)) { throw "未找到产物 $exe" }

Copy-Item -Force 'README.md' (Join-Path (Split-Path $exe -Parent) 'README.md')
$size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "`n完成: $exe  ($size MB)" -ForegroundColor Green
if (-not $OneFile) {
    $total = (Get-ChildItem $exeDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
    Write-Host ("整包大小: {0:N1} MB" -f $total) -ForegroundColor Green
}

# ---- 8. 冒烟测试 -----------------------------------------------------------
if (-not $SkipSmokeTest) {
    Step '冒烟测试（启动 6 秒后关闭）'
    $proc = Start-Process -FilePath $exe -ArgumentList '--tray' -PassThru
    Start-Sleep -Seconds 6
    if ($proc.HasExited) {
        Write-Warning "程序提前退出，退出码 $($proc.ExitCode)；请查看 %APPDATA%\WinSnipRec\app.log"
    } else {
        Write-Host '程序已启动并驻留托盘，测试通过' -ForegroundColor Green
        Stop-Process -Id $proc.Id -Force
        Start-Sleep -Milliseconds 500
        Get-Process -Name '截图工具' -ErrorAction SilentlyContinue | Stop-Process -Force
    }
}
Write-Host "`n打包结束。" -ForegroundColor Green
