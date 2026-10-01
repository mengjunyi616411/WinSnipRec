"""Render the 30 s promo for the Windows 10 style update (1.1.0).

Every UI element comes from the real application: the two windows are offscreen
grabs of MainWindow under the win11 and win10 styles, and the Reveal light is
RevealOverlay's own baked gradient rather than a re-drawn approximation, so the
video cannot drift away from what the app actually shows.

Output: promo/video/update_1920x1080_30s.mp4 (+ .srt, storyboard, contact sheet)
Then add your music:  powershell -File promo\video\混入音乐.ps1 -Music <file>

Usage:
  .venv\\Scripts\\python.exe tools\\make_update_video.py
  .venv\\Scripts\\python.exe tools\\make_update_video.py --preview
"""

from __future__ import annotations

import argparse
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QPointF, QRect, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

# Reuse the existing promo toolchain instead of duplicating ~400 lines of it.
import make_promo_video as P  # noqa: E402

WIDTH, HEIGHT, FPS = 1920, 1080, 30
DURATION = 30.0
TOTAL_FRAMES = int(DURATION * FPS)
OUT_DIR = ROOT / "promo" / "video"

ACCENT = "#4CC2FF"
ACCENT_SOFT = "#8FD8FF"
TEXT = "#F2F7FC"
MUTED = "#93A4B8"

# Every cut sits on a multiple of QUANTUM. Measured on the supplied track: the
# autocorrelation peaks at 900 ms (66.7 BPM) and 600 ms (100 BPM), and the
# dominant inter-onset interval is 305 ms — all multiples of 300 ms, so a 300 ms
# grid lands on the pulse whichever of those is the "real" tempo.
QUANTUM = 0.3

# Scene lengths in pulses (30 s / 0.3 s = 100 pulses total).
SCENE_PULSES = [
    ("intro", 16),      #  4.8 s
    ("switch", 22),     #  6.6 s
    ("acrylic", 20),    #  6.0 s
    ("reveal", 24),     #  7.2 s
    ("strength", 8),    #  2.4 s
    ("outro", 10),      #  3.0 s
]
TOTAL_PULSES = sum(length for _name, length in SCENE_PULSES)


def build_scenes() -> list[tuple[str, float, float]]:
    scenes: list[tuple[str, float, float]] = []
    at = 0.0
    for name, pulses in SCENE_PULSES:
        length = pulses * QUANTUM
        scenes.append((name, round(at, 4), round(length, 4)))
        at += length
    return scenes


SCENES = build_scenes()

# Captions start a hair after their scene so the cut reads first.
SUBTITLES = [
    (1.0, 4.0, "截图工具 1.1.0"),
    (5.4, 6.0, "全新 Windows 10 界面风格"),
    (12.0, 5.4, "Acrylic 亚克力材质"),
    (18.6, 6.6, "Reveal 鼠标光效"),
    (25.2, 2.0, "光效强度可调"),
    (27.6, 2.4, "免费开源 · Windows 10 / 11"),
]


def pulses(length: float) -> list[float]:
    """Times of every pulse inside a scene."""
    return [round(i * QUANTUM, 4) for i in range(int(round(length / QUANTUM)))]

SFX_BEATS: list[tuple[float, str]] = []


