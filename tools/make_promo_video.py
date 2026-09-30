"""Render the WinSnipRec promotional video, frame by frame.

Nothing here records the screen: on this machine a 1080p capture costs ~112 ms
(9 fps ceiling) and translucent windows take seconds to composite, so real
footage would look far worse than the app actually is. Instead every frame is
composited deterministically from the app's *real* widgets, which gives exact
60/30 fps motion and frame-accurate beats.

Run:  .venv\\Scripts\\python.exe tools\\make_promo_video.py [--preview]
Out:  promo/video/promo_1920x1080_30s.mp4
      promo/video/promo_1920x1080_30s.srt
      promo/video/contact_sheet.png
      promo/video/storyboard.md
      promo/video/sfx_track.wav
"""

from __future__ import annotations

import argparse
import math
import os
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_promo_video_config"))

import numpy as np  # noqa: E402
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

WIDTH, HEIGHT, FPS = 1920, 1080, 30
DURATION = 30.0
TOTAL_FRAMES = int(DURATION * FPS)
XFADE = 0.30                       # cross-fade between shots, seconds

OUT_DIR = ROOT / "promo" / "video"
SHOTS_DIR = ROOT / "docs" / "screenshots"

CJK = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"]
ACCENT = "#4CC2FF"
TEXT = "#F2F6FA"
TEXT_DIM = "#9BA8B7"


# --------------------------------------------------------------------------- #
# Tiny drawing helpers
# --------------------------------------------------------------------------- #
def font(size: int, weight: int = 400) -> QFont:
    f = QFont()
    f.setFamilies(CJK)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def text(painter: QPainter, value: str, rect: QRectF, size: int, colour,
         weight: int = 400, align=Qt.AlignmentFlag.AlignLeft, opacity: float = 1.0) -> None:
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.setFont(font(size, weight))
    painter.setPen(QColor(colour) if not isinstance(colour, QColor) else colour)
    painter.drawText(rect, int(align | Qt.AlignmentFlag.AlignVCenter), value)
    painter.restore()


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def ease_out(value: float) -> float:
    value = clamp(value)
    return 1 - (1 - value) ** 3


def ease_in_out(value: float) -> float:
    value = clamp(value)
    return value * value * (3 - 2 * value)


def span(t: float, start: float, length: float) -> float:
    """Normalised 0..1 progress of a sub-animation."""
    if length <= 0:
        return 1.0 if t >= start else 0.0
    return clamp((t - start) / length)


def build_background() -> QImage:
    image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    base = QLinearGradient(0, 0, WIDTH * 0.6, HEIGHT)
    base.setColorAt(0.0, QColor("#070B11"))
    base.setColorAt(0.45, QColor("#101925"))
    base.setColorAt(1.0, QColor("#05080C"))
    painter.fillRect(0, 0, WIDTH, HEIGHT, base)

    for cx, cy, radius, strength in ((0.80, 0.12, 0.55, 0.16), (0.10, 0.85, 0.50, 0.10)):
        glow = QRadialGradient(QPointF(WIDTH * cx, HEIGHT * cy), WIDTH * radius)
        colour = QColor(ACCENT)
        colour.setAlphaF(strength)
        glow.setColorAt(0.0, colour)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.fillRect(0, 0, WIDTH, HEIGHT, glow)

    # faint grid, like the Fluent "material" surfaces
    pen = QPen(QColor(255, 255, 255, 8))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    for x in range(0, WIDTH, 60):
        painter.drawLine(x, 0, x, HEIGHT)
    for y in range(0, HEIGHT, 60):
        painter.drawLine(0, y, WIDTH, y)
    painter.end()
    return image


