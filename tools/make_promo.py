"""Render promotional images for WinSnipRec / 截图工具.

Reuses the application's own palette, fonts, icons and real UI screenshots so
the artwork matches the product exactly.

Run:  .venv\\Scripts\\python.exe tools\\make_promo.py
Out:  <project>/promo/*.png
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPainterPath,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import icons, winapi  # noqa: E402
from winsnip.theme import mica, theme  # noqa: E402

SHOTS = ROOT / "docs" / "screenshots"
OUT = ROOT / "promo"

# --------------------------------------------------------------------------- #
# Typography
# --------------------------------------------------------------------------- #
CJK = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Variable Display", "Segoe UI"]
LATIN = ["Segoe UI Variable Display", "Segoe UI"]


def font(size: int, weight: int = 400, latin: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(LATIN if latin else CJK)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #
def rounded(pixmap: QPixmap, radius: int) -> QPixmap:
    out = QPixmap(pixmap.size())
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addRoundedRect(QRectF(pixmap.rect()), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return out


def draw_card(painter: QPainter, pixmap: QPixmap, rect: QRectF, radius: int = 12,
              shadow_alpha: float = 0.55, border: QColor | None = None) -> None:
    """Draw a screenshot as a floating, rounded, shadowed card."""
    from winsnip.theme import render_shadow

    spread = max(18, int(rect.width() * 0.045))
    shadow = render_shadow(QSize(int(rect.width()) + spread * 2,
                                 int(rect.height()) + spread * 2),
                           radius * 2, spread=spread, opacity=shadow_alpha)
    painter.drawPixmap(int(rect.x() - spread), int(rect.y() - spread + spread * 0.35), shadow)

    scaled = pixmap.scaled(int(rect.width()), int(rect.height()),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    painter.drawPixmap(int(rect.x()), int(rect.y()), rounded(scaled, radius))

    if border is not None:
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(border)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def fit(pixmap: QPixmap, width: float) -> tuple[float, float]:
    """Aspect-correct (width, height) for a screenshot at ``width``."""
    height = width * pixmap.height() / max(1, pixmap.width())
    return width, height


def draw_text(painter: QPainter, text: str, rect: QRectF, size: int, color: QColor,
              weight: int = 400, align=Qt.AlignmentFlag.AlignLeft) -> None:
    painter.setFont(font(size, weight))
    painter.setPen(color)
    painter.drawText(rect, int(align | Qt.AlignmentFlag.AlignVCenter), text)


def draw_pill(painter: QPainter, text: str, x: float, y: float, size: int = 16,
              padding: float = 16, height: float = 38, icon_name: str | None = None,
              accent: bool = False) -> float:
    """Draw a rounded badge; returns its width."""
    f = font(size, 500)
    painter.setFont(f)
    metrics = QFontMetrics(f)
    text_w = metrics.horizontalAdvance(text)
    icon_w = 22 if icon_name else 0
    width = text_w + icon_w + padding * 2

    rect = QRectF(x, y, width, height)
    if accent:
        fill = QColor(theme.palette.accent)
        fill.setAlphaF(0.16)
        border = QColor(theme.palette.accent)
        border.setAlphaF(0.45)
        fg = QColor(theme.palette.accent)
    else:
        fill = QColor(255, 255, 255, 16)
        border = QColor(255, 255, 255, 38)
        fg = QColor("#E9EDF2")

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, height / 2, height / 2)
    pen = painter.pen()
    pen.setWidthF(1.0)
    pen.setColor(border)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect, height / 2, height / 2)

    text_x = x + padding
    if icon_name:
        icons.paint_icon(painter, icon_name,
                         QRectF(text_x, y + (height - 18) / 2, 18, 18), fg)
        text_x += icon_w
    painter.setFont(f)
    painter.setPen(fg)
    painter.drawText(QRectF(text_x, y, text_w + 4, height),
                     int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
    return width


def draw_feature(painter: QPainter, icon_name: str, title: str, desc: str,
                 x: float, y: float, width: float) -> None:
    icon_color = QColor(theme.palette.accent)
    icons.paint_icon(painter, icon_name, QRectF(x, y + 2, 22, 22), icon_color)
    draw_text(painter, title, QRectF(x + 34, y - 4, width - 34, 26), 18, QColor("#F2F5F8"), 500)
    draw_text(painter, desc, QRectF(x + 34, y + 20, width - 34, 22), 14, QColor("#9AA5B1"), 400)


# --------------------------------------------------------------------------- #
# Mock desktop (so promo art never shows the real desktop contents)
# --------------------------------------------------------------------------- #
def mock_desktop(width: int, height: int) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)

    base = QLinearGradient(0, 0, width, height)
    base.setColorAt(0.0, QColor("#123A5E"))
    base.setColorAt(0.45, QColor("#1E5B8C"))
    base.setColorAt(1.0, QColor("#0B2439"))
    painter.fillRect(0, 0, width, height, base)

    glow = QRadialGradient(QPointF(width * 0.68, height * 0.28), width * 0.45)
    glow.setColorAt(0.0, QColor(150, 220, 255, 120))
    glow.setColorAt(1.0, QColor(150, 220, 255, 0))
    painter.fillRect(0, 0, width, height, glow)

    # A couple of plausible windows plus a taskbar, so the frozen desktop reads
    # as a real screen once it is dimmed behind the selection.
    painter.setPen(Qt.PenStyle.NoPen)
    panels = ((0.06, 0.12, 0.42, 0.60), (0.53, 0.20, 0.41, 0.54))
    for px, py, pw, ph in panels:
        rect = QRectF(width * px, height * py, width * pw, height * ph)
        painter.setBrush(QColor(250, 252, 255, 235))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setBrush(QColor(226, 233, 240, 255))
        painter.drawRoundedRect(QRectF(rect.x(), rect.y(), rect.width(), 30), 12, 12)
        painter.setBrush(QColor(168, 186, 204, 255))
        for line in range(4):
            painter.drawRoundedRect(
                QRectF(rect.x() + 24, rect.y() + 60 + line * 34,
                       rect.width() * (0.72 - line * 0.09), 12), 6, 6)

    painter.setBrush(QColor(12, 22, 34, 210))
    painter.drawRoundedRect(QRectF(width * 0.30, height - 54, width * 0.40, 40), 10, 10)

    painter.end()

    divisor = 10
    blurred = image.scaled(max(1, width // divisor), max(1, height // divisor),
                           Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    return blurred.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)


def render_overlay_demo(width: int = 1920, height: int = 1080) -> QPixmap:
    """A fake 'region selection on a frozen desktop' shot for the poster.

    Rendered with the dark palette: the stronger dim makes the selection read
    clearly at poster size, and it matches the artwork's dark theme.
    """
    from winsnip.ui.overlay import CaptureOverlay

    previous_mode = theme.mode
    theme.mode = "dark"
    theme.refresh()
    try:
        overlay = CaptureOverlay(mode="video", shape="rectangle", confirm=True)
        overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        overlay.resize(1536, 864)
        overlay._virtual_rect = QRect(0, 0, 1536, 864)
        overlay._dpr = 1.25
        overlay._screen_image = mock_desktop(width, height)
        overlay.show()
        overlay._position_bar()
        overlay._bar.set_shape("rectangle")
        overlay._selection = QRect(300, 250, 820, 470)
        overlay._pointer = QPoint(1120, 720)
        overlay._committed_selection = False
        QApplication.processEvents()
        pixmap = overlay.grab()
        overlay.close()
        return pixmap
    finally:
        theme.mode = previous_mode
        theme.refresh()


# --------------------------------------------------------------------------- #
# Poster
# --------------------------------------------------------------------------- #
class Poster:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.p = QColor(theme.palette.accent)

    def background(self) -> QImage:
        image = QImage(self.width, self.height, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        base = QLinearGradient(0, 0, self.width * 0.35, self.height)
        base.setColorAt(0.0, QColor("#0C1118"))
        base.setColorAt(0.45, QColor("#121A24"))
        base.setColorAt(1.0, QColor("#080B10"))
        painter.fillRect(0, 0, self.width, self.height, base)

        # Blurred wallpaper for authenticity, kept subtle.
        try:
            wallpaper = mica._base_image()
            if wallpaper is not None and not wallpaper.isNull():
                scaled = wallpaper.scaled(self.width, self.height,
                                          Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                          Qt.TransformationMode.SmoothTransformation)
                painter.setOpacity(0.30)
                painter.drawImage(-(scaled.width() - self.width) // 2,
                                  -(scaled.height() - self.height) // 2, scaled)
                painter.setOpacity(1.0)
        except Exception:
            pass

        veil = QLinearGradient(0, 0, 0, self.height)
        veil.setColorAt(0.0, QColor(8, 11, 16, 205))
        veil.setColorAt(0.55, QColor(8, 11, 16, 170))
        veil.setColorAt(1.0, QColor(6, 8, 12, 235))
        painter.fillRect(0, 0, self.width, self.height, veil)

        glow = QRadialGradient(QPointF(self.width * 0.74, self.height * 0.42),
                               self.width * 0.55)
        accent = QColor(theme.palette.accent)
        accent.setAlpha(58)
        glow.setColorAt(0.0, accent)
        accent.setAlpha(0)
        glow.setColorAt(1.0, accent)
        painter.fillRect(0, 0, self.width, self.height, glow)
        painter.end()
        return image


def build_landscape(shots: dict) -> Path:
    W, H = 1920, 1080
    poster = Poster(W, H)
    image = poster.background()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    accent = QColor(theme.palette.accent)

    # ---- header ----
    painter.drawPixmap(90, 74, icons.app_icon().pixmap(56, 56))
    draw_text(painter, "截图工具 WinSnipRec", QRectF(162, 74, 620, 56), 30, QColor("#FFFFFF"), 600)
    draw_pill(painter, "Windows 10 / 11 (x64)", W - 90 - 260, 82, size=15, height=36)

    # ---- headline ----
    y = 210
    draw_text(painter, "在 Windows 10 上", QRectF(92, y, 760, 60), 46, QColor("#FFFFFF"), 600)
    y += 62
    draw_text(painter, "享受 Windows 11 的录屏体验", QRectF(92, y, 800, 60), 46,
              accent, 600)
    y += 78
    draw_text(painter, "界面、图标与配色按 Windows 11「截图工具」逐像素对照制作", 
              QRectF(92, y, 760, 30), 19, QColor("#A9B4C0"), 400)
    y += 30
    draw_text(painter, "区域 / 窗口 / 全屏录制 · 暂停继续 · 输出 H.264 MP4",
              QRectF(92, y, 760, 30), 19, QColor("#A9B4C0"), 400)

    # ---- features ----
    y += 60
    features = [
        ("add_rect", "框选即录", "松开鼠标立即开始，与 Win11 一致"),
        ("pause", "暂停 / 继续", "计时同步冻结，成片不含暂停段"),
        ("mic", "麦克风与系统声音", "录制中可随时开关麦克风"),
        ("cursor", "录制鼠标光标", "GDI 合成，指针清晰不丢帧"),
        ("save", "H.264 MP4", "30 / 60 fps，画质可调，便于分享"),
        ("window", "全局快捷键", "被系统占用时自动回退并提示"),
        ("settings", "浅色 / 深色主题", "跟随系统，实时切换"),
        ("check", "免安装单文件", "无需 Python，双击即用"),
    ]
    for index, (icon_name, title, desc) in enumerate(features):
        column = index % 2
        row = index // 2
        draw_feature(painter, icon_name, title, desc,
                     92 + column * 380, y + row * 72, 350)

    # ---- footer badges ----
    badge_y = H - 118
    x = 92
    for text, icon_name in (("输出到自定义文件夹", "folder"),
                            ("托盘常驻 · 一键唤起", "monitor"),
                            ("Python + Qt + FFmpeg", "info")):
        x += draw_pill(painter, text, x, badge_y, size=16, icon_name=icon_name) + 12

    # ---- hero ----
    hero_rect = QRectF(940, 176, 890, 458)
    draw_card(painter, shots["main_light"], hero_rect, radius=14, shadow_alpha=0.6)
    draw_text(painter, "主界面 · 与 Windows 11 截图工具同款",
              QRectF(hero_rect.x(), hero_rect.bottom() + 8, 500, 26), 15,
              QColor("#8E99A6"), 400)

    # ---- gallery ----
    panel = QColor(255, 255, 255, 12)
    border = QColor(255, 255, 255, 40)

    dark_w, dark_h = fit(shots["main_dark"], 300)
    dark_rect = QRectF(940, 690, dark_w, dark_h)
    bar_w, bar_h = fit(shots["control_bar"], 300)
    bar_rect = QRectF(940, dark_rect.bottom() + 62, bar_w, bar_h)

    ov_w, ov_h = fit(shots["overlay"], 548)
    ov_rect = QRectF(1262, 690, ov_w, ov_h)

    for rect, pixmap, radius, label in (
        (dark_rect, shots["main_dark"], 12, "深色主题"),
        (bar_rect, shots["control_bar"], 8, "录制控制条 · 暂停 / 计时 / 麦克风"),
        (ov_rect, shots["overlay"], 14, "区域选择 · 冻结屏幕 + 尺寸提示 + 确认按钮"),
    ):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(panel)
        painter.drawRoundedRect(rect.adjusted(-8, -8, 8, 8), radius + 8, radius + 8)
        draw_card(painter, pixmap, rect, radius=radius, shadow_alpha=0.45, border=border)
        draw_text(painter, label, QRectF(rect.x(), rect.bottom() + 10, rect.width(), 24), 14,
                  QColor("#8E99A6"), 400)

    painter.end()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "promo_1920x1080.png"
    image.save(str(path), "PNG")
    return path


def draw_steps(painter: QPainter, x: float, y: float, width: float, gap: float,
               steps: list[tuple[str, str, str]]) -> float:
    """Three numbered 'how it works' panels; returns the used height."""
    count = len(steps)
    panel_w = (width - gap * (count - 1)) / count
    panel_h = 132.0
    accent = QColor(theme.palette.accent)
    for index, (title, desc, icon_name) in enumerate(steps):
        px = x + index * (panel_w + gap)
        rect = QRectF(px, y, panel_w, panel_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 14))
        painter.drawRoundedRect(rect, 14, 14)
        pen = painter.pen()
        pen.setWidthF(1.0)
        border = QColor(255, 255, 255, 34)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, 14, 14)

        badge = QRectF(px + 18, y + 18, 34, 34)
        accent_fill = QColor(accent)
        accent_fill.setAlphaF(0.18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent_fill)
        painter.drawRoundedRect(badge, 9, 9)
        draw_text(painter, str(index + 1), badge, 19, accent, 600,
                  Qt.AlignmentFlag.AlignHCenter)
        icons.paint_icon(painter, icon_name, QRectF(px + panel_w - 46, y + 20, 22, 22),
                         QColor("#7C8896"))
        draw_text(painter, title, QRectF(px + 18, y + 60, panel_w - 36, 28), 19,
                  QColor("#F2F5F8"), 600)
        painter.setFont(font(14))
        painter.setPen(QColor("#9AA5B1"))
        painter.drawText(QRectF(px + 18, y + 88, panel_w - 36, 34),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop), desc)
    return panel_h


def build_vertical(shots: dict) -> Path:
    W, H = 1080, 1920
    poster = Poster(W, H)
    image = poster.background()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    accent = QColor(theme.palette.accent)
    border = QColor(255, 255, 255, 40)
    panel = QColor(255, 255, 255, 12)

    painter.drawPixmap(72, 68, icons.app_icon().pixmap(72, 72))
    draw_text(painter, "截图工具 WinSnipRec", QRectF(164, 68, 700, 72), 36,
              QColor("#FFFFFF"), 600)
    draw_text(painter, "Windows 10 / 11 (x64)", QRectF(164, 118, 500, 30), 17,
              QColor("#8E99A6"), 400)

    y = 218
    draw_text(painter, "在 Windows 10 上", QRectF(72, y, 940, 60), 48, QColor("#FFFFFF"), 600)
    y += 62
    draw_text(painter, "享受 Windows 11 的录屏体验", QRectF(72, y, 980, 60), 48, accent, 600)
    y += 74
    draw_text(painter, "界面、图标与配色按 Windows 11「截图工具」逐像素对照制作",
              QRectF(72, y, 940, 30), 19, QColor("#A9B4C0"), 400)
    y += 30
    draw_text(painter, "区域 / 窗口 / 全屏录制 · 暂停继续 · 输出 H.264 MP4",
              QRectF(72, y, 940, 30), 19, QColor("#A9B4C0"), 400)

    hero = QRectF(72, y + 46, 936, 482)
    draw_card(painter, shots["main_light"], hero, radius=16, shadow_alpha=0.6)
    draw_text(painter, "主界面 · 与 Windows 11 截图工具同款",
              QRectF(72, hero.bottom() + 10, 600, 26), 15, QColor("#8E99A6"), 400)

    gallery_y = int(hero.bottom()) + 62
    ov_w, ov_h = fit(shots["overlay"], 560)
    ov_rect = QRectF(72, gallery_y, ov_w, ov_h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(panel)
    painter.drawRoundedRect(ov_rect.adjusted(-8, -8, 8, 8), 22, 22)
    draw_card(painter, shots["overlay"], ov_rect, radius=14, shadow_alpha=0.45, border=border)
    draw_text(painter, "区域选择 · 冻结屏幕 + 尺寸提示", QRectF(72, ov_rect.bottom() + 10, 560, 26),
              15, QColor("#8E99A6"), 400)

    dark_w, dark_h = fit(shots["main_dark"], 352)
    dark_rect = QRectF(656, gallery_y, dark_w, dark_h)
    painter.setBrush(panel)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(dark_rect.adjusted(-8, -8, 8, 8), 20, 20)
    draw_card(painter, shots["main_dark"], dark_rect, radius=12, shadow_alpha=0.45, border=border)
    draw_text(painter, "深色主题", QRectF(656, dark_rect.bottom() + 10, 352, 24), 15,
              QColor("#8E99A6"), 400)

    bar_w, bar_h = fit(shots["control_bar"], 352)
    bar_rect = QRectF(656, dark_rect.bottom() + 62, bar_w, bar_h)
    painter.setBrush(panel)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(bar_rect.adjusted(-8, -8, 8, 8), 18, 18)
    draw_card(painter, shots["control_bar"], bar_rect, radius=10, shadow_alpha=0.45, border=border)
    draw_text(painter, "暂停 / 计时 / 麦克风", QRectF(656, bar_rect.bottom() + 10, 352, 24),
              15, QColor("#8E99A6"), 400)

    steps_y = 1400
    draw_text(painter, "三步开始录屏", QRectF(72, steps_y - 46, 400, 30), 22,
              QColor("#F2F5F8"), 600)
    steps_h = draw_steps(painter, 72, steps_y, 936, 24, [
        ("按下快捷键", "Win+Shift+S / R\n被占用时自动回退", "window"),
        ("框选区域", "松开鼠标即开始\n窗口 / 全屏同样支持", "add_rect"),
        ("停止并保存", "自动输出 MP4\n可暂停、可丢弃重录", "save"),
    ])

    features = [
        ("add_rect", "框选即录", "与 Win11 行为一致"),
        ("pause", "暂停 / 继续", "成片不含暂停段"),
        ("mic", "麦克风", "录制中随时开关"),
        ("sound", "系统声音", "回环设备录系统音"),
        ("cursor", "录制光标", "指针清晰不丢帧"),
        ("window", "全局快捷键", "冲突时自动回退"),
    ]
    fy = int(steps_y + steps_h) + 58
    for index, (icon_name, title, desc) in enumerate(features):
        column = index % 2
        row = index // 2
        draw_feature(painter, icon_name, title, desc, 72 + column * 470, fy + row * 74, 440)

    badge_y = H - 130
    x = 72
    for text, icon_name in (("免安装单文件 EXE", "check"), ("H.264 MP4", "save"),
                            ("托盘常驻", "monitor")):
        x += draw_pill(painter, text, x, badge_y, size=16, height=36, icon_name=icon_name) + 10

    draw_text(painter, "Python + PySide6 + FFmpeg 构建 · 输出目录 / 帧率 / 画质均可自定义",
              QRectF(72, H - 72, 940, 26), 15, QColor("#6F7A87"), 400)

    painter.end()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "promo_1080x1920.png"
    image.save(str(path), "PNG")
    return path


def build_square(shots: dict) -> Path:
    W, H = 1080, 1080
    poster = Poster(W, H)
    image = poster.background()
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    accent = QColor(theme.palette.accent)
    border = QColor(255, 255, 255, 40)

    painter.drawPixmap(60, 52, icons.app_icon().pixmap(60, 60))
    draw_text(painter, "截图工具 WinSnipRec", QRectF(138, 52, 700, 60), 30,
              QColor("#FFFFFF"), 600)

    draw_text(painter, "在 Windows 10 上", QRectF(62, 146, 900, 52), 40, QColor("#FFFFFF"), 600)
    draw_text(painter, "享受 Windows 11 的录屏体验", QRectF(62, 200, 960, 52), 40, accent, 600)
    draw_text(painter, "界面与 Windows 11「截图工具」同款 · 区域 / 窗口 / 全屏录制",
              QRectF(62, 258, 960, 28), 17, QColor("#A9B4C0"), 400)

    hero_w, hero_h = fit(shots["main_light"], 760)
    hero = QRectF((W - hero_w) / 2, 316, hero_w, hero_h)
    draw_card(painter, shots["main_light"], hero, radius=14, shadow_alpha=0.6)

    row_y = int(hero.bottom()) + 40
    ov_w, ov_h = fit(shots["overlay"], 452)
    dark_w, dark_h = fit(shots["main_dark"], 452)
    for pixmap, rect, label in (
        (shots["overlay"], QRectF(62, row_y, ov_w, ov_h), "区域选择"),
        (shots["main_dark"], QRectF(566, row_y, dark_w, dark_h), "深色主题"),
    ):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.drawRoundedRect(rect.adjusted(-7, -7, 7, 7), 19, 19)
        draw_card(painter, pixmap, rect, radius=12, shadow_alpha=0.45, border=border)
        draw_text(painter, label, QRectF(rect.x(), rect.bottom() + 6, rect.width(), 22), 14,
                  QColor("#8E99A6"), 400)

    x = 62
    for text, icon_name in (("免安装 EXE", "check"), ("暂停继续", "pause"),
                            ("麦克风", "mic"), ("H.264 MP4", "save")):
        x += draw_pill(painter, text, x, H - 76, size=15, height=36, icon_name=icon_name) + 10

    painter.end()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "promo_1080x1080.png"
    image.save(str(path), "PNG")
    return path


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)  # noqa: F841 - required for QPixmap/QPainter
    theme.mode = "dark"
    theme.refresh()

    def shot(name: str, crop_margin: int = 25) -> QPixmap:
        pixmap = QPixmap(str(SHOTS / name))
        if pixmap.isNull():
            raise SystemExit(f"missing screenshot {name}; run: python app.py --selftest-ui")
        # App screenshots carry a transparent shadow margin; trim it.
        return pixmap.copy(pixmap.rect().adjusted(crop_margin, crop_margin,
                                                  -crop_margin, -crop_margin))

    shots = {
        "main_light": shot("01_main_light.png"),
        "main_dark": shot("08_main_dark.png"),
        "control_bar": shot("03_control_bar_light.png", crop_margin=14),
        "overlay": render_overlay_demo(),
    }
    for key, pixmap in shots.items():
        print(f"[info] {key}: {pixmap.width()}x{pixmap.height()}")

    outputs = [build_landscape(shots), build_vertical(shots), build_square(shots)]
    for path in outputs:
        size = path.stat().st_size / 1024
        print(f"[ok] {path.relative_to(ROOT)}  ({size:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
