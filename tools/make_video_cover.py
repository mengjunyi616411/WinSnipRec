"""Cover art for the promotional video — 16:9 and 4:3.

Both are built from the real UI screenshots and the same design tokens as the
app, so the cover, the posters and the video all look like one family.

Run:  .venv\\Scripts\\python.exe tools\\make_video_cover.py
Out:  promo/video/cover_16x9_1920x1080.png
      promo/video/cover_4x3_1440x1080.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import QPointF, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from make_promo import Poster, draw_pill, font, render_overlay_demo, rounded  # noqa: E402
from winsnip import icons, winapi  # noqa: E402
from winsnip.theme import apply_app_theme, theme  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "promo" / "video"

ACCENT = "#4CC2FF"
TEXT = "#F3F7FB"
DIM = "#9AA7B6"


# --------------------------------------------------------------------------- #
def load(name: str) -> QPixmap:
    pixmap = QPixmap(str(SHOTS / name))
    pixmap.setDevicePixelRatio(1.0)
    return pixmap


def draw_screenshot(painter: QPainter, pixmap: QPixmap, rect: QRectF,
                    radius: int = 16, shadow: bool = True) -> None:
    """A screenshot as a floating rounded card with a soft shadow."""
    from winsnip.theme import render_shadow

    if shadow:
        spread = max(20, int(rect.width() * 0.05))
        shadow_pixmap = render_shadow(
            QSize(int(rect.width()) + spread * 2, int(rect.height()) + spread * 2),
            radius * 2, spread=spread, opacity=0.62)
        painter.drawPixmap(rect.adjusted(-spread, -spread + 12, spread, spread + 12),
                           shadow_pixmap, QRectF(shadow_pixmap.rect()))
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    clipped = rounded(pixmap, radius)
    painter.drawPixmap(rect, clipped, QRectF(clipped.rect()))
    painter.restore()


def draw_headline(painter: QPainter, centre_x: float, top: float, width: float,
                  small: int, large: int) -> float:
    """「在 Windows 10 上 / 享受 Windows 11 的录屏体验」; returns the bottom y."""
    painter.setFont(font(small, 500))
    painter.setPen(QColor(DIM))
    painter.drawText(QRectF(centre_x - width / 2, top, width, small * 1.6),
                     int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                     "在 Windows 10 上")

    gradient = QLinearGradient(centre_x - width * 0.45, 0, centre_x + width * 0.45, 0)
    gradient.setColorAt(0.0, QColor("#8FD8FF"))
    gradient.setColorAt(0.55, QColor(ACCENT))
    gradient.setColorAt(1.0, QColor("#3EA6E8"))
    pen = QPen()
    pen.setBrush(gradient)
    painter.setFont(font(large, 700))
    painter.setPen(pen)
    box = QRectF(centre_x - width / 2, top + small * 1.45, width, large * 1.35)
    painter.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                     "享受 Windows 11 的录屏体验")
    return box.bottom()


def draw_brand(painter: QPainter, x: float, y: float, size: int = 44,
               text_size: int = 26) -> None:
    icon = icons.app_icon().pixmap(size, size)
    painter.drawPixmap(QRectF(x, y, size, size), icon, QRectF(icon.rect()))
    painter.setFont(font(text_size, 600))
    painter.setPen(QColor(TEXT))
    metrics = QFontMetrics(font(text_size, 600))
    painter.drawText(QRectF(x + size + 14, y, metrics.horizontalAdvance("截图工具 WinSnipRec") + 8, size),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                     "截图工具 WinSnipRec")


def draw_play(painter: QPainter, centre: QPointF, radius: float,
              opacity: float = 1.0) -> None:
    """Centre play affordance so the artwork reads as a video cover."""
    painter.save()
    painter.setOpacity(opacity)
    glow = QRadialGradient(centre, radius * 1.45)
    glow.setColorAt(0.0, QColor(0, 0, 0, 132))
    glow.setColorAt(0.70, QColor(0, 0, 0, 74))
    glow.setColorAt(1.0, QColor(0, 0, 0, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(glow)
    painter.drawEllipse(centre, radius * 1.45, radius * 1.45)

    disc = QColor(12, 18, 26, 195)
    painter.setBrush(disc)
    painter.drawEllipse(centre, radius, radius)
    pen = QPen(QColor(255, 255, 255, 210))
    pen.setWidthF(max(2.0, radius * 0.055))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(centre, radius, radius)

    side = radius * 0.82
    triangle = QPainterPath()
    triangle.moveTo(centre.x() - side * 0.30, centre.y() - side * 0.52)
    triangle.lineTo(centre.x() + side * 0.56, centre.y())
    triangle.lineTo(centre.x() - side * 0.30, centre.y() + side * 0.52)
    triangle.closeSubpath()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawPath(triangle)
    painter.restore()


def chips(painter: QPainter, centre_x: float, y: float, labels: list[str],
          size: int = 22, height: float = 46) -> None:
    f = font(size, 500)
    metrics = QFontMetrics(f)
    widths = [metrics.horizontalAdvance(label) + 46 for label in labels]
    gap = 18
    total = sum(widths) + gap * (len(labels) - 1)
    x = centre_x - total / 2
    painter.setFont(f)
    for label, width in zip(labels, widths):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 20))
        painter.drawRoundedRect(QRectF(x, y, width, height), height / 2, height / 2)
        pen = QPen(QColor(255, 255, 255, 46))
        pen.setWidthF(1.1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, width - 1, height - 1),
                                height / 2, height / 2)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(x, y, width, height), int(Qt.AlignmentFlag.AlignCenter), label)
        x += width + gap


def draw_rec_badge(painter: QPainter, x: float, y: float, label: str = "30 秒看完") -> float:
    f = font(21, 600)
    painter.setFont(f)
    width = QFontMetrics(f).horizontalAdvance(label) + 74
    rect = QRectF(x, y, width, 44)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(232, 62, 62, 235))
    painter.drawRoundedRect(rect, 22, 22)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(QPointF(x + 26, y + 22), 8, 8)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(QRectF(x + 42, y, width - 46, 44),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
    return width


def vignette(painter: QPainter, width: int, height: int) -> None:
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    for side in ("top", "bottom"):
        gradient = QLinearGradient(0, 0 if side == "top" else height,
                                   0, height * 0.30 if side == "top" else height * 0.70)
        gradient.setColorAt(0.0, QColor(4, 7, 11, 190))
        gradient.setColorAt(1.0, QColor(4, 7, 11, 0))
        painter.setBrush(gradient)
        painter.drawRect(QRectF(0, 0, width, height))
    painter.restore()


# --------------------------------------------------------------------------- #
def build_wide(play: bool = True) -> QImage:
    width, height = 1920, 1080
    image = Poster(width, height).background()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    vignette(painter, width, height)
    draw_brand(painter, 92, 74)

    bottom = draw_headline(painter, width / 2, 168, width - 300, 54, 104)

    window = load("01_main_light.png")
    card_w = 1180.0
    card_h = card_w * window.height() / window.width()
    card = QRectF((width - card_w) / 2, bottom + 34, card_w, card_h)
    # keep the bottom of the card clear of the chips
    chip_y = height - 92
    if card.bottom() > chip_y - 26:
        card.moveTop(chip_y - 26 - card.height())
    draw_screenshot(painter, window, card)
    # Sit in the empty band between the command bar and the hint text instead of
    # covering the hint.
    if play:
        draw_play(painter, QPointF(card.center().x(), card.top() + card.height() * 0.37), 58)

    bar = load("03_control_bar_light.png")
    bar_w = 560.0
    bar_h = bar_w * bar.height() / bar.width()
    bar_rect = QRectF(card.right() - bar_w - 70, card.bottom() - bar_h * 0.52, bar_w, bar_h)
    draw_screenshot(painter, bar, bar_rect, 18)

    draw_rec_badge(painter, 92, card.top() + 6)
    chips(painter, width / 2, chip_y, ["免安装单文件 EXE", "暂停 / 继续", "系统声音", "H.264 MP4"], 23, 48)
    painter.end()
    return image


def build_four_three(play: bool = True) -> QImage:
    width, height = 1440, 1080
    image = Poster(width, height).background()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    vignette(painter, width, height)
    draw_brand(painter, 74, 62, 40, 24)

    bottom = draw_headline(painter, width / 2, 138, width - 200, 46, 86)

    window = load("01_main_light.png")
    card_w = 1090.0
    card_h = card_w * window.height() / window.width()
    card = QRectF((width - card_w) / 2, bottom + 40, card_w, card_h)
    draw_screenshot(painter, window, card)
    if play:
        draw_play(painter, QPointF(card.center().x(), card.top() + card.height() * 0.36), 54)

    bar = load("03_control_bar_light.png")
    bar_w = 500.0
    bar_h = bar_w * bar.height() / bar.width()
    bar_rect = QRectF(card.right() - bar_w - 56, card.bottom() - bar_h * 0.5, bar_w, bar_h)
    draw_screenshot(painter, bar, bar_rect, 16)

    chip_y = min(card.bottom() + 70, height - 96)
    draw_rec_badge(painter, 74, chip_y - 4)
    chips(painter, width / 2 + 60, chip_y, ["免安装 EXE", "暂停继续", "H.264 MP4"], 21, 44)
    painter.end()
    return image


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)  # noqa: F841
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    OUT.mkdir(parents=True, exist_ok=True)
    # Two variants each: with a play badge (reads as a video at a glance) and
    # without it, for platforms that draw their own play button on top.
    outputs = [
        ("cover_16x9_1920x1080.png", build_wide(True)),
        ("cover_16x9_1920x1080_无播放键.png", build_wide(False)),
        ("cover_4x3_1440x1080.png", build_four_three(True)),
        ("cover_4x3_1440x1080_无播放键.png", build_four_three(False)),
    ]
    for name, image in outputs:
        path = OUT / name
        image.save(str(path), "PNG")
        print(f"[ok] {path.relative_to(ROOT)}  {image.width()}x{image.height()}  "
              f"{path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