def rounded_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    result = QPixmap(pixmap.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pixmap.width(), pixmap.height()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def drop_shadow(painter: QPainter, pixmap: QPixmap, target: QRectF, radius: int = 16,
                spread: int = 34, strength: float = 0.55) -> None:
    """Cheap synthetic shadow: a few progressively larger dark rounded rects."""
    for step in range(4, 0, -1):
        layer = QImage(pixmap.size(), QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        lp.setPen(Qt.PenStyle.NoPen)
        lp.setBrush(QColor(0, 0, 0, int(70 * strength)))
        lp.drawRoundedRect(QRectF(0, 0, pixmap.width(), pixmap.height()), radius, radius)
        lp.end()
        grow = spread * step / 4.0
        rect = target.adjusted(-grow / 2, -grow / 2 + 6, grow / 2, grow / 2 + 10)
        painter.drawPixmap(rect, QPixmap.fromImage(layer),
                           QRectF(layer.rect()))


def cursor_path(scale: float = 1.0) -> QPainterPath:
    """Windows 11 style arrow pointer."""
    path = QPainterPath()
    points = [(0, 0), (0, 17.5), (4.2, 13.6), (6.8, 19.6), (9.6, 18.3), (7.0, 12.4), (12.6, 12.2)]
    path.moveTo(points[0][0] * scale, points[0][1] * scale)
    for x, y in points[1:]:
        path.lineTo(x * scale, y * scale)
    path.closeSubpath()
    return path


def draw_cursor(painter: QPainter, pos: QPointF, scale: float = 1.5,
                click: float = 0.0) -> None:
    if click > 0:
        radius = 12 + 46 * ease_out(click)
        colour = QColor(ACCENT)
        colour.setAlphaF(0.42 * (1.0 - click))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(pos, radius, radius)
    path = cursor_path(scale)
    shadow = QPainterPath(path)
    shadow.translate(pos.x() + 1.6, pos.y() + 2.2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, 90))
    painter.drawPath(shadow)
    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(QPen(QColor("#1B1B1B"), 1.15 * scale))
    painter.drawPath(path.translated(pos))


# --------------------------------------------------------------------------- #
# Assets: every shot is built from the application's own widgets
# --------------------------------------------------------------------------- #
def grab_offscreen(widget, size: tuple[int, int] | None = None) -> QPixmap:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    if size:
        widget.resize(*size)
    widget.show()
    QApplication.processEvents()
    pixmap = widget.grab()
    pixmap.setDevicePixelRatio(1.0)
    widget.hide()
    QApplication.processEvents()
    return pixmap


class Assets:
    def __init__(self) -> None:
        self.background = build_background()
        self.build()

    # ------------------------------------------------------------------ #
    def build(self) -> None:
        from winsnip.settings import settings
        from winsnip.theme import theme
        from winsnip.ui.control_bar import CountdownOverlay, RecordControlBar
        from winsnip.ui.main_window import MainWindow
        from winsnip.ui.preview import ImagePreviewWindow
        from winsnip.ui.splash import SplashWindow
        from winsnip.ui.overlay import CaptureOverlay
        from winsnip.ui.widgets import Toast

        settings.animations = False        # deterministic grabs
        settings.minimize_to_tray = False
        settings.last_mode = "video"
        theme.mode = "light"
        theme.refresh()

        # -- splash ---------------------------------------------------- #
        splash = SplashWindow()
        self.splash = grab_offscreen(splash)
        splash.deleteLater()

        # -- main window, both modes ----------------------------------- #
        settings.last_mode = "video"
        self.window_video = MainWindow()
        self.video_shot = grab_offscreen(self.window_video)
        self.seg_rect = QRect(self.window_video.segmented.mapTo(self.window_video, QPoint(0, 0)),
                              self.window_video.segmented.size())
        self.seg_frames = self._segment_frames(self.window_video)

        settings.last_mode = "camera"
        self.window_camera = MainWindow()
        self.camera_shot = grab_offscreen(self.window_camera)

        # -- control bar ---------------------------------------------- #
        self.bar_width = 0
        self.bars: dict[str, QPixmap] = {}
        for key, paused, elapsed, mic in (("run", False, 12.4, True),
                                          ("paused", True, 12.4, True),
                                          ("mic_off", False, 47.0, False)):
            bar = RecordControlBar(mic_available=True, mic_enabled=mic)
            bar.set_mic_enabled(mic, True)
            bar.set_paused(paused)
            bar.set_elapsed(elapsed)
            self.bars[key] = grab_offscreen(bar)
            self.bar_width = self.bars[key].width()
            bar.deleteLater()

        # -- countdown ------------------------------------------------- #
        region = QRect(0, 0, 700, 420)
        self.countdowns = {}
        for value in (3, 2, 1):
            overlay = CountdownOverlay(region, value)
            overlay._value = value
            self.countdowns[value] = grab_offscreen(overlay)
            overlay.deleteLater()

        # -- toast ----------------------------------------------------- #
        toast = Toast("已保存", "屏幕录制 2026-09-30 1422.mp4", "check", duration=99999)
        self.toast = grab_offscreen(toast)
        toast.deleteLater()

        # -- preview window ------------------------------------------- #
        source = QImage(str(SHOTS_DIR / "01_main_light.png"))
        if source.isNull():
            source = QImage(WIDTH, HEIGHT, QImage.Format.Format_RGB32)
            source.fill(QColor("#2C6FA8"))
        preview = ImagePreviewWindow(str(SHOTS_DIR / "01_main_light.png"), source)
        self.preview = grab_offscreen(preview)
        preview.deleteLater()

        # -- soft shadow for the floating windows ----------------------- #
        self.window_shadow = QPixmap.fromImage(self._shadow(self.video_shot.size(), 22, 46))

        # -- mock desktop + overlay ------------------------------------ #
        self.desktop = self._mock_desktop()
        self._overlay_cache: dict = {}
        self.overlay_engine = self._overlay_engine()

    @staticmethod
    def _shadow(size, radius: int, spread: int) -> QImage:
        image = QImage(size.width() + spread * 2, size.height() + spread * 2,
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        for step in range(spread, 0, -1):
            alpha = int(58 * (1.0 - step / spread) ** 1.7)
            if alpha <= 0:
                continue
            painter.setBrush(QColor(0, 0, 0, alpha))
            painter.drawRoundedRect(
                QRectF(spread - step, spread - step + 9,
                       size.width() + step * 2, size.height() + step * 2),
                radius + step, radius + step)
        painter.end()
        return image

    # ------------------------------------------------------------------ #
    def _segment_frames(self, window) -> dict[float, QPixmap]:
        """Sprites of the real segmented control across one switch."""
        seg = window.segmented
        frames: dict[float, QPixmap] = {}
        for step in range(0, 13):
            progress = step / 12.0
            seg._from_index = 0
            seg._to_index = 1
            seg._progress = progress
            sprite = seg.grab()
            sprite.setDevicePixelRatio(1.0)
            frames[progress] = sprite
        seg._from_index = seg._to_index = 1
        seg._progress = 1.0
        seg.repaint()
        return frames

    # ------------------------------------------------------------------ #
    @staticmethod
    def _mock_desktop() -> QImage:
        """A synthetic desktop, so the video never shows the real one."""
        image = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(image)
        base = QLinearGradient(0, 0, WIDTH, HEIGHT)
        base.setColorAt(0.0, QColor("#123A5E"))
        base.setColorAt(0.45, QColor("#1E5B8C"))
        base.setColorAt(1.0, QColor("#0B2439"))
        painter.fillRect(0, 0, WIDTH, HEIGHT, base)
        glow = QRadialGradient(QPointF(WIDTH * 0.68, HEIGHT * 0.28), WIDTH * 0.45)
        glow.setColorAt(0.0, QColor(150, 220, 255, 120))
        glow.setColorAt(1.0, QColor(150, 220, 255, 0))
        painter.fillRect(0, 0, WIDTH, HEIGHT, glow)

        painter.setPen(Qt.PenStyle.NoPen)
        for px, py, pw, ph in ((0.06, 0.12, 0.42, 0.60), (0.53, 0.20, 0.41, 0.54)):
            rect = QRectF(WIDTH * px, HEIGHT * py, WIDTH * pw, HEIGHT * ph)
            painter.setBrush(QColor(250, 252, 255, 235))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setBrush(QColor(226, 233, 240, 255))
            painter.drawRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), 32), 12, 12)
            painter.setBrush(QColor(168, 186, 204, 255))
            for line in range(5):
                painter.drawRoundedRect(
                    QRectF(rect.x() + 26, rect.y() + 64 + line * 36,
                           rect.width() * (0.72 - line * 0.09), 13), 6, 6)
        painter.setBrush(QColor(12, 22, 34, 215))
        painter.drawRoundedRect(QRectF(WIDTH * 0.30, HEIGHT - 58, WIDTH * 0.40, 44), 10, 10)
        painter.end()
        return image

    def _overlay_engine(self):
        """A real CaptureOverlay drawing on the mock desktop, grabbed per frame."""
        from winsnip.theme import theme
        from winsnip.ui.overlay import CaptureOverlay

        theme.mode = "dark"
        theme.refresh()
        overlay = CaptureOverlay(mode="video", shape="rectangle", confirm=False)
        overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        overlay.resize(WIDTH, HEIGHT)
        overlay._virtual_rect = QRect(0, 0, WIDTH, HEIGHT)
        overlay._dpr = 1.0
        overlay._screen_image = self.desktop
        overlay.show()
        overlay._position_bar()
        overlay._bar.set_shape("rectangle")
        overlay._selection = QRect(0, 0, 0, 0)
        overlay._pointer = QPoint(0, 0)
        QApplication.processEvents()
        return overlay

    def overlay_frame(self, selection: QRect, pointer: QPoint) -> QPixmap:
        key = (selection.x(), selection.y(), selection.width(), selection.height(),
               pointer.x(), pointer.y())
        cached = self._overlay_cache.get(key)
        if cached is not None:
            return cached
        overlay = self.overlay_engine
        overlay._selection = selection
        overlay._pointer = pointer
        overlay._committed_selection = False
        overlay.repaint()
        QApplication.processEvents()
        frame = overlay.grab()
        frame.setDevicePixelRatio(1.0)
        if len(self._overlay_cache) < 400:
            self._overlay_cache[key] = frame
        return frame

