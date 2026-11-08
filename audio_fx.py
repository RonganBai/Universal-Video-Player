"""音效引擎：立体声 / 环绕声处理（32 位浮点，全程不降采样）

关闭「音效处理」时完全走系统原生音频输出（原声直出、零额外延迟）；
开启后由 QAudioBufferOutput 取出解码后的 PCM，经 numpy 处理后送入 QAudioSink。
"""
from PyQt6.QtCore import QObject, QSettings, Qt, QTimer, pyqtSignal
from PyQt6.QtMultimedia import (QAudioBufferOutput, QAudioFormat, QAudioSink,
                                QMediaDevices)
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout,
                             QGroupBox, QHBoxLayout, QLabel, QPushButton,
                             QSlider, QVBoxLayout)

np = None   # numpy 仅在开启音效时才加载，平时不占内存


def _load_np():
    global np
    if np is None:
        import numpy
        np = numpy


CFG = QSettings("UniversalPlayer", "Player")
P = QAudioFormat.AudioChannelPosition

AUDIO_DEFAULTS = {
    "fx_enabled": False,
    "fx_channel_mode": 0,      # 0 立体声 1 左右互换 2 单声道 3 仅左 4 仅右
    "fx_balance": 0,           # -100 .. 100
    "fx_width": 100,           # 立体声宽度 0 .. 200 %
    "fx_crossfeed": False,     # 耳机交叉馈送
    "fx_surround": False,      # 虚拟环绕
    "fx_surround_amt": 50,     # 0 .. 100
    "fx_room": 1,              # 0 小 1 中 2 大
    "fx_reverb": 25,           # 0 .. 100
    "fx_lfe": True,            # 下混时保留低音声道
    "fx_output": 0,            # 0 下混为立体声 1 原始多声道直出
}
CHANNEL_MODES = ["立体声（原始）", "左右声道互换", "单声道（混合）", "仅左声道", "仅右声道"]
ROOMS = ["小房间", "客厅", "影院"]
OUTPUTS = ["下混为立体声（耳机/音箱）", "保持原始多声道（5.1/7.1 设备）"]


def acfg(k):
    d = AUDIO_DEFAULTS[k]
    v = CFG.value(k, d)
    if isinstance(d, bool):
        return v in (True, "true", "1", 1)
    try:
        return type(d)(v)
    except (TypeError, ValueError):
        return d


def to_float(raw, fmt):
    sf = fmt.sampleFormat()
    ch = max(fmt.channelCount(), 1)
    F = QAudioFormat.SampleFormat
    if sf == F.Float:
        a = np.frombuffer(raw, dtype=np.float32)
    elif sf == F.Int16:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sf == F.Int32:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sf == F.UInt8:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        return None
    n = len(a) // ch
    return a[: n * ch].reshape(n, ch)


def soft_limit(x, t=0.92):
    a = np.abs(x)
    over = a > t
    if over.any():
        x = x.copy()
        x[over] = np.sign(x[over]) * (t + (1 - t) * np.tanh((a[over] - t) / (1 - t)))
    return x


