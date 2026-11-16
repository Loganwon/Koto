param(
    [ValidateSet('Word','Excel','PowerPoint','Office','Wps','Both')][string]$HostType='Both',
    [string]$ApiKeyFile,
    [string]$Workspace,
    [switch]$Uninstall,
    [switch]$NoStart,
    [switch]$NoAutoStart,
    [switch]$TrustLocalCertificate
)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$python=Join-Path $projectRoot '.venv/Scripts/python.exe'
$installRoot=Join-Path $env:LOCALAPPDATA 'Koto/Addin'
$manifestId='49fe6de2-c48a-4daf-af2d-d034cd83c70e'
$developerKey='HKCU:\Software\Microsoft\Office\16.0\WEF\Developer'
$runKey='HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$pythonw=Join-Path $projectRoot '.venv/Scripts/pythonw.exe'
$agentPython=Join-Path $projectRoot '.venv-agent/Scripts/python.exe'
$agentPythonw=Join-Path $projectRoot '.venv-agent/Scripts/pythonw.exe'
$entryScript=Join-Path $PSScriptRoot 'open_wps.py'
if (-not $Uninstall) {
    if(-not (Test-Path -LiteralPath $agentPython)){
        & $python -m venv (Join-Path $projectRoot '.venv-agent')
        if($LASTEXITCODE -ne 0){throw 'Agent 独立环境创建失败。'}
    }
    & $agentPython -m pip install -r (Join-Path $projectRoot 'companion/requirements-native.txt') --disable-pip-version-check
    if($LASTEXITCODE -ne 0){throw 'Agent 依赖安装失败，尚未更改加载项。'}
    New-Item -ItemType Directory -Path $installRoot -Force|Out-Null
    & $python (Join-Path $PSScriptRoot 'setup_tls.py') $installRoot
    if($LASTEXITCODE -ne 0){throw '本地开发证书生成失败。'}
    if($TrustLocalCertificate){
        & certutil.exe -user -f -addstore Root (Join-Path $installRoot 'localhost.crt') | Out-Null
        if($LASTEXITCODE -ne 0){throw '本机开发证书安装失败。'}
    }else{
        $certificate=New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Join-Path $installRoot 'localhost.crt'))
        if(Test-Path -LiteralPath "Cert:\CurrentUser\Root\$($certificate.Thumbprint)"){
            Write-Output '复用已信任的本机 HTTPS 开发证书。'
        }else{Write-Output '已生成仅用于本机的 HTTPS 开发证书；首次真机加载前需明确允许信任此证书。'}
    }
    $settings=@{host='wps';port=19742;tls_cert=(Join-Path $installRoot 'localhost.crt');tls_key=(Join-Path $installRoot 'localhost.key')}
    $settingsPath=Join-Path $installRoot 'host.json'
    if(Test-Path -LiteralPath $settingsPath){
        $previous=Get-Content -LiteralPath $settingsPath -Raw|ConvertFrom-Json
        foreach($property in $previous.PSObject.Properties){$settings[$property.Name]=$property.Value}
    }
    if($ApiKeyFile){$settings.api_key_file=(Resolve-Path -LiteralPath $ApiKeyFile).Path}
    if($Workspace){$settings.workspace=(Resolve-Path -LiteralPath $Workspace).Path}
    $settings.workflow=$true
    $settings.runtime_python=$agentPythonw
    $settings|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $installRoot 'host.json') -Encoding UTF8
}
foreach($officeHost in @(
    @{name='Word';folder='word';id=$manifestId;file='manifest.xml'},
    @{name='Excel';folder='excel';id='f7a35b59-7631-4794-98dd-61dc12fe7f81';file='excel-manifest.xml'},
    @{name='PowerPoint';folder='powerpoint';id='eaedbd83-a37e-486f-ae91-f49b96278272';file='powerpoint-manifest.xml'}
)){
    if($HostType -notin @($officeHost.name,'Office','Both')){continue}
    if($Uninstall){Remove-ItemProperty -Path $developerKey -Name $officeHost.id -ErrorAction SilentlyContinue}
    else{
        $manifestPath=Join-Path $installRoot $officeHost.file
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ($officeHost.folder+'/manifest.xml')) -Destination $manifestPath -Force
        if(-not (Test-Path -LiteralPath $developerKey)){New-Item -Path $developerKey -Force|Out-Null}
        New-ItemProperty -Path $developerKey -Name $officeHost.id -Value $manifestPath -Force|Out-Null
        Write-Output ($officeHost.name+' 开发加载项已注册；从该应用的加载项中选择 Koto。')
    }
}
if ($HostType -in @('Wps','Both')) {
    $publishRoot=Join-Path $env:APPDATA 'kingsoft/wps/jsaddons'
    $publishFile=Join-Path $publishRoot 'publish.xml'
    if(Test-Path -LiteralPath $publishFile){[xml]$publish=Get-Content -LiteralPath $publishFile -Raw}
    else{[xml]$publish='<?xml version="1.0" encoding="UTF-8"?><jsplugins/>'}
    $element=$publish.DocumentElement
    @($element.SelectNodes('*[@name="Koto"]'))|ForEach-Object {$element.RemoveChild($_)|Out-Null}
    if(-not $Uninstall){
        $node=$publish.CreateElement('jspluginonline')
        foreach($entry in @{name='Koto';type='wps';url='https://127.0.0.1:19742/wps/';enable='true'}.GetEnumerator()){$node.SetAttribute($entry.Key,$entry.Value)}
        $element.AppendChild($node)|Out-Null
    }
    New-Item -ItemType Directory -Path $publishRoot -Force|Out-Null
    $publish.Save($publishFile)
    # Own only these two links; preserve the user's other shortcuts and hotkeys.
    $shell=New-Object -ComObject WScript.Shell
    foreach($link in @(
        (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Koto（WPS）.lnk'),
        (Join-Path ([Environment]::GetFolderPath('Programs')) 'Koto（WPS）.lnk')
    )){
        if($Uninstall){Remove-Item -LiteralPath $link -ErrorAction SilentlyContinue}
        else{
            $shortcut=$shell.CreateShortcut($link)
            $shortcut.TargetPath=$pythonw
            $shortcut.Arguments='"'+$entryScript+'"'
            $shortcut.WorkingDirectory=$projectRoot
            $shortcut.Description='在 WPS 内打开 Koto 助手，不打开新文档'
            $shortcut.IconLocation=(Join-Path $env:LOCALAPPDATA 'Kingsoft/WPS Office/ksolaunch.exe')+',0'
            $shortcut.WindowStyle=7
            # Windows activates this desktop link even while the document has focus.
            if($link.StartsWith([Environment]::GetFolderPath('Desktop'))){$shortcut.Hotkey='CTRL+ALT+K'}
            $shortcut.Save()
        }
    }
    Write-Output 'WPS 加载项和 Koto（WPS）快捷方式已更新。可从开始功能区、文字右键菜单或桌面入口打开；桌面入口快捷键 Ctrl+Alt+K。'
}
if($Uninstall -and $HostType -eq 'Both'){
    Remove-ItemProperty -Path $runKey -Name 'KotoEmbeddedService' -ErrorAction SilentlyContinue
}elseif(-not $Uninstall){
    if($NoAutoStart){Remove-ItemProperty -Path $runKey -Name 'KotoEmbeddedService' -ErrorAction SilentlyContinue}
    else{
        if(-not (Test-Path -LiteralPath $runKey)){New-Item -Path $runKey -Force|Out-Null}
        New-ItemProperty -Path $runKey -Name 'KotoEmbeddedService' -Value ('"'+$pythonw+'" "'+$entryScript+'" --service-only') -PropertyType String -Force|Out-Null
        Write-Output '已启用当前用户登录时的 Koto 后台启动，避免 WPS 入口因服务未启动而加载失败；可用 -NoAutoStart 关闭。'
    }
}
if($Uninstall){
    if($HostType -eq 'Both' -and (Test-Path (Join-Path $installRoot 'localhost.crt'))){
        $certificate=New-Object System.Security.Cryptography.X509Certificates.X509Certificate2((Join-Path $installRoot 'localhost.crt'))
        Remove-Item -LiteralPath "Cert:\CurrentUser\Root\$($certificate.Thumbprint)" -ErrorAction SilentlyContinue
    }
}elseif(-not $NoStart){
    $serviceReady=$false
    try {$health=Invoke-RestMethod 'https://127.0.0.1:19742/health' -TimeoutSec 2; $serviceReady=$health.service -eq 'koto-embedded'}catch{}
    if($serviceReady){Write-Output '复用已运行的 Koto 插件服务。'}else{
        Start-Process -FilePath $agentPython -ArgumentList @(('"'+(Join-Path $PSScriptRoot 'service.py')+'"'),'--settings',('"'+(Join-Path $installRoot 'host.json')+'"')) -WorkingDirectory $projectRoot -WindowStyle Hidden
        Write-Output '本地插件服务已启动，不创建外置浮窗。'
    }
}
