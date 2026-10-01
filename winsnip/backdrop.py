"""Real DWM backdrop materials, with a pixel probe to decide whether they work.

Asking DWM for a Mica/Acrylic backdrop returns success even on machines that
render nothing: the environment here (a virtual display adapter in front of the
session) accepts DWMWA_SYSTEMBACKDROP_TYPE and SetWindowCompositionAttribute and
draws a flat surface - the system's own Start menu is opaque too. So availability
is decided by *measuring pixels*, not by the return code.

The probe builds a throwaway non-layered window, captures the screen behind it,
applies the backdrop, and captures again. If the area does not change, the
material does not render and the caller keeps the wallpaper-based fallback.
"""

from __future__ import annotations

import logging
import time

from . import winapi

log = logging.getLogger(__name__)

# None = not probed yet in this process.
_PROBED: bool | None = None

# Bumped when the probe itself changes, so a stale cached answer is re-checked.
PROBE_VERSION = 1


def probe_native_backdrop(timeout: float = 2.0) -> bool:
    """Measure whether a DWM backdrop actually renders on this machine.

    Must be called with a live QApplication. Returns False on any failure, so
    the caller always has a working fallback.
    """
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication, QWidget
    except Exception:  # pragma: no cover - Qt is always present in the app
        return False

    app = QApplication.instance()
    screen = QGuiApplication.primaryScreen()
    if app is None or screen is None:
        return False

    class _Probe(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                                Qt.WindowType.Tool |
                                Qt.WindowType.WindowStaysOnTopHint)
            # The backdrop only shows where the client area is NOT painted, and a
            # layered window would bypass it entirely - hence neither the
            # translucent attribute nor any background fill.
            self.setAutoFillBackground(False)
            self.resize(240, 150)

        def paintEvent(self, event) -> None:  # noqa: N802
            pass

    window = _Probe()
    try:
        geometry = screen.availableGeometry()
        window.move(geometry.center().x() - 120, geometry.center().y() - 75)
        window.show()
        window.raise_()
        handle = window.windowHandle()
        if handle is None:
            return False
        hwnd = int(handle.winId())
        if not hwnd or winapi.is_layered(hwnd):
            return False

        def settle(seconds: float) -> None:
            end = time.perf_counter() + seconds
            while time.perf_counter() < end:
                app.processEvents()
                time.sleep(0.02)

        settle(0.5)
        rect = (window.x(), window.y(), window.width(), window.height())
        before = _crop(screen, rect)

        applied = winapi.set_system_backdrop(hwnd, winapi.DWMSBT_TRANSIENTWINDOW)
        if not applied:
            applied = winapi.set_accent_blur(hwnd, winapi.ACCENT_ENABLE_ACRYLICBLURBEHIND)
        settle(0.7)
        after = _crop(screen, rect)
        winapi.clear_backdrop(hwnd)

        changed = _difference(before, after)
        log.info("backdrop probe: applied=%s changed=%.1f%%", applied, changed * 100)
        return applied and changed > 0.05
    except Exception:
        log.exception("backdrop probe failed; keeping the wallpaper material")
        return False
    finally:
        try:
            window.close()
            window.deleteLater()
            app.processEvents()
        except Exception:
            pass


def _crop(screen, rect):
    x, y, width, height = rect
    image = screen.grabWindow(0, x, y, width, height).toImage()
    return image.convertToFormat(image.Format.Format_RGB32)


def _difference(before, after) -> float:
    """Share of sampled pixels that changed by more than one level."""
    if before.isNull() or after.isNull():
        return 0.0
    if before.size() != after.size():
        return 1.0
    changed = 0
    total = 0
    for x in range(2, before.width() - 2, 4):
        for y in range(2, before.height() - 2, 4):
            a = before.pixelColor(x, y)
            b = after.pixelColor(x, y)
            total += 1
            if (abs(a.red() - b.red()) + abs(a.green() - b.green())
                    + abs(a.blue() - b.blue())) > 3:
                changed += 1
    return changed / max(1, total)


def native_available(force: bool = False) -> bool:
    """Cached probe result, persisted in the settings file.

    The probe shows a small window for about a second, so it runs once per
    machine (and once more if the OS build changes).
    """
    global _PROBED
    if _PROBED is not None and not force:
        return _PROBED

    from .settings import Settings, settings

    build = winapi_windows_build()
    if (not force
            and getattr(settings, "backdrop_probe_version", 0) == PROBE_VERSION
            and getattr(settings, "backdrop_probe_build", None) == build
            and getattr(settings, "backdrop_native", None) is not None):
        _PROBED = bool(settings.backdrop_native)
        return _PROBED

    _PROBED = probe_native_backdrop()
    try:
        settings.backdrop_native = _PROBED
        settings.backdrop_probe_version = PROBE_VERSION
        settings.backdrop_probe_build = build
        settings.save()
    except Exception:
        log.exception("could not cache the backdrop probe result")
    return _PROBED


def winapi_windows_build() -> int:
    try:
        import sys

        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def wanted() -> bool:
    """Should windows use the native backdrop? Honours the user's setting."""
    from .settings import settings

    mode = getattr(settings, "backdrop", "auto")
    if mode == "classic":
        return False
    if mode == "native":
        return True
    return native_available()


def apply_to(window) -> bool:
    """Apply the native backdrop to a Qt window that is ready for it."""
    try:
        handle = window.windowHandle()
        if handle is None:
            return False
        hwnd = int(handle.winId())
        if not hwnd:
            return False
        if winapi.set_system_backdrop(hwnd, winapi.DWMSBT_TRANSIENTWINDOW):
            return True
        return winapi.set_accent_blur(hwnd, winapi.ACCENT_ENABLE_ACRYLICBLURBEHIND)
    except Exception:
        log.exception("applying the native backdrop failed")
        return False
