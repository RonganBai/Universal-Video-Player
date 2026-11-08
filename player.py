"""万能视频播放器 2.0 —— 基于 Qt6 Multimedia (FFmpeg 后端)
原始分辨率解码、无重编码；画面按窗口等比显示。

快捷键：
  空格 播放/暂停    ← → 快退/快进    ↑ ↓ 音量    M 静音
  F / 双击 全屏      Esc 退出全屏/小窗  P 小窗     L 播放列表
  [ ] 速度 ∓0.1     \\ 速度复位       PgUp/PgDn 上一个/下一个
  O 打开文件        滚轮 调音量        拖拽文件/文件夹到窗口加入播放列表
"""
import json
import os
import random
import sys

import hashlib

from PyQt6.QtCore import (QEasingCurve, QObject, QPoint, QPropertyAnimation,
                          QRect, QRectF, QSettings, QSize, Qt, QTimer, QUrl,
                          pyqtSignal)

APP = "万能视频播放器"
DEFAULT_PL = "默认列表"
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(BASE, "assets", "logo.ico")
THUMB_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP, "thumbs")
if sys.platform == "win32":  # 任务栏显示为独立应用，而不是 Python
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UniversalVideoPlayer.App")
    except Exception:
        pass
DEFAULTS = {
    "accent": "#4f8cff",
    "bar_opacity": 75,          # 控制栏背景不透明度 %
    "hide_delay": 2.0,          # 自动隐藏秒数
    "seek_step": 5,             # 快进步长 秒
    "volume": 80,
    "remember_pos": True,
    "remember_list": True,
    "auto_next": True,
    "hw_decode": True,
    "mini_on_top": True,
    "bg_color": "#000000",
    "play_mode": 0,             # 0 顺序 1 列表循环 2 单曲循环 3 随机
    "show_osd": True,
    "transition": False,       # 切换视频时平滑过渡（画面与声音淡出淡入）
    "transition_ms": 600,      # 淡出 / 淡入各自的时长
    "ui_scale": 100,           # 界面大小 %
}
CFG = QSettings("UniversalPlayer", "Player")


def cfg(key):
    d = DEFAULTS[key]
    v = CFG.value(key, d)
    if isinstance(d, bool):
        return v in (True, "true", "1", 1)
    try:
        return type(d)(v)
    except (TypeError, ValueError):
        return d


os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")
for _k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
if cfg("hw_decode"):
    os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", "d3d11va,dxva2,cuda")
else:
    os.environ["QT_FFMPEG_DECODING_HW_DEVICE_TYPES"] = ""

from PyQt6.QtGui import (QAction, QColor, QFont, QIcon, QImage, QKeySequence,
                         QLinearGradient, QPainter, QPainterPath, QPixmap,
                         QShortcut)
from PyQt6.QtMultimedia import (QAudioOutput, QMediaMetaData, QMediaPlayer,
                                QVideoSink)
from PyQt6.QtQml import QQmlComponent
from PyQt6.QtQuickWidgets import QQuickWidget

import frame
from audio_fx import AudioDialog, AudioEngine
from PyQt6.QtWidgets import (
    QComboBox,
    QApplication, QCheckBox, QColorDialog, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGraphicsOpacityEffect,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton, QSlider,
    QSpinBox, QStyle, QVBoxLayout, QWidget, QWidgetAction,
)

MEDIA_EXT = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".ts",
             ".m2ts", ".mts", ".rmvb", ".rm", ".3gp", ".mpg", ".mpeg", ".m4v",
             ".vob", ".ogv", ".f4v", ".hevc", ".mp3", ".flac", ".wav", ".aac",
             ".m4a", ".ogg", ".opus"}
FILTER = "媒体文件 (" + " ".join("*" + e for e in sorted(MEDIA_EXT)) + ");;所有文件 (*)"

ICON_FONT = "Segoe Fluent Icons"
IC = dict(play="", pause="", prev="", next="",
          vol="", mute="", full="", unfull="",
          mini="", list="", gear="", open="",
          add="", delete="", clear="", menu="",
          seq="", loop="", one="", shuffle="",
          speed="", folder="", link="", close="")
IC.update(chev_l="\uE76B", chev_r="\uE76C", more="", wmin="", wmax="", wrestore="", wclose="", fx="")
MODES = [("顺序播放", "seq"), ("列表循环", "loop"), ("单曲循环", "one"), ("随机播放", "shuffle")]


def fmt(ms):
    s = max(int(ms), 0) // 1000
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def px(n):
    """按「界面大小」缩放尺寸"""
    return max(1, round(n * cfg("ui_scale") / 100))


