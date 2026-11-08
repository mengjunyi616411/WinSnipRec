"""Floating recording control bar (stop / pause / timer / microphone)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QRegion
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons, winapi
from ..settings import settings
from ..theme import rgba, theme, ui_font
from .widgets import FluentWindow, IconButton, Separator
from ..i18n import t as _t

BAR_HEIGHT = 36
BAR_MARGIN = 14


def _button_font(size: int = 15) -> QFont:
    """按钮文字字体：显式用中文字体族。

    ui_font() 的首选族是 Segoe UI Variable Text，不含汉字，"停止/开始" 会走
    font fallback，在 125% DPI 下明显发虚。这里把中文字体放在最前面。
    """
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "SimHei"])
    font.setPixelSize(size)
    font.setWeight(QFont.Weight.DemiBold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


class _StopButton(QPushButton):
    """蓝色主按钮：白圆环 + 文字（开始 / 停止）。

    文字用 QLabel 子控件而不是自绘：之前 drawText 在 125% DPI 下明显发虚，
    换成 QLabel 走 Qt 原生的文字渲染 + 抗锯齿，和系统其它文字一样清晰。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._label = _t("停止")
        self.setText("")        # 文字由 QLabel 显示，QPushButton 的 text 留空
        self.setToolTip(_t("停止录制 (Ctrl+Alt+Q)"))
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hover = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._text = QLabel(self._label, self)
        self._text.setFont(_button_font(15))
        self._text.setStyleSheet("color: #FFFFFF; background: transparent;")
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._fit()

    def _fit(self) -> None:
        metrics = QFontMetrics(_button_font(15))
        width = 11 + 21 + 9 + metrics.horizontalAdvance(self._label) + 14
        self.setFixedSize(max(84, width), 36)
        self._text.setGeometry(39, 0, self.width() - 39 - 8, self.height())

    def set_label(self, text: str) -> None:
        self._label = text
        self._text.setText(text)
        self._fit()
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        color = QColor(theme.palette.accent)
        if self._pressed:
            color = color.darker(112)
        elif self._hover:
            color = color.lighter(108)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 10.0, 10.0)

        # 白色圆环（录制指示）
        ring_size = 21.0
        ring = QRectF(11.0, (self.height() - ring_size) / 2, ring_size, ring_size)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#FFFFFF"), 3.2))
        painter.drawEllipse(ring.adjusted(2, 2, -2, -2))
        painter.end()


