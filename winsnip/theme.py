"""Windows 11 / Fluent design tokens and the Mica backdrop renderer.

Colour values were sampled from the real Windows 11 Snipping Tool on build
26100 and then normalised, so the light and dark palettes below reproduce what
the shipped app looks like when its Mica backdrop is opaque.

Two interface styles are supported and they are orthogonal to light/dark:

* ``win11`` (default) - rounded corners, Mica backdrop, inset rounded caption
  button hover, soft large shadow, Segoe UI Variable.
* ``win10`` - square corners, opaque background (no wallpaper showing through),
  full-bleed square caption hover with the classic #E81123 close button, tighter
  shadow, Segoe UI, and a separator under the caption bar.

Style-dependent values are exposed as :class:`ThemeState` properties so widgets
read them at paint time and a switch takes effect without rebuilding windows.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QImage, QLinearGradient, QPainter, QPalette, QPixmap,
)

from . import winapi

# --------------------------------------------------------------------------- #
# Motion / metrics
# --------------------------------------------------------------------------- #
RADIUS_WINDOW = 8          # win11 defaults; widgets read theme.radius_* instead
RADIUS_CONTROL = 5
RADIUS_FLYOUT = 8
CAPTION_BUTTON_SIZE = QSize(46, 32)
COMMAND_BAR_HEIGHT = 56
CAPTION_BAR_HEIGHT = 40

# Windows 10 'Acrylic': a much stronger blur than Mica, plus the noise grain
# Microsoft overlays to stop large flat gradients from banding.
ACRYLIC_TINT = 0.62          # how much of the window colour sits on top
ACRYLIC_NOISE_ALPHA = 8      # per-pixel alpha of the grain tile (0-255)
ACRYLIC_NOISE_TILE = 96
ACRYLIC_DARKEN = 84          # extra darkening in the dark theme

# Windows 10 caption buttons are the same size but hover fills the whole button
# and the close button uses the older, more saturated red.
WIN10_CLOSE_HOVER = "#E81123"
WIN10_CLOSE_PRESSED = "#F1707A"

UI_FAMILIES = ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"]
UI_FAMILIES_WIN10 = ["Segoe UI", "Microsoft YaHei UI", "Segoe UI Variable"]

# Each writing system needs a family that actually carries its glyphs: kana in
# particular fall back badly if only a Simplified Chinese face is listed.
UI_FAMILIES_BY_LANGUAGE = {
    "zh-Hans": UI_FAMILIES,
    "zh-Hant": ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI",
                "Microsoft JhengHei UI", "Microsoft YaHei UI"],
    "ja": ["Yu Gothic UI", "Meiryo UI", "Segoe UI Variable Text", "Segoe UI",
           "Microsoft YaHei UI"],
    "en": ["Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI", "Microsoft YaHei UI"],
}

# style name -> radii / shadow / metrics
STYLE_TOKENS: dict[str, dict[str, float]] = {
    "win11": {
        "radius_window": RADIUS_WINDOW,
        "radius_control": RADIUS_CONTROL,
        "radius_flyout": RADIUS_FLYOUT,
        "radius_caption": 5,
        "shadow_opacity": 0.28,
        "shadow_spread_scale": 1.0,
        "caption_inset": 2,
    },
    "win10": {
        "radius_window": 0,          # Windows 10 windows are square
        "radius_control": 2,
        "radius_flyout": 4,
        "radius_caption": 0,
        "shadow_opacity": 0.40,      # tighter and darker, like Win10
        "shadow_spread_scale": 0.62,
        "caption_inset": 0,          # hover fills the whole button
    },
}


def current_font_families() -> list[str]:
    """Families for the active language and style."""
    try:
        from . import i18n

        families = UI_FAMILIES_BY_LANGUAGE.get(i18n.language())
    except Exception:
        families = None
    if families is None:
        families = UI_FAMILIES
    if theme.is_win10 and families is UI_FAMILIES:
        return UI_FAMILIES_WIN10
    return families


_FONT_CACHE: dict[tuple, QFont] = {}


def ui_font(size: int = 14, weight: int = 400) -> QFont:
    """A UI font, cached.

    This used to build a fresh QFont and re-resolve the family list on every call.
    The settings window alone calls setFont 69 times while building its rows, which
    measured at ~160ms of pure font construction on every open.
    """
    key = (theme.resolved_style, size, weight)
    cached = _FONT_CACHE.get(key)
    if cached is None:
        font = QFont()
        font.setFamilies(current_font_families())
        font.setPixelSize(size)
        font.setWeight(QFont.Weight(weight))
        _FONT_CACHE[key] = font
        cached = font
    # QFont is implicitly shared, but hand back a copy so a caller that mutates the
    # result cannot poison the cache.
    return QFont(cached)


def clear_font_cache() -> None:
    """Drop cached fonts (after a language or style change)."""
    _FONT_CACHE.clear()


def icon_font(size: int = 16) -> QFont:
    """An icon font, cached (see ui_font)."""
    key = ("icon", size)
    cached = _FONT_CACHE.get(key)
    if cached is None:
        font = QFont()
        font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
        font.setPixelSize(size)
        _FONT_CACHE[key] = font
        cached = font
    return QFont(cached)


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
    mode: str = "system"    # system | light | dark
    style: str = "win11"    # win11 | win10 | system
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

    # -- interface style ---------------------------------------------------- #
    @property
    def resolved_style(self) -> str:
        """'win11' or 'win10' after resolving 'system'."""
        if self.style == "system":
            return "win11" if winapi.is_windows_11() else "win10"
        return "win10" if self.style == "win10" else "win11"

    @property
    def is_win10(self) -> bool:
        return self.resolved_style == "win10"

    def _token(self, name: str) -> float:
        return STYLE_TOKENS[self.resolved_style][name]

    @property
    def radius_window(self) -> int:
        return int(self._token("radius_window"))

    @property
    def radius_control(self) -> int:
        return int(self._token("radius_control"))

    @property
    def radius_flyout(self) -> int:
        return int(self._token("radius_flyout"))

    @property
    def radius_caption(self) -> int:
        return int(self._token("radius_caption"))

    @property
    def caption_inset(self) -> int:
        return int(self._token("caption_inset"))

    @property
    def shadow_opacity(self) -> float:
        return float(self._token("shadow_opacity"))

    @property
    def shadow_spread(self) -> int:
        return int(self._token("shadow_spread_scale") * 22)

    @property
    def uses_mica(self) -> bool:
        """Windows 11 composites Mica; Windows 10 uses Acrylic instead."""
        return not self.is_win10

    @property
    def uses_acrylic(self) -> bool:
        """Windows 10's material: heavy Gaussian blur + grain + a stronger tint."""
        return self.is_win10

    @property
    def reveal_strength(self) -> float:
        """Reveal intensity multiplier from the settings (weak/normal/strong)."""
        try:
            from .settings import settings

            return {"weak": 0.55, "normal": 1.0, "strong": 1.65}.get(
                getattr(settings, "reveal_strength", "weak"), 0.55)
        except Exception:
            return 1.0

    @property
    def uses_reveal(self) -> bool:
        """Windows 10's 'Reveal' highlight: a soft light that follows the pointer.

        Reveal shipped with the Windows 10 Fall Creators Update, so it belongs to
        the win10 style only. It is disabled along with the other animations.
        """
        if not self.is_win10:
            return False
        try:
            from .settings import settings

            return bool(settings.animations)
        except Exception:
            return True

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
_ACRYLIC_NOISE: QPixmap | None = None


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

    # -- acrylic ------------------------------------------------------------ #
    @staticmethod
    def _gaussian_blur(image: QImage, width: int, height: int) -> QImage:
        """Approximate a Gaussian blur with chained smooth down/up scales.

        A real Gaussian over a 1920x1080 crop costs tens of milliseconds per
        window; three smooth resamples produce a visually equivalent soft blur
        and stay in the low single digits.
        """
        small = image.scaled(max(1, width // 10), max(1, height // 10),
                             Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        medium = small.scaled(max(2, width // 4), max(2, height // 4),
                              Qt.AspectRatioMode.IgnoreAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        return medium.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)

    @staticmethod
    def noise_tile() -> QPixmap:
        """The subtle grain Windows 10 overlays on Acrylic surfaces."""
        global _ACRYLIC_NOISE
        if _ACRYLIC_NOISE is not None:
            return _ACRYLIC_NOISE
        size = ACRYLIC_NOISE_TILE
        image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        # Built as raw bytes: per-pixel setPixelColor() in Python is ~50x slower.
        data = bytearray(size * size * 4)
        seed = 0x5F3A1C7
        for index in range(size * size):
            seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
            alpha = (seed >> 16) % (ACRYLIC_NOISE_ALPHA + 1)
            offset = index * 4
            # Premultiplied BGRA of white with the given alpha.
            data[offset] = alpha
            data[offset + 1] = alpha
            data[offset + 2] = alpha
            data[offset + 3] = alpha
        image = QImage(bytes(data), size, size, size * 4,
                       QImage.Format.Format_ARGB32_Premultiplied).copy()
        _ACRYLIC_NOISE = QPixmap.fromImage(image)
        return _ACRYLIC_NOISE

    def invalidate(self) -> None:
        self._source = None
        self._loaded_path = None
        self._failed = False
        self._base = None
        self._base_path = None

    def backdrop(self, physical_rect: QRect, radius: int = RADIUS_WINDOW,
                 dpr: float = 1.0, tint_strength: float = 0.86,
                 extra_lightening: float = 0.0, acrylic: bool = False) -> QPixmap:
        """Return a rounded, blurred, tinted backdrop sized to ``physical_rect``.

        ``acrylic=True`` produces the Windows 10 material: a much heavier
        Gaussian-style blur, the grain overlay, and a stronger tint so the
        desktop behind is felt rather than seen.
        """
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
        if acrylic:
            blurred = self._gaussian_blur(blurred, width, height)

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
            painter.fillRect(QRect(0, 0, width, height),
                             QColor(0, 0, 0, ACRYLIC_DARKEN if acrylic else 96))
        tint = QColor(palette.window_bg)
        tint.setAlphaF(ACRYLIC_TINT if acrylic else tint_strength)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.fillRect(QRect(0, 0, width, height), tint)
        if not palette.dark:
            painter.fillRect(QRect(0, 0, width, height),
                             QColor(255, 255, 255, 30 if acrylic else 46))
        if extra_lightening > 0:
            layer = QColor("#FFFFFF" if not palette.dark else "#FFFFFF")
            layer.setAlphaF(extra_lightening)
            painter.fillRect(QRect(0, 0, width, height), layer)
        if acrylic:
            # Acrylic's grain: without it a heavy blur bands badly on gradients.
            painter.fillRect(QRect(0, 0, width, height),
                             QBrush(self.noise_tile()))
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
    # 控件圆角必须跟着界面风格走（Win11: 控件 5 / 浮出 8；Win10: 2 / 4）。
    # 以前这里写死成 3/5/6/8，导致"设置"窗口在 Win10 风格下和 Win11 长得一模一样。
    r_control = theme.radius_control
    r_flyout = theme.radius_flyout
    return f"""
    QToolTip {{
        background-color: {p.flyout_bg};
        color: {p.text_primary};
        border: 1px solid {p.flyout_border};
        border-radius: {r_flyout}px;
        padding: 6px 10px;
        font-size: 12px;
    }}
    /* QMenu (the tray menu and the overlay's right-click menu) is a native popup:
       without an explicit rule Qt draws it from the system palette, which is a
       white menu inside a dark app. */
    QMenu {{
        background-color: {p.flyout_bg};
        color: {p.text_primary};
        border: 1px solid {p.flyout_border};
        border-radius: {r_flyout}px;
        padding: 6px;
    }}
    QMenu::item {{
        background: transparent;
        color: {p.text_primary};
        padding: 7px 30px 7px 16px;
        border-radius: {r_control}px;
        min-width: 120px;
    }}
    QMenu::item:selected {{
        background-color: {item_hover};
        color: {p.text_primary};
    }}
    QMenu::item:disabled {{ color: {p.text_disabled}; }}
    QMenu::separator {{
        height: 1px;
        background: {p.flyout_border};
        margin: 5px 10px;
    }}
    QMenu::icon {{ padding-left: 10px; }}
    QMenu::right-arrow {{ width: 12px; height: 12px; }}
    QScrollBar:vertical {{
        background: transparent; width: 12px; margin: 4px 2px 4px 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {scroll};
        border-radius: {r_control}px; min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {scroll_hover}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QLineEdit, QSpinBox, QComboBox {{
        background-color: {p.control_bg};
        border: 1px solid {p.control_border};
        border-bottom: 1px solid {underline};
        border-radius: {r_control}px;
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