# --------------------------------------------------------------------------- #
# Timeline
# --------------------------------------------------------------------------- #
SHOTS: list[tuple[str, float, float]] = [
    ("intro",     0.0,  2.4),
    ("window",    2.4,  5.4),
    ("modes",     5.4,  8.4),
    ("region",    8.4, 12.4),
    ("countdown", 12.4, 15.0),
    ("control",   15.0, 17.4),
    ("snap",      17.4, 20.4),
    ("saved",     20.4, 22.4),
    ("features",  22.4, 27.2),
    ("outro",     27.2, 30.0),
]

# Every on-screen caption, also used to write the .srt
CAPTIONS: list[tuple[float, float, str]] = [
    (0.70, 2.30, "在 Windows 10 上"),
    (2.55, 5.30, "享受 Windows 11 的录屏体验"),
    (3.60, 5.30, "界面与 Windows 11「截图工具」同款"),
    (6.10, 8.30, "截图 ⇄ 录屏，切换带 Fluent 动效"),
    (9.40, 12.30, "区域 / 窗口 / 全屏录制，拖拽即选"),
    (13.00, 14.90, "3 秒倒计时，控制条随时暂停"),
    (15.60, 17.30, "暂停与继续，成片不含暂停段"),
    (18.20, 20.30, "截图同样好用 · 自动复制到剪贴板"),
    (21.00, 22.30, "停止后自动保存为 H.264 MP4"),
    (23.00, 27.10, "免安装 · 系统声音 · 录制光标 · 全局快捷键"),
    (27.60, 30.00, "在 Windows 10 上享受 Windows 11 的录屏体验"),
]

SFX_BEATS: list[tuple[float, str]] = [
    (0.10, "whoosh"), (0.75, "chime"), (2.45, "pop"),
    (5.60, "click"), (6.30, "click"), (7.00, "click"), (7.70, "click"),
    (8.60, "whoosh"), (9.30, "tick"), (10.10, "click"),
    (12.55, "tick"), (13.05, "tick"), (13.55, "tick"), (14.05, "chime"),
    (15.55, "click"), (16.35, "click"), (17.45, "whoosh"), (18.25, "shutter"),
    (19.10, "chime"), (20.50, "click"), (21.05, "chime"),
    (22.60, "tick"), (22.88, "tick"), (23.16, "tick"),
    (23.44, "tick"), (23.72, "tick"), (24.00, "tick"),
    (27.30, "whoosh"), (27.90, "chime"),
]


def fit(pixmap: QPixmap, max_width: float, max_height: float) -> QRectF:
    scale = min(max_width / pixmap.width(), max_height / pixmap.height())
    width, height = pixmap.width() * scale, pixmap.height() * scale
    return QRectF((WIDTH - width) / 2, (HEIGHT - height) / 2, width, height)


def draw_widget(painter: QPainter, pixmap: QPixmap, rect: QRectF,
                opacity: float = 1.0) -> None:
    painter.save()
    painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))
    painter.restore()


def draw_main_window(painter: QPainter, assets: Assets, *, camera: bool,
                     centre: QPointF, width: float, opacity: float = 1.0,
                     seg_progress: float = 1.0, shadow: bool = True) -> QRectF:
    """Draw a real window shot, optionally with an animated mode switch."""
    shot = assets.camera_shot if camera else assets.video_shot
    scale = width / shot.width()
    height = shot.height() * scale
    rect = QRectF(centre.x() - width / 2, centre.y() - height / 2, width, height)

    if shadow:
        painter.save()
        painter.setOpacity(opacity * 0.9)
        pad = 46
        shadow_rect = rect.adjusted(-pad, -pad + 6, pad, pad)
        painter.drawPixmap(shadow_rect, assets.window_shadow,
                           QRectF(assets.window_shadow.rect()))
        painter.restore()

    painter.save()
    painter.setOpacity(opacity)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.translate(rect.topLeft())
    painter.scale(scale, scale)
    painter.drawPixmap(0, 0, shot)
    if not camera:
        dpr = shot.width() / 620.0
        sprite = assets.seg_frames[min(assets.seg_frames, key=lambda k: abs(k - seg_progress))]
        painter.drawPixmap(int(assets.seg_rect.x() * dpr), int(assets.seg_rect.y() * dpr), sprite)
    painter.restore()
    return rect


