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
ChangesAssociations=yes

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

; 正式构建由命令行注册 kotosign。它同时签署 Setup 与 Inno 生成的
; unins000.exe；诊断构建明确关闭签名，不能成为正式发布候选。
#ifdef KotoAuthenticodeSigning
SignTool=kotosign
SignedUninstaller=yes
#else
SignedUninstaller=no
#endif

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
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
; 与 Koto.exe 创建的命名 Mutex 完全一致。升级/卸载时先要求退出旧实例，
; 避免一边运行旧 Python/DLL，一边替换 _internal。
AppMutex=Local\KotoMainWindowMutex_v2

[Languages]
; ChineseSimplified.isl 放在 build\ 目录，本地和 CI 均可引用，无需依赖系统语言包
Name: "chinesesimp"; MessagesFile: "build\ChineseSimplified.isl"
Name: "english";     MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建 Koto 快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "localmodel"; Description: "立即打开 AI 初始化设置（也可在首次启动时选择云端 API 或本地模型）"; GroupDescription: "AI 初始化:"; Flags: unchecked
Name: "fileopen"; Description: "将 Koto 添加到 Word、Excel、PowerPoint 和 PDF 的“打开方式”"; GroupDescription: "文件集成:"

[Files]
; 将 dist\Koto_Portable\ 下全部文件（含 _internal\ 子目录）复制到安装目录
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; 原位升级必须先移除上一版的受管运行时。仅覆盖新文件会留下已删除的
; Python 模块、DLL 和前端资产，造成新旧代码混跑。用户数据目录
; config/chats/logs/workspace 与 .webview2_profile 不在清理范围内。
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\Koto.exe"
Type: files; Name: "{app}\LocalModelInstaller.exe"
Type: files; Name: "{app}\Start_Koto.bat"
Type: files; Name: "{app}\Stop_Koto.bat"
Type: files; Name: "{app}\Install_Local_Model.bat"
Type: files; Name: "{app}\Install_WebView2_Runtime.bat"
Type: files; Name: "{app}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
Type: files; Name: "{app}\webview2-runtime.json"
Type: files; Name: "{app}\README_便携版.txt"
Type: files; Name: "{app}\PORTABLE_RELEASE_GUIDE.md"

[Icons]
; 开始菜单快捷方式
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
; 可选桌面快捷方式
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Registry]
; Register a non-invasive Open With entry. Windows remains the authority for
; the user's default application; Koto never silently replaces Office/PDF.
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe"; Tasks: fileopen; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe\shell\open\command"; ValueType: string; ValueData: """{app}\Koto.exe"" ""%1"""; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe\SupportedTypes"; ValueType: string; ValueName: ".docx"; ValueData: ""; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe\SupportedTypes"; ValueType: string; ValueName: ".xlsx"; ValueData: ""; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe\SupportedTypes"; ValueType: string; ValueName: ".pptx"; ValueData: ""; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Applications\Koto.exe\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Tasks: fileopen; Flags: uninsdeletekeyifempty
; Register with Windows Default Apps without changing any user-selected default.
; The settings deep link uses this exact HKCU RegisteredApplications value.
Root: HKCU; Subkey: "Software\Classes\Koto.AssistedDocument"; ValueType: string; ValueData: "Koto 可编辑文档"; Tasks: fileopen; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Koto.AssistedDocument\DefaultIcon"; ValueType: string; ValueData: """{app}\Koto.exe"",0"; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Classes\Koto.AssistedDocument\shell\open\command"; ValueType: string; ValueData: """{app}\Koto.exe"" ""%1"""; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "Koto"; Tasks: fileopen; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "使用 Koto 打开、阅读和编辑办公文档与 PDF"; Tasks: fileopen
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\Koto.exe"",0"; Tasks: fileopen
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities\FileAssociations"; ValueType: string; ValueName: ".docx"; ValueData: "Koto.AssistedDocument"; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xlsx"; ValueData: "Koto.AssistedDocument"; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pptx"; ValueData: "Koto.AssistedDocument"; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\Loganwon\Koto\Capabilities\FileAssociations"; ValueType: string; ValueName: ".pdf"; ValueData: "Koto.AssistedDocument"; Tasks: fileopen; Flags: uninsdeletekeyifempty
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "Koto"; ValueData: "Software\Loganwon\Koto\Capabilities"; Tasks: fileopen; Flags: uninsdeletevalue

