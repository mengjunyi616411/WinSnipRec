# 把你自己准备的 BGM 混到宣传片里（音效已内置在成片中）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File promo\video\混入BGM.ps1 -Music "D:\music\bgm.mp3"
#   powershell -ExecutionPolicy Bypass -File promo\video\混入BGM.ps1 -Music "bgm.wav" -Volume 0.18
#
# 说明：
#   * 原片的 UI 音效保留，BGM 以指定音量铺在下面并自动循环到片长
#   * 输出 promo\video\promo_1920x1080_30s_带BGM.mp4，视频流直接复制不重新编码
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Music,
    [double]$Volume = 0.22,
    [string]$Output
)

$ErrorActionPreference = 'Stop'
$videoDir = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $videoDir)
$source = Join-Path $videoDir 'promo_1920x1080_30s.mp4'

if (-not (Test-Path $source)) { throw "找不到成片：$source，请先运行 tools\make_promo_video.py" }
if (-not (Test-Path $Music)) { throw "找不到音乐文件：$Music" }
if (-not $Output) { $Output = Join-Path $videoDir 'promo_1920x1080_30s_带BGM.mp4' }

# 找 ffmpeg：优先虚拟环境，其次打包产物
$ffmpeg = Join-Path $root '.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
if (-not (Test-Path $ffmpeg)) {
    $found = Get-ChildItem -Path (Join-Path $root 'dist') -Recurse -Filter 'ffmpeg*.exe' -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($found) { $ffmpeg = $found.FullName }
}
if (-not (Test-Path $ffmpeg)) { throw '找不到 ffmpeg，请先运行 build_exe.ps1 或确认虚拟环境完整' }

Write-Host "成片  : $source"
Write-Host "音乐  : $Music  (音量 $Volume)"
Write-Host "输出  : $Output"
Write-Host "ffmpeg: $ffmpeg"

# [1:a] 音乐循环铺满片长并降音量，与原片音效混合；视频流 copy
$filter = "[1:a]volume=$Volume,aloop=loop=-1:size=2147483647[bgm];" +
          "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"

& $ffmpeg -hide_banner -loglevel error -y `
    -i $source -i $Music `
    -filter_complex $filter -map 0:v -map '[aout]' `
    -c:v copy -c:a aac -b:a 192k -shortest $Output

if ($LASTEXITCODE -ne 0) { throw "混音失败（ffmpeg 退出码 $LASTEXITCODE）" }

$size = [math]::Round((Get-Item $Output).Length / 1MB, 1)
Write-Host "完成：$Output  ($size MB)" -ForegroundColor Green