def draw_pill(painter: QPainter, label: str, centre_x: float, y: float,
              size: int = 26, opacity: float = 1.0, accent: bool = True) -> None:
    f = font(size, 500)
    painter.setFont(f)
    width = QFontMetrics(f).horizontalAdvance(label) + 54
    rect = QRectF(centre_x - width / 2, y, width, 52)
    painter.save()
    painter.setOpacity(opacity)
    painter.setPen(Qt.PenStyle.NoPen)
    fill = QColor(ACCENT if accent else "#FFFFFF")
    fill.setAlphaF(0.16)
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, 26, 26)
    pen = QPen(QColor(ACCENT if accent else "#FFFFFF"))
    pen.setWidthF(1.2)
    pen.setColor(QColor(pen.color().red(), pen.color().green(), pen.color().blue(), 110))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, 26, 26)
    painter.setPen(QColor(ACCENT if accent else TEXT))
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
    painter.restore()


# --------------------------------------------------------------------------- #
# Shots
# --------------------------------------------------------------------------- #
def shot_intro(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    appear = ease_out(span(t, 0.05, 0.75))
    card_w = 870 * (0.92 + 0.08 * appear)
    rect = fit(assets.splash, card_w, 620)
    rect.moveCenter(QPointF(WIDTH / 2, 660))
    painter.save()
    painter.setOpacity(appear * 0.85)
    pad = 70
    painter.drawPixmap(rect.adjusted(-pad, -pad, pad, pad),
                       assets.window_shadow,
                       QRectF(assets.window_shadow.rect()))
    painter.restore()
    draw_widget(painter, assets.splash, rect, appear)
    text(painter, "在 Windows 10 上", QRectF(0, 200, WIDTH, 90), 62, TEXT, 600,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 0.75, 0.6)))
    text(painter, "WinSnipRec · 录屏与截图", QRectF(0, 292, WIDTH, 46), 26, TEXT_DIM, 400,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 1.05, 0.6)))


def shot_window(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    painter.save()
    painter.setOpacity(1.0 - ease_out(span(t, 0.0, 0.45)))
    card = fit(assets.splash, 720, 520)
    card.moveCenter(QPointF(WIDTH / 2, 640))
    draw_widget(painter, assets.splash, card, 1.0)
    painter.restore()

    rise = ease_out(span(t, 0.25, 0.85))
    opacity = ease_out(span(t, 0.25, 0.70))
    centre = QPointF(WIDTH / 2, 600 + (1 - rise) * 46)
    draw_main_window(painter, assets, camera=False, centre=centre, width=1220,
                     opacity=opacity, seg_progress=1.0)

    text(painter, "在 Windows 10 上", QRectF(0, 128, WIDTH, 60), 40, TEXT_DIM, 500,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 0.0, 0.4)))
    painter.save()
    painter.setOpacity(ease_out(span(t, 0.55, 0.7)))
    painter.setFont(font(72, 600))
    gradient = QLinearGradient(WIDTH * 0.22, 0, WIDTH * 0.78, 0)
    gradient.setColorAt(0.0, QColor("#8FD6FF"))
    gradient.setColorAt(1.0, QColor(ACCENT))
    pen = QPen()
    pen.setBrush(gradient)
    painter.setPen(pen)
    painter.drawText(QRectF(0, 186, WIDTH, 104),
                     int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                     "享受 Windows 11 的录屏体验")
    painter.restore()

    draw_pill(painter, "界面与 Windows 11「截图工具」同款", WIDTH / 2, HEIGHT - 84,
              opacity=ease_out(span(t, 1.25, 0.6)))

    # cursor drifts in and settles over the video segment
    p = ease_out(span(t, 1.5, 1.1))
    if p > 0:
        start = QPointF(WIDTH * 0.86, HEIGHT * 0.92)
        end = QPointF(WIDTH / 2 + 12, 600 - 40)
        draw_cursor(painter, QPointF(start.x() + (end.x() - start.x()) * p,
                                     start.y() + (end.y() - start.y()) * p), 1.6)

def seg_sprite(assets: Assets, from_index: int, to_index: int, progress: float) -> QPixmap:
    """Sprite for a switch in either direction (0 = camera, 1 = video)."""
    if from_index == to_index:                 # settled: keep that segment
        key = float(to_index)
    elif from_index == 0:
        key = progress
    else:
        key = 1.0 - progress
    return assets.seg_frames[min(assets.seg_frames, key=lambda k: abs(k - key))]


def switch_progress(t: float, beats: list[float], duration: float = 0.24) -> tuple[int, int, float]:
    """Which pair is switching at time t, and how far along."""
    state = 1                                     # start on the video segment
    for beat in beats:
        if t < beat:
            break
        elapsed = t - beat
        if elapsed < duration:
            return state, 1 - state, clamp(elapsed / duration)
        state = 1 - state
    return state, state, 1.0