[Run]
; Windows 10 clean images may not carry the Evergreen Runtime.  The portable
; payload contains Microsoft's signed offline installer, so setup can repair
; the prerequisite without Python, a browser download, or administrator input.
Filename: "{app}\{#WebView2Installer}"; Parameters: "/silent /install"; StatusMsg: "正在准备 Koto 桌面界面运行时…"; Flags: runhidden waituntilterminated; Check: WebView2RuntimeMissing
; 安装完成后可选"立即启动 Koto"
Filename: "{app}\{#AppExeName}"; Description: "立即启动 Koto"; Flags: nowait postinstall skipifsilent
; 如勾选"安装本地 AI 模型助手"则在安装完成后自动打开模型安装向导
Filename: "{app}\LocalModelInstaller.exe"; Description: "正在启动本地模型安装向导…"; Tasks: localmodel; Flags: nowait skipifsilent

[UninstallDelete]
; 卸载时删除日志（config/ workspace/ chats/ 等用户数据保留）
Type: filesandordirs; Name: "{app}\logs"
Type: filesandordirs; Name: "{app}\.ipc"

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';

var
  UpgradeBackupPrepared: Boolean;
  InstallCompleted: Boolean;

function UpgradeBackupRoot: String;
begin
  Result := AddBackslash(ExpandConstant('{app}')) + '.koto_upgrade_backup';
end;

function UpgradeSuccessMarker: String;
begin
  Result := AddBackslash(ExpandConstant('{app}')) + '.koto_upgrade_completed';
end;

function ManagedPath(const RelativePath: String): String;
begin
  Result := AddBackslash(ExpandConstant('{app}')) + RelativePath;
end;

function BackupPath(const RelativePath: String): String;
begin
  Result := AddBackslash(UpgradeBackupRoot) + RelativePath;
end;

function PathExists(const Path: String): Boolean;
begin
  Result := FileExists(Path) or DirExists(Path);
end;

function RemovePath(const Path: String): Boolean;
begin
  Result := True;
  if DirExists(Path) then
    Result := DelTree(Path, True, True, True)
  else if FileExists(Path) then
    Result := DeleteFile(Path);
end;

function MoveManagedPathToBackup(const RelativePath: String): Boolean;
var
  SourcePath: String;
  DestinationPath: String;
begin
  SourcePath := ManagedPath(RelativePath);
  DestinationPath := BackupPath(RelativePath);
  Result := True;
  if not PathExists(SourcePath) then
    exit;

  if PathExists(DestinationPath) then
  begin
    Log('Upgrade backup destination already exists: ' + DestinationPath);
    Result := False;
    exit;
  end;

  Result := RenameFile(SourcePath, DestinationPath);
  if not Result then
    Log('Could not move managed runtime into upgrade backup: ' + SourcePath);
end;

function RestoreManagedPath(const RelativePath: String): Boolean;
var
  SourcePath: String;
  DestinationPath: String;
begin
  SourcePath := BackupPath(RelativePath);
  DestinationPath := ManagedPath(RelativePath);
  Result := True;
  if not PathExists(SourcePath) then
    exit;

  if PathExists(DestinationPath) and not RemovePath(DestinationPath) then
  begin
    Log('Could not remove partial upgrade path before recovery: ' + DestinationPath);
    Result := False;
    exit;
  end;

  Result := RenameFile(SourcePath, DestinationPath);
  if not Result then
    Log('Could not restore managed runtime from upgrade backup: ' + SourcePath);
end;

function RestoreUpgradeBackup: Boolean;
begin
  Result := True;
  if not DirExists(UpgradeBackupRoot) then
    exit;

  if not RestoreManagedPath('_internal') then Result := False;
  if not RestoreManagedPath('Koto.exe') then Result := False;
  if not RestoreManagedPath('LocalModelInstaller.exe') then Result := False;
  if not RestoreManagedPath('Start_Koto.bat') then Result := False;
  if not RestoreManagedPath('Stop_Koto.bat') then Result := False;
  if not RestoreManagedPath('Install_Local_Model.bat') then Result := False;
  if not RestoreManagedPath('Install_WebView2_Runtime.bat') then Result := False;
  if not RestoreManagedPath('MicrosoftEdgeWebView2RuntimeInstallerX64.exe') then Result := False;
  if not RestoreManagedPath('webview2-runtime.json') then Result := False;
  if not RestoreManagedPath('README_便携版.txt') then Result := False;
  if not RestoreManagedPath('PORTABLE_RELEASE_GUIDE.md') then Result := False;

  if Result then
  begin
    DeleteFile(UpgradeSuccessMarker);
    if not DelTree(UpgradeBackupRoot, True, True, True) then
      Result := False;
  end;
end;

function HasManagedRuntime: Boolean;
begin
  Result := PathExists(ManagedPath('_internal')) or
    PathExists(ManagedPath('Koto.exe')) or
    PathExists(ManagedPath('LocalModelInstaller.exe')) or
    PathExists(ManagedPath('Start_Koto.bat')) or
    PathExists(ManagedPath('Stop_Koto.bat')) or
    PathExists(ManagedPath('Install_Local_Model.bat')) or
    PathExists(ManagedPath('Install_WebView2_Runtime.bat')) or
    PathExists(ManagedPath('MicrosoftEdgeWebView2RuntimeInstallerX64.exe')) or
    PathExists(ManagedPath('webview2-runtime.json')) or
    PathExists(ManagedPath('README_便携版.txt')) or
    PathExists(ManagedPath('PORTABLE_RELEASE_GUIDE.md'));
