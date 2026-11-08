; WinSnipRec 安装包脚本（Inno Setup 6）
;
; 由 build_installer.ps1 调用，通常不用手工执行：
;   ISCC.exe /DAppVersion=<版本号> tools\installer.iss   （build_installer.ps1 会自动填）
;
; 设计取舍：
;   * 按用户安装（{localappdata}\Programs），全程不需要管理员权限，
;     和「安装到本机.bat」的行为一致；要装到 Program Files 就把
;     PrivilegesRequired 改成 admin 并把 DefaultDirName 换成 {autopf}。
;   * 目录页和程序组页都关掉：这是单目录免安装式程序，问用户装哪儿没有意义。

#define AppName        "截图工具 WinSnipRec"
#define AppShortName   "截图工具"
#define AppExeName     "截图工具.exe"
#define AppPublisher   "WinSnipRec contributors"
#define AppUrl         "https://github.com/mengjunyi616411/WinSnipRec"
#ifndef AppVersion
  #define AppVersion "1.4.2"
#endif
#define SourceDir      "..\dist\截图工具"

[Setup]
AppId={{8F3C1A64-5B2E-4C7D-9A18-2D6E7F0B4C31}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} 安装程序

DefaultDirName={localappdata}\Programs\WinSnipRec
DefaultGroupName={#AppShortName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest

OutputDir=..\dist\installer
OutputBaseFilename=WinSnipRec-Setup-{#AppVersion}
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

; 用户问过打包能不能更快。lzma2/max 在 205MB 的 dist 上要压 4 分钟，
; lzma2/normal 快得多，安装包只大几 MB。
Compression=lzma2/fast
; 用户问过打包能不能更快：solid 会把所有文件压成一个流，速度最慢。
SolidCompression=no
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes
ShowLanguageDialog=auto

[Languages]
; 中文语言文件是社区翻译（见 build_installer.ps1 注释），缺失时脚本会传 /DNoChinese=1
#ifdef NoChinese
Name: "english"; MessagesFile: "compiler:Default.isl"
#else
Name: "chinesesimplified"; MessagesFile: "innosetup\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "开机自动启动（登录后静默进入通知区域）"; GroupDescription: "启动选项："; Flags: unchecked

[Files]
; 整目录打包：主程序 + _internal（Python 运行时、Qt、ffmpeg 都在里面）
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,{#AppShortName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppShortName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; 勾了「开机自动启动」就写 Run 项；值带 --tray，登录后静默进托盘
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "WinSnipRec"; \
    ValueData: """{app}\{#AppExeName}"" --tray"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppShortName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallRun]
; 程序运行中也可能自己写入这个启动项，所以卸载时无条件删掉，避免留下死路径
Filename: "{cmd}"; Parameters: "/c reg delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v WinSnipRec /f"; \
    Flags: runhidden; RunOnceId: "RemoveAutostart"

[UninstallDelete]
; 只清理安装目录里的残留；用户配置 %APPDATA%\WinSnipRec 保留，方便重装后接着用
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
Type: files; Name: "{app}\selftest_record.txt"
Type: files; Name: "{app}\*.log"
Type: dirifempty; Name: "{app}"