def shot_modes(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    zoom_in = ease_in_out(span(t, 0.0, 0.65))
    zoom_out = ease_in_out(span(t, 2.55, 0.45))
    peak = 1.75
    zoom = peak - (peak - 1.0) * zoom_out
    if zoom_in < 1.0:
        zoom = 1.0 + (peak - 1.0) * zoom_in - (peak - 1.0) * zoom_out
    zoom = max(1.0, zoom)

    shot = assets.video_shot
    dpr = shot.width() / 620.0
    ctrl = QPointF(assets.seg_rect.center().x() * dpr, assets.seg_rect.center().y() * dpr)
    base_scale = 1290.0 / shot.width()
    scale = base_scale * zoom
    focus = QPointF(WIDTH / 2, HEIGHT * 0.46)

    from_index, to_index, progress = switch_progress(t, [0.80, 1.50, 2.20])

    painter.save()
    painter.setOpacity(ease_out(span(t, 0.0, 0.3)))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.translate(focus)
    painter.scale(scale, scale)
    painter.translate(-ctrl.x(), -ctrl.y())
    painter.drawPixmap(0, 0, shot)
    sprite = seg_sprite(assets, from_index, to_index, progress)
    painter.drawPixmap(int(assets.seg_rect.x() * dpr), int(assets.seg_rect.y() * dpr), sprite)
    painter.restore()

    # dim everything except the switch so the eye stays on it
    dim = ease_out(span(t, 0.45, 0.5))
    if dim > 0.01:
        painter.save()
        painter.setOpacity(dim)
        painter.setPen(Qt.PenStyle.NoPen)
        ctrl_w = assets.seg_frames[1.0].width() * scale
        ctrl_h = assets.seg_frames[1.0].height() * scale
        spot = QRectF(focus.x() - ctrl_w / 2 - 66, focus.y() - ctrl_h / 2 - 52,
                      ctrl_w + 132, ctrl_h + 104)
        outer = QPainterPath()
        outer.addRect(QRectF(0, 0, WIDTH, HEIGHT))
        inner = QPainterPath()
        inner.addRoundedRect(spot, 30, 30)
        painter.fillPath(outer.subtracted(inner), QColor(6, 10, 16, 178))
        painter.restore()
    draw_pill(painter, "截图 ⇄ 录屏，切换带 Fluent 动效", WIDTH / 2, HEIGHT - 96,
              opacity=ease_out(span(t, 0.35, 0.5)))


def shot_region(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    start = QPoint(430, 300)
    end = QPoint(1460, 840)
    fade = ease_out(span(t, 0.0, 0.35))
    drag = ease_in_out(span(t, 0.75, 1.30))

    if t < 0.75:
        selection = QRect(0, 0, 0, 0)
        cursor = QPointF(start.x(), start.y())
    else:
        current = QPoint(int(start.x() + (end.x() - start.x()) * drag),
                         int(start.y() + (end.y() - start.y()) * drag))
        selection = QRect(start, current).normalized()
        cursor = QPointF(current.x(), current.y())

    frame = assets.overlay_frame(selection, QPoint(int(cursor.x()), int(cursor.y())))
    draw_widget(painter, frame, QRectF(0, 0, WIDTH, HEIGHT), fade)

    if selection.width() > 2:
        label = f"{selection.width()} × {selection.height()}"
        painter.save()
        painter.setOpacity(fade)
        painter.setFont(font(20, 500))
        metrics = QFontMetrics(font(20, 500))
        lw = metrics.horizontalAdvance(label) + 30
        box = QRectF(selection.right() - lw, selection.bottom() + 14, lw, 38)
        if box.bottom() > HEIGHT - 40:
            box.moveTop(selection.bottom() - 52)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(24, 28, 34, 225))
        painter.drawRoundedRect(box, 8, 8)
        painter.setPen(QColor("#EAF2FA"))
        painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), label)
        painter.restore()

    ripple = 1.0 - ease_out(span(t, 0.75, 0.35)) if t >= 0.75 else 0.0
    draw_cursor(painter, cursor, 1.6, ripple if t >= 0.75 else 0.0)
    draw_pill(painter, "区域 / 窗口 / 全屏录制，拖拽即选", WIDTH / 2, HEIGHT - 116,
              opacity=ease_out(span(t, 1.6, 0.5)))
    assets.final_selection = selection