class RecordControlBar(FluentWindow):
    """Always-on-top recording controls."""

    #: 预备模式（框选完还没开录）下按主按钮时发这个；录制中则发 stopRequested。
    startRequested = Signal()
    stopRequested = Signal()
    pauseRequested = Signal(bool)      # True -> pause, False -> resume
    discardRequested = Signal()
    micToggled = Signal(bool)

    def __init__(self, *, mic_available: bool = True, mic_enabled: bool = False,
                 preview: bool = False) -> None:
        # margin=0：原来留给投影的 14px 边距在这台机器上渲染不出投影，
        # 只剩一圈透明白边（菜单和 Toast 之前也是这个毛病）。
        super().__init__(None, tint_strength=0.88, open_slide=10, margin=0,
                         native_backdrop=False, shadow=False)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # 预备模式：主按钮显示「开始」，点了才真正开录（对应 Win11 截图工具框选后的条）
        self._preview = preview
        self._paused = False
        self._elapsed = 0.0
        self._drag_origin: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 12, 10)
        layout.setSpacing(2)

        # ---- 控件全部先建好，顺序按模式决定 ----
        self.stop_button = _StopButton(self)
        if preview:
            self.stop_button.set_label(_t("开始"))
        self.stop_button.clicked.connect(self._on_main_clicked)

        self.timer_label = QLabel("00:00:00", self)
        self.timer_label.setFont(ui_font(14, 600))
        self.timer_label.setFixedHeight(36)
        self.timer_label.setMinimumWidth(74)
        self.timer_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.mic_button = IconButton(
            "mic" if mic_enabled else "mic_off", self, width=40, height=36,
            tooltip=_t("麦克风"), checkable=True,
        )
        self.mic_button.setEnabled(mic_available)
        self.mic_button.setChecked(mic_enabled)
        self.mic_button.clicked.connect(self._on_mic_clicked)

        self.sound_button = IconButton(
            "sound" if getattr(settings, "system_audio", False) else "sound_off",
            self, width=40, height=36, tooltip=_t("录制系统声音"), checkable=True)
        self.sound_button.setChecked(bool(getattr(settings, "system_audio", False)))
        self.sound_button.clicked.connect(self._on_sound_clicked)

        self.discard_button = IconButton("close", self, width=40, height=36,
                                         tooltip=_t("取消并删除这段录制"))
        self.discard_button.clicked.connect(self.discardRequested.emit)

        self.dot = QWidget(self)
        self.dot.setFixedSize(16, 36)
        self.dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.pause_button = IconButton("pause", self, width=40, height=36,
                                       tooltip=_t("暂停 (Ctrl+Alt+P)"))
        self.pause_button.clicked.connect(self._toggle_pause)

        # ---- 布局顺序 ----
        if preview:
            # 用户参考图： [● 开始] 00:00:00  🎤  🔊  |  ✕
            # 准备阶段没有红点和暂停（还没开始录，暂停没有意义）
            # 这两个控件也创建了，但不进布局时必须隐藏，
            # 否则作为子控件会浮在窗口左上角（实测出现红点和暂停贴在按钮上）。
            self.dot.hide()
            self.pause_button.hide()
            layout.addWidget(self.stop_button)
            layout.addWidget(self.timer_label)
            layout.addWidget(self.mic_button)
            layout.addWidget(self.sound_button)
            layout.addWidget(Separator(self, height=22))
            layout.addWidget(self.discard_button)
        else:
            # 录制中： [●] 00:00:00  ‖  🎤  🔊  |  ✕  [■ 停止]
            layout.addWidget(self.dot)
            layout.addWidget(self.timer_label)
            layout.addWidget(self.pause_button)
            layout.addWidget(self.mic_button)
            layout.addWidget(self.sound_button)
            layout.addWidget(Separator(self, height=22))
            layout.addWidget(self.discard_button)
            layout.addWidget(self.stop_button)

        hint = layout.sizeHint()
        self.setFixedSize(hint.width() + 4, hint.height())
        self.refresh()
        self._pulse = QTimer(self)
        self._pulse.setInterval(700)
        self._pulse.timeout.connect(self._on_pulse)
        self._pulse_on = True
        self._pulse.start()

    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        palette = theme.palette
        self.timer_label.setStyleSheet(
            f"color: {palette.text_primary}; letter-spacing: 0.5px;"
        )
        self.mic_button.set_icon_name("mic" if self.mic_button.isChecked() else "mic_off")
        self.update()

    def set_recording(self) -> None:
        """从预备条切到录制态：按钮变「停止」，红点和暂停回到布局里。
    
        两套布局的控件顺序不同，所以直接清空布局重建。
        """
        if not self._preview:
            return
        self._preview = False
        self.stop_button.set_label(_t("停止"))
        self._rebuild_layout(recording=True)
    
    def _rebuild_layout(self, *, recording: bool) -> None:
        """按模式重排控件。takeAt 只把控件移出布局，不销毁。"""
        layout = self.layout()
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
        if recording:
            self.dot.show()
            self.pause_button.show()
            layout.addWidget(self.dot)
            layout.addWidget(self.timer_label)
            layout.addWidget(self.pause_button)
            layout.addWidget(self.mic_button)
            layout.addWidget(self.sound_button)
            layout.addWidget(Separator(self, height=22))
            layout.addWidget(self.discard_button)
            layout.addWidget(self.stop_button)
        else:
            layout.addWidget(self.stop_button)
            layout.addWidget(self.timer_label)
            layout.addWidget(self.mic_button)
            layout.addWidget(self.sound_button)
            layout.addWidget(Separator(self, height=22))
            layout.addWidget(self.discard_button)
        for widget in (self.stop_button, self.timer_label, self.mic_button,
                       self.sound_button, self.discard_button):
            widget.show()
        hint = layout.sizeHint()
        self.setFixedSize(hint.width() + 4, hint.height())
        self.update()
    
    def _on_main_clicked(self) -> None:
        """主按钮：预备模式发 startRequested 并切到录制态，录制中发 stopRequested。"""
        if self._preview:
            self.set_recording()
            self.startRequested.emit()
        else:
            self.stopRequested.emit()

    def _on_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self.dot.update()

    def _on_mic_clicked(self) -> None:
        self.mic_button.set_icon_name("mic" if self.mic_button.isChecked() else "mic_off")
        self.micToggled.emit(self.mic_button.isChecked())

    def _on_sound_clicked(self) -> None:
        """系统声音开关。录制中切换要 recorder 支持，这里先同步 UI 与设置。"""
        from .widgets import show_toast
    
        on = self.sound_button.isChecked()
        self.sound_button.set_icon_name("sound" if on else "sound_off")
        try:
            settings.system_audio = on
        except Exception:
            pass
        show_toast(_t("系统声音"), _t("已开启") if on else _t("已关闭"),
                   "sound" if on else "sound_off", duration=1600)

    def _toggle_pause(self) -> None:
        self.set_paused(not self._paused)
        self.pauseRequested.emit(self._paused)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_button.set_icon_name("play" if paused else "pause")
        self.pause_button.setToolTip(_t("继续 (Ctrl+Alt+P)") if paused else _t("暂停 (Ctrl+Alt+P)"))
        self._pulse.stop() if paused else self._pulse.start()
        self.update()

    def is_paused(self) -> bool:
        return self._paused

    def set_elapsed(self, seconds: float) -> None:
        self._elapsed = seconds
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        self.timer_label.setText(f"{hours:02d}:{minutes:02d}:{secs:02d}")

    def set_mic_enabled(self, enabled: bool, available: bool = True) -> None:
        self.mic_button.setEnabled(available)
        self.mic_button.setChecked(enabled)
        self.mic_button.set_icon_name("mic" if enabled else "mic_off")

    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        # 准备条里 dot 是隐藏的（没进布局），这里必须跳过，
        # 否则红点会被画在窗口左上角（实测就是这个问题）。
        if self.dot.isVisible():
            dot_geo = self.dot.geometry()
            if self._paused:
                dot_color = QColor(palette.text_secondary)
            else:
                dot_color = QColor("#E81123") if self._pulse_on else rgba("#E81123", 0.35)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(dot_color)
            painter.drawEllipse(QRectF(dot_geo.x() + 3.5, dot_geo.y() + 13.5, 9, 9))
        painter.end()

    # ------------------------------------------------------------------ #
    def place_outside(self, physical_region: QRect | None, logical_region: QRect | None = None) -> None:
        """Position the bar so that it is not inside the recorded area."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        dpr = screen.devicePixelRatio()
        region = logical_region
        if region is None and physical_region is not None:
            region = QRect(
                int(physical_region.x() / dpr), int(physical_region.y() / dpr),
                int(physical_region.width() / dpr), int(physical_region.height() / dpr),
            )
        margin = 12
        width = self.width()
        height = self.height()
        if region is None:
            x = available.left() + (available.width() - width) // 2
            y = available.top() + margin
            self.move(x, y)
            return

        candidates = [
            QPoint(region.center().x() - width // 2, region.top() - height - margin),
            QPoint(region.center().x() - width // 2, region.bottom() + margin),
            QPoint(region.left() - width - margin, region.center().y() - height // 2),
            QPoint(region.right() + margin, region.center().y() - height // 2),
            QPoint(available.center().x() - width // 2, available.top() + margin),
            QPoint(available.center().x() - width // 2, available.bottom() - height - margin),
        ]
        chosen = None
        for candidate in candidates:
            bar = QRect(candidate, QSize(width, height))
            if not available.contains(bar):
                continue
            if bar.intersects(region.adjusted(-4, -4, 4, 4)):
                continue
            chosen = candidate
            break
        if chosen is None:
            chosen = candidates[4]
        self.move(chosen.x(), chosen.y())

    def exclude_from_capture(self) -> None:
        """Best effort: keep the bar out of the recording on Windows 10 2004+."""
        try:
            handle = self.windowHandle()
            if handle is None:
                return
            WDA_EXCLUDEFROMCAPTURE = 0x00000011
            import ctypes

            ctypes.windll.user32.SetWindowDisplayAffinity(int(handle.winId()), WDA_EXCLUDEFROMCAPTURE)
        except Exception:
            pass

    # -- dragging ---------------------------------------------------------- #
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()
                return
        super().mousePressEvent(event)


class CountdownOverlay(FluentWindow):
    """Large countdown number shown over the capture region before recording."""

    finished = Signal()

    def __init__(self, logical_region: QRect, seconds: int) -> None:
        super().__init__(None, tint_strength=0.80, margin=12,
                         open_animation="fade")
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._value = seconds
        self._region = logical_region
        size = min(220, max(140, min(logical_region.width(), logical_region.height()) // 2))
        self.set_card_size(size, size)
        centre = logical_region.center()
        self.move_card_to(centre.x() - size // 2, centre.y() - size // 2)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self._value -= 1
        if self._value <= 0:
            self._timer.stop()
            self.finished.emit()
            self.close()
            return
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self.card_rect()
        font = ui_font(int(card.height() * 0.42), 600)
        painter.setFont(font)
        painter.setPen(QColor(theme.palette.text_primary))
        painter.drawText(QRectF(card), int(Qt.AlignmentFlag.AlignCenter), str(max(0, self._value)))
        painter.end()
