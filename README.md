<p align="center"><img src="assets/logo.png" width="96" alt="logo"></p>

<h1 align="center">万能视频播放器</h1>

<p align="center">原画直出、全格式的 Windows 视频播放器。基于 Qt 6 + FFmpeg，GPU 硬解、零拷贝显示。</p>

## 特性

- **原画直出**：按原始分辨率解码，不重编码；硬解出的帧直接作为显卡纹理显示，不回读内存
- **全格式**：mp4 / mkv / avi / mov / flv / wmv / webm / ts / rmvb / mpg 等，以及 HLS(m3u8)、rtsp、rtmp 网络流
- **现代界面**：自有窗口边框；低对比度浮动控制面板，播放时自动隐藏；按窗口宽度逐级折叠按钮
- **进度条预览**：拖动时跟随滑块显示画面（后台关键帧解码 + 压缩缓存，内存占用低）
- **播放列表**：缩略图、拖拽排序、记忆列表与每个视频的播放进度；宽窗口并排、窄窗口覆盖
- **倍速**：0.1×–4.0×，每档 0.1×
- **音效**：声道模式、平衡、立体声宽度、耳机交叉馈送、虚拟环绕、多声道下混 / 直出
- **平滑过渡**：切换上一个 / 下一个时画面与声音淡出淡入（可选）
- **小窗模式**：始终置顶、自动保持在屏幕内，可直接拖动画面移动
- **个性化**：主题色、背景色、界面大小（70%–160%）、自动隐藏时间、快进步长等

## 安装

到 [Releases](https://github.com/RonganBai/Universal-Video-Player/releases) 下载 `UniversalVideoPlayer-Setup-x.y.z.exe` 运行即可。
安装时勾选「注册为视频播放器」后，可在 Windows「设置 → 应用 → 默认应用」中把它设为默认播放器。

## 从源码运行

需要 Windows 10/11 x64、Python 3.11+。

```powershell
python -m pip install -r requirements.txt
python player.py
```

## 构建安装包

另需 [Inno Setup 6](https://jrsoftware.org/isinfo.php)（`winget install JRSoftware.InnoSetup`）。

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

产物：`dist\万能视频播放器\`（免安装版）与 `installer\Output\UniversalVideoPlayer-Setup-*.exe`（安装包）。

## 项目结构

| 文件 | 说明 |
|---|---|
| `player.py` | 主程序：界面、播放、播放列表、预览、设置 |
| `audio_fx.py` | 音效引擎（立体声 / 环绕声处理） |
| `frame.py` | 自有窗口边框与标题栏 |
| `assets/` | 图标 |
| `installer/` | Inno Setup 安装包脚本 |
| `build.ps1` | 一键构建 |
| `注册为默认播放器.ps1`、`注册到系统_管理员.ps1` | 免安装版手动注册文件关联用（安装包已自动处理） |

## 快捷键

| 按键 | 功能 |
|---|---|
| 空格 / 单击画面 | 播放 / 暂停 |
| ← / → | 快退 / 快进 |
| ↑ / ↓、滚轮 | 音量 |
| M | 静音 |
| F / 双击画面 | 全屏 |
| P | 小窗 |
| L | 播放列表 |
| [ / ] / \\ | 减速 / 加速 / 复位 |
| PgUp / PgDn | 上一个 / 下一个 |
| O | 打开文件 |