def shot_countdown(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    selection = getattr(assets, "final_selection", QRect(430, 300, 1030, 540))
    frame = assets.overlay_frame(selection, QPoint(-10, -10))
    draw_widget(painter, frame, QRectF(0, 0, WIDTH, HEIGHT), 1.0)

    painter.save()
    painter.setBrush(QColor(0, 0, 0, 90))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRect(QRectF(0, 0, WIDTH, HEIGHT))
    painter.restore()

    beats = ((3, 0.45, 1.02), (2, 1.02, 1.55), (1, 1.55, 2.05))
    for value, begin, finish in beats:
        if begin <= t < finish + 0.18:
            local = clamp((t - begin) / (finish - begin))
            pop = ease_out(clamp((t - begin) / 0.18))
            card = fit(assets.countdowns[value], selection.width() * 0.62, selection.height() * 0.72)
            card.moveCenter(QPointF(selection.center().x(), selection.center().y()))
            scale = 1.18 - 0.18 * pop
            card = QRectF(card.center().x() - card.width() * scale / 2,
                          card.center().y() - card.height() * scale / 2,
                          card.width() * scale, card.height() * scale)
            draw_widget(painter, assets.countdowns[value], card,
                        (1.0 - local ** 3) if finish <= t else pop)

    rise = ease_out(span(t, 1.85, 0.6))
    bar = assets.bars["run"]
    bar_w = 900.0
    bar_h = bar.height() * bar_w / bar.width()
    bar_rect = QRectF(WIDTH / 2 - bar_w / 2, HEIGHT - 190 + (1 - rise) * 90, bar_w, bar_h)
    draw_widget(painter, bar, bar_rect, rise)
    draw_pill(painter, "3 秒倒计时，控制条随时暂停", WIDTH / 2, HEIGHT - 96,
              opacity=ease_out(span(t, 2.1, 0.4)))


def shot_control(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    selection = getattr(assets, "final_selection", QRect(430, 300, 1030, 540))
    frame = assets.overlay_frame(selection, QPoint(-10, -10))
    painter.save()
    painter.setOpacity(0.5)
    draw_widget(painter, frame, QRectF(0, 0, WIDTH, HEIGHT), 1.0)
    painter.restore()

    paused = 0.55 <= t < 1.45
    bar = assets.bars["paused" if paused else "run"]
    bar_w = 1500.0
    bar_h = bar.height() * bar_w / bar.width()
    rect = QRectF(WIDTH / 2 - bar_w / 2, HEIGHT / 2 - bar_h / 2, bar_w, bar_h)
    draw_widget(painter, bar, rect, 1.0)

    for beat in (0.55, 1.45):
        if beat <= t < beat + 0.4:
            ripple = 1.0 - ease_out((t - beat) / 0.4)
            draw_cursor(painter, QPointF(rect.center().x() + 30, rect.center().y()),
                        1.4, ripple)
    if t < 0.55:
        draw_cursor(painter, QPointF(rect.center().x() + 30 + (1 - ease_out(span(t, 0.0, 0.5))) * 260,
                                     rect.center().y() + 40), 1.4)
    draw_pill(painter, "暂停与继续，成片不含暂停段", WIDTH / 2, HEIGHT - 120)


def shot_snap(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    opacity = ease_out(span(t, 0.0, 0.7))
    rise = ease_out(span(t, 0.0, 0.8))
    centre = QPointF(600, 600 + (1 - rise) * 40)
    draw_main_window(painter, assets, camera=True, centre=centre, width=1010,
                     opacity=opacity)

    flash = 0.0
    if 0.92 <= t < 1.24:
        flash = math.sin(clamp((t - 0.92) / 0.32) * math.pi) * 0.5
    if flash > 0:
        painter.save()
        painter.setOpacity(flash)
        painter.fillRect(QRectF(0, 0, WIDTH, HEIGHT), QColor(255, 255, 255))
        painter.restore()

    p = ease_out(span(t, 1.30, 0.7))
    if p > 0:
        preview_target = fit(assets.preview, 780, 620)
        preview_target.moveCenter(QPointF(1450, 580))
        offset = (1 - p) * 46
        preview_target = QRectF(preview_target.x(), preview_target.y() + offset,
                                preview_target.width(), preview_target.height())
        painter.save()
        painter.setOpacity(p * 0.85)
        painter.drawPixmap(preview_target.adjusted(-50, -50, 50, 50),
                           assets.window_shadow,
                           QRectF(assets.window_shadow.rect()))
        painter.restore()
        draw_widget(painter, assets.preview, preview_target, p)
        draw_pill(painter, "已复制到剪贴板", 1450, preview_target.bottom() + 26, 22,
                  ease_out(span(t, 2.1, 0.5)))
    draw_pill(painter, "截图同样好用 · 自动复制到剪贴板", WIDTH / 2, HEIGHT - 106,
              opacity=ease_out(span(t, 0.5, 0.5)))


def shot_saved(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    centre = QPointF(WIDTH / 2 - 120, 560)
    draw_main_window(painter, assets, camera=False, centre=centre, width=1180,
                     opacity=ease_out(span(t, 0.0, 0.5)))

    p = ease_out(span(t, 0.35, 0.7))
    if p > 0:
        target = fit(assets.toast, 620, 200)
        target.moveCenter(QPointF(WIDTH - 420, HEIGHT - 300))
        target = QRectF(target.x() + (1 - p) * 90, target.y() + (1 - p) * 40,
                        target.width(), target.height())
        draw_widget(painter, assets.toast, target, p)
    draw_pill(painter, "停止后自动保存为 H.264 MP4", WIDTH / 2 - 120, HEIGHT - 110,
              opacity=ease_out(span(t, 1.0, 0.5)))


FEATURES = [
    ("save", "免安装 EXE", "单文件，双击即用"),
    ("pause", "暂停与继续", "成片不含暂停段"),
    ("mic", "麦克风", "录制中随时切换"),
    ("sound", "系统声音", "回环设备录系统音"),
    ("cursor", "录制光标", "指针平滑不丢帧"),
    ("play", "全局快捷键", "冲突时自动回退"),
]


def shot_features(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    text(painter, "功能一览", QRectF(0, 120, WIDTH, 70), 52, TEXT, 600,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 0.0, 0.5)))

    card_w, card_h, gap = 480, 190, 60
    total = card_w * 3 + gap * 2
    left = (WIDTH - total) / 2
    from winsnip import icons
    for index, (icon_name, title, desc) in enumerate(FEATURES):
        begin = 0.30 + index * 0.20
        p = ease_out(span(t, begin, 0.55))
        if p <= 0.01:
            continue
        row, column = divmod(index, 3)
        x = left + column * (card_w + gap)
        y = 260 + row * (card_h + 46) + (1 - p) * 26

        painter.save()
        painter.setOpacity(p)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 14))
        painter.drawRoundedRect(QRectF(x, y, card_w, card_h), 18, 18)
        pen = QPen(QColor(255, 255, 255, 40))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, card_w - 1, card_h - 1), 18, 18)

        icons.paint_icon(painter, icon_name, QRectF(x + 40, y + 40, 46, 46), QColor(ACCENT))
        text(painter, title, QRectF(x + 40, y + 100, card_w - 80, 40), 30, TEXT, 600)
        text(painter, desc, QRectF(x + 40, y + 140, card_w - 80, 32), 21, TEXT_DIM, 400)
        painter.restore()

    text(painter, "Python + PySide6 + FFmpeg 构建 · 输出 MP4 可直接分享", QRectF(0, HEIGHT - 130, WIDTH, 40),
         22, TEXT_DIM, 400, Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 1.9, 0.6)))