# --------------------------------------------------------------------------- #
# Assets
# --------------------------------------------------------------------------- #
class UpdateAssets:
    """The two window styles, the icon, and the app's own Reveal light."""

    def __init__(self) -> None:
        from winsnip.settings import settings
        from winsnip.theme import apply_app_theme, theme
        from winsnip.ui.main_window import MainWindow
        from winsnip.ui.widgets import RevealOverlay

        settings.animations = False          # deterministic grabs
        settings.minimize_to_tray = False
        settings.last_mode = "video"
        settings.reveal_strength = "normal"

        self.windows: dict[str, QPixmap] = {}
        for style in ("win11", "win10"):
            theme.style = style
            theme.mode = "dark"
            theme.refresh()
            apply_app_theme(QApplication.instance())
            window = MainWindow()
            self.windows[style] = P.grab_offscreen(window)
            window._quitting = True
            window.close()
            window.deleteLater()
            QApplication.processEvents()

        # The real gradient the app paints, baked by its own overlay widget.
        host = QWidget()
        overlay = RevealOverlay(host)
        self.glow_radius = 260.0
        self.glow = overlay.glow_pixmap(self.glow_radius)
        host.deleteLater()

        theme.style = "win10"
        theme.mode = "dark"
        theme.refresh()
        apply_app_theme(QApplication.instance())

        from winsnip import icons

        self.icon = icons.app_icon().pixmap(256, 256)
        self.background = P.build_background()


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #
def paint_glow(painter: QPainter, assets: UpdateAssets, centre: QPointF,
               scale: float = 1.0, opacity: float = 1.0) -> None:
    if opacity <= 0.01:
        return
    radius = assets.glow_radius * scale
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.drawPixmap(QPointF(centre.x() - radius, centre.y() - radius),
                       assets.glow.scaled(int(radius * 2), int(radius * 2),
                                          Qt.AspectRatioMode.IgnoreAspectRatio,
                                          Qt.TransformationMode.SmoothTransformation))
    painter.restore()


def paint_window(painter: QPainter, assets: UpdateAssets, style: str,
                 rect: QRectF, *, radius: int = 18, shadow: bool = True) -> None:
    pixmap = assets.windows[style]
    if shadow:
        P.drop_shadow(painter, pixmap, rect, radius=radius, spread=30, strength=0.85)
    painter.drawPixmap(rect, pixmap, QRectF(pixmap.rect()))


def label(painter: QPainter, value: str, centre_x: float, y: float, size: int,
          colour, weight: int = 600, opacity: float = 1.0) -> None:
    box = QRectF(centre_x - 700, y, 1400, size * 1.9)
    P.text(painter, value, box, size, colour, weight,
           Qt.AlignmentFlag.AlignHCenter, opacity)


def pill(painter: QPainter, value: str, centre_x: float, y: float,
         opacity: float = 1.0, highlight: bool = False) -> None:
    size = 30
    width = 34 + P.font(size, 600).pixelSize() * 0.0 + len(value) * size * 0.92
    rect = QRectF(centre_x - width / 2, y, width, 62)
    painter.save()
    painter.setOpacity(painter.opacity() * opacity)
    painter.setPen(Qt.PenStyle.NoPen)
    if highlight:
        painter.setBrush(QColor(ACCENT))
    else:
        painter.setBrush(QColor(255, 255, 255, 22))
    painter.drawRoundedRect(rect, 31, 31)
    if not highlight:
        pen = QPen(QColor(255, 255, 255, 34))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 31, 31)
    P.text(painter, value, rect, size, "#04222F" if highlight else TEXT, 600,
           Qt.AlignmentFlag.AlignHCenter)
    painter.restore()