def handle_rules():
    """滑块圆点：保证 圆点高 = 轨道高 + 2×外边距，任何缩放下都是正圆"""
    out = []
    # 注意：不要给进度条加 #seek / :hover 专属规则，Qt 会因此回退成纯白填充
    # 轨道约 3px，圆点 12px；控件本身高 20px 作为鼠标命中区
    for sel, g in (("QSlider", px(3)),):
        m = max(1, (px(12) - g + 1) // 2)
        d = g + 2 * m
        # 轨道（未播放部分）：白色 60% 透明 = 40% 不透明
        out.append(f"    {sel}::groove:horizontal {{ height:{g}px; background:rgba(255,255,255,0.40); "
                   f"border-radius:{max(1, g // 2)}px; }}\n"
                   f"    {sel}::add-page:horizontal {{ background:transparent; }}\n"
                   f"    {sel}::handle:horizontal {{ background:white; width:{d}px; height:{d}px; "
                   f"margin:-{m}px 0; border-radius:{d // 2}px; }}")
    # 垂直音量条（浮窗内）：下方已填充部分为主题色
    g = px(5)
    m = max(1, (px(14) - g + 1) // 2)
    d = g + 2 * m
    out.append(f"    QSlider::groove:vertical {{ width:{g}px; background:rgba(255,255,255,0.40); border-radius:{max(1, g // 2)}px; }}\n"
               f"    QSlider::sub-page:vertical {{ background:transparent; }}\n"
               f"    QSlider::add-page:vertical {{ background:{cfg('accent')}; border-radius:{max(1, g // 2)}px; }}\n"
               f"    QSlider::handle:vertical {{ background:white; width:{d}px; height:{d}px; margin:0 -{m}px; border-radius:{d // 2}px; }}")
    return "\n".join(out)


def low_sat(hex_color):
    """主题色降低饱和度，用作播放列表当前项的底色，减少对画面的干扰"""
    c = QColor(hex_color)
    h, s, l, _ = c.getHsl()
    c.setHsl(max(h, 0), int(s * 0.35), max(40, int(l * 0.45)), 200)
    return f"rgba({c.red()},{c.green()},{c.blue()},0.78)"


def stylesheet():
    a = cfg("accent")
    return f"""
    * {{ font-family: "Segoe UI Variable", "Microsoft YaHei UI", sans-serif; color:#f2f2f2; }}
    QMainWindow, #stage {{ background:{cfg('bg_color')}; }}
    QFrame#dock {{ background:transparent; border:none; }}
    QFrame#panel {{ background:rgba(22,22,26,0.72); border:1px solid rgba(255,255,255,0.06);
        border-radius:{px(16)}px; }}
    /* 线性图标按钮：默认透明，悬停浅色圆角底，按下再深一级，不可用时置灰 */
    QPushButton[bubble="true"] {{
        font-family:"{ICON_FONT}","Segoe MDL2 Assets"; font-size:{px(18)}px; padding:0; margin:0;
        background:transparent; border:none; color:#ececf0;
        border-radius:{px(10)}px; min-width:{px(38)}px; max-width:{px(38)}px; min-height:{px(38)}px; max-height:{px(38)}px; }}
    QPushButton[bubble="true"]:hover {{ background:rgba(255,255,255,0.12); }}
    QPushButton[bubble="true"]:pressed {{ background:rgba(255,255,255,0.22); }}
    QPushButton[bubble="true"]:disabled {{ color:rgba(255,255,255,0.28); background:transparent; }}
    QPushButton[active="true"] {{ background:rgba(255,255,255,0.18); }}
    /* 播放键：40px 浅色实心圆 + 深色图标 */
    QPushButton#playBtn {{ background:transparent; border:none; padding:0; margin:0;
        min-width:{px(52)}px; max-width:{px(52)}px; min-height:{px(52)}px; max-height:{px(52)}px; }}
    QFrame#preview {{ background:rgba(18,18,22,0.94); border:1px solid rgba(255,255,255,0.10); border-radius:{px(10)}px; }}
    QLabel#previewImg {{ background:#0c0c0e; border-radius:{px(7)}px; color:rgba(255,255,255,0.5); font-size:{px(12)}px; }}
    QLabel#previewTime {{ font-size:{px(13)}px; font-weight:600; color:#f2f2f4; }}
    /* 文字按钮（倍速）：同样默认透明 */
    QPushButton#pill {{ background:transparent; border:none; margin:0; color:#ececf0;
        border-radius:{px(10)}px; min-height:{px(38)}px; max-height:{px(38)}px; padding:0 {px(10)}px; font-size:{px(13)}px; font-weight:600; }}
    QPushButton#pill:hover {{ background:rgba(255,255,255,0.12); }}
    QPushButton#pill:pressed {{ background:rgba(255,255,255,0.22); }}
    QPushButton#openBig {{ background:#f2f2f4; color:#16161a; border:none; border-radius:{px(22)}px;
        min-height:{px(44)}px; padding:0 {px(26)}px; font-size:{px(15)}px; font-weight:600; }}
    QPushButton#openBig:hover {{ background:#ffffff; }}
    QPushButton#openBig:pressed {{ background:#c9c9ce; }}
    QLabel#hint {{ font-size:{px(13)}px; color:rgba(255,255,255,0.55); }}
    QLabel#drag {{ background:rgba(22,22,26,0.9); border-radius:{px(6)}px; padding:{px(3)}px {px(8)}px; font-size:{px(12)}px; }}
    QLabel#time {{ font-size:{px(13)}px; color:#dcdcdc; }}
    QLabel#title {{ font-size:{px(15)}px; font-weight:600; }}
    QLabel#res {{ font-size:{px(12)}px; color:rgba(255,255,255,0.6); }}
    QSlider::sub-page:horizontal {{ background:{a}; border-radius:2px; }}
{handle_rules()}
    #playlist {{ background:rgba(18,18,22,0.50); border-left:1px solid rgba(255,255,255,0.08); }}
    QPushButton#plHandle {{ font-family:"{ICON_FONT}","Segoe MDL2 Assets"; font-size:{px(12)}px; color:#ececf0;
        background:rgba(22,22,26,0.72); border:1px solid rgba(255,255,255,0.08); border-right:none;
        border-top-left-radius:{px(10)}px; border-bottom-left-radius:{px(10)}px; padding:0; }}
    QPushButton#plHandle:hover {{ background:rgba(60,60,68,0.85); }}
    QPushButton#plHandle:pressed {{ background:rgba(90,90,100,0.9); }}
    QComboBox#plCombo {{ background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.10);
        border-radius:{px(8)}px; padding:{px(5)}px {px(10)}px; font-size:{px(14)}px; font-weight:600; min-height:{px(26)}px; }}
    QComboBox#plCombo:hover {{ background:rgba(255,255,255,0.14); }}
    QComboBox#plCombo::drop-down {{ border:none; width:{px(22)}px; }}
    QListWidget {{ background:transparent; border:none; font-size:{px(13)}px; outline:none; }}
    QListWidget::item {{ padding:{px(6)}px {px(6)}px; border-radius:8px; margin:1px 4px; color:#d8d8dc; }}
    QListWidget::item:hover {{ background:rgba(255,255,255,0.06); }}
    QListWidget::item:selected {{ background:{low_sat(a)}; color:#ffffff; }}
    QMenu {{ background:rgba(32,32,36,0.97); border:1px solid rgba(255,255,255,0.1);
        border-radius:10px; padding:6px; }}
    QMenu::item {{ padding:7px 22px; border-radius:6px; }}
    QMenu::item:selected {{ background:{a}; }}
    QDialog {{ background:#1e1e22; }}
    QSpinBox, QDoubleSpinBox {{ background:#2a2a30; border:1px solid #3a3a42; border-radius:6px; padding:4px; }}
    QCheckBox::indicator {{ width:16px; height:16px; }}
    QDialogButtonBox QPushButton {{ background:#2e2e36; border:1px solid #3a3a42; border-radius:6px; padding:6px 16px; }}
    QDialogButtonBox QPushButton:hover {{ background:{a}; }}
    #titlebar {{ background:rgba(20,20,24,0.30); border:none; }}
    QLabel#wintitle {{ font-size:{px(12)}px; color:#cfcfd4; }}
    QPushButton#wbtn, QPushButton#wclose {{ font-family:"{ICON_FONT}","Segoe MDL2 Assets"; font-size:{px(10)}px;
        background:transparent; border:none; border-radius:0; padding:0; margin:0; min-width:{px(46)}px; max-width:{px(46)}px;
        min-height:{px(38)}px; max-height:{px(38)}px; color:#e6e6e6; }}
    QPushButton#wbtn:hover {{ background:rgba(255,255,255,0.10); }}
    QPushButton#wbtn:pressed {{ background:rgba(255,255,255,0.18); }}
    QPushButton#wclose:hover {{ background:#e81123; color:white; }}
    QPushButton#wclose:pressed {{ background:#a50f1c; }}
    QGroupBox {{ border:1px solid rgba(255,255,255,0.10); border-radius:10px; margin-top:14px; padding:10px 8px 6px 8px; font-weight:600; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 4px; color:{a}; }}
    QComboBox {{ background:#2a2a30; border:1px solid #3a3a42; border-radius:6px; padding:4px 8px; }}
    QComboBox QAbstractItemView {{ background:#2a2a30; selection-background-color:{a}; }}
    QDialog QPushButton {{ background:#2e2e36; border:1px solid #3a3a42; border-radius:14px; padding:5px 14px; }}
    QDialog QPushButton:hover {{ background:{a}; }}
    QToolTip {{ background:#222; color:#eee; border:1px solid #444; border-radius:4px; padding:3px 6px; }}
    """


def bubble(icon, tip, obj=None):
    b = QPushButton(IC[icon])
    b.setProperty("bubble", obj is None)
    if obj:
        b.setObjectName(obj)
        b.setFont(QFont(ICON_FONT))
    b.setToolTip(tip)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


TW, TH = 96, 54   # 缩略图尺寸（小缩略图，减少列表对画面的干扰）


def rounded(img: QImage, dur_ms=0):
    """把截图做成圆角缩略图，右下角标时长"""
    pm = QPixmap(TW, TH)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, TW, TH), 8, 8)
    p.setClipPath(path)
    p.fillRect(0, 0, TW, TH, QColor(40, 40, 46))
    if img is not None and not img.isNull():
        s = img.scaled(TW, TH, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
        p.drawImage((TW - s.width()) // 2, (TH - s.height()) // 2, s)
    else:
        f = QFont(ICON_FONT)
        f.setPixelSize(26)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 120))
        p.drawText(QRect(0, 0, TW, TH), Qt.AlignmentFlag.AlignCenter, IC["play"])
    if dur_ms > 0:
        t = fmt(dur_ms)
        f = QFont("Segoe UI")
        f.setPixelSize(11)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(t) + 10
        r = QRectF(TW - w - 4, TH - 20, w, 16)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(r, 4, 4)
        p.setPen(QColor("white"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, t)
    p.end()
    return pm


class Thumbnailer(QObject):
    """后台逐个截取视频画面（约 10% 处）作为缩略图，并缓存到磁盘"""
    ready = pyqtSignal(str, QImage, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        os.makedirs(THUMB_DIR, exist_ok=True)
        self.queue, self.cur, self.target = [], None, 0
        self.p = self.sink = None              # 解码器按需创建，空闲时释放内存
        self.timeout = QTimer(self, singleShot=True, interval=8000)
        self.timeout.timeout.connect(lambda: self._done(None))
        self.resume = QTimer(self, singleShot=True)
        self.resume.timeout.connect(self._next)

    def hold(self, ms=3000):
        """主视频刚打开时暂停生成，避免抢占解码器造成开播卡顿"""
        if self.cur is None:
            self.resume.start(ms)
        else:
            self.queue.insert(0, self.cur)
            self._abort()
            self.resume.start(ms)

    def _make(self):
        self.p = QMediaPlayer(self)            # 不接音频输出 → 静音
        self.sink = QVideoSink(self)
        self.p.setVideoSink(self.sink)
        self.sink.videoFrameChanged.connect(self._frame)
        self.p.mediaStatusChanged.connect(self._status)
        self.p.errorOccurred.connect(lambda *a: self._done(None))

    def _release(self):
        if self.p:
            self.p.stop()
            self.p.deleteLater()
            self.sink.deleteLater()
        self.p = self.sink = None

    def _abort(self):
        self.cur = None
        self.timeout.stop()
        if self.p:
            self.p.stop()
            self.p.setSource(QUrl())

    @staticmethod
    def _key(path):
        try:
            st = os.stat(path)
            raw = f"{path}|{st.st_mtime}|{st.st_size}"
        except OSError:
            raw = path
        return os.path.join(THUMB_DIR, hashlib.md5(raw.encode("utf-8")).hexdigest())

    def request(self, path):
        k = self._key(path)
        if os.path.exists(k + ".jpg"):
            dur = 0
            try:
                dur = int(open(k + ".txt").read())
            except (OSError, ValueError):
                pass
            self.ready.emit(path, QImage(k + ".jpg"), dur)
            return
        if "://" in path or os.path.splitext(path)[1].lower() in {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus"}:
            return
        self.queue.append(path)
        if self.cur is None and not self.resume.isActive():
            self.resume.start(0)

    def _next(self):
        if self.resume.isActive() or self.cur is not None:
            return
        if not self.queue:
            self._release()
            return
        if self.p is None:
            self._make()
        self.cur = self.queue.pop(0)
        self.target = 0
        self.timeout.start()
        self.p.setSource(QUrl.fromLocalFile(self.cur))

    def _status(self, st):
        if self.cur and st == QMediaPlayer.MediaStatus.LoadedMedia:
            d = self.p.duration()
            self.target = int(d * 0.1) if d > 0 else 0
            if self.target:
                self.p.setPosition(self.target)
            self.p.play()

    def _frame(self, frame):
        if self.cur and frame.isValid() and self.p.position() >= self.target - 300:
            img = frame.toImage()
            if not img.isNull():
                self._done(img.scaled(TW * 2, TH * 2, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                      Qt.TransformationMode.SmoothTransformation))

    def _done(self, img):
        if self.cur is None:
            return
        path, dur = self.cur, max(self.p.duration(), 0)
        self.cur = None
        self.timeout.stop()
        self.p.stop()
        self.p.setSource(QUrl())
        if img is not None:
            k = self._key(path)
            img.save(k + ".jpg", "JPG", 88)
            with open(k + ".txt", "w") as f:
                f.write(str(dur))
        self.ready.emit(path, img if img is not None else QImage(), dur)
        QTimer.singleShot(0, self._next)


def dock(*widgets, spacing=6):
    """半透明胶囊底板，把一组按键托起来"""
    f = QFrame()
    f.setObjectName("dock")
    l = QHBoxLayout(f)
    l.setContentsMargins(6, 5, 6, 5)
    l.setSpacing(spacing)
    for w in widgets:
        l.addWidget(w)
    return f


class SeekSlider(QSlider):
    """细进度条：控件高 20px 作为命中区；点击处即定位，悬停/拖动时显示时间，松手后跳转"""
    hovered = pyqtSignal(int, int)
    left = pyqtSignal()

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setObjectName("seek")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _val(self, x):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(x), self.width())

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.setValue(self._val(e.position().x()))   # 圆点移到点击处，随即进入拖动
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        x = int(e.position().x())
        self.hovered.emit(self._val(x), max(0, min(self.width(), x)))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.left.emit()
        super().leaveEvent(e)


class PlayButton(QPushButton):
    """播放键：浅色实心圆 + 深色图标，自绘交互反馈
    - 悬停：底色提亮，外圈出现淡淡光环
    - 按下：圆形缩小到 88%，底色加深
    - 松开：带回弹放大回原尺寸，并向外扩散一圈波纹
    - 播放/暂停切换：图标弹一下
    """
    def __init__(self, glyph, tip):
        super().__init__(glyph)
        self.setObjectName("playBtn")
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._scale, self._ripple, self._icon = 1.0, 0.0, 1.0
        self._hover = 0.0
        self.a_scale = self._anim("_scale")
        self.a_ripple = self._anim("_ripple")
        self.a_icon = self._anim("_icon")
        self.a_hover = self._anim("_hover")

    def _anim(self, attr):
        from PyQt6.QtCore import QVariantAnimation
        a = QVariantAnimation(self)
        a.valueChanged.connect(lambda v, attr=attr: (setattr(self, attr, float(v)), self.update()))
        return a

    def _run(self, a, start, end, ms, curve=QEasingCurve.Type.OutCubic):
        a.stop()
        a.setStartValue(float(start))
        a.setEndValue(float(end))
        a.setDuration(ms)
        a.setEasingCurve(curve)
        a.start()

    def enterEvent(self, e):
        self._run(self.a_hover, self._hover, 1.0, 160)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._run(self.a_hover, self._hover, 0.0, 220)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._run(self.a_scale, self._scale, 0.88, 90)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._run(self.a_scale, self._scale, 1.0, 260, QEasingCurve.Type.OutBack)
        if self.rect().contains(e.position().toPoint()):
            self._run(self.a_ripple, 0.0, 1.0, 520)
        super().mouseReleaseEvent(e)

    def bounce(self):
        """图标切换时弹一下"""
        self._run(self.a_icon, 0.55, 1.0, 300, QEasingCurve.Type.OutBack)

    def paintEvent(self, e):
        from PyQt6.QtGui import QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.rect().center()
        cx, cy = c.x() + 0.5, c.y() + 0.5
        base_r = px(20)
        r = base_r * self._scale
        # 波纹：从圆边向外扩散并淡出
        if 0 < self._ripple < 1:
            rr = base_r * (1 + 0.32 * self._ripple)
            pen = QPen(QColor(255, 255, 255, int(150 * (1 - self._ripple))), max(1.5, px(2) * (1 - self._ripple) + 0.5))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))
        # 悬停光环
        if self._hover > 0:
            hr = base_r + px(3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(40 * self._hover)))
            p.drawEllipse(QRectF(cx - hr, cy - hr, hr * 2, hr * 2))
        # 实心圆
        fill = QColor("#c9c9ce") if self.isDown() else QColor(242, 242, 244).lighter(100 + int(6 * self._hover))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        # 图标
        f = QFont(ICON_FONT)
        f.setPixelSize(max(6, int(px(16) * self._scale * self._icon)))
        p.setFont(f)
        p.setPen(QColor("#16161a"))
        p.drawText(QRectF(cx - r, cy - r, r * 2, r * 2), Qt.AlignmentFlag.AlignCenter, self.text())


