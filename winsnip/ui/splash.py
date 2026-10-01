"""Launch splash screen with a Fluent motion transition into the main window."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .. import __version__, anim, icons
from ..theme import theme, ui_font
from .widgets import FluentWindow

MIN_VISIBLE_MS = 900          # a splash that flashes for 80 ms feels broken
MAX_VISIBLE_MS = 6000         # never let a slow start hold the splash forever


class ProgressRing(QWidget):
    """Fluent indeterminate progress ring."""

    def __init__(self, parent: QWidget | None = None, size: int = 30,
                 thickness: float = 3.0) -> None:
        super().__init__(parent)
        self._size = size
        self._thickness = thickness
        self._angle = 0.0
        self._sweep = 90.0
        self._phase = 0.0
        self.setFixedSize(size, size)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    # -- lifecycle --------------------------------------------------------- #
    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if anim.animations_enabled():
            self.start()
        else:
            self._angle = 270.0
            self._sweep = 300.0
            self.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._angle = (self._angle + 6.5) % 360.0
        # Breathe the arc length the way WinUI's ring does.
        self._phase = (self._phase + 0.035) % 1.0
        import math

        self._sweep = 70.0 + 190.0 * (0.5 + 0.5 * math.sin(self._phase * 2 * math.pi))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        inset = self._thickness / 2 + 0.5
        box = QRectF(inset, inset, self._size - inset * 2, self._size - inset * 2)

        track = QPen(QColor(palette.accent))
        track.setWidthF(self._thickness)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        colour = QColor(palette.accent)
        colour.setAlphaF(0.18)
        track.setColor(colour)
        painter.setPen(track)
        painter.drawEllipse(box)

        arc = QPen(QColor(palette.accent))
        arc.setWidthF(self._thickness)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        painter.drawArc(box, int(self._angle * 16), int(-self._sweep * 16))
        painter.end()


class SplashWindow(FluentWindow):
    """Small launch window: icon + name + progress ring."""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, tint_strength=0.92, margin=22,
                         open_animation="none")
        self.setWindowTitle("截图工具")
        # SplashScreen keeps it out of the taskbar and without decorations.
        self.setWindowFlags(Qt.WindowType.SplashScreen |
                            Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.set_card_size(400, 236)
        self._shown_at = time.perf_counter()
        self._finishing = False

        from PySide6.QtWidgets import QLabel

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22 + 24, 22 + 26, 22 + 24, 22 + 22)
        layout.setSpacing(6)
        layout.addStretch(1)

        self.icon = QLabel(self)
        self.icon.setPixmap(icons.app_icon().pixmap(64, 64))
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)

        # NOTE: no ui_font() here on purpose. The first custom font family costs
        # 3-4 s to resolve on a software-rendered desktop, and Qt pays it inside
        # show(), before showEvent — which would keep the splash unseen for that
        # whole time. showEvent applies the fonts once the window is on screen.
        self.title = QLabel("截图工具", self)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title)

        self.subtitle = QLabel(f"WinSnipRec {__version__}", self)
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.subtitle)

        layout.addSpacing(10)
        self.ring = ProgressRing(self, 30, 3.0)
        layout.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

        self.refresh_theme()
        self._centre_on_screen()

    # ------------------------------------------------------------------ #
    def refresh_theme(self) -> None:
        palette = theme.palette
        self.title.setStyleSheet(f"color: {palette.text_primary};")
        self.subtitle.setStyleSheet(f"color: {palette.text_secondary};")
        self.update()

    def _centre_on_screen(self) -> None:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move_card_to(available.center().x() - self.card_size().width() // 2,
                          available.center().y() - self.card_size().height() // 2)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)

    def _apply_fonts(self) -> None:
        """Resolve the real fonts now that the splash is already visible.

        Qt resolves the first custom font family during the window's first
        polish, i.e. inside show() and before showEvent, which costs 3-4 s on a
        software-rendered desktop. Setting the fonts in __init__ therefore kept
        the splash invisible for that whole time, so they are applied here
        instead, queued one event-loop turn after the window is on screen.
        """
        if getattr(self, "_fonts_applied", False):
            return
        self._fonts_applied = True
        self.title.setFont(ui_font(21, 600))
        self.subtitle.setFont(ui_font(12))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_fonts)

    # ------------------------------------------------------------------ #
    def start(self) -> None:
        from PySide6.QtCore import QPropertyAnimation

        self.show()
        self.ring.start()
        if anim.animations_enabled():
            self.setWindowOpacity(0.0)
            fade = QPropertyAnimation(self, b"windowOpacity", self)
            fade.setDuration(220)
            fade.setStartValue(0.0)
            fade.setEndValue(1.0)
            fade.setEasingCurve(anim.curve("out"))
            fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        else:
            self.setWindowOpacity(1.0)
        QTimer.singleShot(MAX_VISIBLE_MS, self._force_finish)

    def _force_finish(self) -> None:
        if not self._finishing:
            self.close()

    def finish(self, window: QWidget | None, *, then=None) -> None:
        """Hand over to the real window after the minimum splash time."""
        if self._finishing:
            return
        self._finishing = True
        elapsed_ms = (time.perf_counter() - self._shown_at) * 1000
        wait = max(0, int(MIN_VISIBLE_MS - elapsed_ms))

        def handover() -> None:
            if window is not None:
                # The window plays its own Fluent enter transition in showEvent.
                window.show()
            elif then is not None:
                then()
            anim.hide_window_animated(self, on_finished=self.close)

        QTimer.singleShot(wait, handover)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.ring.stop()
        super().closeEvent(event)
        self.closed.emit()
