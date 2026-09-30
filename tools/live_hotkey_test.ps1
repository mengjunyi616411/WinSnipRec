Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KB {
  [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, IntPtr extra);
  public static void KeyDown(byte vk) { keybd_event(vk, 0, 0, IntPtr.Zero); }
  public static void KeyUp(byte vk)   { keybd_event(vk, 0, 0x0002, IntPtr.Zero); }
}
"@
Add-Type -AssemblyName System.Windows.Forms,System.Drawing

$root = Split-Path $PSScriptRoot -Parent          # ...\WinSnipRec
$workspace = Split-Path $root -Parent             # ...\<workspace> (holds .venv)
$shots = Join-Path $root "docs\screenshots"
New-Item -ItemType Directory -Force -Path $shots | Out-Null

function Shot($name) {
  $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
  $g.Dispose()
  $bmp.Save((Join-Path $shots "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Host "  shot: $name"
}

function Send-Hotkey($spec) {
  $mods = @()
  $vk = $null
  foreach ($part in ($spec -replace '-', '+' -split '\+')) {
    $p = $part.Trim()
    switch ($p.ToLower()) {
      'ctrl'      { $mods += 0x11 }
      'control'   { $mods += 0x11 }
      'alt'       { $mods += 0x12 }
      'shift'     { $mods += 0x10 }
      'win'       { $mods += 0x5B }
      default     { if ($p.Length -eq 1) { $vk = [byte][char]$p.ToUpper() } }
    }
  }
  if ($null -eq $vk) { throw "cannot parse hotkey '$spec'" }
  Write-Host "  injecting $spec (vk=0x$('{0:X2}' -f $vk))"
  foreach ($m in $mods) { [KB]::KeyDown([byte]$m); Start-Sleep -Milliseconds 40 }
  [KB]::KeyDown($vk); Start-Sleep -Milliseconds 80
  [KB]::KeyUp($vk)
  foreach ($m in ($mods | Sort-Object -Descending)) { [KB]::KeyUp([byte]$m) }
  Start-Sleep -Milliseconds 200
}

$vpy = $null
$vpy = $env:WINSNIPREC_TEST_EXE
if (-not ($vpy -and (Test-Path $vpy))) {
  $vpy = $null
  foreach ($candidate in @(
      (Join-Path $workspace ".venv\Scripts\pythonw.exe"),
      (Join-Path $root ".venv\Scripts\pythonw.exe"),
      (Join-Path $root "venv\Scripts\pythonw.exe"))) {
    if (Test-Path $candidate) { $vpy = $candidate; break }
  }
}
if (-not $vpy) { throw "venv pythonw not found (searched $workspace\.venv and $root\.venv)" }
Write-Host "using: $vpy"

$launchArgs = @("app.py")
if ((Split-Path $vpy -Leaf) -ne "pythonw.exe") {
  $launchArgs = @()
  Write-Host "mode: packaged executable"
}

Get-Process -Name python,pythonw,"截图工具" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\WinSnipRec\settings.json" -Force -ErrorAction SilentlyContinue
Remove-Item "$env:APPDATA\WinSnipRec\app.log" -Force -ErrorAction SilentlyContinue

$proc = Start-Process -FilePath $vpy -ArgumentList $launchArgs -WorkingDirectory $root -PassThru
Write-Host "launched pid=$($proc.Id)"
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 500
  $log = Get-Content "$env:APPDATA\WinSnipRec\app.log" -ErrorAction SilentlyContinue
  if ($log -match 'ready') { break }
}
Write-Host "=== startup log ==="
Get-Content "$env:APPDATA\WinSnipRec\app.log" -ErrorAction SilentlyContinue

$settingsPath = "$env:APPDATA\WinSnipRec\settings.json"
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 500
  $log = Get-Content "$env:APPDATA\WinSnipRec\app.log" -ErrorAction SilentlyContinue
  if ($log -match 'hotkey') { break }
}
Write-Host "=== startup log ==="
Get-Content "$env:APPDATA\WinSnipRec\app.log" -ErrorAction SilentlyContinue

$snipKey = "Ctrl+Alt+S"
$recKey = "Ctrl+Alt+R"
if (Test-Path $settingsPath) {
  $settings = Get-Content -Raw $settingsPath -Encoding UTF8 | ConvertFrom-Json
  if ($settings.hotkey_snip) { $snipKey = $settings.hotkey_snip }
  if ($settings.hotkey_record) { $recKey = $settings.hotkey_record }
}
Write-Host "effective hotkeys: snip=$snipKey record=$recKey"

Write-Host "`n--- 1. press the SNIP hotkey ---"
Shot "live_before_hotkey"
Send-Hotkey $snipKey
Start-Sleep -Seconds 2
Shot "live_after_snip_hotkey"

Write-Host "`n--- 2. cancel with Esc ---"
[KB]::KeyDown(0x1B); Start-Sleep -Milliseconds 60; [KB]::KeyUp(0x1B)
Start-Sleep -Seconds 1

Write-Host "`n--- 3. press the RECORD hotkey ---"
Send-Hotkey $recKey
Start-Sleep -Seconds 2
Shot "live_after_record_hotkey"

Write-Host "`n--- 4. drag a region to start recording ---"
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class MS {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, int d, IntPtr e);
  public const uint LD = 0x0002, LU = 0x0004;
  public static void Drag(int x1,int y1,int x2,int y2){
    SetCursorPos(x1,y1); System.Threading.Thread.Sleep(200);
    mouse_event(LD,0,0,0,IntPtr.Zero); System.Threading.Thread.Sleep(200);
    for(int i=1;i<=15;i++){ SetCursorPos(x1+(x2-x1)*i/15, y1+(y2-y1)*i/15); System.Threading.Thread.Sleep(25); }
    System.Threading.Thread.Sleep(200); mouse_event(LU,0,0,0,IntPtr.Zero);
  }
}
"@
[MS]::Drag(300, 300, 1100, 750)
Start-Sleep -Seconds 3
Shot "live_recording_bar"

Write-Host "`n--- 5. press the record hotkey again (should be ignored while recording) ---"
Send-Hotkey $recKey
Start-Sleep -Seconds 1
Shot "live_recording_still"

Write-Host "`n--- 6. stop the recording with its own hotkey (Ctrl+Alt+Q) ---"
Send-Hotkey "Ctrl+Alt+Q"
Start-Sleep -Seconds 6
Shot "live_after_stop"

Write-Host "`n=== app.log tail ==="
Get-Content "$env:APPDATA\WinSnipRec\app.log" -ErrorAction SilentlyContinue | Select-Object -Last 12
Write-Host "`n=== produced recordings ==="
$videoDir = (Get-Content -Raw "$env:APPDATA\WinSnipRec\settings.json" -Encoding UTF8 | ConvertFrom-Json).video_dir
Write-Host "video_dir: $videoDir"
Get-ChildItem $videoDir -Filter "屏幕录制 *.mp4" -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, Length, LastWriteTime | Format-Table -AutoSize
Write-Host "`nprocess alive: $(-not $proc.HasExited)"
