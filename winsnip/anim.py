"""Fluent motion helpers.

Animations follow the Windows 11 motion language: short durations (150-300 ms)
with ease-out curves, plus a small directional offset for entering surfaces.
They are skipped entirely when Windows' "show animations" accessibility setting
is off, or when the user disabled them in the app's settings.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QRectF,
    Qt, QTimer,
)
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from . import winapi

# Fluent duration tokens (Windows 11 motion guidelines)
DURATION_FAST = 150
DURATION_NORMAL = 240
DURATION_SLOW = 320


def _settings_enabled() -> bool:
    try:
        from .settings import settings

        return bool(settings.animations)
    except Exception:
        return True


def animations_enabled() -> bool:
    """True when both the app and Windows allow animations."""
    return _settings_enabled() and winapi.client_area_animations_enabled()


def curve(kind: str = "out") -> QEasingCurve:
    mapping = {
        "out": QEasingCurve.Type.OutCubic,
        "in": QEasingCurve.Type.InCubic,
        "inout": QEasingCurve.Type.InOutCubic,
        "decelerate": QEasingCurve.Type.OutQuint,
    }
    return QEasingCurve(mapping.get(kind, QEasingCurve.Type.OutCubic))


def _freeze(window: QWidget, frozen: bool) -> None:
    """Skip Mica re-computation while a window is moving, then refresh once."""
    if hasattr(window, "_freeze_backdrop"):
        window._freeze_backdrop = frozen
        if not frozen and hasattr(window, "invalidate_backdrop"):
            window.invalidate_backdrop()


def play_window_open(window: QWidget, *, slide: int = 14, fade_only: bool = False,
                     duration: int = DURATION_NORMAL) -> None:
    """Animate an already-visible window in. Safe to call from ``showEvent``.

    The window is made fully transparent *before* returning, so no frame is ever
    painted at full opacity (which would show up as a flash).
    """
    window.setWindowOpacity(0.0)
    if not animations_enabled():
        window.setWindowOpacity(1.0)
        return
    _freeze(window, True)
    final = QRect(window.geometry())
    if not fade_only:
        window.move(final.x(), final.y() + slide)

    group = QParallelAnimationGroup(window)
    fade = QPropertyAnimation(window, b"windowOpacity", group)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(curve("out"))

    if not fade_only:
        move = QPropertyAnimation(window, b"pos", group)
        move.setDuration(duration)
        move.setStartValue(QPoint(final.x(), final.y() + slide))
        move.setEndValue(QPoint(final.x(), final.y()))
        move.setEasingCurve(curve("decelerate"))

    def finished() -> None:
        if not fade_only:
            window.setGeometry(final)
        window.setWindowOpacity(1.0)
        _freeze(window, False)

    group.finished.connect(finished)
    group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)


def show_window_animated(window: QWidget, *, slide: int = 14,
                         duration: int = DURATION_NORMAL) -> None:
    """Show a window with the Fluent enter transition.

    The window is shown first (at zero opacity) so the platform still performs
    its own placement -- moving a never-shown window would pin it to Qt's
    default position instead of the centred one Windows chooses. The automatic
    transition that ``FluentWindow.showEvent`` would play is suppressed so the
    two animations cannot fight over the window position.
    """
    if not animations_enabled():
        window.setWindowOpacity(1.0)
        window.show()
        return

    if hasattr(window, "_suppress_open_animation"):
        window._suppress_open_animation = True
    try:
        window.setWindowOpacity(0.0)
        window.show()
    finally:
        if hasattr(window, "_suppress_open_animation"):
            window._suppress_open_animation = False
    play_window_open(window, slide=slide, duration=duration)


def hide_window_animated(window: QWidget, *, on_finished=None,
                         duration: int = DURATION_FAST) -> None:
    """Fade a window out, then hide it."""
    if not animations_enabled():
        window.hide()
        window.setWindowOpacity(1.0)
        if on_finished is not None:
            on_finished()
        return

    fade = QPropertyAnimation(window, b"windowOpacity", window)
    fade.setDuration(duration)
    fade.setStartValue(window.windowOpacity())
    fade.setEndValue(0.0)
    fade.setEasingCurve(curve("in"))

    def finished() -> None:
        window.hide()
        window.setWindowOpacity(1.0)
        if on_finished is not None:
            on_finished()

    fade.finished.connect(finished)
    fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


#: Ghosts currently animating. Holding them also stops Python from collecting
#: the widget mid-flight.
_live_ghosts: list = []


def _minimize_ghost_count() -> int:
    """How many minimize snapshots are on screen (used by the self-tests)."""
    return len(_live_ghosts)


def minimize_target(window: QWidget, scale: float = 0.34) -> QRect:
    """Where a minimize animation should end: just above the taskbar."""
    geometry = window.geometry()
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.screenAt(geometry.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else geometry
    except Exception:
        area = geometry

    width = max(90, int(geometry.width() * scale))
    height = max(70, int(geometry.height() * scale))
    x = geometry.center().x() - width // 2
    x = max(area.left() + 6, min(area.right() - width - 6, x))
    y = area.bottom() - height - 6
    return QRect(x, y, width, height)


class _MinimizeGhost(QWidget):
    """A snapshot of a window, animated down to the taskbar."""

    def __init__(self, snapshot: QPixmap, radius: float) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._radius = radius
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QPainter, QPainterPath

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.setClipPath(path)
        painter.drawPixmap(QRectF(self.rect()), self._snapshot,
                           QRectF(self._snapshot.rect()))
        painter.end()


def minimize_window_animated(window: QWidget, *, on_finished=None,
                             duration: int = DURATION_NORMAL) -> None:
    """Play the Windows-style minimize, then actually minimize the window.

    The real window is minimized at once and a snapshot ghost provides the
    motion: resizing the live window would re-lay-out its contents every frame,
    which looks nothing like the system animation.
    """
    def fall_back() -> None:
        window.showMinimized()
        if on_finished is not None:
            on_finished()

    if not animations_enabled():
        fall_back()
        return

    try:
        snapshot = window.grab()
        snapshot.setDevicePixelRatio(1.0)
    except Exception:
        fall_back()
        return

    origin = window.geometry()
    target = minimize_target(window)
    window.showMinimized()

    ghost = _MinimizeGhost(snapshot, 14.0)
    _live_ghosts.append(ghost)
    ghost.setGeometry(origin)
    ghost.setWindowOpacity(1.0)
    ghost.show()

    def cleanup() -> None:
        ghost.hide()
        try:
            _live_ghosts.remove(ghost)
        except ValueError:
            pass
        ghost.deleteLater()
        if on_finished is not None:
            on_finished()

    group = QParallelAnimationGroup()
    group.setParent(ghost)

    move = QPropertyAnimation(ghost, b"geometry", group)
    move.setDuration(duration)
    move.setStartValue(origin)
    move.setEndValue(target)
    move.setEasingCurve(curve("in_out"))

    fade = QPropertyAnimation(ghost, b"windowOpacity", group)
    fade.setDuration(duration)
    fade.setStartValue(1.0)
    fade.setEndValue(0.0)
    fade.setEasingCurve(curve("in"))

    group.addAnimation(move)
    group.addAnimation(fade)
    group.finished.connect(cleanup)
    group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)


def fade_in(widget: QWidget, *, duration: int = DURATION_NORMAL, start: float = 0.0,
            effect_owner: QWidget | None = None) -> QGraphicsOpacityEffect | None:
    """Fade a plain widget (no window) in, using an opacity effect."""
    if not animations_enabled():
        return None
    owner = effect_owner or widget
    effect = QGraphicsOpacityEffect(owner)
    effect.setOpacity(start)
    owner.setGraphicsEffect(effect)
    animation = QPropertyAnimation(effect, b"opacity", owner)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(curve("out"))

    def finished() -> None:
        # Leaving the effect installed would keep the widget on a slow path.
        owner.setGraphicsEffect(None)

    animation.finished.connect(finished)
    animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    return effect


def after(milliseconds: int, callback) -> None:
    QTimer.singleShot(milliseconds, callback)
