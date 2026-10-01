"""Floating recording control bar (stop / pause / timer / microphone)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QRegion
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from .. import icons, winapi
from ..theme import rgba, theme, ui_font
from .widgets import FluentWindow, IconButton, Separator

BAR_HEIGHT = 48
BAR_MARGIN = 14


class _StopButton(QPushButton):
    """Red stop button, matching the Windows 11 recording bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 36)
        self.setToolTip("停止录制 (Ctrl+Alt+Q)")
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._hover = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

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
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        color = QColor("#C42B1C")
        if self._pressed:
            color = color.darker(115)
        elif self._hover:
            color = color.lighter(115)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, theme.radius_control, theme.radius_control)
        size = 14
        icons.paint_icon(painter, "stop",
                         QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size),
                         QColor("#FFFFFF"))
        painter.end()


class RecordControlBar(FluentWindow):
    """Always-on-top recording controls."""

    stopRequested = Signal()
    pauseRequested = Signal(bool)      # True -> pause, False -> resume
    discardRequested = Signal()
    micToggled = Signal(bool)

    def __init__(self, *, mic_available: bool = True, mic_enabled: bool = False) -> None:
        super().__init__(None, tint_strength=0.88, open_slide=10, margin=BAR_MARGIN)
        self.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._paused = False
        self._elapsed = 0.0
        self._drag_origin: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(BAR_MARGIN + 8, BAR_MARGIN + 6, BAR_MARGIN + 6, BAR_MARGIN + 6)
        layout.setSpacing(2)

        self.grip = QWidget(self)
        self.grip.setFixedSize(18, 36)
        self.grip.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.grip)

        self.dot = QWidget(self)
        self.dot.setFixedSize(16, 36)
        self.dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.dot)

        self.timer_label = QLabel("00:00:00", self)
        self.timer_label.setFont(ui_font(14, 600))
        self.timer_label.setFixedHeight(36)
        self.timer_label.setMinimumWidth(74)
        self.timer_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.timer_label)

        self.pause_button = IconButton("pause", self, width=40, height=36, tooltip="暂停 (Ctrl+Alt+P)")
        self.pause_button.clicked.connect(self._toggle_pause)
        layout.addWidget(self.pause_button)

        self.mic_button = IconButton(
            "mic" if mic_enabled else "mic_off", self, width=40, height=36,
            tooltip="麦克风", checkable=True,
        )
        self.mic_button.setEnabled(mic_available)
        self.mic_button.setChecked(mic_enabled)
        self.mic_button.clicked.connect(self._on_mic_clicked)
        layout.addWidget(self.mic_button)

        layout.addWidget(Separator(self, height=22))

        self.discard_button = IconButton("trash", self, width=40, height=36,
                                         tooltip="取消并删除这段录制")
        self.discard_button.clicked.connect(self.discardRequested.emit)
        layout.addWidget(self.discard_button)

        self.stop_button = _StopButton(self)
        self.stop_button.clicked.connect(self.stopRequested.emit)
        layout.addWidget(self.stop_button)

        self.setFixedSize(layout.sizeHint().width() + 4, BAR_HEIGHT + 2 * BAR_MARGIN)
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

    def _on_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        self.dot.update()

    def _on_mic_clicked(self) -> None:
        self.mic_button.set_icon_name("mic" if self.mic_button.isChecked() else "mic_off")
        self.micToggled.emit(self.mic_button.isChecked())

    def _toggle_pause(self) -> None:
        self.set_paused(not self._paused)
        self.pauseRequested.emit(self._paused)

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.pause_button.set_icon_name("play" if paused else "pause")
        self.pause_button.setToolTip("继续 (Ctrl+Alt+P)" if paused else "暂停 (Ctrl+Alt+P)")
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
        grip_color = rgba(palette.text_secondary, 0.55)
        grip_geo = self.grip.geometry()
        icons.paint_icon(painter, "grip",
                         QRectF(grip_geo.x(), grip_geo.y() + 6, grip_geo.width(), 24), grip_color)
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
            self.move(x - BAR_MARGIN, y - BAR_MARGIN)
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
        self.move(chosen.x() - BAR_MARGIN, chosen.y() - BAR_MARGIN)

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
