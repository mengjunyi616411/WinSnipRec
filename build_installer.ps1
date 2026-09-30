# 打包 Windows 安装包（Inno Setup）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1 -SkipAppBuild   # 复用现有 dist
#
# 产物：dist\installer\WinSnipRec-Setup-<版本>.exe
#
# 依赖：
#   1. 主程序已打包（dist\截图工具\）—— 本脚本默认会自动先跑 build_exe.ps1
#   2. Inno Setup 6（命令行编译器 ISCC.exe）
#         winget install --id JRSoftware.InnoSetup -e
#
# 说明：中文安装界面用的是社区翻译文件 tools\innosetup\ChineseSimplified.isl
#       （来自 https://github.com/kira-96/Inno-Setup-Chinese-Simplified-Translation）。
#       该文件不随仓库分发，缺失时本脚本会自动下载；下载不到就退回英文界面。

[CmdletBinding()]
param(
    [switch]$SkipAppBuild,
    [string]$Version
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

function Step([string]$text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

# ---------------------------------------------------------------- 版本号
if (-not $Version) {
    $init = Join-Path $root 'winsnip\__init__.py'
    $match = Select-String -Path $init -Pattern '__version__\s*=\s*"([^"]+)"'
    if (-not $match) { throw "无法从 $init 读取 __version__" }
    $Version = $match.Matches[0].Groups[1].Value
}
Write-Host "版本: $Version"

# ---------------------------------------------------------------- 主程序
$appDir = Join-Path $root 'dist\截图工具'
if ($SkipAppBuild) {
    if (-not (Test-Path (Join-Path $appDir '截图工具.exe'))) {
        throw "找不到 $appDir\截图工具.exe，去掉 -SkipAppBuild 让脚本先打包主程序"
    }
    Write-Host "跳过主程序打包，复用现有 dist"
} else {
    Step '打包主程序'
    & powershell -ExecutionPolicy Bypass -File (Join-Path $root 'build_exe.ps1') -SkipSmokeTest
    if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 失败（退出码 $LASTEXITCODE）" }
}

# ---------------------------------------------------------------- Inno Setup
Step '定位 Inno Setup'
$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }
}
if (-not $iscc) {
    throw "找不到 ISCC.exe。请先安装 Inno Setup 6：winget install --id JRSoftware.InnoSetup -e"
}
Write-Host "ISCC: $iscc"

# ---------------------------------------------------------------- 中文语言文件
$islDir = Join-Path $root 'tools\innosetup'
$isl = Join-Path $islDir 'ChineseSimplified.isl'
if (-not (Test-Path $isl)) {
    Step '下载简体中文语言文件'
    New-Item -ItemType Directory -Force -Path $islDir | Out-Null
    $url = 'https://raw.githubusercontent.com/kira-96/Inno-Setup-Chinese-Simplified-Translation/master/ChineseSimplified.isl'
    try {
        Invoke-WebRequest -Uri $url -OutFile $isl -TimeoutSec 30 -UseBasicParsing
        $bytes = [System.IO.File]::ReadAllBytes($isl)
        if (-not ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)) {
            $text = [System.IO.File]::ReadAllText($isl, [System.Text.Encoding]::UTF8)
            [System.IO.File]::WriteAllText($isl, $text, (New-Object System.Text.UTF8Encoding($true)))
        }
        Write-Host "已下载（$([math]::Round($bytes.Length / 1KB, 1)) KB）"
    } catch {
        Write-Warning "下载失败，安装界面将使用英文：$($_.Exception.Message)"
    }
}
$hasChinese = Test-Path $isl
if (-not $hasChinese) {
    # 让 .iss 里的 chinesesimplified 段失效而不报错
    Write-Warning '没有中文语言文件，改用英文界面'
}

# ---------------------------------------------------------------- 编译
Step '编译安装包'
$iss = Join-Path $root 'tools\installer.iss'
$args = @($iss, "/DAppVersion=$Version")
if (-not $hasChinese) { $args += '/DNoChinese=1' }
& $iscc @args
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败（退出码 $LASTEXITCODE）" }

# ---------------------------------------------------------------- 结果
$out = Join-Path $root "dist\installer\WinSnipRec-Setup-$Version.exe"
if (-not (Test-Path $out)) { throw "没有生成 $out" }

$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
$hash = (Get-FileHash $out -Algorithm SHA256).Hash
Step '完成'
Write-Host "安装包: $out" -ForegroundColor Green
Write-Host "体积  : $size MB"
Write-Host "SHA256: $hash"