class FramePreview(QObject):
    """进度条预览取帧（内存优先，其次流畅）

    用 PyAV 在后台线程里单线程软解，不另开硬件解码器（硬解 4K 会额外占几百 MB）：
    - 拖动中：只解「目标位置前最近的关键帧」，约 50ms 一张，且直接缩放到预览尺寸；
    - 停顿 0.3 秒：再从关键帧往后解到精确画面（最多 1.5 秒，超时用最近一帧）；
    - 最新优先：只处理最新的请求，旧请求直接丢弃，拖多快都不积压；
    - 压缩缓存：预览帧存成 JPEG 字节（约 6–10KB/帧，最多 160 帧 ≈ 1–1.5MB）；
    - 按需：只在鼠标停在进度条上或拖动时预取，离开 4 秒后关闭文件、释放解码内存。
    """
    ready = pyqtSignal(QImage, int)
    _done = pyqtSignal(QImage, int, int, bool)     # 后台线程 → 主线程（排队连接）
    MAX_CACHE = 160

    def __init__(self, parent=None):
        super().__init__(parent)
        import threading
        self._done.connect(self._on_done, Qt.ConnectionType.QueuedConnection)
        from collections import OrderedDict
        self.cache = OrderedDict()            # 桶号 -> jpeg bytes
        self.src = None
        self.path = None
        self.dur = 0
        self.cv = threading.Condition()
        self.job = None                       # (ms, exact) 最新的用户请求
        self.prefill = []
        self.alive_until = 0.0
        self.gen = 0                          # 换视频时递增，作废旧结果
        self.box = px(208)                    # 预览尺寸在主线程算好（QSettings 不能跨线程读）
        self.th = threading.Thread(target=self._loop, daemon=True)
        self.th.start()

    # ---------- 缓存 ----------
    def _step(self):
        return max(1000, self.dur // self.MAX_CACHE) if self.dur > 0 else 2000

    def lookup(self, ms):
        if not self.cache:
            return None
        b = ms // self._step()
        for k in (b, b - 1, b + 1):
            if k in self.cache:
                self.cache.move_to_end(k)
                return QImage.fromData(self.cache[k], "JPG")
        return None

    def _store(self, img, ms):
        from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPG", 82)
        k = ms // self._step()
        self.cache[k] = bytes(ba)
        self.cache.move_to_end(k)
        while len(self.cache) > self.MAX_CACHE:
            self.cache.popitem(last=False)

    # ---------- 对外接口（主线程） ----------
    def set_source(self, src: QUrl, dur):
        if src != self.src:
            with self.cv:
                self.src = src
                self.path = src.toLocalFile() if src.isLocalFile() else src.toString()
                self.dur = dur
                self.cache.clear()
                self.prefill = []
                self.job = None
                self.gen += 1
                self.cv.notify()
        elif dur > 0:
            self.dur = dur

    def touch(self):
        """用户正在和进度条交互：保持文件打开并在空闲时预取"""
        import time
        self.box = px(208)
        with self.cv:
            self.alive_until = time.monotonic() + 4.0
            if not self.prefill and self.dur > 0:
                step = self._step()
                ks = [k for k in range(self.dur // step + 1) if k not in self.cache]
                # 从中间向两边交替排列，任何位置都能较早有图
                mid = len(ks) // 2
                order = []
                for i in range(len(ks)):
                    j = mid + (i + 1) // 2 * (1 if i % 2 else -1)
                    if 0 <= j < len(ks):
                        order.append(ks[j] * step + step // 2)
                self.prefill = order
            self.cv.notify()

    def request(self, ms, exact=False):
        import time
        with self.cv:
            self.job = (ms, exact)
            self.alive_until = time.monotonic() + 4.0
            self.cv.notify()

    def done(self):
        with self.cv:
            self.job = None

    def release(self):
        with self.cv:
            self.alive_until = 0
            self.job = None
            self.prefill = []
            self.cv.notify()

    # ---------- 后台线程 ----------
    def _emit(self, img, ms, gen, user):
        self._done.emit(img, ms, gen, user)

    def _on_done(self, img, ms, gen, user):
        # 主线程：存缓存、通知界面
        if gen != self.gen:
            return
        self._store(img, ms)
        if user:
            self.ready.emit(img, ms)

    def _decode(self, c, vs, ms, exact):
        """解出 ms 处（或之前最近关键帧）的画面，直接缩放到预览尺寸，返回 QImage"""
        import time
        tb = vs.time_base
        c.seek(int(ms / 1000 / tb), stream=vs, backward=True, any_frame=False)
        vs.codec_context.skip_frame = "DEFAULT" if exact else "NONKEY"
        target = ms / 1000
        last = None
        t0 = time.monotonic()
        for pkt in c.demux(vs):
            if not exact and not pkt.is_keyframe:
                continue
            for fr in pkt.decode():
                last = fr
                if not exact or fr.time is None or fr.time >= target - 0.02 or time.monotonic() - t0 > 1.5:
                    break
            else:
                continue
            break
        if last is None:
            return None
        W = B = self.box
        H = max(2, int(W * last.height / max(1, last.width)) // 2 * 2)
        if H > B:
            H = B; W = max(2, int(H * last.width / max(1, last.height)) // 2 * 2)
        rgb = last.reformat(width=W, height=H, format="rgb24")
        pl = rgb.planes[0]
        img = QImage(bytes(pl), W, H, pl.line_size, QImage.Format.Format_RGB888).copy()
        return img

    def _loop(self):
        import time
        c = vs = None
        opened = None
        while True:
            with self.cv:
                while True:
                    now = time.monotonic()
                    if self.job is not None or (self.prefill and now < self.alive_until):
                        break
                    if c is not None and now >= self.alive_until:
                        break                         # 闲置：关闭文件释放内存
                    self.cv.wait(timeout=max(0.2, self.alive_until - now) if c is not None else None)
                gen, path = self.gen, self.path
                if self.job is not None:
                    (ms, exact), user = self.job, True
                    self.job = None
                elif self.prefill and time.monotonic() < self.alive_until:
                    ms, exact, user = self.prefill.pop(0), False, False
                    if ms // self._step() in self.cache:
                        continue
                else:
                    ms = None
            if ms is None:
                if c is not None:
                    c.close(); c = vs = None; opened = None
                    import gc
                    gc.collect()
                    try:   # 把解码器释放的堆内存还给系统
                        import ctypes
                        ctypes.cdll.ucrtbase._heapmin()
                        ctypes.windll.kernel32.SetProcessWorkingSetSize(
                            ctypes.windll.kernel32.GetCurrentProcess(), ctypes.c_size_t(-1), ctypes.c_size_t(-1))
                    except Exception:
                        pass
                continue
            try:
                if opened != (gen, path):
                    if c is not None:
                        c.close()
                    import av
                    c = av.open(path, options={"probesize": "2000000"}) if "://" in path else av.open(path)
                    vs = c.streams.video[0]
                    vs.thread_type = "NONE"
                    vs.codec_context.thread_count = 1
                    opened = (gen, path)
                img = self._decode(c, vs, ms, exact)
                if img is not None and gen == self.gen:
                    self._emit(img, ms, gen, user)
            except Exception:
                try:
                    if c is not None:
                        c.close()
                except Exception:
                    pass
                c = vs = None; opened = None
                time.sleep(0.05)


class PreviewPopup(QFrame):
    """跟随进度条滑块的画面预览小窗"""
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("preview")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        v = QVBoxLayout(self)
        v.setContentsMargins(px(4), px(4), px(4), px(4))
        v.setSpacing(px(4))
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setObjectName("previewImg")
        self.t = QLabel()
        self.t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.t.setObjectName("previewTime")
        v.addWidget(self.img)
        v.addWidget(self.t)
        self.hide()

    def set_box(self, w, h):
        self.img.setFixedSize(w, h)
        self.adjustSize()

    def set_loading(self, on):
        self.img.setText("加载中…" if on and self.img.pixmap().isNull() else "")

    def set_image(self, img):
        pm = QPixmap.fromImage(img).scaled(self.img.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation)
        self.img.setPixmap(pm)

    def clear(self):
        self.img.setPixmap(QPixmap())


class Spinner(QWidget):
    """网络视频缓冲时显示在播放键旁的小型加载提示"""
    def __init__(self):
        super().__init__()
        self.setFixedSize(px(22), px(22))
        self.angle = 0
        self.t = QTimer(self, interval=40)
        self.t.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self.angle = (self.angle + 30) % 360
        self.update()

    def setVisible(self, on):
        super().setVisible(on)
        self.t.start() if on else self.t.stop()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        from PyQt6.QtGui import QPen
        pen = QPen(QColor(255, 255, 255, 220), max(2, px(2)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        r = self.rect().adjusted(px(4), px(4), -px(4), -px(4))
        p.drawArc(r, -self.angle * 16, 270 * 16)


class Bar(QWidget):
    """渐变半透明背景的控制栏"""
    def __init__(self, top):
        super().__init__()
        self.top = top
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(1)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setDuration(250)

    def paintEvent(self, e):
        if not self.top:      # 底部用浮动面板自身的背景，不画渐变
            return
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        a = int(255 * cfg("bar_opacity") / 100)
        c0, c1 = QColor(0, 0, 0, a), QColor(0, 0, 0, 0)
        g.setColorAt(0, c0 if self.top else c1)
        g.setColorAt(1, c1 if self.top else c0)
        p.fillRect(self.rect(), g)

    def fade(self, show):
        target = 1.0 if show else 0.0
        if show:
            self.show()
        self.anim.stop()
        self.anim.setStartValue(self.eff.opacity())
        self.anim.setEndValue(target)
        try:
            self.anim.finished.disconnect()
        except TypeError:
            pass
        if not show:
            self.anim.finished.connect(self.hide)
        self.anim.start()


class Bubble(QLabel):
    """屏幕中央的气泡提示（播放/暂停/音量/速度等）"""
    def __init__(self, parent, size=96, font=36, icon=True):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = QFont(ICON_FONT if icon else "Microsoft YaHei UI")
        f.setPixelSize(font)
        self.setFont(f)
        self.setFixedSize(size, size) if icon else self.setMinimumHeight(40)
        r = size // 2 if icon else 20
        self.setStyleSheet(f"background:rgba(0,0,0,0.55); border-radius:{r}px; padding:0 16px; color:white;")
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setEasingCurve(QEasingCurve.Type.InQuad)
        self.hide()

    def flash(self, text, ms=700):
        self.setText(text)
        if not self.minimumWidth() or self.maximumWidth() > 10000:
            self.adjustSize()
        self.parent().layout_overlays()
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setDuration(ms)
        self.anim.setStartValue(1.0)
        self.anim.setKeyValueAt(0.6, 1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()


VIDEO_QML = """
import QtQuick
import QtQuick.Effects
import QtMultimedia
Rectangle {
    id: root
    color: "black"
    property alias output: vo
    // 播放列表抽屉后面的高斯模糊区域（由 Python 设置位置；宽度为 0 时不渲染，不耗 GPU）
    property real blurX: 0
    property real blurY: 0
    property real blurW: 0
    property real blurH: 0
    VideoOutput { id: vo; objectName: "vo"; anchors.fill: parent; fillMode: VideoOutput.PreserveAspectFit }
    Item {
        id: blurBox
        x: root.blurX; y: root.blurY; width: root.blurW; height: root.blurH
        visible: width > 1
        clip: true
        ShaderEffectSource {
            id: snap
            anchors.fill: parent
            sourceItem: vo
            sourceRect: Qt.rect(blurBox.x, blurBox.y, blurBox.width, blurBox.height)
            live: true
            visible: false
        }
        Rectangle { anchors.fill: parent; color: root.color }
        MultiEffect {
            anchors.fill: parent
            source: snap
            blurEnabled: true
            blur: 1.0
            blurMax: 48
            autoPaddingEnabled: false
        }
    }
}
""".encode("utf-8")


class VideoView(QQuickWidget):
    """GPU 零拷贝渲染：硬解出的帧直接作为纹理显示，不回读到内存"""
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self.setClearColor(QColor(cfg("bg_color")))
        comp = QQmlComponent(self.engine())
        comp.setData(VIDEO_QML, QUrl())
        self.root = comp.create(self.engine().rootContext())
        self._comp = comp
        self.setContent(QUrl(), comp, self.root)
        self.item = self.root.findChild(QObject, "vo")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.click_timer = QTimer(self, singleShot=True, interval=230)
        self.click_timer.timeout.connect(win.toggle_play)
        self.apply_bg()

    def apply_bg(self):
        c = QColor(cfg("bg_color"))
        self.setClearColor(c)
        self.root.setProperty("color", c)

    def mouseMoveEvent(self, e):
        # 小窗/普通窗口下按住画面拖动超过几像素 → 移动窗口（不触发暂停）
        p0 = getattr(self, "_press", None)
        if p0 is not None and e.buttons() & Qt.MouseButton.LeftButton and \
                not (self.win.isFullScreen() or self.win.isMaximized()) and \
                (e.position() - p0).manhattanLength() > 6:
            self._press = None
            self.click_timer.stop()
            if self.win.windowHandle():
                self.win.windowHandle().startSystemMove()

    def mouseReleaseEvent(self, e):
        # 单击在松开时才生效（按住拖动不会暂停）；双击的第二次松开不再触发
        if e.button() == Qt.MouseButton.LeftButton and self._press is not None \
                and not getattr(self, "_dbl", False):
            self.click_timer.start()
        self._dbl = False
        self._press = None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press = e.position()
        elif e.button() == Qt.MouseButton.RightButton:
            self.win.main_menu().exec(e.globalPosition().toPoint())

    def mouseDoubleClickEvent(self, e):
        self.click_timer.stop()
        self._dbl = True
        self._press = None
        self.win.toggle_fullscreen()

    def wheelEvent(self, e):
        self.win.change_volume(5 if e.angleDelta().y() > 0 else -5)


class Stage(QWidget):
    """视频 + 浮层（顶栏/底栏/播放列表/气泡）"""
    def __init__(self, win):
        super().__init__()
        self.setObjectName("stage")
        self.win = win
        self.view = VideoView(win)
        self.view.setParent(self)

    def layout_overlays(self):
        w, h = self.width(), self.height()
        win = self.win
        if not hasattr(win, "empty"):
            return
        th = 0 if win.isFullScreen() else win.titlebar.height()
        win.titlebar.setGeometry(0, 0, w, win.titlebar.height())
        # 播放列表：右侧抽屉，盖在画面上（70% 透明背景）；窄窗口时占满宽度
        PW = px(340) if w >= px(520) else w
        dx = int(PW * win.pl_p)
        vw = w - dx if w >= px(700) else w        # 控制栏可用宽度（宽窗口时让出抽屉）
        self.view.setGeometry(0, 0, w, h)
        # 顶部（渐变铺到窗口顶边，内容让到标题栏下方）
        # 顶部渐变铺满整个窗口宽度，按钮让到抽屉左侧（避免抽屉上方出现一块断层）
        win.top.layout().setContentsMargins(px(16), th + px(6), px(12) + (w - vw), px(6))
        win.adapt_top(vw)
        win.top.setGeometry(0, 0, w, th + px(38) + px(12))
        # 底部浮动面板
        M = px(14)
        win.adapt_bottom(vw - 2 * M)
        bh = win.bottom.sizeHint().height()
        win.bottom.setGeometry(M, h - bh - M, vw - 2 * M, bh)
        r = self.view.root
        if win.playlist.isVisible():
            # 抽屉从窗口顶边开始（标题栏半透明盖在其上），内容用上边距让出标题栏
            win.playlist.layout().setContentsMargins(px(10), th + px(12), px(10), px(10))
            win.playlist.setGeometry(w - dx, 0, PW, h)
            win.playlist.raise_()
            # 抽屉背后的视频做高斯模糊（视频层坐标 = stage 坐标）
            for k, val in (("blurX", w - dx), ("blurY", 0), ("blurW", dx), ("blurH", h)):
                r.setProperty(k, float(val))
        else:
            r.setProperty("blurW", 0.0)
        hw, hh = px(20), px(72)
        win.pl_handle.setGeometry(w - dx - hw, th + (h - th - hh) // 2, hw, hh)
        win.pl_handle.raise_()
        # 首次打开提示
        win.empty.adjustSize()
        win.empty.move((vw - win.empty.width()) // 2, (h - win.empty.height()) // 2)
        cx = vw // 2
        win.center.move(cx - win.center.width() // 2, h // 2 - win.center.height() // 2)
        win.osd.adjustSize()
        win.osd.move(cx - win.osd.width() // 2, th + px(64))
        win.titlebar.raise_()

    def resizeEvent(self, e):
        self.layout_overlays()


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("个性化设置")
        self.setMinimumWidth(380)
        self.win = win
        f = QFormLayout(self)
        f.setSpacing(12)
        self.accent = cfg("accent")
        self.bg = cfg("bg_color")
        self.btn_accent = QPushButton(); self.btn_accent.clicked.connect(lambda: self.pick("accent"))
        self.btn_bg = QPushButton(); self.btn_bg.clicked.connect(lambda: self.pick("bg"))
        self.refresh_colors()
        self.opacity = QSpinBox(); self.opacity.setRange(0, 100); self.opacity.setSuffix(" %"); self.opacity.setValue(cfg("bar_opacity"))
        self.delay = QDoubleSpinBox(); self.delay.setRange(1, 10); self.delay.setSingleStep(0.5); self.delay.setSuffix(" 秒"); self.delay.setValue(cfg("hide_delay"))
        self.scale = QSpinBox(); self.scale.setRange(70, 160); self.scale.setSingleStep(10); self.scale.setSuffix(" %"); self.scale.setValue(cfg("ui_scale"))
        self.step = QSpinBox(); self.step.setRange(1, 60); self.step.setSuffix(" 秒"); self.step.setValue(cfg("seek_step"))
        self.vol = QSpinBox(); self.vol.setRange(0, 100); self.vol.setSuffix(" %"); self.vol.setValue(cfg("volume"))
        self.checks = {}
        f.addRow("主题色", self.btn_accent)
        f.addRow("视频背景色", self.btn_bg)
        f.addRow("控制栏背景浓度", self.opacity)
        f.addRow("控制栏自动隐藏", self.delay)
        f.addRow("界面大小", self.scale)
        f.addRow("快进/快退步长", self.step)
        f.addRow("默认音量", self.vol)
        self.trans_ms = QSpinBox(); self.trans_ms.setRange(200, 2000); self.trans_ms.setSingleStep(100)
        self.trans_ms.setSuffix(" 毫秒"); self.trans_ms.setValue(cfg("transition_ms"))
        self.trans_ms.setToolTip("淡出、淡入各用这么长时间")
        f.addRow("过渡时长", self.trans_ms)
        for k, t in (("remember_pos", "记住每个视频的播放进度"), ("remember_list", "记住播放列表"),
                     ("auto_next", "播放结束自动下一个"), ("mini_on_top", "小窗模式始终置顶"),
                     ("show_osd", "显示操作提示气泡"),
                     ("transition", "切换上一个/下一个时平滑过渡（画面与声音淡出淡入）"),
                     ("hw_decode", "硬件解码（重启生效）")):
            c = QCheckBox(t); c.setChecked(cfg(k)); self.checks[k] = c; f.addRow(c)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                              | QDialogButtonBox.StandardButton.RestoreDefaults)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("恢复默认")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(self.reset)
        f.addRow(bb)

    def refresh_colors(self):
        for b, c in ((self.btn_accent, self.accent), (self.btn_bg, self.bg)):
            b.setText(c)
            fg = "black" if QColor(c).lightness() > 140 else "white"
            b.setStyleSheet(f"background:{c}; color:{fg}; border-radius:6px; padding:6px;")

    def pick(self, which):
        cur = self.accent if which == "accent" else self.bg
        c = QColorDialog.getColor(QColor(cur), self, "选择颜色")
        if c.isValid():
            setattr(self, "accent" if which == "accent" else "bg", c.name())
            self.refresh_colors()

    def reset(self):
        for k in DEFAULTS:
            if k not in ("play_mode",):
                CFG.remove(k)
        self.win.apply_settings()
        self.reject()

    def save(self):
        CFG.setValue("accent", self.accent)
        CFG.setValue("bg_color", self.bg)
        CFG.setValue("bar_opacity", self.opacity.value())
        CFG.setValue("hide_delay", self.delay.value())
        CFG.setValue("seek_step", self.step.value())
        CFG.setValue("ui_scale", self.scale.value())
        CFG.setValue("volume", self.vol.value())
        CFG.setValue("transition_ms", self.trans_ms.value())
        for k, c in self.checks.items():
            CFG.setValue(k, c.isChecked())
        self.win.apply_settings()
        self.accept()


class Player(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP)
        self.resize(1280, 760)
        self.setMinimumSize(360, 220)
        self.setAcceptDrops(True)
        self.files, self.idx = [], -1
        self.pending_seek = 0
        self.mini = False
        self.normal_geo = None

        self.setWindowIcon(QIcon(LOGO))
        self.thumbs = Thumbnailer(self)
        self.thumbs.ready.connect(self._thumb_ready)
        self.placeholder = rounded(None)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.fx = AudioEngine(self.player, self.audio, self)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.WindowMinMaxButtonsHint)
        QApplication.instance().installEventFilter(frame.EdgeResizer(self))

        self.titlebar = frame.TitleBar(self, APP, LOGO, ICON_FONT,
                                       dict(min=IC["wmin"], max=IC["wmax"], restore=IC["wrestore"], close=IC["wclose"]))
        self.stage = Stage(self)
        self.setCentralWidget(self.stage)
        # 标题栏放进视频区域做浮层，和其他控制栏一起淡入淡出
        self.titlebar.setParent(self.stage)
        self.titlebar.eff = QGraphicsOpacityEffect(self.titlebar)
        self.titlebar.setGraphicsEffect(self.titlebar.eff)
        self.titlebar.anim = QPropertyAnimation(self.titlebar.eff, b"opacity", self.titlebar)
        self.titlebar.anim.setDuration(250)
        self.player.setVideoOutput(self.stage.view.item)

        self._build_top()
        self._build_bottom()
        self._build_playlist()
        self._build_empty()
        self.full_title = ""
        self.center = Bubble(self.stage)
        self.osd = Bubble(self.stage, font=17, icon=False)

        self.player.positionChanged.connect(self.on_pos)
        self.player.durationChanged.connect(self.on_dur)
        self.player.playbackStateChanged.connect(self.on_state)
        self.player.mediaStatusChanged.connect(self.on_status)
        self.player.metaDataChanged.connect(self.show_info)
        self.player.errorOccurred.connect(lambda e, s: self.flash_osd(f"无法播放：{s}", 3000))

        self.hide_timer = QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.auto_hide)
        self.save_timer = QTimer(self, interval=5000)
        self.save_timer.timeout.connect(self.save_position)
        self.save_timer.start()
        QApplication.instance().installEventFilter(self)
        self._shortcuts()
        self.apply_settings()
        self.audio.setVolume(cfg("volume") / 100)
        self.vol.setValue(cfg("volume"))
        self.set_mode(cfg("play_mode"))
        if cfg("remember_list"):
            self._load_lists()
        else:
            self._refresh_combo()
        self.show_controls()

    # ================= UI 构建 =================
    def _build_top(self):
        """视频区顶部：只放当前文件名、打开文件、播放列表入口；分辨率仅在空间足够时显示"""
        self.top = Bar(top=True)
        self.top.setParent(self.stage)
        l = QHBoxLayout(self.top)
        l.setSpacing(px(6))
        self.title = QLabel("")
        self.title.setObjectName("title")
        self.info = QLabel("")            # 分辨率（编码、帧率放进「视频详情」）
        self.info.setObjectName("res")
        self.btn_open = bubble("open", "打开文件 (O)")
        self.btn_open.clicked.connect(self.open_files)
        self.btn_list = bubble("list", "播放列表 (L)")
        self.btn_list.clicked.connect(self.toggle_playlist)
        l.addWidget(self.title)
        l.addSpacing(px(8))
        l.addWidget(self.info)
        l.addStretch(1)
        l.addWidget(self.btn_open)
        self.btn_list.hide()                 # 播放列表入口改为右侧边缘把手

    def _build_bottom(self):
        """底部：一块低对比度浮动面板。上排细进度条，下排常用按钮"""
        self.bottom = Bar(top=False)
        self.bottom.setParent(self.stage)
        outer = QVBoxLayout(self.bottom)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("panel")
        outer.addWidget(panel)
        v = QVBoxLayout(panel)
        v.setContentsMargins(px(14), px(6), px(10), px(6))
        v.setSpacing(0)
        self.seek = SeekSlider()
        self.seek.setRange(0, 0)
        self.seek.sliderPressed.connect(self._seek_drag)
        self.seek.sliderMoved.connect(self._seek_drag)
        self.seek.sliderReleased.connect(self._seek_release)
        self.seek.hovered.connect(self._seek_hover)
        self.seek.left.connect(lambda: self.seek.isSliderDown() or self.drag_lbl.hide())
        v.addWidget(self.seek)

        r = QHBoxLayout()
        r.setSpacing(px(2))
        self.btn_prev = bubble("prev", "上一项 (PgUp)")
        self.btn_prev.clicked.connect(lambda: self.step_list(-1))
        self.btn_play = PlayButton(IC["play"], "播放/暂停 (空格)")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_next = bubble("next", "下一项 (PgDn)")
        self.btn_next.clicked.connect(lambda: self.step_list(1))
        self.spinner = Spinner()
        self.btn_vol = bubble("vol", "静音 (M)")
        self.btn_vol.clicked.connect(self._vol_clicked)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setFixedWidth(px(96))
        self.vol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol.valueChanged.connect(self._vol_changed)
        self.time = QLabel("00:00 / 00:00")
        self.time.setObjectName("time")
        self.time.setContentsMargins(px(8), 0, px(8), 0)
        self.btn_speed = QPushButton("1×")
        self.btn_speed.setObjectName("pill")
        self.btn_speed.setToolTip("播放速度  [ / ] 微调  \\ 复位")
        self.btn_speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_speed.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_speed.clicked.connect(self.speed_menu)
        self.btn_more = bubble("more", "更多")
        self.btn_more.clicked.connect(self.more_menu)
        self.btn_full = bubble("full", "全屏 (F)")
        self.btn_full.clicked.connect(self.toggle_fullscreen)
        for wd in (self.btn_prev, self.btn_play, self.btn_next, self.spinner, self.btn_vol, self.vol, self.time):
            r.addWidget(wd)
        r.addStretch(1)
        for wd in (self.btn_speed, self.btn_more, self.btn_full):
            r.addWidget(wd)
        v.addLayout(r)
        self.bottom_row = r
        self.row_widgets = [self.btn_prev, self.btn_play, self.btn_next, self.spinner, self.btn_vol,
                            self.vol, self.time, self.btn_speed, self.btn_more, self.btn_full]
        # 兼容旧代码：低频功能已移入「更多」
        self.btn_mode = QPushButton(); self.btn_mini = QPushButton(); self.btn_fx = QPushButton()
        self.level = -1
        self.time_short = False
        # 拖动/悬停进度条时跟随的时间标签
        self.drag_lbl = QLabel(self.stage)
        self.drag_lbl.setObjectName("drag")
        self.drag_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.drag_lbl.hide()
        # 拖动进度条时的画面预览：停顿 0.5 秒后加载滑块位置的画面
        self.preview = PreviewPopup(self.stage)
        self.framer = FramePreview(self)
        self.framer.ready.connect(self._preview_ready)
        self.prev_timer = QTimer(self, singleShot=True, interval=300)
        self.prev_timer.timeout.connect(self._preview_load)

    def _build_empty(self):
        """首次打开：画面中央的「打开文件」与拖放提示"""
        self.empty = QWidget(self.stage)
        v = QVBoxLayout(self.empty)
        v.setSpacing(px(12))
        b = QPushButton("打开文件")
        b.setObjectName("openBig")
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(self.open_files)
        hint = QLabel("也可以将文件拖到这里")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(hint)
        self.empty_btn = b

    def _build_playlist(self):
        """右侧抽屉式播放列表：边缘把手点开，可建多个自定义列表"""
        self.playlist = QFrame(self.stage)
        self.playlist.setObjectName("playlist")
        v = QVBoxLayout(self.playlist)
        v.setContentsMargins(px(10), px(12), px(10), px(10))
        v.setSpacing(px(6))
        # 第一行：列表选择 + 新建 / 更多 / 关闭
        h = QHBoxLayout()
        h.setSpacing(px(2))
        self.pl_combo = QComboBox()
        self.pl_combo.setObjectName("plCombo")
        self.pl_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pl_combo.setToolTip("切换播放列表")
        self.pl_combo.activated.connect(lambda i: self.switch_playlist(self.pl_combo.itemText(i)))
        b_new = bubble("add", "新建播放列表")
        b_new.clicked.connect(self.new_playlist)
        self.pl_more = bubble("more", "重命名 / 删除列表")
        self.pl_more.clicked.connect(self._pl_menu)
        close = bubble("close", "收起 (L)")
        close.clicked.connect(self.toggle_playlist)
        h.addWidget(self.pl_combo, 1)
        h.addWidget(b_new)
        h.addWidget(self.pl_more)
        h.addWidget(close)
        v.addLayout(h)
        # 第二行：添加文件 / 文件夹 / 移除 / 清空 + 数量
        h2 = QHBoxLayout()
        h2.setSpacing(px(2))
        for ic, tip, fn in (("open", "添加文件", self.open_files), ("folder", "添加文件夹", self.open_folder),
                            ("delete", "移除选中", self.remove_selected), ("clear", "清空此列表", self.clear_list)):
            b = bubble(ic, tip)
            b.clicked.connect(fn)
            h2.addWidget(b)
        h2.addStretch(1)
        self.pl_count = QLabel("")
        self.pl_count.setObjectName("time")
        h2.addWidget(self.pl_count)
        v.addLayout(h2)
        self.list = QListWidget()
        self.list.setIconSize(QSize(TW, TH))
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.model().rowsMoved.connect(self._rows_moved)
        self.list.itemDoubleClicked.connect(lambda it: self.play_index(self.list.row(it)))
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._item_menu)
        v.addWidget(self.list, 1)
        self.playlist.hide()
        # 边缘把手：和其他控件一起定时隐藏
        self.pl_handle = QPushButton(IC["chev_l"], self.stage)
        self.pl_handle.setObjectName("plHandle")
        self.pl_handle.setFont(QFont(ICON_FONT))
        self.pl_handle.setToolTip("播放列表 (L)")
        self.pl_handle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pl_handle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.pl_handle.clicked.connect(self.toggle_playlist)
        self.pl_handle.eff = QGraphicsOpacityEffect(self.pl_handle)
        self.pl_handle.setGraphicsEffect(self.pl_handle.eff)
        self.pl_handle.anim = QPropertyAnimation(self.pl_handle.eff, b"opacity", self.pl_handle)
        self.pl_handle.anim.setDuration(250)
        from PyQt6.QtCore import QVariantAnimation
        self.pl_p = 0.0                       # 抽屉展开程度 0~1
        self.pl_open = False
        self.pl_anim = QVariantAnimation(self)
        self.pl_anim.setDuration(240)
        self.pl_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.pl_anim.valueChanged.connect(self._drawer_step)
        self.pl_anim.finished.connect(lambda: self.pl_open or self.playlist.hide())
        # 多个播放列表
        self.playlists = {DEFAULT_PL: []}
        self.cur_pl = DEFAULT_PL

    def _shortcuts(self):
        st = lambda: cfg("seek_step") * 1000
        keys = {
            "Space": self.toggle_play, "F": self.toggle_fullscreen, "Esc": self.escape,
            "Left": lambda: self.seek_by(-st()), "Right": lambda: self.seek_by(st()),
            "Up": lambda: self.change_volume(5), "Down": lambda: self.change_volume(-5),
            "M": self.toggle_mute, "P": self.toggle_mini, "L": self.toggle_playlist,
            "[": lambda: self.set_speed(self.player.playbackRate() - 0.1),
            "]": lambda: self.set_speed(self.player.playbackRate() + 0.1),
            "\\": lambda: self.set_speed(1.0), "O": self.open_files,
            "PgUp": lambda: self.step_list(-1), "PgDown": lambda: self.step_list(1),
        }
        for k, fn in keys.items():
            QShortcut(QKeySequence(k), self, fn)

    def apply_settings(self):
        QApplication.instance().setStyleSheet(stylesheet())
        self.stage.view.apply_bg()
        self.hide_timer.setInterval(int(cfg("hide_delay") * 1000))
        # 按界面大小调整固定尺寸
        self.titlebar.setFixedHeight(px(frame.TitleBar.H))
        self.titlebar.logo.setPixmap(QIcon(LOGO).pixmap(px(18), px(18)))
        self.vol.setFixedWidth(px(96))
        for s in (self.vol, self.seek):
            s.setFixedHeight(px(20))          # 3px 轨道 + 20px 鼠标命中区
        self.spinner.setFixedSize(px(22), px(22))
        self.list.setIconSize(QSize(px(TW), px(TH)))
        # 样式表在下一轮事件循环才生效，之后再按新尺寸排版
        QTimer.singleShot(0, self._relayout)
        QTimer.singleShot(50, self._relayout)
        self.top.update()
        self.bottom.update()
        if self.mini:
            self._set_on_top(cfg("mini_on_top"))

    def _relayout(self):
        for bar in (self.top, self.bottom):
            for wdg in bar.findChildren(QWidget):
                wdg.updateGeometry()
            bar.layout().invalidate()
            bar.layout().activate()
        self.stage.layout_overlays()

    # ================= 菜单 =================
    def main_menu(self):
        m = QMenu(self)
        m.addAction("打开文件…\tO", self.open_files)
        m.addAction("打开文件夹…", self.open_folder)
        m.addAction("打开网络地址…", self.open_url)
        m.addSeparator()
        m.addAction("播放 / 暂停\t空格", self.toggle_play)
        sp = m.addMenu("播放速度")
        for r in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0):
            a = sp.addAction(f"{r}x", lambda r=r: self.set_speed(r))
            a.setCheckable(True)
            a.setChecked(abs(self.player.playbackRate() - r) < 0.01)
        md = m.addMenu("播放模式")
        for i, (name, _) in enumerate(MODES):
            a = md.addAction(name, lambda i=i: self.set_mode(i, True))
            a.setCheckable(True)
            a.setChecked(i == self.mode)
        m.addSeparator()
        m.addAction("播放列表\tL", self.toggle_playlist)
        m.addAction("小窗模式\tP", self.toggle_mini)
        m.addAction("全屏\tF", self.toggle_fullscreen)
        m.addSeparator()
        m.addAction("音效…", self.open_audio_fx)
        m.addAction("视频详情…", self.show_details)
        m.addAction("设置…", lambda: SettingsDialog(self).exec())
        m.aboutToHide.connect(self.show_controls)
        return m

    # ================= 响应式布局 =================
    # 优先保留：播放键、当前时间、全屏。窗口越窄折叠级别越高：
    # 0 全部展开（含音量滑杆、倍速文字按钮）
    # 1 音量滑杆 → 点音量键弹出垂直浮窗
    # 2 倍速 → 收进「更多」
    # 3 时间只显示当前时间
    # 4 上一项/下一项 → 收进「更多」
    # 5 音量键隐藏（滚轮 / ↑↓ 仍可调音量）
    def _apply_level(self, lv):
        self.vol.setVisible(lv < 1)
        self.btn_speed.setVisible(lv < 2)
        self.time_short = lv >= 3
        self.btn_prev.setVisible(lv < 4)
        self.btn_next.setVisible(lv < 4)
        self.btn_vol.setVisible(lv < 5)          # 极窄时音量用滚轮 / ↑↓ 调
        self.btn_vol.setToolTip("音量（点击展开）" if lv >= 1 else "静音 (M)")
        self.on_pos(self.player.position())
        # 时间标签不允许被挤压截断
        sample = "00:00:00" if self.player.duration() >= 3600_000 else "00:00"
        txt = sample if self.time_short else f"{sample} / {sample}"
        m = self.time.contentsMargins()
        self.time.setMinimumWidth(self.time.fontMetrics().horizontalAdvance(txt) + m.left() + m.right() + 2)

    def adapt_bottom(self, avail):
        m = self.bottom.findChild(QFrame, "panel").layout().contentsMargins()
        avail -= m.left() + m.right()
        gap = self.bottom_row.spacing()
        for lv in range(6):
            self._apply_level(lv)
            vis = [wd for wd in self.row_widgets if not wd.isHidden()]
            need = sum(max(wd.sizeHint().width(), wd.minimumWidth()) for wd in vis) + gap * (len(vis) - 1) + px(24)
            if need <= avail:
                break
        self.level = lv
        self.bottom_row.invalidate()

    def adapt_top(self, avail):
        if not hasattr(self, "full_title"):
            self.full_title = self.title.text()
        l = self.top.layout()
        m = l.contentsMargins()
        avail -= m.left() + m.right()
        fixed = self.btn_open.sizeHint().width() + l.spacing() * 2 + px(24)
        fm = self.title.fontMetrics()
        full_w = fm.horizontalAdvance(self.full_title)
        res_w = self.info.sizeHint().width() + px(8)
        show_res = bool(self.info.text()) and full_w + res_w + fixed <= avail
        self.info.setVisible(show_res)
        room = max(px(40), avail - fixed - (res_w if show_res else 0))
        self.title.setText(fm.elidedText(self.full_title, Qt.TextElideMode.ElideMiddle, room))
        self.title.setToolTip(self.full_title)

    def _set_active(self, btn, on):
        btn.setProperty("active", on)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _update_nav(self):
        """没有可切换的媒体项时，上一项/下一项置灰"""
        many = len(self.files) > 1
        self.btn_prev.setEnabled(many)
        self.btn_next.setEnabled(many)

    # ================= 进度条拖动/悬停时间标签 =================
    def _place_drag(self, value, x=None):
        s = self.seek
        if x is None:
            x = QStyle.sliderPositionFromValue(s.minimum(), s.maximum(), value, s.width())
        self.drag_lbl.setText(fmt(value))
        self.drag_lbl.adjustSize()
        p = s.mapTo(self.stage, QPoint(int(x), 0))
        lw = self.drag_lbl.width()
        self.drag_lbl.move(max(4, min(self.stage.width() - lw - 4, p.x() - lw // 2)),
                           p.y() - self.drag_lbl.height() - px(6))
        self.drag_lbl.show()
        self.drag_lbl.raise_()

    def _seek_drag(self, *a):
        v = a[0] if a else self.seek.value()    # sliderMoved 先于 value 更新，用信号携带的值
        self.time.setText(fmt(v) if self.time_short else f"{fmt(v)} / {fmt(self.player.duration())}")
        if not self.player.source().isValid() or self.player.duration() <= 0:
            self._place_drag(v)
            return
        self.drag_lbl.hide()
        self._place_preview(v)
        self.framer.set_source(self.player.source(), self.player.duration())
        self.framer.touch()
        cached = self.framer.lookup(v)
        if cached is not None and not cached.isNull():
            self.preview.set_image(cached)          # 附近有缓存：立即显示
        self.framer.request(v, exact=False)         # 关键帧：快速、最新优先
        self.prev_timer.start()                     # 停顿 0.3 秒后取精确画面

    def _place_preview(self, v):
        s = self.seek
        res = self.player.metaData().value(QMediaMetaData.Key.Resolution)
        ar = res.width() / res.height() if res and res.isValid() and res.height() else 16 / 9
        bw, bh = (px(208), int(px(208) / ar)) if ar >= 1 else (int(px(150) * ar), px(150))
        if self.preview.img.size() != QSize(bw, bh):
            self.preview.set_box(bw, bh)
        self.preview.t.setText(fmt(v))
        self.preview.set_loading(True)
        x = QStyle.sliderPositionFromValue(s.minimum(), s.maximum(), v, s.width())
        p = s.mapTo(self.stage, QPoint(int(x), 0))
        pw, ph = self.preview.width(), self.preview.height()
        self.preview.move(max(4, min(self.stage.width() - pw - 4, p.x() - pw // 2)),
                          max(4, p.y() - ph - px(8)))
        self.preview.show()
        self.preview.raise_()

    def _preview_load(self):
        if self.seek.isSliderDown() and self.preview.isVisible():
            self.framer.request(self.seek.sliderPosition(), exact=True)

    def _preview_ready(self, img, ms):
        # 只显示和当前滑块位置足够接近的帧，避免拖得快时画面倒退
        if self.preview.isVisible() and abs(ms - self.seek.sliderPosition()) <= max(1500, self.framer._step()):
            self.preview.set_image(img)

    def _seek_release(self):
        self.prev_timer.stop()
        self.preview.hide()                      # 松开：小窗消失并跳转
        self.preview.clear()
        self.framer.done()
        self.player.setPosition(self.seek.value())
        self.drag_lbl.hide()

    def _seek_hover(self, value, x):
        if self.player.duration() > 0 and self.player.source().isValid():
            self.framer.set_source(self.player.source(), self.player.duration())
            self.framer.touch()
        if not self.seek.isSliderDown() and self.seek.maximum() > 0:
            self._place_drag(value, x)

    def _vol_clicked(self):
        if self.level >= 1:
            self.volume_popup()
        else:
            self.toggle_mute()

    def volume_popup(self):
        """垂直音量浮窗：点浮窗外关闭（这次点击不会传给视频，不会暂停）"""
        m = QMenu(self)
        m.setObjectName("volpop")
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(px(10), px(10), px(10), px(10))
        v.setSpacing(px(8))
        pct = QLabel(f"{self.vol.value()}")
        pct.setObjectName("time")
        pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        s = QSlider(Qt.Orientation.Vertical)
        s.setObjectName("vvol")
        s.setRange(0, 100)
        s.setValue(self.vol.value())
        s.setFixedHeight(px(140))
        s.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        def changed(x):
            self.vol.setValue(x)
            pct.setText(str(x))
        s.valueChanged.connect(changed)
        mute = bubble("mute" if self.audio.isMuted() else "vol", "静音 (M)")

        def do_mute():
            self.toggle_mute()
            mute.setText(IC["mute"] if self.audio.isMuted() else IC["vol"])
        mute.clicked.connect(do_mute)
        fx = bubble("fx", "音效：立体声 / 环绕声")
        fx.clicked.connect(lambda: (m.close(), self.open_audio_fx()))
        v.addWidget(pct)
        v.addWidget(s, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(mute, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(fx, 0, Qt.AlignmentFlag.AlignHCenter)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.aboutToHide.connect(lambda: (CFG.setValue("volume", self.vol.value()), self.show_controls()))
        sz = m.sizeHint()
        b = self.btn_vol
        m.exec(b.mapToGlobal(QPoint(b.width() // 2 - sz.width() // 2, -sz.height() - px(8))))

    SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0)

    def _fill_speed(self, menu):
        """倍速选项，勾选标识当前倍速"""
        cur = self.player.playbackRate()
        for r in self.SPEEDS:
            a = menu.addAction(f"{r:g}×", lambda r=r: self.set_speed(r))
            a.setCheckable(True)
            a.setChecked(abs(cur - r) < 0.01)
        menu.addSeparator()
        menu.addAction("精确调节（0.1× 一档）…", lambda: QTimer.singleShot(0, self.speed_popup))

    def _exec_menu(self, m, btn, align_right=False):
        """菜单打开期间对应按钮保持高亮，关闭后恢复"""
        self._set_active(btn, True)
        m.aboutToHide.connect(lambda: (self._set_active(btn, False), self.show_controls()))
        sz = m.sizeHint()
        x = btn.width() - sz.width() if align_right else btn.width() // 2 - sz.width() // 2
        m.exec(btn.mapToGlobal(QPoint(x, -sz.height() - px(8))))

    def speed_menu(self):
        m = QMenu(self)
        self._fill_speed(m)
        self._exec_menu(m, self.btn_speed)

    def more_menu(self):
        m = QMenu(self)
        if self.level >= 4:
            a = m.addAction("上一项", lambda: self.step_list(-1)); a.setEnabled(len(self.files) > 1)
            a = m.addAction("下一项", lambda: self.step_list(1)); a.setEnabled(len(self.files) > 1)
            m.addSeparator()
        if self.level >= 2:
            self._fill_speed(m.addMenu(f"播放速度（{self.player.playbackRate():g}×）"))
        md = m.addMenu(f"循环模式（{MODES[self.mode][0]}）")
        for i, (name, _) in enumerate(MODES):
            a = md.addAction(name, lambda i=i: self.set_mode(i, True))
            a.setCheckable(True)
            a.setChecked(i == self.mode)
        m.addAction("音效…", self.open_audio_fx)
        m.addAction("退出小窗\tP" if self.mini else "小窗模式\tP", self.toggle_mini)
        m.addSeparator()
        m.addAction("视频详情…", self.show_details)
        m.addAction("设置…", lambda: SettingsDialog(self).exec())
        self._exec_menu(m, self.btn_more, align_right=True)

    def show_details(self):
        """编码、帧率等详细信息"""
        md = self.player.metaData()
        K = QMediaMetaData.Key
        rows = []
        p = self.files[self.idx] if 0 <= self.idx < len(self.files) else ""
        if p:
            rows.append(("文件", os.path.basename(p) or p))
            rows.append(("位置", os.path.dirname(p) if "://" not in p else p))
            try:
                rows.append(("大小", f"{os.path.getsize(p) / 2**20:.1f} MB"))
            except OSError:
                pass
        res = md.value(K.Resolution)
        if res and res.isValid():
            rows.append(("分辨率", f"{res.width()} × {res.height()}"))
        for key, name in ((K.VideoCodec, "视频编码"), (K.AudioCodec, "音频编码")):
            v = md.value(key)
            if v is not None:
                rows.append((name, str(getattr(v, "name", v))))
        fr = md.value(K.VideoFrameRate)
        if fr:
            rows.append(("帧率", f"{fr:.3f} fps"))
        br = md.value(K.VideoBitRate)
        if br:
            rows.append(("视频码率", f"{int(br) / 1000:.0f} kbps"))
        if self.player.duration() > 0:
            rows.append(("时长", fmt(self.player.duration())))
        rows.append(("输出", "原画直出 · GPU 直接显示"))
        d = QDialog(self)
        d.setWindowTitle("视频详情")
        d.setMinimumWidth(px(380))
        f = QFormLayout(d)
        f.setSpacing(px(8))
        for k, v in rows:
            lab = QLabel(v)
            lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lab.setWordWrap(True)
            f.addRow(QLabel(k), lab)
        if not rows:
            f.addRow(QLabel("尚未打开视频"))
        ok = QPushButton("关闭")
        ok.clicked.connect(d.accept)
        f.addRow(ok)
        d.exec()

    def speed_popup(self):
        m = QMenu(self)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 10, 14, 10)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size:20px; font-weight:600;")
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(1, 40)              # 0.1x ~ 4.0x，每格 0.1
        s.setPageStep(1)
        s.setTickInterval(5)
        s.setTickPosition(QSlider.TickPosition.TicksBelow)
        s.setFixedWidth(260)
        s.setValue(round(self.player.playbackRate() * 10))
        lbl.setText(f"{s.value() / 10:.1f}x")

        def ch(val):
            lbl.setText(f"{val / 10:.1f}x")
            self.set_speed(val / 10, osd=False)
        s.valueChanged.connect(ch)
        ends = QHBoxLayout()
        for t in ("0.1x", "1.0x", "2.0x", "4.0x"):
            q = QLabel(t)
            q.setObjectName("time")
            ends.addWidget(q)
            if t != "4.0x":
                ends.addStretch(1)
        presets = QHBoxLayout()
        for r in (0.5, 1.0, 1.5, 2.0):
            b = QPushButton(f"{r}x")
            b.setObjectName("pill")
            b.clicked.connect(lambda _, r=r: s.setValue(round(r * 10)))
            presets.addWidget(b)
        v.addWidget(lbl)
        v.addWidget(s)
        v.addLayout(ends)
        v.addLayout(presets)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)
        m.aboutToHide.connect(self.show_controls)
        sz = m.sizeHint()
        anchor = self.btn_more if self.level >= 2 else self.btn_speed
        p = anchor.mapToGlobal(QPoint(anchor.width() // 2 - sz.width() // 2, -sz.height() - 8))
        m.exec(p)

    # ================= 播放控制 =================
    def toggle_play(self):
        if not self.player.source().isValid():
            if self.files:
                self.play_index(max(self.idx, 0))
            else:
                self.open_files()
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.center.flash(IC["pause"])
        else:
            self.player.play()
            self.center.flash(IC["play"])

    def seek_by(self, d):
        self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + d)))
        self.flash_osd(f"{'快进' if d > 0 else '快退'} {abs(d) // 1000}s  ·  {fmt(self.player.position())}")

    def set_speed(self, r, osd=True):
        r = round(min(max(r, 0.1), 4.0), 1)
        self.player.setPlaybackRate(r)
        self.btn_speed.setText(f"{r:g}×")
        if osd:
            self.flash_osd(f"播放速度 {r:.1f}x")

    def change_volume(self, d):
        self.vol.setValue(self.vol.value() + d)
        self.flash_osd(f"音量 {self.vol.value()}%")

    def _apply_volume(self):
        """实际输出音量 = 用户音量 × 过渡增益（淡入淡出时增益在 0~1 间变化，不改用户的音量设置）"""
        v = self.vol.value() / 100 * getattr(self, "gain", 1.0)
        self.audio.setVolume(v)
        self.fx.set_volume(v, self.audio.isMuted())

    def _vol_changed(self, v):
        self._apply_volume()
        if self.audio.isMuted() and v > 0:
            self.audio.setMuted(False)
        self._vol_icon()

    def toggle_mute(self):
        self.audio.setMuted(not self.audio.isMuted())
        self._vol_icon()
        self.flash_osd("已静音" if self.audio.isMuted() else f"音量 {self.vol.value()}%")

    def _vol_icon(self):
        self.btn_vol.setText(IC["mute"] if self.audio.isMuted() or self.vol.value() == 0 else IC["vol"])
        self._apply_volume()

    def flash_osd(self, text, ms=1100):
        if cfg("show_osd") or ms > 2000:
            self.osd.flash(text, ms)

    # ================= 播放列表 =================
    # ================= 播放列表：条目 =================
    def _make_item(self, p):
        it = QListWidgetItem(os.path.basename(p) or p)
        it.setToolTip(p)
        it.setData(Qt.ItemDataRole.UserRole, p)
        it.setIcon(QIcon(self.placeholder))
        self.thumbs.request(p)
        return it

    def _rebuild_list(self):
        self.list.clear()
        for p in self.files:
            self.list.addItem(self._make_item(p))

    def add_files(self, paths, play=True):
        first_new = len(self.files)
        for p in paths:
            p = p if "://" in p else os.path.normpath(p)
            if p in self.files:
                continue
            self.files.append(p)
            self.list.addItem(self._make_item(p))
        self._list_changed()
        if play and paths:
            target = paths[0] if "://" in paths[0] else os.path.normpath(paths[0])
            self.play_index(self.files.index(target) if target in self.files else first_new)

    def _thumb_ready(self, path, img, dur):
        pm = rounded(img if not img.isNull() else None, dur)
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                it.setIcon(QIcon(pm))

    def _rows_moved(self, *a):
        cur = self.files[self.idx] if 0 <= self.idx < len(self.files) else None
        self.files = [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]
        self.idx = self.files.index(cur) if cur in self.files else -1
        self._list_changed()

    def _list_changed(self):
        self.playlists[self.cur_pl] = list(self.files)
        self.pl_count.setText(f"{len(self.files)} 项")
        self._save_lists()
        for i in range(self.list.count()):
            it = self.list.item(i)
            f = it.font()
            f.setBold(i == self.idx)
            it.setFont(f)
        self._update_nav()

    def remove_selected(self):
        rows = sorted((self.list.row(it) for it in self.list.selectedItems()), reverse=True)
        for r in rows:
            self.list.takeItem(r)
            self.files.pop(r)
            if r < self.idx:
                self.idx -= 1
            elif r == self.idx:
                self.idx = -1
        self._list_changed()

    def clear_list(self):
        self.list.clear()
        self.files, self.idx = [], -1
        self._list_changed()

    # ================= 播放列表：多个列表 =================
    def _save_lists(self):
        if cfg("remember_list"):
            CFG.setValue("playlists", json.dumps(self.playlists, ensure_ascii=False))
            CFG.setValue("current_playlist", self.cur_pl)

    def _load_lists(self):
        data = {}
        try:
            data = json.loads(CFG.value("playlists", "") or "{}")
        except (ValueError, TypeError):
            data = {}
        if not data:                                # 迁移旧版的单一播放列表
            try:
                data = {DEFAULT_PL: json.loads(CFG.value("playlist", "[]"))}
            except (ValueError, TypeError):
                data = {DEFAULT_PL: []}
        self.playlists = {k: [p for p in v if "://" in p or os.path.exists(p)]
                          for k, v in data.items() if isinstance(v, list)} or {DEFAULT_PL: []}
        cur = CFG.value("current_playlist", "")
        self.cur_pl = cur if cur in self.playlists else next(iter(self.playlists))
        self.files = list(self.playlists[self.cur_pl])
        self.idx = -1
        self._rebuild_list()
        self._refresh_combo()
        self._list_changed()

    def _refresh_combo(self):
        self.pl_combo.blockSignals(True)
        self.pl_combo.clear()
        for name, items in self.playlists.items():
            self.pl_combo.addItem(name)
        self.pl_combo.setCurrentText(self.cur_pl)
        self.pl_combo.blockSignals(False)

    def _playing_path(self):
        u = self.player.source()
        if not u.isValid():
            return None
        return os.path.normpath(u.toLocalFile()) if u.isLocalFile() else u.toString()

    def switch_playlist(self, name):
        if name not in self.playlists or name == self.cur_pl:
            return
        self.playlists[self.cur_pl] = list(self.files)
        self.cur_pl = name
        self.files = list(self.playlists[name])
        cur = self._playing_path()
        self.idx = self.files.index(cur) if cur in self.files else -1   # 正在播的视频不受影响
        self._rebuild_list()
        if self.idx >= 0:
            self.list.setCurrentRow(self.idx)
        self._refresh_combo()
        self._list_changed()
        self.flash_osd(f"播放列表：{name}")

    def _unique_name(self, base):
        name, n = base, 2
        while name in self.playlists:
            name, n = f"{base} {n}", n + 1
        return name

    def _ask_name(self, title, default):
        name, ok = QInputDialog.getText(self, title, "列表名称：", text=default)
        name = name.strip()
        return name if ok and name else None

    def new_playlist(self, paths=None):
        name = self._ask_name("新建播放列表", self._unique_name("新建列表"))
        if not name:
            return None
        name = self._unique_name(name) if name in self.playlists else name
        self.playlists[name] = []
        if paths:
            self.playlists[name] = list(dict.fromkeys(paths))
            self._refresh_combo()
            self._save_lists()
            self.flash_osd(f"已添加 {len(paths)} 项到「{name}」")
        else:
            self.switch_playlist(name)
        return name

    def rename_playlist(self):
        old = self.cur_pl
        name = self._ask_name("重命名播放列表", old)
        if not name or name == old:
            return
        if name in self.playlists:
            self.flash_osd(f"已有名为「{name}」的列表")
            return
        self.playlists = {(name if k == old else k): v for k, v in self.playlists.items()}
        self.cur_pl = name
        self._refresh_combo()
        self._save_lists()

    def delete_playlist(self):
        from PyQt6.QtWidgets import QMessageBox
        name = self.cur_pl
        if len(self.playlists) <= 1:
            self.flash_osd("至少保留一个播放列表")
            return
        r = QMessageBox.question(self, "删除播放列表",
                                 f"删除播放列表「{name}」？\n（只删除列表，不会删除视频文件）")
        if r != QMessageBox.StandardButton.Yes:
            return
        del self.playlists[name]
        first = next(iter(self.playlists))
        self.cur_pl = first
        self.files = list(self.playlists[first])
        cur = self._playing_path()
        self.idx = self.files.index(cur) if cur in self.files else -1
        self._rebuild_list()
        self._refresh_combo()
        self._list_changed()
        self.flash_osd(f"已删除「{name}」，当前列表：{first}")

    def add_to_playlist(self, paths, name):
        lst = self.playlists.setdefault(name, [])
        n = 0
        for p in paths:
            if p not in lst:
                lst.append(p)
                n += 1
        self._save_lists()
        self.flash_osd(f"已添加 {n} 项到「{name}」")

    def _pl_menu(self):
        m = QMenu(self)
        m.addAction("重命名当前列表…", self.rename_playlist)
        a = m.addAction("删除当前列表…", self.delete_playlist)
        a.setEnabled(len(self.playlists) > 1)
        m.addSeparator()
        m.addAction("新建播放列表…", self.new_playlist)
        self._set_active(self.pl_more, True)
        m.aboutToHide.connect(lambda: self._set_active(self.pl_more, False))
        m.exec(self.pl_more.mapToGlobal(QPoint(0, self.pl_more.height() + px(4))))

    def _item_menu(self, pos):
        it = self.list.itemAt(pos)
        if it is None:
            return
        if not it.isSelected():
            self.list.setCurrentItem(it)
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]
        m = QMenu(self)
        m.addAction("播放", lambda: self.play_index(self.list.row(it)))
        sub = m.addMenu(f"添加到播放列表（{len(paths)} 项）")
        for name in self.playlists:
            if name != self.cur_pl:
                sub.addAction(name, lambda name=name: self.add_to_playlist(paths, name))
        if sub.actions():
            sub.addSeparator()
        sub.addAction("新建列表…", lambda: self.new_playlist(paths))
        m.addAction("从此列表移除", self.remove_selected)
        p = it.data(Qt.ItemDataRole.UserRole)
        if "://" not in p:
            m.addSeparator()
            m.addAction("在文件夹中显示", lambda: __import__("subprocess").Popen(["explorer", "/select,", p]))
        m.exec(self.list.viewport().mapToGlobal(pos))

    # ================= 播放列表：右侧抽屉 =================
    def toggle_playlist(self):
        self._set_drawer(not self.pl_open)

    def _set_drawer(self, open_, animate=True):
        self.pl_open = open_
        self.pl_handle.setText(IC["chev_r"] if open_ else IC["chev_l"])
        self.pl_handle.setToolTip("收起播放列表 (L)" if open_ else "播放列表 (L)")
        if open_:
            self.playlist.show()
            self.playlist.raise_()
            self.pl_handle.raise_()
        self.pl_anim.stop()
        if animate:
            self.pl_anim.setStartValue(float(self.pl_p))
            self.pl_anim.setEndValue(1.0 if open_ else 0.0)
            self.pl_anim.start()
        else:
            self._drawer_step(1.0 if open_ else 0.0)
            if not open_:
                self.playlist.hide()
        self.show_controls()

    def _drawer_step(self, v):
        self.pl_p = float(v)
        self.stage.layout_overlays()

    # ================= 平滑过渡 =================
    def _fade(self, to, ms, then=None):
        """画面不透明度与音量增益同步渐变到 to（0=黑场静音，1=正常）；缓入缓出曲线"""
        from PyQt6.QtCore import QVariantAnimation
        if not hasattr(self, "fade_anim"):
            self.gain = 1.0
            self.fade_anim = QVariantAnimation(self)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
            self.fade_anim.valueChanged.connect(self._fade_step)
        a = self.fade_anim
        a.stop()
        try:
            a.finished.disconnect()
        except TypeError:
            pass
        a.setStartValue(float(getattr(self, "gain", 1.0)))
        a.setEndValue(float(to))
        a.setDuration(int(ms))
        if then:
            a.finished.connect(then)
        a.start()

    def _fade_step(self, g):
        self.gain = float(g)
        self.stage.view.item.setProperty("opacity", self.gain)
        self._apply_volume()

    def _fade_reset(self):
        if hasattr(self, "fade_anim"):
            self.fade_anim.stop()
        self._fading_out = False
        self._need_fadein = False
        self._fade_step(1.0)

    def play_index(self, i):
        if not (0 <= i < len(self.files)):
            return
        T = cfg("transition_ms")
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if cfg("transition") and playing and getattr(self, "gain", 1.0) > 0.05:
            # 正在播放：先淡出（画面渐黑、声音渐弱），结束后再切换
            self._fading_out = True
            self._fade(0.0, T * getattr(self, "gain", 1.0), lambda: self._play_index_now(i))
        else:
            self._play_index_now(i)

    def _play_index_now(self, i):
        if not (0 <= i < len(self.files)):
            return
        self._fading_out = self._prefading = False
        if cfg("transition"):
            # 新视频从黑场静音开始，开播后淡入
            if hasattr(self, "fade_anim"):
                self.fade_anim.stop()
            self._fade_step(0.0)
            self._need_fadein = True
            QTimer.singleShot(2500, self._fadein_fallback)
        else:
            self._fade_reset()
        self.save_position()
        self.idx = i
        p = self.files[i]
        self.list.setCurrentRow(i)
        self._list_changed()
        self.pending_seek = 0
        if cfg("remember_pos"):
            self.pending_seek = self._positions().get(p, 0)
        if p.startswith(("http://", "https://", "rtsp://", "rtmp://")):
            self.player.setSource(QUrl(p))
        else:
            self.player.setSource(QUrl.fromLocalFile(p))
        name = os.path.basename(p) or p
        self.full_title = name
        self.title.setText(name)
        self.stage.layout_overlays()
        self.setWindowTitle(f"{name} - {APP}")

        self.thumbs.hold(3000)
        if self.pending_seek:
            self._start_after_load = True        # 先定位再播放，避免先播开头再跳转的卡顿
        else:
            self.player.play()

    def step_list(self, d):
        if not self.files:
            return
        if self.mode == 3 and len(self.files) > 1:
            self.play_index(random.choice([i for i in range(len(self.files)) if i != self.idx]))
        else:
            self.play_index((self.idx + d) % len(self.files))

    def set_mode(self, m, osd=False):
        self.mode = m
        CFG.setValue("play_mode", m)
        name, ic = MODES[m]
        self.btn_mode.setText(IC[ic])
        self.btn_mode.setToolTip(f"播放模式：{name}")
        if osd:
            self.flash_osd(name)

    # ================= 进度记忆 =================
    def _positions(self):
        try:
            return json.loads(CFG.value("positions", "{}"))
        except (ValueError, TypeError):
            return {}

    def save_position(self):
        if not cfg("remember_pos") or not (0 <= self.idx < len(self.files)):
            return
        pos, dur = self.player.position(), self.player.duration()
        d = self._positions()
        p = self.files[self.idx]
        if dur > 0 and 10_000 < pos < dur - 10_000:
            d[p] = pos
        else:
            d.pop(p, None)
        if len(d) > 300:
            d = dict(list(d.items())[-300:])
        CFG.setValue("positions", json.dumps(d, ensure_ascii=False))

    # ================= 打开 =================
    def open_files(self):
        ps, _ = QFileDialog.getOpenFileNames(self, "打开视频", CFG.value("last_dir", ""), FILTER)
        if ps:
            CFG.setValue("last_dir", os.path.dirname(ps[0]))
            self.add_files(ps)

    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "添加文件夹", CFG.value("last_dir", ""))
        if d:
            CFG.setValue("last_dir", d)
            self.add_files(self._scan(d))

    def open_url(self):
        u, ok = QInputDialog.getText(self, "打开网络地址", "视频 URL（http / rtsp / m3u8 …）：")
        if ok and u.strip():
            self.add_files([u.strip()])

    @staticmethod
    def _scan(d):
        out = []
        for root, _, fs in os.walk(d):
            out += [os.path.join(root, f) for f in sorted(fs) if os.path.splitext(f)[1].lower() in MEDIA_EXT]
        return out

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        ps = []
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            ps += self._scan(p) if os.path.isdir(p) else [p]
        self.add_files(ps)

    # ================= 回调 =================
    def on_pos(self, p):
        if self.seek.isSliderDown():
            return                     # 拖动中：时间显示跟随滑块，不被播放进度覆盖
        if getattr(self, "_need_fadein", False) and p > 0 and \
                self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._need_fadein = False
            self._fade(1.0, cfg("transition_ms"))           # 新视频已出画面：淡入
        self._maybe_prefade(p)
        self.seek.setValue(p)
        self.time.setText(fmt(p) if self.time_short else f"{fmt(p)} / {fmt(self.player.duration())}")

    def _fadein_fallback(self):
        if getattr(self, "_need_fadein", False):
            self._need_fadein = False
            self._fade(1.0, cfg("transition_ms"))

    def _maybe_prefade(self, p):
        """自动播下一个时：在结尾前提前淡出，让衔接自然（结束后由「播放结束」切到下一个）"""
        d = self.player.duration()
        T = cfg("transition_ms")
        if getattr(self, "_prefading", False) and p < d - T - 300:
            # 淡出途中往回拖：恢复画面和声音
            self._prefading = self._fading_out = False
            self._fade(1.0, 200)
            return
        if not cfg("transition") or getattr(self, "_fading_out", False) or not cfg("auto_next"):
            return
        if d <= T * 3 or p < d - T or self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        last = self.idx >= len(self.files) - 1
        if self.mode == 2 or len(self.files) < 2 or (self.mode == 0 and last):
            return
        self._fading_out = self._prefading = True
        self._fade(0.0, max(150, d - p))

    def on_dur(self, d):
        self.seek.setRange(0, d)

    def on_state(self, s):
        playing = s == QMediaPlayer.PlaybackState.PlayingState
        new = IC["pause"] if playing else IC["play"]
        if self.btn_play.text() != new:
            self.btn_play.setText(new)
            self.btn_play.bounce()
        self.show_controls()

    def on_status(self, st):
        S = QMediaPlayer.MediaStatus
        # 有媒体后收起首次打开提示；网络视频缓冲时在播放键旁转圈
        self.empty.setVisible(st in (S.NoMedia, S.InvalidMedia) and not self.player.source().isValid())
        src = self.player.source().toString()
        net = src.startswith(("http", "rtsp", "rtmp"))
        self.spinner.setVisible(net and st in (S.LoadingMedia, S.BufferingMedia, S.StalledMedia))
        if st == S.LoadedMedia and getattr(self, "_start_after_load", False):
            self._start_after_load = False
            d = self.player.duration()
            if self.pending_seek and (d <= 0 or self.pending_seek < d):
                self.player.setPosition(self.pending_seek)
                self.flash_osd(f"已从上次位置 {fmt(self.pending_seek)} 继续播放", 2500)
            self.pending_seek = 0
            self.player.play()
        elif st == S.InvalidMedia and getattr(self, "_start_after_load", False):
            self._start_after_load = False
        if st == QMediaPlayer.MediaStatus.EndOfMedia:
            if 0 <= self.idx < len(self.files):
                self._positions_clear(self.files[self.idx])
            if self.mode == 2:
                self.player.setPosition(0)
                self.player.play()
            elif cfg("auto_next") and self.files:
                last = self.idx >= len(self.files) - 1
                if self.mode == 0 and last:
                    return
                self.step_list(1)

    def _positions_clear(self, p):
        d = self._positions()
        if d.pop(p, None) is not None:
            CFG.setValue("positions", json.dumps(d, ensure_ascii=False))

    def show_info(self):
        """顶部只显示分辨率（空间足够时）；编码、帧率等在「视频详情」里"""
        res = self.player.metaData().value(QMediaMetaData.Key.Resolution)
        self.info.setText(f"{res.width()}×{res.height()}" if res and res.isValid() else "")
        self.stage.layout_overlays()

    # ================= 自动隐藏 =================
    def show_controls(self):
        if not self.bottom.isVisible() or self.bottom.eff.opacity() < 1:
            self.top.fade(True)
            self.bottom.fade(True)
            if not self.isFullScreen():
                Bar.fade(self.titlebar, True)
            Bar.fade(self.pl_handle, True)
        self.stage.unsetCursor()
        self.hide_timer.start()

    def auto_hide(self):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        over = (self.bottom.underMouse() or self.top.underMouse() or self.playlist.underMouse()
                or self.titlebar.underMouse() or self.pl_handle.underMouse())
        if not playing or over or QApplication.activePopupWidget() or QApplication.activeModalWidget():
            self.hide_timer.start()
            return
        self.top.fade(False)
        self.bottom.fade(False)
        if self.titlebar.isVisible():
            Bar.fade(self.titlebar, False)
        Bar.fade(self.pl_handle, False)
        if self.stage.underMouse():
            self.stage.setCursor(Qt.CursorShape.BlankCursor)

    def eventFilter(self, obj, e):
        if e.type() in (e.Type.MouseMove, e.Type.MouseButtonPress) and isinstance(obj, QWidget) \
                and obj.window() is self:
            self.show_controls()
        return False

    def open_audio_fx(self):
        if getattr(self, "_fx_dlg", None) is None:
            self._fx_dlg = AudioDialog(self.fx, self)
            self._fx_dlg.finished.connect(lambda *_: setattr(self, "_fx_dlg", None))
        self._fx_dlg.show()
        self._fx_dlg.raise_()

    # ================= 自有窗口边框 =================
    def showEvent(self, e):
        super().showEvent(e)
        frame.apply_dwm(int(self.winId()), QColor(cfg("accent")).darker(140).name())

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange:
            self.titlebar.sync()
            self.titlebar.setVisible(not self.isFullScreen())
            self.stage.layout_overlays()

    # ================= 窗口模式 =================
    def _set_on_top(self, on):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()

    def toggle_fullscreen(self):
        if self.mini:
            self.toggle_mini()
        if self.isFullScreen():
            self.showMaximized() if getattr(self, "_was_max", False) else self.showNormal()
            self.btn_full.setText(IC["full"])
        else:
            self._was_max = self.isMaximized()
            self.showFullScreen()
            self.btn_full.setText(IC["unfull"])
        self.titlebar.setVisible(not self.isFullScreen())
        self.show_controls()

    def toggle_mini(self):
        if self.isFullScreen():
            self.showNormal()
            self.btn_full.setText(IC["full"])
        if not self.mini:
            self._mini_was_max = self.isMaximized()
            if self._mini_was_max:
                self.showNormal()
            self.normal_geo = self.geometry()
            self.mini = True
            self._set_drawer(False, animate=False)
            if cfg("mini_on_top"):
                self._set_on_top(True)
            scr = self.screen().availableGeometry()
            # 按视频比例缩放进「屏幕宽 30% × 屏幕高 45%」的框内：竖屏视频也不会超出屏幕
            res = self.player.metaData().value(QMediaMetaData.Key.Resolution)
            ar = res.width() / res.height() if res and res.isValid() and res.height() else 16 / 9
            box_w, box_h = min(480, int(scr.width() * 0.30)), int(scr.height() * 0.45)
            w, h = box_w, int(box_w / ar)
            if h > box_h:
                h, w = box_h, int(box_h * ar)
            w, h = max(w, 200), max(h, 150)
            self.setMinimumSize(200, 150)
            self.setGeometry(QRect(scr.right() - w - 24, scr.bottom() - h - 24, w, h))
            self.keep_on_screen()
            self.btn_mini.setToolTip("退出小窗 (P / Esc)")
        else:
            self.mini = False
            self._set_on_top(False)
            self.setMinimumSize(360, 220)
            if self.normal_geo:
                self.setGeometry(self.normal_geo)
                self.keep_on_screen()
            if getattr(self, "_mini_was_max", False):
                self.showMaximized()
            self.btn_mini.setToolTip("小窗模式 (P)")
        self.stage.layout_overlays()
        self.show_controls()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.mini:   # 小窗拖动停下后，如有部分跑出屏幕则自动收回
            if not hasattr(self, "_clamp_timer"):
                self._clamp_timer = QTimer(self, singleShot=True, interval=350)
                self._clamp_timer.timeout.connect(self.keep_on_screen)
            self._clamp_timer.start()

    def keep_on_screen(self):
        """保证窗口完整落在所在显示器的可用区域内（标题栏不会跑到屏幕外）"""
        if self.isMaximized() or self.isFullScreen():
            return
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        g = self.geometry()
        w, h = min(g.width(), scr.width()), min(g.height(), scr.height())
        x = min(max(g.x(), scr.left()), scr.right() - w + 1)
        y = min(max(g.y(), scr.top()), scr.bottom() - h + 1)
        if (x, y, w, h) != (g.x(), g.y(), g.width(), g.height()):
            self.setGeometry(x, y, w, h)

    def escape(self):
        if self.pl_open:
            self.toggle_playlist()
            return
        if self.isFullScreen():
            self.toggle_fullscreen()
        elif self.mini:
            self.toggle_mini()

    def closeEvent(self, e):
        self.save_position()
        if not self.mini and not self.isFullScreen():
            CFG.setValue("geometry", self.saveGeometry())
        CFG.setValue("volume", self.vol.value())
        super().closeEvent(e)


if __name__ == "__main__":
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setWindowIcon(QIcon(LOGO))
    w = Player()
    g = CFG.value("geometry")
    if g is not None:
        w.restoreGeometry(g)
        w.keep_on_screen()
    w.show()
    args = [a for a in sys.argv[1:] if os.path.exists(a) or "://" in a]
    if args:
        w.add_files(args)
    sys.exit(app.exec())
