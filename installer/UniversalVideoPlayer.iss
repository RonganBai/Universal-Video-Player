; 万能视频播放器 安装包脚本（Inno Setup 6）
; 构建：先运行 build.ps1 生成 dist\万能视频播放器，再由本脚本打包成单个安装程序

#define AppName "万能视频播放器"
#define AppVersion "1.1.2"
#define AppPublisher "RonganBai"
#define AppURL "https://github.com/RonganBai/Universal-Video-Player"
#define AppExe "万能视频播放器.exe"
#define ProgId "UniversalVideoPlayer.Media"
; 打包来源目录，可用 ISCC /DDistDir=... 覆盖
#ifndef DistDir
  #define DistDir "..\dist\万能视频播放器"
#endif

[Setup]
AppId={{6E7A1F3C-9B54-4C1E-A7D2-3F8B5C2E9A41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; 默认装到 Program Files（需要管理员）；安装时也可选择「仅为我安装」
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=Output
OutputBaseFilename=UniversalVideoPlayer-Setup-{#AppVersion}
SetupIconFile=..\assets\logo.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ChangesAssociations=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} 安装程序

[Languages]
Name: "default"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
default.TaskDesktop=创建桌面快捷方式
default.TaskAssoc=注册为视频播放器（出现在「打开方式」和「默认应用」中）
default.GroupExtra=附加选项：
default.LaunchApp=立即运行 万能视频播放器
default.OpenDefaults=打开「默认应用」设置，将其设为默认播放器

[Tasks]
Name: "desktopicon"; Description: "{cm:TaskDesktop}"; GroupDescription: "{cm:GroupExtra}"
Name: "fileassoc"; Description: "{cm:TaskAssoc}"; GroupDescription: "{cm:GroupExtra}"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 程序标识（ProgId）：双击媒体文件时用本程序打开
Root: HKA; Subkey: "Software\Classes\{#ProgId}"; ValueType: string; ValueName: ""; ValueData: "媒体文件 - {#AppName}"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"",0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\{#ProgId}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: fileassoc
; 「默认应用」设置页里的登记
Root: HKA; Subkey: "Software\Clients\Media\UniversalVideoPlayer"; ValueType: string; ValueName: ""; ValueData: "{#AppName}"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Clients\Media\UniversalVideoPlayer\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#AppName}"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Clients\Media\UniversalVideoPlayer\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "原画直出的全格式视频播放器"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Clients\Media\UniversalVideoPlayer\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "UniversalVideoPlayer"; ValueData: "Software\Clients\Media\UniversalVideoPlayer\Capabilities"; Flags: uninsdeletevalue; Tasks: fileassoc
; 每种格式
#include "extensions.iss"

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
Filename: "ms-settings:defaultapps"; Description: "{cm:OpenDefaults}"; Flags: shellexec nowait postinstall skipifsilent unchecked; Tasks: fileassoc

[UninstallDelete]
; 缩略图缓存
Type: filesandordirs; Name: "{localappdata}\{#AppName}\thumbs"
Type: dirifempty; Name: "{localappdata}\{#AppName}"
