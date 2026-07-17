; ══════════════════════════════════════════════════════════════════════════
;  Koto — Windows 安装向导脚本 (Inno Setup 6)
;
;  本地手动构建：
;    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 koto_installer.iss
;    （管理员安装时路径为："C:\Program Files (x86)\Inno Setup 6\ISCC.exe"）
;
;  输出：dist\Koto_v{version}_Setup.exe
; ══════════════════════════════════════════════════════════════════════════

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif

#define AppName      "Koto"
#define AppPublisher "Loganwon"
#define AppURL       "https://github.com/Loganwon/Koto"
#define AppExeName   "Koto.exe"
#define SourceDir    "dist\Koto_Portable"
#define WebView2Installer "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"

[Setup]
; ── AppId 必须固定，Inno Setup 用它识别"同一个程序"以支持升级覆盖安装 ──
; ── 不要修改此值 ──────────────────────────────────────────────────────
AppId={{A3F8E291-7C44-4B2A-9D6E-8C5F1A347B90}

AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases

; ── 安装目录（用户本地 AppData，无需管理员权限）─────────────────────
DefaultDirName={localappdata}\{#AppName}
DisableDirPage=no
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

; ── 开始菜单（单个分组，无子菜单）──────────────────────────────────
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes

; ── 输出 ────────────────────────────────────────────────────────────
OutputDir=dist
OutputBaseFilename=Koto_v{#AppVersion}_Setup
SetupIconFile=src\assets\koto_icon.ico

; ── 压缩（生成更小的单文件安装包）──────────────────────────────────
Compression=lzma2/ultra64
SolidCompression=yes

; ── 外观 ────────────────────────────────────────────────────────────
WizardStyle=modern
WizardSizePercent=110

; ── Windows 文件属性 ─────────────────────────────────────────────────
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=Koto AI 助手安装程序
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoCopyright=Copyright (C) 2026 {#AppPublisher}

; ── 卸载 ────────────────────────────────────────────────────────────
RestartIfNeededByRun=no
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} v{#AppVersion}

; ── 升级时自动关闭正在运行的实例 ───────────────────────────────────
CloseApplications=yes
CloseApplicationsFilter=Koto.exe

[Languages]
; ChineseSimplified.isl 放在 build\ 目录，本地和 CI 均可引用，无需依赖系统语言包
Name: "chinesesimp"; MessagesFile: "build\ChineseSimplified.isl"
Name: "english";     MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建 Koto 快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "localmodel"; Description: "安装本地 AI 模型助手（可选，加速离线任务分类，需额外下载约 2–8 GB）"; GroupDescription: "本地 AI 模型:"; Flags: unchecked

[Files]
; 将 dist\Koto_Portable\ 下全部文件（含 _internal\ 子目录）复制到安装目录
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
; 可选桌面快捷方式
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
; Windows 10 clean images may not carry the Evergreen Runtime. The portable
; payload contains Microsoft's signed offline installer, so setup can repair it.
Filename: "{app}\{#WebView2Installer}"; Parameters: "/silent /install"; StatusMsg: "正在准备 Koto 桌面界面运行时…"; Flags: runhidden waituntilterminated; Check: WebView2RuntimeMissing
; 安装完成后可选"立即启动 Koto"
Filename: "{app}\{#AppExeName}"; Description: "立即启动 Koto"; Flags: nowait postinstall skipifsilent
; 如勾选"安装本地 AI 模型助手"则在安装完成后自动打开模型安装向导
Filename: "{app}\LocalModelInstaller.exe"; Description: "正在启动本地模型安装向导…"; Tasks: localmodel; Flags: nowait skipifsilent

[UninstallDelete]
; 卸载时删除日志（config/ workspace/ chats/ 等用户数据保留）
Type: filesandordirs; Name: "{app}\logs"

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

function IsUsableWebView2Version(const Version: String): Boolean;
begin
  Result := (Trim(Version) <> '') and (Trim(Version) <> '0.0.0.0');
end;

function WebView2RuntimeMissing: Boolean;
var
  Version: String;
begin
  Result := True;
  if RegQueryStringValue(HKLM32, WebView2ClientKey, 'pv', Version) and
     IsUsableWebView2Version(Version) then
  begin
    Result := False;
    exit;
  end;
  if RegQueryStringValue(HKCU, WebView2ClientKey, 'pv', Version) and
     IsUsableWebView2Version(Version) then
    Result := False;
end;
