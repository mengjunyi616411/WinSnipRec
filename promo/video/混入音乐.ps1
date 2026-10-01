# 给 1.1.0 更新宣传片混入音乐（例如 Watch Me Work）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File promo\video\混入音乐.ps1 -Music "D:\music\Watch Me Work.mp3"
#   powershell -ExecutionPolicy Bypass -File promo\video\混入音乐.ps1 -Music "bgm.m4a" -Volume 0.4 -Offset 32
#
# 参数：
#   -Music    音乐文件（mp3 / m4a / wav / flac 都行，ffmpeg 能解就行）
#   -Volume   音乐音量，默认 0.35（片里已经有 UI 音效，音乐铺在下面）
#   -Offset   从音乐的第几秒开始用，默认 0（想直接进副歌/主歌就填，例如 32）
#   -FadeOut  结尾淡出秒数，默认 1.5
#   -Video    要配的片子，默认 promo\video\update_1920x1080_30s.mp4
#   -Output   输出文件，默认 <片子名>_配乐.mp4
#
# 说明：
#   * 视频流直接复制，不重新编码，几秒钟就完成
#   * 音乐短于片长会自动循环；长于片长自动裁掉
#   * 音乐做了响度归一，压到 -18 LUFS 再混，避免盖住 UI 音效
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Music,
    [double]$Volume = 0.35,
    [double]$Offset = 0.0,
    [double]$FadeOut = 1.5,
    [string]$Video,
    [string]$Output
)

$ErrorActionPreference = 'Stop'

$videoDir = $PSScriptRoot
$root = Split-Path -Parent (Split-Path -Parent $videoDir)

if (-not $Video) { $Video = Join-Path $videoDir 'update_1920x1080_30s.mp4' }
if (-not (Test-Path $Video)) {
    throw "找不到片子：$Video`n请先运行: .venv\Scripts\python.exe tools\make_update_video.py"
}
if (-not (Test-Path $Music)) {
    throw "找不到音乐文件：$Music`n（本仓库不附带任何商业音乐，请提供你自己的文件）"
}
if (-not $Output) {
    $base = [System.IO.Path]::GetFileNameWithoutExtension($Video)
    $Output = Join-Path $videoDir "$base`_配乐.mp4"
}

# 找 ffmpeg：优先虚拟环境，其次打包产物
$ffmpeg = Join-Path $root '.venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
if (-not (Test-Path $ffmpeg)) {
    $found = Get-ChildItem -Path (Join-Path $root 'dist') -Recurse -Filter 'ffmpeg*.exe' -ErrorAction SilentlyContinue |
             Select-Object -First 1
    if ($found) { $ffmpeg = $found.FullName }
}
if (-not (Test-Path $ffmpeg)) { throw '找不到 ffmpeg，请确认虚拟环境完整（pip install imageio-ffmpeg）' }

# 片长（用 ffprobe 没有就退回默认 30 秒）
$duration = 30.0
$ffprobe = Join-Path (Split-Path -Parent $ffmpeg) 'ffprobe.exe'
if (Test-Path $ffprobe) {
    $measured = & $ffprobe -v error -show_entries format=duration -of csv=p=0 $Video
    if ($measured -and [double]::TryParse($measured.Trim(), [ref]$null)) { $duration = [double]$measured.Trim() }
}
$fadeStart = [Math]::Max(0.0, $duration - $FadeOut)

Write-Host "片子    : $Video"
Write-Host "片长    : $([Math]::Round($duration, 2)) s"
Write-Host "音乐    : $Music"
Write-Host "音量    : $Volume  起点: ${Offset}s  淡出: ${FadeOut}s"
Write-Host "输出    : $Output"
Write-Host "ffmpeg  : $ffmpeg"
Write-Host ""

# [0:a] 片内 UI 音效；[1:a] 音乐先裁起点、循环铺满、降音量、响度归一、结尾淡出
$filter = "[1:a]atrim=start=$Offset,asetpts=PTS-STARTPTS," +
          "loudnorm=I=-18:TP=-1.5:LRA=11," +
          "volume=$Volume," +
          "afade=t=out:st=$fadeStart`:d=$FadeOut[bgm];" +
          "[0:a][bgm]amix=inputs=2:duration=first:normalize=0[out]"

$args = @(
    '-hide_banner', '-loglevel', 'error', '-y',
    '-i', $Video,
    '-stream_loop', '-1', '-i', $Music,
    '-filter_complex', $filter,
    '-map', '0:v', '-map', '[out]',
    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
    '-movflags', '+faststart',
    '-shortest',
    $Output
)

& $ffmpeg @args
if ($LASTEXITCODE -ne 0) { throw "ffmpeg 混音失败（退出码 $LASTEXITCODE）" }

$size = (Get-Item $Output).Length / 1MB
Write-Host ""
Write-Host "完成：$Output  ($([Math]::Round($size, 1)) MB)"
