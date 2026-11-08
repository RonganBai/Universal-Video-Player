# 将「万能视频播放器」注册到 Windows（仅当前用户，无需管理员）
# 用法：右键 → 使用 PowerShell 运行；加 -Uninstall 参数可撤销注册
param([switch]$Uninstall)

$AppName = "万能视频播放器"
$ProgId  = "UniversalVideoPlayer.Media"
$Exe     = Join-Path $PSScriptRoot "dist\万能视频播放器\万能视频播放器.exe"
$Exts    = ".mp4 .mkv .avi .mov .flv .wmv .webm .ts .m2ts .mts .rmvb .rm .3gp .mpg .mpeg .m4v .vob .ogv .f4v .hevc .mp3 .flac .wav .aac .m4a .ogg .opus".Split(" ")
$C       = "HKCU:\Software\Classes"
$Cap     = "HKCU:\Software\Clients\Media\UniversalVideoPlayer\Capabilities"

if ($Uninstall) {
    foreach ($e in $Exts) { Remove-ItemProperty "$C\$e\OpenWithProgids" -Name $ProgId -ErrorAction SilentlyContinue }
    Remove-Item "$C\$ProgId", "HKCU:\Software\UniversalVideoPlayer", "HKCU:\Software\Clients\Media\UniversalVideoPlayer", "$C\Applications\万能视频播放器.exe" -Recurse -ErrorAction SilentlyContinue
    Remove-ItemProperty "HKCU:\Software\RegisteredApplications" -Name "UniversalVideoPlayer","万能视频播放器" -ErrorAction SilentlyContinue
    Write-Host "已撤销注册。"; return
}
if (-not (Test-Path $Exe)) { Write-Host "找不到 $Exe"; return }

$cmd = "`"$Exe`" `"%1`""
New-Item "$C\$ProgId\shell\open\command" -Force | Out-Null
Set-ItemProperty "$C\$ProgId" -Name "(default)" -Value "媒体文件 - $AppName"
Set-ItemProperty "$C\$ProgId" -Name "FriendlyTypeName" -Value "媒体文件"
New-Item "$C\$ProgId\DefaultIcon" -Force | Out-Null
Set-ItemProperty "$C\$ProgId\DefaultIcon" -Name "(default)" -Value "`"$Exe`",0"
Set-ItemProperty "$C\$ProgId\shell\open" -Name "FriendlyAppName" -Value $AppName
Set-ItemProperty "$C\$ProgId\shell\open\command" -Name "(default)" -Value $cmd

$app = "$C\Applications\万能视频播放器.exe"
New-Item "$app\shell\open\command" -Force | Out-Null
Set-ItemProperty "$app" -Name "FriendlyAppName" -Value $AppName
Set-ItemProperty "$app\shell\open\command" -Name "(default)" -Value $cmd
New-Item "$app\SupportedTypes" -Force | Out-Null

New-Item "$Cap\FileAssociations" -Force | Out-Null
Set-ItemProperty $Cap -Name "ApplicationName" -Value $AppName
Set-ItemProperty $Cap -Name "ApplicationDescription" -Value "原画直出的全格式视频播放器"
Set-ItemProperty $Cap -Name "ApplicationIcon" -Value "`"$Exe`",0"

foreach ($e in $Exts) {
    New-Item "$C\$e\OpenWithProgids" -Force | Out-Null
    New-ItemProperty "$C\$e\OpenWithProgids" -Name $ProgId -Value "" -PropertyType String -Force | Out-Null
    Set-ItemProperty "$Cap\FileAssociations" -Name $e -Value $ProgId
    New-ItemProperty "$app\SupportedTypes" -Name $e -Value "" -PropertyType String -Force | Out-Null
}
New-Item "HKCU:\Software\RegisteredApplications" -Force -ErrorAction SilentlyContinue | Out-Null
Set-ItemProperty "HKCU:\Software\RegisteredApplications" -Name "UniversalVideoPlayer" -Value "Software\Clients\Media\UniversalVideoPlayer\Capabilities"

# 通知资源管理器刷新文件关联
Add-Type -Namespace W -Name S -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int a,int b,System.IntPtr c,System.IntPtr d);'
[W.S]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Host "注册完成，正在打开「默认应用」设置…"
Start-Process "ms-settings:defaultapps?registeredAppUser=UniversalVideoPlayer"