class AudioEngine(QObject):
    info = pyqtSignal(str)

    def __init__(self, player, native_output, parent=None):
        super().__init__(parent)
        self.player, self.native = player, native_output
        self.bo = QAudioBufferOutput(self)
        self.bo.audioBufferReceived.connect(self._on_buffer)
        self.sink = self.io = None
        self.sink_key = None
        self.queue = bytearray()
        self.queue_ts, self.bps = 0, 1
        self.frame_bytes = 8
        self.hist = None
        self.expect_us = None
        self.volume, self.muted = 0.8, False
        self.active = False
        self.pump_timer = QTimer(self, interval=5)
        self.pump_timer.timeout.connect(self._pump)
        self.src_desc = ""
        self.apply()

    # ---------- 开关 ----------
    def apply(self):
        on = acfg("fx_enabled")
        # 系统音频输出保持连接但静音为 0 音量：作为播放主时钟，保证音画同步；
        # 实际听到的声音来自处理后的 QAudioSink。
        if on and not self.active:
            self.native.setVolume(0.0)
            self.player.setAudioBufferOutput(self.bo)
            self.pump_timer.start()
            self.active = True
        elif not on and self.active:
            self.player.setAudioBufferOutput(None)
            self.native.setVolume(self.volume)
            self.pump_timer.stop()
            self._close_sink()
            self.active = False
        self.sink_key = None if on else self.sink_key  # 参数变化后重建输出
        self.hist = None

    def set_volume(self, v, muted):
        self.volume, self.muted = v, muted
        if self.active:
            self.native.setVolume(0.0)
        if self.sink:
            self.sink.setVolume(0.0 if muted else v)

    def _close_sink(self):
        if self.sink:
            self.sink.stop()
        self.sink = self.io = None
        self.queue.clear()

    def _ensure_sink(self, sr, ch):
        if self.sink_key == (sr, ch) and self.sink:
            return
        self._close_sink()
        dev = QMediaDevices.defaultAudioOutput()
        fmt = QAudioFormat()
        fmt.setSampleRate(sr)
        fmt.setChannelCount(ch)
        fmt.setChannelConfig(QAudioFormat.defaultChannelConfigForChannelCount(ch))
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Float)
        if not dev.isFormatSupported(fmt):
            fmt.setChannelCount(2)
            fmt.setChannelConfig(QAudioFormat.defaultChannelConfigForChannelCount(2))
        self.out_ch = fmt.channelCount()
        self.sink = QAudioSink(dev, fmt, self)
        self.sink.setBufferSize(int(sr * self.out_ch * 4 * 0.06))   # 60ms，尽量减小音画延迟
        self.sink.setVolume(0.0 if self.muted else self.volume)
        self.io = self.sink.start()
        self.frame_bytes = 4 * self.out_ch
        self.sink_key = (sr, ch)

    # ---------- 数据流 ----------
    def _on_buffer(self, buf):
        if not buf.isValid():
            return
        _load_np()
        fmt = buf.format()
        raw = buf.constData().asstring(buf.byteCount())
        x = to_float(raw, fmt)
        if x is None or not len(x):
            return
        sr, ch = fmt.sampleRate(), fmt.channelCount()
        # 跳转 / 换片检测 → 清空缓冲，避免残留声音
        st = buf.startTime()
        if self.expect_us is not None and abs(st - self.expect_us) > 150_000:
            self.queue.clear()
            self.hist = None
        self.expect_us = st + buf.duration()

        passthrough = acfg("fx_output") == 1 and ch > 2 and \
            QMediaDevices.defaultAudioOutput().maximumChannelCount() >= ch
        self._ensure_sink(sr, ch if passthrough else 2)
        if passthrough and self.out_ch == ch:
            y = self._balance_multi(x, fmt)
        else:
            y = self._process(x, fmt, sr)
        self.src_desc = f"音源 {ch} 声道 · {sr / 1000:g} kHz  →  输出 {self.out_ch} 声道"
        data = soft_limit(y).astype(np.float32).tobytes()
        if not self.queue:
            self.queue_ts = st                            # 队首数据对应的媒体时间（微秒）
        self.queue += data
        self.bps = sr * self.frame_bytes
        cap = self.bps * 2                                # 安全上限 2 秒
        if len(self.queue) > cap:
            cut = len(self.queue) - cap
            cut -= cut % self.frame_bytes
            del self.queue[:cut]
            self.queue_ts += cut * 1_000_000 // self.bps
        self._pump()

    def _pump(self):
        """按时间戳送数据：保证每段声音恰好在对应画面时刻播出"""
        if not self.io or not self.queue:
            return
        bps, fb = self.bps, self.frame_bytes
        pos = self.player.position() * 1000
        # 丢弃已经过时的数据（跳转、卡顿后）
        if self.queue_ts < pos - 80_000:
            cut = int((pos - self.queue_ts) * bps / 1_000_000)
            cut = min(cut - cut % fb, len(self.queue))
            del self.queue[:cut]
            self.queue_ts += cut * 1_000_000 // bps
            if not self.queue:
                return
        buffered_us = (self.sink.bufferSize() - self.sink.bytesFree()) * 1_000_000 // bps
        if self.queue_ts > pos + buffered_us + 20_000:    # 还没到时间
            return
        n = min(self.sink.bytesFree(), len(self.queue))
        n -= n % fb
        if n > 0:
            w = self.io.write(bytes(self.queue[:n]))
            if w > 0:
                w -= w % fb
                del self.queue[:w]
                self.queue_ts += w * 1_000_000 // bps

    # ---------- 处理 ----------
    @staticmethod
    def _idx(fmt, pos):
        try:
            return fmt.channelOffset(pos)
        except Exception:
            return -1

    def _balance_multi(self, x, fmt):
        b = acfg("fx_balance") / 100
        y = x.copy()
        for pos, g in ((P.FrontLeft, min(1, 1 - b)), (P.FrontRight, min(1, 1 + b)),
                       (P.BackLeft, min(1, 1 - b)), (P.BackRight, min(1, 1 + b)),
                       (P.SideLeft, min(1, 1 - b)), (P.SideRight, min(1, 1 + b))):
            i = self._idx(fmt, pos)
            if 0 <= i < y.shape[1]:
                y[:, i] *= g
        return y

    def _downmix(self, x, fmt):
        """返回 L, R, 后左, 后右（后置由多声道直接取，或由立体声差信号推导）"""
        ch = x.shape[1]
        if ch == 1:
            return x[:, 0], x[:, 0], None, None
        if ch == 2:
            return x[:, 0], x[:, 1], None, None
        g = lambda pos: x[:, i] if 0 <= (i := self._idx(fmt, pos)) < ch else 0.0
        fl, fr, fc, lfe = g(P.FrontLeft), g(P.FrontRight), g(P.FrontCenter), g(P.LFE)
        ls = g(P.SideLeft) + g(P.BackLeft) * (1.0 if self._idx(fmt, P.SideLeft) < 0 else 0.7)
        rs = g(P.SideRight) + g(P.BackRight) * (1.0 if self._idx(fmt, P.SideRight) < 0 else 0.7)
        c = 0.707 * fc + (0.5 * lfe if acfg("fx_lfe") else 0.0)
        L = (fl + c + 0.707 * ls) * 0.6
        R = (fr + c + 0.707 * rs) * 0.6
        return np.asarray(L, np.float32), np.asarray(R, np.float32), \
            np.asarray(ls * 0.6, np.float32) * np.ones(len(x), np.float32), \
            np.asarray(rs * 0.6, np.float32) * np.ones(len(x), np.float32)

    def _process(self, x, fmt, sr):
        n = len(x)
        L, R, Ls, Rs = self._downmix(x, fmt)
        L = np.array(L, np.float32, copy=True)
        R = np.array(R, np.float32, copy=True)

        mode = acfg("fx_channel_mode")
        if mode == 1:
            L, R = R, L
        elif mode == 2:
            L = R = (L + R) * 0.5
        elif mode == 3:
            R = L.copy()
        elif mode == 4:
            L = R.copy()

        w = acfg("fx_width") / 100
        if w != 1.0:
            M, S = (L + R) * 0.5, (L - R) * 0.5 * w
            L, R = M + S, M - S

        if Ls is None:  # 立体声片源：被动矩阵解码出环绕成分
            S = (L - R) * 0.5
            Ls, Rs = S, -S

        # 历史缓冲（用于延迟线），列：L R Ls Rs
        sig = np.stack([L, R, Ls, Rs], axis=1).astype(np.float32)
        H = int(sr * 0.25)
        if self.hist is None or self.hist.shape[0] != H:
            self.hist = np.zeros((H, 4), np.float32)
        cat = np.concatenate([self.hist, sig])
        self.hist = cat[-H:]

        def d(col, ms):
            k = min(int(sr * ms / 1000), H)
            return cat[H - k: H - k + n, col]

        outL, outR = L.copy(), R.copy()

        if acfg("fx_surround"):
            k = acfg("fx_surround_amt") / 100 * 0.9
            sm = np.array([0.25, 0.5, 0.25], np.float32)     # 轻微低通，模拟后方声源
            lp = lambda v: np.convolve(v, sm, mode="same")
            outL += k * (lp(d(2, 15)) - 0.45 * lp(d(3, 21)))
            outR += k * (lp(d(3, 15)) - 0.45 * lp(d(2, 21)))
            rv = acfg("fx_reverb") / 100
            if rv > 0:
                scale = (0.7, 1.0, 1.6)[acfg("fx_room")]
                taps = ((23, .38), (37, .30), (53, .24), (71, .18), (97, .13), (131, .09))
                for j, (ms, gain) in enumerate(taps):
                    a, b = (0, 1) if j % 2 == 0 else (1, 0)
                    outL += rv * gain * d(a, ms * scale)
                    outR += rv * gain * d(b, ms * scale * 1.07)
            norm = 1 / (1 + 0.5 * k + 0.4 * rv)
            outL *= norm
            outR *= norm

        if acfg("fx_crossfeed"):
            sm = np.array([0.2, 0.3, 0.3, 0.2], np.float32)
            xL = np.convolve(d(1, 0.3), sm, mode="same")
            xR = np.convolve(d(0, 0.3), sm, mode="same")
            outL, outR = (outL + 0.35 * xL) / 1.2, (outR + 0.35 * xR) / 1.2

        b = acfg("fx_balance") / 100
        outL *= min(1.0, 1 - b)
        outR *= min(1.0, 1 + b)
        return np.stack([outL, outR], axis=1)


