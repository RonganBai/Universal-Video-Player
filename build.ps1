# 一键构建：打包 exe（PyInstaller）→ 生成安装包（Inno Setup）
# 用法：在项目根目录运行  powershell -ExecutionPolicy Bypass -File .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "== 安装依赖 ==" -ForegroundColor Cyan
python -m pip install -r requirements.txt

Write-Host "== 打包 exe ==" -ForegroundColor Cyan
pyinstaller --noconfirm --windowed --name "万能视频播放器" `
    --icon "$root\assets\logo.ico" --add-data "$root\assets;assets" `
    --collect-all av `
    --exclude-module PyQt6.QtWebEngineCore --exclude-module PyQt6.QtWebEngineWidgets `
    --exclude-module PyQt6.QtPdf --exclude-module PyQt6.Qt3DCore --exclude-module tkinter `
    --workpath "$root\build" --specpath "$root\build" --distpath "$root\dist" player.py

Write-Host "== 生成安装包 ==" -ForegroundColor Cyan
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "未找到 Inno Setup 6，请先安装：winget install JRSoftware.InnoSetup" }
& $iscc /Qp "$root\installer\UniversalVideoPlayer.iss"
Write-Host "完成：installer\Output\" -ForegroundColor Green
