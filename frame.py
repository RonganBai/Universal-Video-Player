"""应用自有窗口边框

无系统标题栏（FramelessWindowHint），标题栏与最小化/最大化/关闭按钮由应用绘制；
Windows 11 上通过 DWM 保留圆角、阴影，并使用自定义边框颜色；
拖动标题栏移动（支持拖到屏幕边缘分屏）、拖动窗口边缘缩放、双击标题栏最大化。
"""
import ctypes
import sys

from PyQt6.QtCore import QEvent, QObject, QPoint, Qt
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QPushButton,
                             QWidget)

IS_WIN = sys.platform == "win32"
EDGE = 6


def apply_dwm(hwnd, border_hex):
    """深色模式 + 圆角 + 阴影 + 自定义边框颜色"""
    if not IS_WIN:
        return
    from ctypes import wintypes
    dwm = ctypes.windll.dwmapi
    h = wintypes.HWND(hwnd)

    def set_(attr, val):
        v = ctypes.c_int(val)
        dwm.DwmSetWindowAttribute(h, attr, ctypes.byref(v), ctypes.sizeof(v))
    set_(20, 1)   # 深色模式
    set_(33, 2)   # 圆角
    set_(34, -2)  # DWMWA_BORDER_COLOR = DWMWA_COLOR_NONE(0xFFFFFFFE)：不画描边线

    class MARGINS(ctypes.Structure):
        _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]
    dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref(MARGINS(1, 1, 1, 1)))   # 阴影


class TitleBar(QWidget):
    H = 38

    def __init__(self, win, title, icon_path, icon_font, glyphs):
        super().__init__(win)
        self.win = win
        self.setObjectName("titlebar")
        self.setFixedHeight(self.H)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        l = QHBoxLayout(self)
        l.setContentsMargins(12, 0, 0, 0)
        l.setSpacing(8)
        self.logo = logo = QLabel()
        logo.setPixmap(QIcon(icon_path).pixmap(18, 18))
        self.title = QLabel(title)
        self.title.setObjectName("wintitle")
        for w in (logo, self.title):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        l.addWidget(logo)
        l.addWidget(self.title, 1)
        self.g = glyphs
        self.btns = []
        for key, tip, fn, name in (("min", "最小化", win.showMinimized, "wbtn"),
                                   ("max", "最大化", self.toggle_max, "wbtn"),
                                   ("close", "关闭", win.close, "wclose")):
            b = QPushButton(glyphs[key])
            b.setObjectName(name)
            b.setToolTip(tip)
            b.setFont(QFont(icon_font))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(fn)
            l.addWidget(b)
            self.btns.append(b)
        self.btn_max = self.btns[1]

    def setText(self, t):
        self.title.setText(t)

    def toggle_max(self):
        self.win.showNormal() if self.win.isMaximized() else self.win.showMaximized()

    def sync(self):
        m = self.win.isMaximized()
        self.btn_max.setText(self.g["restore" if m else "max"])
        self.btn_max.setToolTip("向下还原" if m else "最大化")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()   # 系统级拖动：支持贴边分屏

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.toggle_max()


class EdgeResizer(QObject):
    """窗口边缘拖动缩放（安装到 QApplication 上）"""
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.cursor_set = False

    def _edges(self, gpos):
        w = self.win
        if w.isMaximized() or w.isFullScreen():
            return Qt.Edge(0)
        p = w.mapFromGlobal(gpos)
        e = Qt.Edge(0)
        if p.x() <= EDGE: e |= Qt.Edge.LeftEdge
        if p.x() >= w.width() - EDGE: e |= Qt.Edge.RightEdge
        if p.y() <= EDGE: e |= Qt.Edge.TopEdge
        if p.y() >= w.height() - EDGE: e |= Qt.Edge.BottomEdge
        return e

    @staticmethod
    def _cursor(e):
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        if e in (L | T, R | B): return Qt.CursorShape.SizeFDiagCursor
        if e in (R | T, L | B): return Qt.CursorShape.SizeBDiagCursor
        if e & (L | R): return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.HoverMove):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.win:
            return False
        gp = ev.globalPosition().toPoint() if hasattr(ev, "globalPosition") else None
        if gp is None:
            return False
        e = self._edges(gp)
        if t == QEvent.Type.MouseButtonPress and e != Qt.Edge(0) and ev.button() == Qt.MouseButton.LeftButton:
            self.win.windowHandle().startSystemResize(e)
            return True
        if e != Qt.Edge(0):
            if not self.cursor_set:
                QApplication.setOverrideCursor(self._cursor(e))
                self.cursor_set = True
            else:
                QApplication.changeOverrideCursor(self._cursor(e))
        elif self.cursor_set:
            QApplication.restoreOverrideCursor()
            self.cursor_set = False
        return False