class AudioDialog(QDialog):
    """音效设置（实时生效）"""
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("音效设置")
        self.setMinimumWidth(420)
        v = QVBoxLayout(self)
        v.setSpacing(12)

        self.en = QCheckBox("启用音效处理（关闭时为原声直出）")
        self.en.setChecked(acfg("fx_enabled"))
        self.en.toggled.connect(lambda c: self._set("fx_enabled", c, apply=True))
        v.addWidget(self.en)

        g1 = QGroupBox("立体声")
        f1 = QFormLayout(g1)
        self.mode = QComboBox(); self.mode.addItems(CHANNEL_MODES); self.mode.setCurrentIndex(acfg("fx_channel_mode"))
        self.mode.currentIndexChanged.connect(lambda i: self._set("fx_channel_mode", i))
        f1.addRow("声道模式", self.mode)
        f1.addRow("声道平衡", self._slider("fx_balance", -100, 100, lambda x: "居中" if x == 0 else (f"左 {-x}" if x < 0 else f"右 {x}")))
        f1.addRow("立体声宽度", self._slider("fx_width", 0, 200, lambda x: f"{x}%"))
        cf = QCheckBox("耳机交叉馈送（减轻耳机听感疲劳）"); cf.setChecked(acfg("fx_crossfeed"))
        cf.toggled.connect(lambda c: self._set("fx_crossfeed", c))
        f1.addRow(cf)
        v.addWidget(g1)

        g2 = QGroupBox("环绕声")
        f2 = QFormLayout(g2)
        sur = QCheckBox("虚拟环绕声"); sur.setChecked(acfg("fx_surround"))
        sur.toggled.connect(lambda c: self._set("fx_surround", c))
        f2.addRow(sur)
        f2.addRow("环绕强度", self._slider("fx_surround_amt", 0, 100, lambda x: f"{x}%"))
        room = QComboBox(); room.addItems(ROOMS); room.setCurrentIndex(acfg("fx_room"))
        room.currentIndexChanged.connect(lambda i: self._set("fx_room", i))
        f2.addRow("空间大小", room)
        f2.addRow("空间混响", self._slider("fx_reverb", 0, 100, lambda x: f"{x}%"))
        out = QComboBox(); out.addItems(OUTPUTS); out.setCurrentIndex(acfg("fx_output"))
        out.currentIndexChanged.connect(lambda i: self._set("fx_output", i, apply=True))
        f2.addRow("多声道输出", out)
        lfe = QCheckBox("下混时保留低音炮（LFE）声道"); lfe.setChecked(acfg("fx_lfe"))
        lfe.toggled.connect(lambda c: self._set("fx_lfe", c))
        f2.addRow(lfe)
        v.addWidget(g2)

        self.status = QLabel("")
        self.status.setObjectName("time")
        v.addWidget(self.status)
        h = QHBoxLayout()
        rst = QPushButton("恢复默认"); rst.clicked.connect(self._reset)
        ok = QPushButton("完成"); ok.clicked.connect(self.accept)
        h.addWidget(rst); h.addStretch(1); h.addWidget(ok)
        v.addLayout(h)
        self.t = QTimer(self, interval=500)
        self.t.timeout.connect(self._refresh)
        self.t.start()
        self._refresh()

    def _slider(self, key, lo, hi, text):
        w = QHBoxLayout()
        s = QSlider(Qt.Orientation.Horizontal); s.setRange(lo, hi); s.setValue(acfg(key))
        lbl = QLabel(text(s.value())); lbl.setFixedWidth(56)
        s.valueChanged.connect(lambda x: (lbl.setText(text(x)), self._set(key, x)))
        s.setPageStep(5)
        w.addWidget(s, 1); w.addWidget(lbl)
        box = QGroupBox(); box.setFlat(True); box.setStyleSheet("QGroupBox{border:none;margin:0;padding:0;}")
        box.setLayout(w)
        return box

    def _set(self, k, v, apply=False):
        CFG.setValue(k, v)
        if apply:
            self.engine.apply()
        self._refresh()

    def _reset(self):
        for k in AUDIO_DEFAULTS:
            CFG.remove(k)
        self.engine.apply()
        self.accept()

    def _refresh(self):
        if not acfg("fx_enabled"):
            self.status.setText("当前：原声直出（未经任何处理）")
        else:
            self.status.setText(self.engine.src_desc or "音效处理已开启，播放时显示声道信息")
