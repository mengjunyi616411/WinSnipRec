"""Windows 11 / Fluent design tokens and the Mica backdrop renderer.

Colour values were sampled from the real Windows 11 Snipping Tool on build
26100 and then normalised, so the light and dark palettes below reproduce what
the shipped app looks like when its Mica backdrop is opaque.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor, QFont, QImage, QLinearGradient, QPainter, QPalette, QPixmap,
)

from . import winapi

# --------------------------------------------------------------------------- #
# Motion / metrics
# --------------------------------------------------------------------------- #
RADIUS_WINDOW = 8
RADIUS_CONTROL = 5
RADIUS_FLYOUT = 8
CAPTION_BUTTON_SIZE = QSize(46, 32)
COMMAND_BAR_HEIGHT = 56
CAPTION_BAR_HEIGHT = 40

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"]


def ui_font(size: int = 14, weight: int = 400) -> QFont:
    font = QFont()
    font.setFamilies(UI_FAMILIES)
    font.setPixelSize(size)
    font.setWeight(QFont.Weight(weight))
    return font


def icon_font(size: int = 16) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    font.setPixelSize(size)
    return font


# --------------------------------------------------------------------------- #
# Palettes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Palette:
    dark: bool
    accent: str
    window_bg: str
    band_bg: str
    content_bg: str
    control_bg: str
    control_bg_hover: str
    control_bg_pressed: str
    control_border: str
    toggle_track: str
    toggle_selected: str
    text_primary: str
    text_secondary: str
    text_disabled: str
    icon_primary: str
    icon_secondary: str
    separator: str
    overlay_dim: str
    flyout_bg: str
    flyout_border: str
    accent_text: str
    danger: str
    overlay_chip_bg: str


LIGHT = Palette(
    dark=False,
    accent="#0067C0",
    window_bg="#F3F3F3",
    band_bg="#EEF4F9",
    content_bg="#F7FAFC",
    control_bg="#FFFFFF",
    control_bg_hover="#F5F5F5",
    control_bg_pressed="#EFEFEF",
    control_border="#E1E6EA",
    toggle_track="#E7EDF2",
    toggle_selected="#FFFFFF",
    text_primary="#1A1A1B",
    text_secondary="#5D5D5D",
    text_disabled="#9A9A9A",
    icon_primary="#1A1A1B",
    icon_secondary="#6B6B6B",
    separator="#DCE1E5",
    overlay_dim="rgba(0, 0, 0, 46)",
    flyout_bg="#F9F9F9",
    flyout_border="#E1E6EA",
    accent_text="#0067C0",
    danger="#C42B1C",
    overlay_chip_bg="#FFFFFF",
)

DARK = Palette(
    dark=True,
    accent="#60CDFF",
    window_bg="#202020",
    band_bg="#272727",
    content_bg="#2B2B2B",
    control_bg="#2D2D2D",
    control_bg_hover="#333333",
    control_bg_pressed="#3A3A3A",
    control_border="#3D3D3D",
    toggle_track="#2A2A2A",
    toggle_selected="#3B3B3B",
    text_primary="#FFFFFF",
    text_secondary="#C8C8C8",
    text_disabled="#787878",
    icon_primary="#F0F0F0",
    icon_secondary="#A0A0A0",
    separator="#3A3A3A",
    overlay_dim="rgba(0, 0, 0, 92)",
    flyout_bg="#2C2C2C",
    flyout_border="#3D3D3D",
    accent_text="#60CDFF",
    danger="#FF99A4",
    overlay_chip_bg="#2C2C2C",
)


@dataclass
class ThemeState:
    mode: str = "system"  # system | light | dark
    _palette: Palette | None = field(default=None, repr=False)

    def refresh(self) -> None:
        self._palette = None

    @property
    def dark(self) -> bool:
        if self.mode == "dark":
            return True
        if self.mode == "light":
            return False
        return winapi.is_dark_mode()

    @property
    def palette(self) -> Palette:
        if self._palette is None:
            base = DARK if self.dark else LIGHT
            accent = QColor(winapi.system_accent_color(base.dark))
            # WinUI renders accents with SystemAccentColorDark1 in light theme and
            # a lightened variant in dark theme; #0078D4 -> #0067C0 / #60CDFF.
            accent = accent.lighter(150) if base.dark else accent.darker(115)
            self._palette = base.__class__(**{**base.__dict__, "accent": accent.name()})
        return self._palette

    def color(self, name: str) -> QColor:
        value = getattr(self.palette, name)
        return QColor(value)


theme = ThemeState()


def rgba(color: QColor | str, alpha: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# --------------------------------------------------------------------------- #
# Mica backdrop
# --------------------------------------------------------------------------- #
class MicaProvider:
    """Reproduces the Windows 11 'Mica' material.

    Real Mica composites a heavily blurred, desaturated copy of the desktop
    wallpaper behind the window. We rebuild it from the wallpaper file so the
    result is identical on Windows 10 (which has no Mica API) and never
    captures our own window.

    The wallpaper is covered + downscaled **once** into a small base image; each
    window then only crops and upscales that base (a few milliseconds), because
    rescaling the full-resolution wallpaper on every paint took ~1 second on a
    software-rendered desktop.
    """

    BASE_DIVISOR = 16

    def __init__(self) -> None:
        self._source: QImage | None = None
        self._loaded_path: str | None = None
        self._failed = False
        self._base: QImage | None = None
        self._base_path: str | None = None
        self._base_rect = QRect(0, 0, 1920, 1080)

    # -- wallpaper ---------------------------------------------------------- #
    def _wallpaper(self) -> QImage | None:
        path = winapi.wallpaper_path()
        if self._failed:
            return self._fallback()
        if path and path == self._loaded_path and self._source is not None:
            return self._source
        image = QImage()
        if not path or not image.load(path):
            self._failed = True
            return self._fallback()
        self._loaded_path = path
        self._source = image
        return image

    def _fallback(self) -> QImage:
        """A Windows 11 'bloom'-like gradient when no wallpaper can be read."""
        img = QImage(512, 288, QImage.Format.Format_RGB32)
        gradient = QLinearGradient(0, 0, 512, 288)
        if theme.dark:
            gradient.setColorAt(0.0, QColor("#0B1B33"))
            gradient.setColorAt(0.55, QColor("#123A63"))
            gradient.setColorAt(1.0, QColor("#08111F"))
        else:
            gradient.setColorAt(0.0, QColor("#DCE9F7"))
            gradient.setColorAt(0.55, QColor("#BBD5EE"))
            gradient.setColorAt(1.0, QColor("#E8F0F8"))
        painter = QPainter(img)
        painter.fillRect(img.rect(), gradient)
        painter.end()
        return img

    # -- compositing -------------------------------------------------------- #
    def _base_image(self) -> QImage:
        """The whole desktop wallpaper, blurred and cached at low resolution."""
        path = winapi.wallpaper_path() or ""
        if self._base is not None and self._base_path == path:
            return self._base
        target = self._virtual_rect_physical()
        width = max(64, target.width() // self.BASE_DIVISOR)
        height = max(36, target.height() // self.BASE_DIVISOR)

        base = self._decode_scaled_base(path, target, width, height)
        if base is None:
            wallpaper = self._wallpaper()
            assert wallpaper is not None
            covered = self._cover_rect(wallpaper, target)
            base = covered.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        self._base = base
        self._base_rect = target
        self._base_path = path
        return base

    def _decode_scaled_base(self, path: str, target: QRect, width: int,
                            height: int) -> QImage | None:
        """Decode the wallpaper already scaled down to the base size.

        Qt then hands the scaled size to the image plug-in, so a 4K JPEG is never
        expanded to full resolution just to be blurred away again (this was the
        single biggest startup cost: ~0.9 s -> ~0.1 s).
        """
        if not path or self._failed:
            return None
        try:
            from PySide6.QtGui import QImageReader

            reader = QImageReader(path)
            reader.setAutoTransform(True)
            size = reader.size()
            if not size.isValid() or size.width() <= 0 or size.height() <= 0:
                return None
            style = winapi.wallpaper_style()
            divisor = float(self.BASE_DIVISOR)
            if style == 2:  # stretch
                scaled = QSize(width, height)
            elif style in (0, 1):  # centre / tile
                scaled = QSize(max(1, int(size.width() / divisor)),
                               max(1, int(size.height() / divisor)))
            else:
                if style == 6:  # fit
                    cover = min(target.width() / size.width(), target.height() / size.height())
                else:  # 10 fill, 22 span
                    cover = max(target.width() / size.width(), target.height() / size.height())
                scaled = QSize(max(1, int(size.width() * cover / divisor)),
                               max(1, int(size.height() * cover / divisor)))
            reader.setScaledSize(scaled)
            image = reader.read()
            if image.isNull():
                return None
            if image.size() == QSize(width, height):
                return image
            canvas = QImage(width, height, image.format())
            canvas.fill(QColor(theme.palette.window_bg))
            painter = QPainter(canvas)
            painter.drawImage((width - image.width()) // 2, (height - image.height()) // 2, image)
            painter.end()
            return canvas
        except Exception:
            return None

    def invalidate(self) -> None:
        self._source = None
        self._loaded_path = None
        self._failed = False
        self._base = None
        self._base_path = None

    def backdrop(self, physical_rect: QRect, radius: int = RADIUS_WINDOW,
                 dpr: float = 1.0, tint_strength: float = 0.86,
                 extra_lightening: float = 0.0) -> QPixmap:
        """Return a rounded, blurred, tinted backdrop sized to ``physical_rect``."""
        width = max(1, physical_rect.width())
        height = max(1, physical_rect.height())
        base = self._base_image()
        source = self._base_rect

        scale_x = base.width() / max(1, source.width())
        scale_y = base.height() / max(1, source.height())
        crop = QRect(
            int(round((physical_rect.x() - source.x()) * scale_x)),
            int(round((physical_rect.y() - source.y()) * scale_y)),
            max(1, int(round(width * scale_x))),
            max(1, int(round(height * scale_y))),
        )
        crop = crop.intersected(QRect(0, 0, base.width(), base.height()))
        if crop.isEmpty():
            crop = QRect(0, 0, base.width(), base.height())
        blurred = base.copy(crop).scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)

        pixmap = QPixmap.fromImage(blurred)
        # NOTE: the device pixel ratio is intentionally *not* set on the backdrop.
        # It is a raw physical-pixel image that the window blits with an explicit
        # source rect, which keeps Qt's coordinate handling unambiguous.

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        if palette.dark:
            # Windows darkens and desaturates the wallpaper before tinting it, which
            # is what keeps dark Mica neutral instead of showing a coloured wash.
            painter.fillRect(QRect(0, 0, width, height), QColor(0, 0, 0, 96))
        tint = QColor(palette.window_bg)
        tint.setAlphaF(tint_strength)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(QRect(0, 0, width, height), tint)
        if not palette.dark:
            painter.fillRect(QRect(0, 0, width, height), QColor(255, 255, 255, 46))
        if extra_lightening > 0:
            layer = QColor("#FFFFFF" if not palette.dark else "#FFFFFF")
            layer.setAlphaF(extra_lightening)
            painter.fillRect(QRect(0, 0, width, height), layer)
        # Fluent windows carry a very subtle vertical light gradient.
        sheen = QLinearGradient(0, 0, 0, height)
        if palette.dark:
            sheen.setColorAt(0.0, QColor(255, 255, 255, 6))
            sheen.setColorAt(1.0, QColor(0, 0, 0, 0))
        else:
            sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillRect(QRect(0, 0, width, height), sheen)
        painter.end()

        if radius <= 0:
            return pixmap
        rounded = QPixmap(pixmap.size())
        rounded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path_rect = QRectF(0, 0, width, height)
        painter.setBrush(pixmap)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(path_rect, radius, radius)
        painter.end()
        return rounded

    def _cover_rect(self, image: QImage, target: QRect) -> QImage:
        """Scale the wallpaper the way Windows does for the current style."""
        style = winapi.wallpaper_style()
        src_w, src_h = image.width(), image.height()
        if src_w <= 0 or src_h <= 0:
            return image

        if style == 2:  # stretch
            return image.scaled(target.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        if style in (0, 1):  # centre / tile
            scale = 1.0
        elif style == 6:  # fit
            scale = min(target.width() / src_w, target.height() / src_h)
        else:  # 10 fill, 22 span
            scale = max(target.width() / src_w, target.height() / src_h)

        draw_w = max(1, int(round(src_w * scale)))
        draw_h = max(1, int(round(src_h * scale)))
        scaled = image.scaled(draw_w, draw_h, Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        canvas = QImage(target.size(), QImage.Format.Format_RGB32)
        canvas.fill(QColor(theme.palette.window_bg))
        painter = QPainter(canvas)
        offset_x = (target.width() - draw_w) // 2
        offset_y = (target.height() - draw_h) // 2
        painter.drawImage(offset_x, offset_y, scaled)
        painter.end()
        return canvas

    def _virtual_rect_physical(self) -> QRect:
        """Bounding box of every screen in *physical* pixels."""
        try:
            from PySide6.QtWidgets import QApplication

            union: QRect | None = None
            for screen in QApplication.screens():
                geometry = screen.geometry()
                ratio = screen.devicePixelRatio()
                rect = QRect(int(geometry.x() * ratio), int(geometry.y() * ratio),
                             max(1, int(geometry.width() * ratio)),
                             max(1, int(geometry.height() * ratio)))
                union = rect if union is None else union.united(rect)
            if union is not None and union.width() > 0:
                return union
        except Exception:
            pass
        return QRect(0, 0, 1920, 1080)


mica = MicaProvider()


# --------------------------------------------------------------------------- #
# Soft shadow renderer (Windows 11 style drop shadow for frameless windows)
# --------------------------------------------------------------------------- #
def render_shadow(size: QSize, radius: int, spread: int = 22, opacity: float = 0.28,
                  dark: bool | None = None) -> QPixmap:
    """A cached, blurred rounded-rectangle shadow."""
    width, height = max(1, size.width()), max(1, size.height())
    reduced = max(4, width // 12)
    reduced_h = max(4, height // 12)
    scaled = QImage(reduced, reduced_h, QImage.Format.Format_ARGB32_Premultiplied)
    scaled.fill(Qt.GlobalColor.transparent)
    painter = QPainter(scaled)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    alpha = int(max(0.0, min(1.0, opacity)) * 255)
    painter.setBrush(QColor(0, 0, 0, alpha))
    painter.setPen(Qt.PenStyle.NoPen)
    inset = spread / max(1, width) * reduced
    painter.drawRoundedRect(QRectF(inset, inset, reduced - 2 * inset, reduced_h - 2 * inset),
                            max(1.0, radius / 6.0), max(1.0, radius / 6.0))
    painter.end()
    return QPixmap.fromImage(scaled.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))


# --------------------------------------------------------------------------- #
# Stylesheet shared by flyouts, tooltips, scrollbars and line edits
# --------------------------------------------------------------------------- #
def application_stylesheet() -> str:
    p = theme.palette
    dark = p.dark
    hover = "rgba(255,255,255,0.08)" if dark else "rgba(0,0,0,0.05)"
    item_hover = "rgba(255,255,255,0.07)" if dark else "rgba(0,0,0,0.045)"
    scroll = rgba(p.text_secondary, 0.35).name(QColor.NameFormat.HexArgb)
    scroll_hover = rgba(p.text_secondary, 0.55).name(QColor.NameFormat.HexArgb)
    underline = rgba(p.text_secondary, 0.45).name(QColor.NameFormat.HexArgb)
    return f"""
    QToolTip {{
        background-color: {p.flyout_bg};
        color: {p.text_primary};
        border: 1px solid {p.flyout_border};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 12px;
    }}
    QScrollBar:vertical {{
        background: transparent; width: 12px; margin: 4px 2px 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {scroll};
        border-radius: 3px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {p.control_bg};
        border: 1px solid {p.control_border};
        border-bottom: 1px solid {underline};
        border-radius: 5px;
        padding: 5px 8px;
        color: {p.text_primary};
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QComboBox:on {{
        border-bottom: 2px solid {p.accent};
    }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {p.text_disabled}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 26px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: none;
        width: 0px;
        height: 0px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.flyout_bg};
        color: {p.text_primary};
        border: 1px solid {p.flyout_border};
        padding: 4px;
        outline: none;
        selection-background-color: {item_hover};
        selection-color: {p.text_primary};
    }}
    """


def qt_palette() -> QPalette:
    """The Qt palette matching the current Fluent theme.

    Without this, Qt keeps the palette of the Windows session: with the app set
    to dark on a light Windows, combo box popups drew dark text on a dark
    background and were completely unreadable.
    """
    p = theme.palette
    palette = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup
    palette.setColor(role.Window, QColor(p.window_bg))
    palette.setColor(role.WindowText, QColor(p.text_primary))
    palette.setColor(role.Base, QColor(p.flyout_bg))
    palette.setColor(role.AlternateBase, QColor(p.content_bg))
    palette.setColor(role.Text, QColor(p.text_primary))
    palette.setColor(role.Button, QColor(p.control_bg))
    palette.setColor(role.ButtonText, QColor(p.text_primary))
    palette.setColor(role.BrightText, QColor("#FFFFFF"))
    palette.setColor(role.ToolTipBase, QColor(p.flyout_bg))
    palette.setColor(role.ToolTipText, QColor(p.text_primary))
    palette.setColor(role.Highlight, QColor(p.accent))
    palette.setColor(role.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(role.Link, QColor(p.accent))
    for disabled_role in (role.Text, role.ButtonText, role.WindowText):
        palette.setColor(group.Disabled, disabled_role, QColor(p.text_disabled))
    return palette


def apply_app_theme(app) -> None:
    """Re-apply palette + stylesheet; call whenever the theme changes."""
    app.setPalette(qt_palette())
    app.setStyleSheet(application_stylesheet())


def contrast_text(color: QColor) -> QColor:
    """Black or white, whichever reads better on ``color``."""
    luminance = (0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()) / 255.0
    return QColor("#000000") if luminance > 0.6 else QColor("#FFFFFF")


def points_on_circle(centre: QPoint, radius: float, count: int) -> list[QPoint]:
    return [
        QPoint(int(centre.x() + radius * math.cos(2 * math.pi * i / count)),
               int(centre.y() + radius * math.sin(2 * math.pi * i / count)))
        for i in range(count)
    ]