end;

function PrepareManagedRuntimeBackup: Boolean;
begin
  Result := True;
  if not HasManagedRuntime then
    exit;

  if not CreateDir(UpgradeBackupRoot) then
  begin
    Log('Could not create upgrade backup directory: ' + UpgradeBackupRoot);
    Result := False;
    exit;
  end;
  UpgradeBackupPrepared := True;

  if not MoveManagedPathToBackup('_internal') then Result := False;
  if Result and not MoveManagedPathToBackup('Koto.exe') then Result := False;
  if Result and not MoveManagedPathToBackup('LocalModelInstaller.exe') then Result := False;
  if Result and not MoveManagedPathToBackup('Start_Koto.bat') then Result := False;
  if Result and not MoveManagedPathToBackup('Stop_Koto.bat') then Result := False;
  if Result and not MoveManagedPathToBackup('Install_Local_Model.bat') then Result := False;
  if Result and not MoveManagedPathToBackup('Install_WebView2_Runtime.bat') then Result := False;
  if Result and not MoveManagedPathToBackup('MicrosoftEdgeWebView2RuntimeInstallerX64.exe') then Result := False;
  if Result and not MoveManagedPathToBackup('webview2-runtime.json') then Result := False;
  if Result and not MoveManagedPathToBackup('README_便携版.txt') then Result := False;
  if Result and not MoveManagedPathToBackup('PORTABLE_RELEASE_GUIDE.md') then Result := False;

  if not Result then
  begin
    RestoreUpgradeBackup;
    UpgradeBackupPrepared := False;
  end;
end;

function HasCommandLineSwitch(const SwitchName: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if ParamStr(Index) = SwitchName then
    begin
      Result := True;
      exit;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  CompletedBackupMarker: String;
begin
  Result := '';
  CompletedBackupMarker := AddBackslash(UpgradeBackupRoot) + 'completed.marker';

  { A previous successful install may have been unable to remove its backup
    because an antivirus scanner briefly held a file. It is safe to discard. }
  if DirExists(UpgradeBackupRoot) and
     (FileExists(UpgradeSuccessMarker) or FileExists(CompletedBackupMarker)) then
  begin
    if not DelTree(UpgradeBackupRoot, True, True, True) then
    begin
      Result := '无法清理上一版本的升级备份。请重启 Windows 后再次运行安装程序。';
      exit;
    end;
    DeleteFile(UpgradeSuccessMarker);
  end
  else if DirExists(UpgradeBackupRoot) then
  begin
    { No completion marker means Setup was interrupted. Restore the last known
      good runtime before starting a new upgrade attempt. }
    if not RestoreUpgradeBackup then
    begin
      Result := '检测到未完成的 Koto 升级，但旧版本自动恢复失败。请保留安装目录并联系支持。';
      exit;
    end;
  end
  else
    DeleteFile(UpgradeSuccessMarker);

  if not PrepareManagedRuntimeBackup then
  begin
    Result := '无法安全备份当前 Koto 版本。旧版本已保留，请关闭占用安装目录的程序后重试。';
    exit;
  end;

  { Used only by the installer E2E to prove that the rollback path restores the
    old runtime. The switch is harmless in production: it aborts and recovers. }
  if HasCommandLineSwitch('/KOTO_FAIL_AFTER_BACKUP') then
    Result := 'Koto upgrade recovery test injection';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  CompletedBackupMarker: String;
begin
  if CurStep = ssDone then
  begin
    InstallCompleted := True;
    if UpgradeBackupPrepared and DirExists(UpgradeBackupRoot) then
    begin
      CompletedBackupMarker := AddBackslash(UpgradeBackupRoot) + 'completed.marker';
      SaveStringToFile(UpgradeSuccessMarker, 'completed', False);
      SaveStringToFile(CompletedBackupMarker, 'completed', False);
      if DelTree(UpgradeBackupRoot, True, True, True) then
        DeleteFile(UpgradeSuccessMarker)
      else
        Log('Upgrade succeeded, but its backup will be cleaned on the next install.');
    end;
  end;
end;

procedure DeinitializeSetup;
begin
  if UpgradeBackupPrepared and not InstallCompleted then
  begin
    Log('Setup did not complete; restoring the previous Koto runtime.');
    if not RestoreUpgradeBackup then
      Log('Automatic Koto runtime recovery did not complete. The backup remains at: ' + UpgradeBackupRoot);
  end;
end;

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
