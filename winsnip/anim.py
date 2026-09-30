"""Fluent motion helpers.

Animations follow the Windows 11 motion language: short durations (150-300 ms)
with ease-out curves, plus a small directional offset for entering surfaces.
They are skipped entirely when Windows' "show animations" accessibility setting
is off, or when the user disabled them in the app's settings.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRect, QTimer,
)
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