# --------------------------------------------------------------------------- #
# Scenes
# --------------------------------------------------------------------------- #
def shot_intro(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    appear = P.ease_out(P.span(t, 0.0, 0.7))
    icon_size = 180
    centre_x = WIDTH / 2
    icon_y = 300 - 26 * (1 - appear)

    painter.save()
    painter.setOpacity(appear)
    glow = QRadialGradient(QPointF(centre_x, icon_y + icon_size / 2), 420)
    colour = QColor(ACCENT)
    colour.setAlphaF(0.30 * appear)
    glow.setColorAt(0.0, colour)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(QRectF(0, 0, WIDTH, HEIGHT), glow)
    painter.drawPixmap(
        QRectF(centre_x - icon_size / 2, icon_y, icon_size, icon_size),
        assets.icon, QRectF(assets.icon.rect()))
    painter.restore()

    label(painter, "截图工具", centre_x, 520, 96, TEXT, 600, P.span(t, 0.35, 0.6))
    label(painter, "1.1.0", centre_x, 640, 46, ACCENT_SOFT, 600, P.span(t, 0.55, 0.6))
    label(painter, "Windows 10 / 11 · 免费开源", centre_x, 760, 30, MUTED, 400,
          P.span(t, 0.8, 0.7))

    fade = 1.0 - P.ease_in_out(P.span(t, length - 0.45, 0.45))
    if fade < 1.0:
        painter.fillRect(QRectF(0, 0, WIDTH, HEIGHT), QColor(5, 8, 12, int(255 * (1 - fade))))


def shot_switch(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    """Windows 11 style wipes away to reveal the Windows 10 one."""
    target = QRectF(360, 250, 1200, 620)
    progress = P.ease_in_out(P.span(t, 0.6, 2.2))
    label(painter, "界面风格一键切换", WIDTH / 2, 96, 54, TEXT, 600,
          P.span(t, 0.0, 0.5))

    paint_window(painter, assets, "win11", target)

    if progress > 0:
        painter.save()
        clip = QRectF(target.x(), target.y() - 40, target.width() * progress,
                      target.height() + 80)
        painter.setClipRect(clip)
        paint_window(painter, assets, "win10", target, shadow=False)
        painter.restore()
        edge = target.x() + target.width() * progress
        pen = QPen(QColor(ACCENT))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(edge, target.y() - 20), QPointF(edge, target.bottom() + 20))

    left_opacity = 1.0 - progress
    right_opacity = progress
    pill(painter, "Windows 11", target.x() + 200, 920, left_opacity, highlight=False)
    pill(painter, "Windows 10", target.right() - 200, 920, right_opacity, highlight=True)


def shot_acrylic(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    """The same patch of window under both materials, so the blur is comparable."""
    appear = P.ease_out(P.span(t, 0.0, 0.6))
    label(painter, "Acrylic 亚克力材质", WIDTH / 2, 88, 54, TEXT, 600, appear)
    label(painter, "重高斯模糊 + 噪点颗粒", WIDTH / 2, 156, 30, MUTED, 400,
          P.span(t, 0.3, 0.6))

    # Both panels show the identical region of the respective window: the lower
    # band, where the wallpaper glow makes a blur difference actually visible.
    window = assets.windows["win10"]
    src = QRectF(window.width() * 0.06, window.height() * 0.34,
                 window.width() * 0.88, window.height() * 0.60)
    panel_w, panel_h = 780, 500
    gap = 60
    total = panel_w * 2 + gap
    left_x = (WIDTH - total) / 2
    top = 250

    panels = [("win11", "Windows 11 · Mica", "平滑 · 保留壁纸构图",
               left_x, 0.0),
              ("win10", "Windows 10 · Acrylic", "重模糊 · 叠一层噪点",
               left_x + panel_w + gap, 0.22)]

    for style, title, note, x, delay in panels:
        step = P.span(t, 0.35 + delay, 0.6)
        rise = (1 - P.ease_out(step)) * 30
        card = QRectF(x, top + rise, panel_w, panel_h)
        painter.save()
        painter.setOpacity(appear * step)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.drawRoundedRect(card, 22, 22)

        inner = card.adjusted(12, 12, -12, -12)
        painter.setClipRect(inner)
        painter.drawPixmap(inner, assets.windows[style], src)
        painter.setClipping(False)

        pen = QPen(QColor(ACCENT) if style == "win10" else QColor(255, 255, 255, 40))
        pen.setWidthF(2.2 if style == "win10" else 1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 22, 22)

        P.text(painter, title, QRectF(x, card.bottom() + 22, panel_w, 54), 34,
               ACCENT_SOFT if style == "win10" else TEXT, 600,
               Qt.AlignmentFlag.AlignHCenter)
        P.text(painter, note, QRectF(x, card.bottom() + 78, panel_w, 48), 26, MUTED, 400,
               Qt.AlignmentFlag.AlignHCenter)
        painter.restore()

    # Magnifier on the Acrylic panel: 3.4x, the grain is what it is there for.
    zoom = 3.4
    material = assets.windows["win10"]
    # Sample the lower-right corner: the wallpaper glow lives there, so the
    # zoom shows grain on colour rather than magnified text.
    centre_src = QPointF(material.width() * 0.84, material.height() * 0.78)
    half_w = (210 / zoom) / 2
    half_h = (170 / zoom) / 2
    src_small = QRectF(centre_src.x() - half_w, centre_src.y() - half_h, half_w * 2, half_h * 2)
    dest = QRectF(left_x + panel_w + gap + panel_w - 250, top + 40, 210, 170)
    ring = P.span(t, 1.0, 0.5)
    if ring > 0:
        painter.save()
        painter.setOpacity(appear * ring)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(6, 10, 16, 200))
        painter.drawRoundedRect(dest.adjusted(-5, -5, 5, 5), 16, 16)
        painter.setClipRect(dest)
        painter.drawPixmap(dest, material, src_small)
        painter.setClipping(False)
        pen = QPen(QColor(ACCENT))
        pen.setWidthF(2.6)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(dest.adjusted(-0.5, -0.5, 0.5, 0.5), 16, 16)
        painter.drawLine(QPointF(dest.left(), dest.top() - 4),
                         QPointF(dest.left() + 26, dest.top() - 26))
        P.text(painter, "3.4×  噪点", QRectF(dest.x(), dest.bottom() + 10, dest.width(), 40),
               22, ACCENT_SOFT, 600, Qt.AlignmentFlag.AlignHCenter)
        painter.restore()


def shot_reveal(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    """Cursor sweeps the window and the light follows it - the real gradient."""
    target = QRectF(330, 230, 1260, 650)
    appear = P.ease_out(P.span(t, 0.0, 0.5))
    label(painter, "Reveal 鼠标光效", WIDTH / 2, 92, 54, TEXT, 600, appear)
    label(painter, "一束柔光跟随光标，扫过窗口和按钮", WIDTH / 2, 162, 30, MUTED, 400,
          P.span(t, 0.3, 0.6))

    painter.save()
    painter.setOpacity(appear)
    paint_window(painter, assets, "win10", target)
    painter.restore()

    # A gentle S-curve across the window, so the light travels and lingers.
    travel = P.span(t, 0.7, length - 1.4)
    eased = P.ease_in_out(travel)
    cursor = QPointF(target.x() + target.width() * (0.16 + 0.68 * eased),
                     target.y() + target.height() * (0.34 + 0.26 * math.sin(eased * math.pi)))

    painter.save()
    clip = QRectF(target.adjusted(-20, -20, 20, 20))
    painter.setClipRect(clip)
    paint_glow(painter, assets, cursor, scale=1.05,
               opacity=appear * (0.35 + 0.65 * P.span(t, 0.7, 0.9)))
    painter.restore()
    P.draw_cursor(painter, cursor, scale=1.9)

    pill(painter, "光斑跟随指针 · 移出淡出", WIDTH / 2, 930, P.span(t, 1.4, 0.6))


def shot_strength(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    """The same window at the three selectable intensities."""
    appear = P.ease_out(P.span(t, 0.0, 0.5))
    label(painter, "光效强度可调", WIDTH / 2, 92, 54, TEXT, 600, appear)

    names = [("弱", 0.55), ("标准", 1.0), ("强", 1.65)]
    card_w, card_h = 440, 300
    gap = 70
    total = card_w * 3 + gap * 2
    start_x = (WIDTH - total) / 2

    for index, (name, strength) in enumerate(names):
        step = P.span(t, 0.35 + index * 0.28, 0.5)
        x = start_x + index * (card_w + gap)
        y = 300 + (1 - P.ease_out(step)) * 26
        card = QRectF(x, y, card_w, card_h)
        painter.save()
        painter.setOpacity(appear * step)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 14))
        painter.drawRoundedRect(card, 20, 20)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), 20, 20)

        # The real window, cropped, with the light scaled by the real strength.
        window = assets.windows["win10"]
        src = QRectF(window.width() * 0.12, window.height() * 0.10,
                     window.width() * 0.76, window.height() * 0.80)
        inner = card.adjusted(18, 18, -18, -18)
        painter.setClipRect(inner)
        painter.drawPixmap(inner, window, src)
        centre = QPointF(inner.center().x() + inner.width() * 0.16,
                         inner.center().y() - inner.height() * 0.14)
        paint_glow(painter, assets, centre, scale=0.34,
                   opacity=min(1.0, strength) * 1.1 * step)
        painter.setClipping(False)
        painter.restore()

        P.text(painter, name, QRectF(card.x(), card.bottom() + 26, card.width(), 60), 34,
               TEXT if name != "标准" else ACCENT_SOFT, 600,
               Qt.AlignmentFlag.AlignHCenter, appear * step)