def shot_outro(painter: QPainter, assets: Assets, t: float, length: float) -> None:
    from winsnip import icons

    appear = ease_out(span(t, 0.0, 0.6))
    icon = icons.app_icon().pixmap(150, 150)
    icon_rect = QRectF(WIDTH / 2 - 75, 250 + (1 - appear) * 24, 150, 150)
    painter.save()
    painter.setOpacity(appear)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawPixmap(icon_rect, icon, QRectF(icon.rect()))
    painter.restore()

    text(painter, "截图工具 WinSnipRec", QRectF(0, 440, WIDTH, 90), 66, TEXT, 700,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 0.25, 0.6)))
    text(painter, "在 Windows 10 上享受 Windows 11 的录屏体验",
         QRectF(0, 540, WIDTH, 56), 32, TEXT_DIM, 400,
         Qt.AlignmentFlag.AlignHCenter, ease_out(span(t, 0.5, 0.6)))

    chips = ["免安装单文件", "H.264 MP4", "开机自启", "深浅主题"]
    widths = []
    f = font(21, 500)
    painter.setFont(f)
    metrics = QFontMetrics(f)
    for chip in chips:
        widths.append(metrics.horizontalAdvance(chip) + 44)
    total = sum(widths) + 20 * (len(chips) - 1)
    x = (WIDTH - total) / 2
    opacity = ease_out(span(t, 0.9, 0.7))
    for chip, width in zip(chips, widths):
        painter.save()
        painter.setOpacity(opacity)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRoundedRect(QRectF(x, 660, width, 48), 24, 24)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(x, 660, width, 48), int(Qt.AlignmentFlag.AlignCenter), chip)
        painter.restore()
        x += width + 20


HANDLERS = {
    "intro": shot_intro,
    "window": shot_window,
    "modes": shot_modes,
    "region": shot_region,
    "countdown": shot_countdown,
    "control": shot_control,
    "snap": shot_snap,
    "saved": shot_saved,
    "features": shot_features,
    "outro": shot_outro,
}

# --------------------------------------------------------------------------- #
# SFX: synthesised with numpy (no external assets, no licensing questions)
# --------------------------------------------------------------------------- #
SAMPLE_RATE = 48000


def _envelope(length: int, attack: float = 0.005, decay: float = 1.0) -> np.ndarray:
    t = np.linspace(0.0, 1.0, length, endpoint=False)
    attack_part = np.clip(t / max(attack, 1e-4), 0.0, 1.0)
    return attack_part * np.exp(-t * 6.0 * decay)


def _click() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.09)
    rng = np.random.default_rng(7)
    noise = rng.normal(0.0, 1.0, length) * 0.35
    t = np.arange(length) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * 1750 * t) * 0.5 + np.sin(2 * np.pi * 2620 * t) * 0.25
    return (_envelope(length, 0.002, 2.4) * (noise + tone)) * 0.5


def _tick() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.05)
    t = np.arange(length) / SAMPLE_RATE
    tone = np.sin(2 * np.pi * 2400 * t)
    return _envelope(length, 0.001, 3.2) * tone * 0.30


def _pop() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.16)
    t = np.arange(length) / SAMPLE_RATE
    sweep = np.sin(2 * np.pi * (520 + 900 * t / 0.16) * t)
    return _envelope(length, 0.003, 2.0) * sweep * 0.42


def _chime() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.85)
    t = np.arange(length) / SAMPLE_RATE
    tone = (np.sin(2 * np.pi * 784 * t) * 0.6 +
            np.sin(2 * np.pi * 1176 * t) * 0.3 +
            np.sin(2 * np.pi * 1568 * t) * 0.12)
    return _envelope(length, 0.006, 1.1) * tone * 0.34


def _whoosh() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.42)
    rng = np.random.default_rng(11)
    noise = rng.normal(0.0, 1.0, length)
    # cheap one-pole low-pass sweep for a "swish" instead of white hiss
    out = np.zeros(length)
    cutoff = np.linspace(0.06, 0.5, length)
    previous = 0.0
    for i in range(length):
        previous += cutoff[i] * (noise[i] - previous)
        out[i] = previous
    t = np.linspace(0.0, 1.0, length)
    shape = np.sin(np.pi * t) ** 1.4
    return out * shape * 1.6


def _shutter() -> np.ndarray:
    length = int(SAMPLE_RATE * 0.18)
    rng = np.random.default_rng(23)
    noise = rng.normal(0.0, 1.0, length)
    t = np.arange(length) / SAMPLE_RATE
    clack = np.sin(2 * np.pi * 320 * t) * np.exp(-t * 40)
    return (_envelope(length, 0.001, 5.0) * (noise * 0.5 + clack * 0.9)) * 0.45


SFX_BUILDERS = {"click": _click, "tick": _tick, "pop": _pop, "chime": _chime,
                "whoosh": _whoosh, "shutter": _shutter}


def build_sfx_track(path: Path, beats: list[tuple[float, str]]) -> Path:
    total = int(SAMPLE_RATE * (DURATION + 0.5))
    track = np.zeros(total, dtype=np.float32)
    cache: dict[str, np.ndarray] = {}
    for when, name in beats:
        if name not in cache:
            cache[name] = SFX_BUILDERS[name]()
        samples = cache[name]
        start = int(when * SAMPLE_RATE)
        end = min(total, start + len(samples))
        track[start:end] += samples[:end - start]
    peak = float(np.max(np.abs(track))) or 1.0
    track = np.tanh(track / peak * 1.15) * 0.62        # soft limit, keep headroom
    pcm = (track * 32767).astype(np.int16)

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return path


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #
def render_frame(painter: QPainter, assets: Assets, t: float) -> None:
    painter.drawImage(0, 0, assets.background)

    index = 0
    for i, (_name, start, end) in enumerate(SHOTS):
        if t >= start:
            index = i
    name, start, end = SHOTS[index]
    if t >= end and index + 1 < len(SHOTS):
        # cross-fade the tail of this shot into the next
        if t >= end - XFADE:
            p = ease_in_out((t - end + XFADE) / XFADE)
            painter.save()
            HANDLERS[name](painter, assets, end - start, end - start)
            painter.restore()
            painter.save()
            painter.setOpacity(p)
            HANDLERS[SHOTS[index + 1][0]](painter, assets, max(0.0, t - SHOTS[index + 1][1]),
                                          SHOTS[index + 1][2] - SHOTS[index + 1][1])
            painter.restore()
            return
    local = min(t - start, end - start)
    HANDLERS[name](painter, assets, local, end - start)


