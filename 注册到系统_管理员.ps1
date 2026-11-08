# 以管理员身份把「万能视频播放器」登记到系统级默认应用列表（-Uninstall 撤销）
param([switch]$Uninstall)
$AppName = "万能视频播放器"
$ProgId  = "UniversalVideoPlayer.Media"
$Exe     = Join-Path $PSScriptRoot "dist\万能视频播放器\万能视频播放器.exe"
$Exts    = ".mp4 .mkv .avi .mov .flv .wmv .webm .ts .m2ts .mts .rmvb .rm .3gp .mpg .mpeg .m4v .vob .ogv .f4v .hevc .mp3 .flac .wav .aac .m4a .ogg .opus".Split(" ")
$Cap     = "HKLM:\Software\Clients\Media\UniversalVideoPlayer\Capabilities"
$C       = "HKLM:\Software\Classes"

if ($Uninstall) {
    Remove-Item "HKLM:\Software\Clients\Media\UniversalVideoPlayer", "$C\$ProgId" -Recurse -ErrorAction SilentlyContinue
    Remove-ItemProperty "HKLM:\Software\RegisteredApplications" -Name "UniversalVideoPlayer" -ErrorAction SilentlyContinue
    foreach ($e in $Exts) { Remove-ItemProperty "$C\$e\OpenWithProgids" -Name $ProgId -ErrorAction SilentlyContinue }
    "已撤销系统级注册"; return
}
$cmd = "`"$Exe`" `"%1`""
New-Item "$C\$ProgId\shell\open\command" -Force | Out-Null
Set-ItemProperty "$C\$ProgId" -Name "(default)" -Value "媒体文件 - $AppName"
New-Item "$C\$ProgId\DefaultIcon" -Force | Out-Null
Set-ItemProperty "$C\$ProgId\DefaultIcon" -Name "(default)" -Value "`"$Exe`",0"
Set-ItemProperty "$C\$ProgId\shell\open" -Name "FriendlyAppName" -Value $AppName
Set-ItemProperty "$C\$ProgId\shell\open\command" -Name "(default)" -Value $cmd

New-Item "$Cap\FileAssociations" -Force | Out-Null
Set-ItemProperty "HKLM:\Software\Clients\Media\UniversalVideoPlayer" -Name "(default)" -Value $AppName
Set-ItemProperty $Cap -Name "ApplicationName" -Value $AppName
Set-ItemProperty $Cap -Name "ApplicationDescription" -Value "原画直出的全格式视频播放器"
Set-ItemProperty $Cap -Name "ApplicationIcon" -Value "`"$Exe`",0"
foreach ($e in $Exts) {
    Set-ItemProperty "$Cap\FileAssociations" -Name $e -Value $ProgId
    New-Item "$C\$e\OpenWithProgids" -Force | Out-Null
    New-ItemProperty "$C\$e\OpenWithProgids" -Name $ProgId -Value "" -PropertyType String -Force | Out-Null
}
Set-ItemProperty "HKLM:\Software\RegisteredApplications" -Name "UniversalVideoPlayer" -Value "Software\Clients\Media\UniversalVideoPlayer\Capabilities"
Add-Type -Namespace W -Name S -MemberDefinition '[DllImport("shell32.dll")] public static extern void SHChangeNotify(int a,int b,System.IntPtr c,System.IntPtr d);'
[W.S]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
"OK" | Out-File (Join-Path $env:TEMP "uvp_admin_ok.txt")