def shot_outro(painter: QPainter, assets: UpdateAssets, t: float, length: float) -> None:
    appear = P.ease_out(P.span(t, 0.0, 0.6))
    centre_x = WIDTH / 2
    glow = QRadialGradient(QPointF(centre_x, 470), 520)
    colour = QColor(ACCENT)
    colour.setAlphaF(0.16 * appear)
    glow.setColorAt(0.0, colour)
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.fillRect(QRectF(0, 0, WIDTH, HEIGHT), glow)

    painter.save()
    painter.setOpacity(appear)
    painter.drawPixmap(QRectF(centre_x - 70, 300, 140, 140), assets.icon,
                       QRectF(assets.icon.rect()))
    painter.restore()
    label(painter, "截图工具", centre_x, 480, 76, TEXT, 600, P.span(t, 0.2, 0.5))
    label(painter, "Windows 10 / 11 · 免安装 · 免费开源", centre_x, 590, 32, MUTED, 400,
          P.span(t, 0.45, 0.5))
    pill(painter, "github.com 搜索 WinSnipRec", centre_x, 700, P.span(t, 0.7, 0.5),
         highlight=True)


SCENE_FUNCS = {
    "intro": shot_intro,
    "switch": shot_switch,
    "acrylic": shot_acrylic,
    "reveal": shot_reveal,
    "strength": shot_strength,
    "outro": shot_outro,
}