def write_srt(path: Path) -> None:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    lines = []
    for i, (begin, finish, label) in enumerate(CAPTIONS, start=1):
        lines += [str(i), f"{stamp(begin)} --> {stamp(finish)}", label, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_storyboard(path: Path) -> None:
    rows = ["# 宣传片分镜（16:9 · 30 秒 · 30fps）", "",
            "全部画面由程序逐帧合成，使用应用**真实控件**渲染，不含屏幕录制。", "",
            "| # | 时间 | 镜头 | 时长 | 内容与动效 |", "|---|---|---|---|---|"]
    notes = {
        "intro": "启动画面淡入并轻微缩放，主标题浮现",
        "window": "主窗口淡入上滑（应用真实的开窗动画），副标题与光标进入",
        "modes": "推近到模式开关，真实的分栏控件动画：强调条滑动 + 图标颜色渐变",
        "region": "真实浮层：整屏压暗、拖拽选区、尺寸标签跟随光标",
        "countdown": "倒计时 3→2→1 弹出，控制条自下方滑入",
        "control": "控制条特写：暂停 → 计时冻结 → 继续，带点击涟漪",
        "snap": "截图模式：快门闪白 → 预览窗淡入 → 已复制提示",
        "saved": "停止录制，通知横幅从右下角滑入",
        "features": "六张功能卡依次飞入（错开 0.2 秒）",
        "outro": "图标 + 主标题 + 特性标签定格",
    }
    for i, (name, start, end) in enumerate(SHOTS, start=1):
        rows.append(f"| {i} | {start:04.1f}–{end:04.1f}s | {name} | {end - start:.1f}s | "
                    f"{notes.get(name, '')} |")
    rows += ["", "## 音效节拍", "",
             "| 时间 | 音效 |", "|---|---|"]
    for when, name in SFX_BEATS:
        rows.append(f"| {when:04.2f}s | {name} |")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_contact_sheet(frames: list[QImage], path: Path) -> None:
    columns, rows = 6, 5
    cell_w, cell_h = 320, 180
    sheet = QImage(columns * cell_w, rows * cell_h, QImage.Format.Format_RGB32)
    sheet.fill(QColor("#05080C"))
    painter = QPainter(sheet)
    for index, frame in enumerate(frames[:columns * rows]):
        x = (index % columns) * cell_w
        y = (index // columns) * cell_h
        painter.drawImage(QRectF(x, y, cell_w, cell_h), frame,
                          QRectF(0, 0, frame.width(), frame.height()))
        painter.setPen(QColor(255, 255, 255, 60))
        painter.drawRect(x, y, cell_w - 1, cell_h - 1)
    painter.end()
    sheet.save(str(path), "PNG")


def frame_bytes(image: QImage) -> bytes:
    """Raw BGRA bytes, one row at a time so row padding can never slip in."""
    stride = image.bytesPerLine()
    row_bytes = WIDTH * 4
    view = image.constBits().tobytes()
    if stride == row_bytes:
        return view
    return b"".join(view[y * stride:y * stride + row_bytes] for y in range(HEIGHT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                        help="render only 1 frame per second into a contact sheet")
    parser.add_argument("--keep-silent", action="store_true",
                        help="skip the audio mix (video only)")
    args = parser.parse_args()

    from winsnip.core.encoder import ffmpeg_path
    from winsnip.theme import apply_app_theme, theme
    from winsnip import winapi

    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("==> 准备素材（离屏渲染真实控件）")
    started = time.perf_counter()
    assets = Assets()
    print(f"    完成，用时 {time.perf_counter() - started:.1f}s")

    write_storyboard(OUT_DIR / "storyboard.md")
    write_srt(OUT_DIR / "promo_1920x1080_30s.srt")
    print("==> 已写分镜表与字幕")

    silent_video = OUT_DIR / "_video_only.mp4"
    ffmpeg = ffmpeg_path()

    if args.preview:
        thumbs: list[QImage] = []
        for second in range(int(DURATION)):
            frame = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
            frame.fill(Qt.GlobalColor.transparent)
            painter = QPainter(frame)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            render_frame(painter, assets, second + 0.35)
            painter.end()
            thumbs.append(frame.convertToFormat(QImage.Format.Format_RGB32))
            print(f"    preview {second + 1}/{int(DURATION)}")
        write_contact_sheet(thumbs, OUT_DIR / "contact_sheet.png")
        print("==> 预览网格已输出")
        return 0

    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}",
               "-r", str(FPS), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent_video)]
    print(f"==> 渲染 {TOTAL_FRAMES} 帧 @ {FPS}fps")
    process = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    thumbs = []
    started = time.perf_counter()
    for index in range(TOTAL_FRAMES):
        t = index / FPS
        frame = QImage(WIDTH, HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        render_frame(painter, assets, t)
        painter.end()
        process.stdin.write(frame_bytes(frame))
        if index % FPS == 5 and len(thumbs) < 30:
            thumbs.append(frame.copy().convertToFormat(QImage.Format.Format_RGB32))
        if index % 90 == 0:
            elapsed = time.perf_counter() - started
            rate = (index + 1) / max(elapsed, 1e-6)
            print(f"    {index + 1}/{TOTAL_FRAMES} 帧  {rate:.0f} fps  "
                  f"剩余 ~{(TOTAL_FRAMES - index - 1) / max(rate, 1e-6):.0f}s")
    process.stdin.close()
    error = process.stderr.read().decode("utf-8", "replace")
    if process.wait() != 0:
        print(error[-2000:])
        raise SystemExit("ffmpeg 编码失败")
    print(f"==> 画面完成，用时 {time.perf_counter() - started:.1f}s")

    write_contact_sheet(thumbs, OUT_DIR / "contact_sheet.png")

    final = OUT_DIR / "promo_1920x1080_30s.mp4"
    if args.keep_silent:
        silent_video.replace(final)
    else:
        print("==> 合成音效轨")
        sfx = build_sfx_track(OUT_DIR / "sfx_track.wav", SFX_BEATS)
        mix = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-i", str(silent_video), "-i", str(sfx),
               "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)]
        subprocess.run(mix, check=True)
        silent_video.unlink(missing_ok=True)

    size_mb = final.stat().st_size / 1_048_576
    print(f"==> 输出 {final.relative_to(ROOT)}  {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