def render_frame(painter: QPainter, assets: UpdateAssets, t: float) -> None:
    painter.drawImage(0, 0, assets.background)
    for name, start, length in SCENES:
        if start <= t < start + length:
            SCENE_FUNCS[name](painter, assets, t - start, length)
            return
    if t >= SCENES[-1][1] + SCENES[-1][2]:
        SCENE_FUNCS["outro"](painter, assets, SCENES[-1][2] - 0.01, SCENES[-1][2])


# --------------------------------------------------------------------------- #
# Side outputs
# --------------------------------------------------------------------------- #
def build_sfx() -> list[tuple[float, str]]:
    """Sparse UI sounds on the pulse grid, so they sit under the music.

    Only every 4th pulse gets a tick and every 8th a click: the track is mixed
    underneath and a busy effect layer would fight it.
    """
    beats: list[tuple[float, str]] = []
    count = int(round(DURATION / QUANTUM))
    for index in range(count + 1):
        at = round(index * QUANTUM, 4)
        if at >= DURATION:
            break
        if index % 8 == 0:
            beats.append((at, "click"))
        elif index % 4 == 0:
            beats.append((at, "tick"))
    for _name, start, _length in SCENES:
        beats.append((round(start, 4), "whoosh"))
        beats.append((round(start + 0.06, 4), "chime"))
    beats.append((0.0, "pop"))
    beats.append((round(DURATION - 0.6, 4), "pop"))
    return sorted(beats)


def write_srt(path: Path) -> None:
    def stamp(value: float) -> str:
        ms = int(round(value * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    lines = []
    for index, (start, length, value) in enumerate(SUBTITLES, 1):
        lines.append(f"{index}\n{stamp(start)} --> {stamp(start + length)}\n{value}\n")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_storyboard(path: Path) -> None:
    rows = ["# 1.1.0 更新宣传片分镜（1920×1080 · 30fps · 30s）", "",
            f"剪辑网格：每 {QUANTUM * 1000:.0f} ms 一个脉冲，所有切点都落在脉冲上。",
            "  所配音乐实测自相关在 900 ms(66.7 BPM) 与 600 ms(100 BPM) 都强，",
            "  重拍间隔 305 ms —— 三者都是 300 ms 的整数倍，所以切点量化到 300 ms",
            "  后无论真实速度是哪个，剪辑都踩在拍上。",
            "音乐：用 `promo\\video\\混入音乐.ps1 -Music <文件> -Offset <秒>` 混入。", "",
            "| 时间 | 时长 | 画面 | 文案 |", "|---|---|---|---|"]
    for name, start, length in SCENES:
        title = {
            "intro": "应用图标 + 标题",
            "switch": "Windows 11 窗口横向擦除成 Windows 10",
            "acrylic": "放大镜看真实窗口的模糊与噪点",
            "reveal": "光标划过窗口，柔光跟随（真实渐变）",
            "strength": "弱 / 标准 / 强 三档并排",
            "outro": "图标 + 下载信息",
        }[name]
        caption = next((v for s, _, v in SUBTITLES if abs(s - start) < 0.4), "")
        rows.append(f"| {start:04.1f}s | {length:.1f}s | {title} | {caption} |")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                        help="render 1 frame per second into a contact sheet")
    parser.add_argument("--keep-silent", action="store_true",
                        help="skip the built-in UI sound effects")
    parser.add_argument("--quantum", type=float, default=QUANTUM,
                        help="cut grid in seconds; all cuts land on a multiple")
    args = parser.parse_args()

    from winsnip import winapi
    from winsnip.core.encoder import ffmpeg_path
    from winsnip.theme import apply_app_theme, theme

    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    theme.mode = "dark"
    theme.style = "win10"
    theme.refresh()
    apply_app_theme(app)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("==> 准备素材（离屏抓取两种风格的真实窗口 + 程序自己的 Reveal 光晕）")
    started = time.perf_counter()
    assets = UpdateAssets()
    print(f"    完成，用时 {time.perf_counter() - started:.1f}s")

    write_srt(OUT_DIR / "update_1920x1080_30s.srt")
    write_storyboard(OUT_DIR / "update_storyboard.md")
    print("==> 已写分镜表与字幕")

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
        P.write_contact_sheet(thumbs, OUT_DIR / "update_contact_sheet.png")
        print("==> 预览网格已输出")
        return 0

    silent = OUT_DIR / "_update_video_only.mp4"
    ffmpeg = ffmpeg_path()
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{WIDTH}x{HEIGHT}",
               "-r", str(FPS), "-i", "-",
               "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(silent)]
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
        process.stdin.write(P.frame_bytes(frame))
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

    P.write_contact_sheet(thumbs, OUT_DIR / "update_contact_sheet.png")

    final = OUT_DIR / "update_1920x1080_30s.mp4"
    if args.keep_silent:
        silent.replace(final)
    else:
        print("==> 合成 UI 音效轨")
        sfx = P.build_sfx_track(OUT_DIR / "update_sfx_track.wav", build_sfx())
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", str(silent), "-i", str(sfx),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                        str(final)], check=True)
        silent.unlink(missing_ok=True)

    print(f"==> 输出 {final.relative_to(ROOT)}  {final.stat().st_size / 1_048_576:.1f} MB")
    print("==> 加音乐: powershell -ExecutionPolicy Bypass -File "
          "promo\\video\\混入音乐.ps1 -Music <音乐文件>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
