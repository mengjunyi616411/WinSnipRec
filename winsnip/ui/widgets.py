"""Reusable Fluent (Windows 11) widgets shared by every window in the app."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QPainter,
    QPainterPath, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from .. import anim, icons, winapi
from ..theme import (
    CAPTION_BUTTON_SIZE, WIN10_CLOSE_HOVER, WIN10_CLOSE_PRESSED, mica, render_shadow, rgba,
    theme, ui_font,
)

SHADOW_MARGIN = 20


def paint_reveal_on(widget, painter: QPainter, radius: float = 0.0,
                    strength: float = 0.55) -> None:
    """Paint the window's Reveal light clipped to ``widget``.

    Drawn in the widget's own coordinates so the light continues smoothly
    across buttons instead of stopping at their edges.
    """
    window = widget.window()
    getter = getattr(window, "reveal_centre_for", None)
    if getter is None:
        return
    found = getter(widget)
    if found is None:
        return
    centre, reveal = found
    clip = QRectF(widget.rect())
    extent = max(clip.width(), clip.height()) * 1.35
    if extent <= 1:
        return
    glow = QRadialGradient(centre, extent)
    if theme.dark:
        light = QColor("#FFFFFF")
        peak = 0.20 * reveal * strength
    else:
        light = QColor(theme.palette.accent)
        peak = 0.24 * reveal * strength
    glow.setColorAt(0.0, rgba(light, peak))
    glow.setColorAt(0.45, rgba(light, peak * 0.5))
    glow.setColorAt(1.0, rgba(light, 0.0))
    painter.save()
    if radius > 0:
        path = QPainterPath()
        path.addRoundedRect(clip, radius, radius)
        painter.setClipPath(path)
    else:
        painter.setClipRect(clip)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.fillRect(clip, glow)
    painter.restore()


def control_radius(widget) -> int:
    """Radius for buttons and other controls, honouring the active style."""
    override = getattr(widget, "_radius_override", None)
    return override if override is not None else theme.radius_control


def _mix(first: QColor, second: QColor, amount: float) -> QColor:
    """Blend two colours (amount 0 = first, 1 = second) for cross-fades."""
    amount = max(0.0, min(1.0, amount))
    return QColor(
        round(first.red() + (second.red() - first.red()) * amount),
        round(first.green() + (second.green() - first.green()) * amount),
        round(first.blue() + (second.blue() - first.blue()) * amount),
        round(first.alpha() + (second.alpha() - first.alpha()) * amount),
    )


# --------------------------------------------------------------------------- #
# Frameless Mica window
# --------------------------------------------------------------------------- #
class FluentWindow(QWidget):
    """A frameless window painted with a Mica backdrop, rounded corners and a
    soft drop shadow. Works identically on Windows 10 and 11."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        resizable: bool = False,
        radius: int | None = None,        # None = follow the active style
        shadow: bool = True,
        tint_strength: float = 0.90,
        margin: int = SHADOW_MARGIN,
        open_animation: str = "slide",        # slide | fade | none
        open_slide: int = 14,
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._radius = radius
        self._shadow = shadow
        self._tint_strength = tint_strength
        self._margin = margin
        self._resizable = resizable
        self._open_animation = open_animation
        self._open_slide = open_slide
        self._open_animation_running = False
        self._suppress_open_animation = False
        self._backdrop: QPixmap | None = None
        self._shadow_pixmap: QPixmap | None = None
        self._resize_edges: Qt.Edge | None = None
        self._normal_geometry: QRect | None = None
        self._maximized = False
        # Windows 10 'Reveal': a soft light that follows the pointer.
        self._pointer = QPointF(-1.0, -1.0)
        self._reveal = 0.0
        self._reveal_timer: QTimer | None = None
        self._reveal_anim: QVariantAnimation | None = None
        # While a show/hide animation is moving the window the Mica backdrop is
        # left alone: recomputing it every frame would stutter.
        self._freeze_backdrop = False
        self.setMouseTracking(True)

    @property
    def radius(self) -> int:
        """Corner radius in device-independent pixels (style-aware)."""
        return self._radius if self._radius is not None else theme.radius_window

    # -- geometry ---------------------------------------------------------- #
    def card_rect(self) -> QRect:
        m = self._margin
        return QRect(m, m, max(1, self.width() - 2 * m), max(1, self.height() - 2 * m))

    def set_card_size(self, width: int, height: int) -> None:
        self.resize(width + 2 * self._margin, height + 2 * self._margin)

    def card_size(self) -> QSize:
        return self.card_rect().size()

    def move_card_to(self, x: int, y: int) -> None:
        self.move(x - self._margin, y - self._margin)

    def card_global_rect(self) -> QRect:
        return QRect(self.mapToGlobal(self.card_rect().topLeft()), self.card_rect().size())

    # -- painting ---------------------------------------------------------- #
    def invalidate_backdrop(self) -> None:
        self._backdrop = None
        self._shadow_pixmap = None
        self.update()

    def _ensure_backdrop(self) -> None:
        if self._backdrop is not None or self._freeze_backdrop:
            return
        card = self.card_rect()
        handle = self.windowHandle()
        dpr = handle.devicePixelRatio() if handle else 1.0
        physical = QRect(
            int(card.x() * dpr), int(card.y() * dpr),
            max(1, int(card.width() * dpr)), max(1, int(card.height() * dpr)),
        )
        try:
            self._backdrop = mica.backdrop(physical, 0, dpr, self._tint_strength,
                                           acrylic=theme.uses_acrylic)
        except Exception:
            self._backdrop = None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            self._paint_card(painter)
        except Exception:
            import logging

            logging.exception("FluentWindow.paintEvent failed")
            try:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(theme.palette.window_bg))
                painter.drawRoundedRect(QRectF(self.card_rect()), self.radius, self.radius)
            except Exception:
                pass
        finally:
            if painter.isActive():
                painter.end()

    def _paint_card(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self.card_rect()

        if self._shadow:
            if self._shadow_pixmap is None or self._shadow_pixmap.size() != self.size():
                self._shadow_pixmap = render_shadow(self.size(), max(1, self.radius * 2),
                                                    spread=self._margin,
                                                    opacity=theme.shadow_opacity)
            painter.drawPixmap(0, 0, self._shadow_pixmap)

        self._ensure_backdrop()
        path_rect = QRectF(card)
        if self._backdrop is not None:
            from PySide6.QtGui import QPainterPath

            painter.save()
            rounded = QPainterPath()
            rounded.addRoundedRect(path_rect, self.radius, self.radius)
            painter.setClipPath(rounded)
            painter.drawPixmap(QRectF(card), self._backdrop, QRectF(self._backdrop.rect()))
            painter.restore()
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.palette.window_bg))
            painter.drawRoundedRect(path_rect, self.radius, self.radius)

        self.paint_reveal(painter, QRectF(card), float(self.radius))

        border = rgba("#000000" if not theme.dark else "#FFFFFF", 0.10 if not theme.dark else 0.09)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(border)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(card).adjusted(0.5, 0.5, -0.5, -0.5),
                                self.radius, self.radius)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.invalidate_backdrop()
        self._apply_native_rounding()
        self._start_open_animation()
        self._start_reveal_tracking()

    def _start_open_animation(self) -> None:
        """Every window fades (and usually slides) in when it is opened."""
        if self._open_animation == "none" or self._open_animation_running:
            return
        if self._suppress_open_animation:
            return
        if not anim.animations_enabled():
            self.setWindowOpacity(1.0)
            return
        # Setting the opacity synchronously matters: deferring it to the next
        # tick would let one frame paint at full opacity and flash.
        self._open_animation_running = True
        self.setWindowOpacity(0.0)
        QTimer.singleShot(0, self._run_open_animation)

    def _run_open_animation(self) -> None:
        self._open_animation_running = False
        if not self.isVisible() or not anim.animations_enabled():
            self.setWindowOpacity(1.0)
            return
        anim.play_window_open(
            self,
            slide=self._open_slide,
            fade_only=self._open_animation == "fade",
        )

    # -- Reveal (Windows 10 pointer light) ---------------------------------- #
    def _start_reveal_tracking(self) -> None:
        if not theme.uses_reveal:
            return
        if self._reveal_timer is None:
            timer = QTimer(self)
            timer.setInterval(33)          # ~30 Hz is plenty for a soft light
            timer.timeout.connect(self._track_pointer)
            self._reveal_timer = timer
        self._reveal_timer.start()

    def _stop_reveal_tracking(self) -> None:
        if self._reveal_timer is not None:
            self._reveal_timer.stop()

    def _track_pointer(self) -> None:
        """Poll the cursor: child widgets swallow mouseMoveEvent."""
        if not theme.uses_reveal:
            return
        local = self.mapFromGlobal(QCursor.pos())
        inside = self.rect().contains(local)
        moved = (QPointF(local) - self._pointer).manhattanLength() >= 3.0
        if inside:
            self._pointer = QPointF(local)
        target = 1.0 if inside else 0.0
        if abs(self._reveal - target) > 0.02:
            self._animate_reveal(target)
        if inside and moved:
            self.update()

    def _animate_reveal(self, target: float) -> None:
        if self._reveal_anim is not None:
            self._reveal_anim.stop()
        animation = QVariantAnimation(self)
        animation.setDuration(anim.DURATION_NORMAL)
        animation.setStartValue(self._reveal)
        animation.setEndValue(target)
        animation.setEasingCurve(anim.curve("out"))
        animation.valueChanged.connect(self._on_reveal_tick)
        self._reveal_anim = animation
        animation.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

    def _on_reveal_tick(self, value) -> None:
        self._reveal = float(value)
        self.update()

    def reveal_centre_for(self, widget) -> tuple[QPointF, float] | None:
        """Pointer position in ``widget``'s coordinates, or None when off.

        Child controls paint after the window, so they have to draw the
        Reveal light themselves or it would stop at their edges.
        """
        if not theme.uses_reveal or self._reveal <= 0.02 or self._pointer.x() < 0:
            return None
        local = widget.mapFrom(self, QPoint(int(self._pointer.x()),
                                            int(self._pointer.y())))
        return QPointF(local), self._reveal

    def paint_reveal(self, painter: QPainter, clip: QRectF, radius: float = 0.0,
                     strength: float = 1.0) -> None:
        """Paint the Reveal light into ``clip`` (window or a single control)."""
        if not theme.uses_reveal or self._reveal <= 0.02 or self._pointer.x() < 0:
            return
        # Tight enough to read as a light rather than a wash over the surface.
        extent = max(clip.width(), clip.height()) * 0.34
        if extent <= 1:
            return
        glow = QRadialGradient(self._pointer, extent)
        # On a near-white surface a white light is invisible (a few levels at
        # most), so the light theme lights with the accent colour the way a
        # coloured spotlight reads on paper; the dark theme glows white.
        if theme.dark:
            light = QColor("#FFFFFF")
            peak = 0.26 * self._reveal * strength
        else:
            light = QColor(theme.palette.accent)
            peak = 0.32 * self._reveal * strength
        glow.setColorAt(0.0, rgba(light, peak))
        glow.setColorAt(0.30, rgba(light, peak * 0.55))
        glow.setColorAt(0.65, rgba(light, peak * 0.14))
        glow.setColorAt(1.0, rgba(light, 0.0))
        painter.save()
        if radius > 0:
            path = QPainterPath()
            path.addRoundedRect(clip, radius, radius)
            painter.setClipPath(path)
        else:
            painter.setClipRect(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(clip, glow)
        painter.restore()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._stop_reveal_tracking()
        super().hideEvent(event)

    def _apply_native_rounding(self) -> None:
        try:
            handle = self.windowHandle()
            if handle is not None and theme.radius_window > 0 and winapi.is_windows_11():
                winapi.set_rounded_corners(int(handle.winId()), 2)
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.invalidate_backdrop()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._backdrop = None
        self.update()

    def changeEvent(self, event) -> None:  # noqa: N802
        if event.type() == QEvent.Type.ActivationChange:
            self.invalidate_backdrop()
        super().changeEvent(event)

    # -- resizing ---------------------------------------------------------- #
    def _edge_at(self, pos: QPoint) -> Qt.Edge | None:
        if not self._resizable or self._maximized:
            return None
        m = self._margin
        band = m + 4
        edges = Qt.Edge(0)
        if pos.x() <= band:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - band:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= band:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - band:
            edges |= Qt.Edge.BottomEdge
        return edges if edges else None

    def _cursor_for(self, edges: Qt.Edge | None) -> Qt.CursorShape:
        if edges is None:
            return Qt.CursorShape.ArrowCursor
        left = bool(edges & Qt.Edge.LeftEdge)
        right = bool(edges & Qt.Edge.RightEdge)
        top = bool(edges & Qt.Edge.TopEdge)
        bottom = bool(edges & Qt.Edge.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.CursorShape.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.CursorShape.SizeBDiagCursor
        if left or right:
            return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.setCursor(QCursor(self._cursor_for(self._edge_at(event.position().toPoint()))))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        edges = self._edge_at(event.position().toPoint())
        if edges is not None and event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemResize(edges)
                return
        super().mousePressEvent(event)

    # -- maximise / restore ------------------------------------------------ #
    def is_maximized(self) -> bool:
        return self._maximized

    def toggle_maximized(self) -> None:
        if not self._resizable:
            return
        from PySide6.QtGui import QGuiApplication

        if self._maximized:
            if self._normal_geometry is not None:
                self.setGeometry(self._normal_geometry)
            self._maximized = False
        else:
            self._normal_geometry = self.geometry()
            screen = self.screen() or QGuiApplication.primaryScreen()
            available = screen.availableGeometry().adjusted(0, 0, 0, 0)
            available = available.adjusted(self._margin, self._margin, -self._margin, -self._margin)
            self.setGeometry(available)
            self._maximized = True
        self.invalidate_backdrop()


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #
class FluentButton(QPushButton):
    """Standard / accent / subtle / hyperlink button in the Fluent style."""

    def __init__(
        self,
        text: str = "",
        parent: QWidget | None = None,
        *,
        variant: str = "standard",
        icon_name: str | None = None,
        icon_size: int = 16,
        height: int = 36,
        radius: int | None = None,
        accent_icon: bool = False,
        font_size: int = 14,
        font_weight: int = 400,
    ) -> None:
        super().__init__(text, parent)
        self.variant = variant
        self.icon_name = icon_name
        self.icon_size = icon_size
        self._radius_override = radius
        self.accent_icon = accent_icon
        self._hover = False
        self._pressed = False
        self.setFixedHeight(height)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFont(ui_font(font_size, font_weight))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.text())
        width = text_width
        if self.icon_name:
            width += self.icon_size + (8 if text_width else 0)
        padding = 12 if self.variant != "hyperlink" else 4
        return QSize(width + padding * 2, self.height())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()

        bg = None
        border = None
        if self.variant == "accent":
            bg = QColor(palette.accent)
            if self._pressed and enabled:
                bg = bg.darker(115)
            elif self._hover and enabled:
                bg = bg.lighter(112)
        elif self.variant == "standard":
            bg = QColor(palette.control_bg)
            border = QColor(palette.control_border)
            if self._pressed and enabled:
                bg = QColor(palette.control_bg_pressed)
            elif self._hover and enabled:
                bg = QColor(palette.control_bg_hover)
        elif self.variant == "subtle":
            if self._pressed and enabled:
                bg = rgba("#000000" if not palette.dark else "#FFFFFF", 0.06)
            elif self._hover and enabled:
                bg = rgba("#000000" if not palette.dark else "#FFFFFF", 0.04)
        elif self.variant == "hyperlink":
            bg = None
        if not enabled:
            if self.variant == "accent":
                bg = rgba(palette.accent, 0.35)
            elif self.variant == "standard":
                bg = rgba(palette.control_bg, 0.5)

        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, control_radius(self), control_radius(self))
        paint_reveal_on(self, painter, float(control_radius(self)))
        if border is not None:
            pen = painter.pen()
            pen.setWidthF(1.0)
            pen.setColor(border if enabled else rgba(border, 0.5))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, control_radius(self), control_radius(self))

        # content
        if self.variant == "accent":
            text_color = QColor("#FFFFFF") if enabled else rgba("#FFFFFF", 0.6)
            icon_color = QColor("#FFFFFF") if enabled else rgba("#FFFFFF", 0.6)
        elif self.variant == "hyperlink":
            text_color = QColor(palette.accent) if enabled else QColor(palette.text_disabled)
            icon_color = text_color
        else:
            text_color = QColor(palette.text_primary) if enabled else QColor(palette.text_disabled)
            icon_color = QColor(palette.accent) if (self.accent_icon and enabled) else text_color

        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.text())
        content_width = text_width + (self.icon_size + 8 if self.icon_name and text_width else
                                      (self.icon_size if self.icon_name else 0))
        x = (self.width() - content_width) / 2.0
        if self.icon_name:
            icon_rect = QRectF(x, (self.height() - self.icon_size) / 2.0, self.icon_size, self.icon_size)
            icons.paint_icon(painter, self.icon_name, icon_rect, icon_color)
            x += self.icon_size + (8 if text_width else 0)
        if self.text():
            painter.setPen(text_color)
            painter.setFont(self.font())
            painter.drawText(QRectF(x, 0, text_width + 2, self.height()),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             self.text())
        painter.end()


class IconButton(QPushButton):
    """Square icon-only button with a rounded hover highlight."""

    def __init__(
        self,
        icon_name: str,
        parent: QWidget | None = None,
        *,
        size: int = 20,
        width: int = 40,
        height: int = 36,
        radius: int | None = None,
        tooltip: str = "",
        color: QColor | str | None = None,
        checkable: bool = False,
        with_chevron: bool = False,
    ) -> None:
        super().__init__(parent)
        self.icon_name = icon_name
        self.icon_size = size
        self._radius_override = radius
        self.chevron = with_chevron
        self._hover = False
        self._pressed = False
        self._checked = False
        self._custom_color = QColor(color) if color is not None else None
        self.setFixedSize(width, height)
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        if tooltip:
            self.setToolTip(tooltip)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        if checkable:
            self.toggled.connect(self._on_toggled)

    def _on_toggled(self, value: bool) -> None:
        self._checked = value
        self.update()

    def set_icon_name(self, name: str) -> None:
        self.icon_name = name
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        enabled = self.isEnabled()

        bg = None
        if self._checked:
            bg = rgba("#000000" if not palette.dark else "#FFFFFF", 0.06)
        if self._pressed and enabled:
            bg = rgba("#000000" if not palette.dark else "#FFFFFF", 0.08)
        elif self._hover and enabled and bg is None:
            bg = rgba("#000000" if not palette.dark else "#FFFFFF", 0.045)
        if bg is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, control_radius(self), control_radius(self))
        paint_reveal_on(self, painter, float(control_radius(self)))

        color = self._custom_color or QColor(
            palette.icon_primary if enabled else palette.text_disabled
        )
        if not enabled:
            color = QColor(palette.text_disabled)
        icon_w = self.icon_size + (12 if self.chevron else 0)
        x = (self.width() - icon_w) / 2.0
        icons.paint_icon(
            painter, self.icon_name,
            QRectF(x, (self.height() - self.icon_size) / 2.0, self.icon_size, self.icon_size),
            color,
        )
        if self.chevron:
            chevron = QColor(palette.icon_secondary)
            if not enabled:
                chevron = QColor(palette.text_disabled)
            icons.paint_icon(
                painter, "chevron_down",
                QRectF(x + self.icon_size + 1, (self.height() - 12) / 2.0 + 1, 12, 12),
                chevron,
            )
        painter.end()


class CaptionButton(QPushButton):
    """Minimise / maximise / close button sized like the Windows caption buttons."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self._hover = False
        self._pressed = False
        self.setFixedSize(CAPTION_BUTTON_SIZE)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setToolTip({"min": "最小化", "max": "最大化", "restore": "还原", "close": "关闭"}[kind])

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        is_close = self.kind == "close"
        # win10: the hover fills the whole button and corners are square;
        # win11: an inset rounded wash, and a softer red for the close button.
        inset = theme.caption_inset
        radius = theme.radius_caption
        if self._hover or self._pressed:
            if is_close:
                if theme.is_win10:
                    color = QColor(WIN10_CLOSE_PRESSED if self._pressed else WIN10_CLOSE_HOVER)
                else:
                    color = QColor("#B02419" if self._pressed else "#C42B1C")
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
                                        radius, radius)
                glyph = QColor("#FFFFFF")
            else:
                alpha = 0.075 if self._pressed else 0.05
                if theme.is_win10:
                    alpha = 0.14 if self._pressed else 0.10
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", alpha))
                painter.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
                                        radius, radius)
                glyph = QColor(palette.icon_primary)
        else:
            glyph = QColor(palette.icon_primary)
        name = {"min": "minimize", "max": "maximize", "restore": "restore", "close": "close"}[self.kind]
        size = 16
        icons.paint_icon(painter, name,
                         QRectF((self.width() - size) / 2.0, (self.height() - size) / 2.0, size, size),
                         glyph)
        painter.end()


class SegmentedControl(QWidget):
    """The camera / video mode switch from the Snipping Tool command bar.

    Switching animates like the real control: the accent underline slides to the
    new segment while the selection pill and the icon colours cross-fade.
    """

    currentChanged = Signal(int)
    itemClicked = Signal(int)

    def __init__(self, items: list[tuple[str, str]], parent: QWidget | None = None,
                 *, item_width: int = 54, height: int = 36) -> None:
        super().__init__(parent)
        self._items = items
        self._item_width = item_width
        self._current = 0
        self._hover = -1
        # Indicator animation state: cross-fade from *_from* to *_to*.
        self._from_index = 0
        self._to_index = 0
        self._progress = 1.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(anim.DURATION_NORMAL)
        self._anim.setEasingCurve(anim.curve("decelerate"))
        self._anim.valueChanged.connect(self._on_progress)
        self.setFixedSize(item_width * len(items), height)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        for index, (_, tooltip) in enumerate(items):
            if tooltip:
                self.setToolTip(tooltip)

    def current(self) -> int:
        return self._current

    def set_current(self, index: int, *, emit: bool = True, animate: bool = True) -> None:
        index = max(0, min(len(self._items) - 1, index))
        if index == self._current:
            return
        previous = self._current
        self._current = index
        self._start_indicator(previous, index, animate)
        self.update()
        if emit:
            self.currentChanged.emit(index)

    # -- indicator animation ------------------------------------------------ #
    def _start_indicator(self, previous: int, index: int, animate: bool) -> None:
        if (not animate or not anim.animations_enabled() or not self.isVisible()
                or previous == index):
            self._anim.stop()
            self._from_index = self._to_index = index
            self._progress = 1.0
            return
        self._from_index = previous
        self._to_index = index
        self._progress = 0.0
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _on_progress(self, value) -> None:
        self._progress = float(value)
        self.update()

    def indicator_position(self) -> float:
        """Continuous indicator position in item units (for tests)."""
        return self._from_index + (self._to_index - self._from_index) * self._progress

    def _index_at(self, x: int) -> int:
        return max(0, min(len(self._items) - 1, x // self._item_width))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        index = self._index_at(int(event.position().x()))
        if index != self._hover:
            self._hover = index
            self.setToolTip(self._items[index][1])
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._index_at(int(event.position().x()))
            self.itemClicked.emit(index)
            self.set_current(index)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.toggle_track))
        painter.drawRoundedRect(QRectF(self.rect()), theme.radius_control, theme.radius_control)

        base = QColor(palette.icon_secondary)
        active = QColor(palette.icon_primary)
        fill = QColor(palette.toggle_selected)
        progress = self._progress
        settled = self._from_index == self._to_index

        for index, (icon_name, _) in enumerate(self._items):
            x = index * self._item_width
            item_rect = QRectF(x + 1, 1, self._item_width - 2, self.height() - 2)
            if settled:
                selectedness = 1.0 if index == self._to_index else 0.0
            elif index == self._from_index:
                selectedness = 1.0 - progress
            elif index == self._to_index:
                selectedness = progress
            else:
                selectedness = 0.0

            if selectedness > 0.01:
                colour = QColor(fill)
                colour.setAlphaF(colour.alphaF() * selectedness)
                painter.setBrush(colour)
                painter.drawRoundedRect(item_rect, theme.radius_control - 1, theme.radius_control - 1)
            elif index == self._hover:
                painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", 0.04))
                painter.drawRoundedRect(item_rect, theme.radius_control - 1, theme.radius_control - 1)

            icon_colour = _mix(base, active, selectedness)
            size = 20
            icon_x = x + (self._item_width - size) / 2.0
            icons.paint_icon(painter, icon_name,
                             QRectF(icon_x, (self.height() - size) / 2.0 - 1, size, size),
                             icon_colour)

        # The accent underline slides continuously between segments.
        bar_w = 20
        centre = (self.indicator_position() + 0.5) * self._item_width
        bar = QRectF(centre - bar_w / 2.0, self.height() - 4.0, bar_w, 3.0)
        painter.setBrush(QColor(palette.accent))
        painter.drawRoundedRect(bar, 1.5, 1.5)
        painter.end()


class Separator(QFrame):
    def __init__(self, parent: QWidget | None = None, *, height: int = 22, vertical: bool = True) -> None:
        super().__init__(parent)
        self._vertical = vertical
        if vertical:
            self.setFixedWidth(1)
            self.setFixedHeight(height)
        else:
            self.setFixedHeight(1)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.palette.separator))
        painter.end()


class ToggleSwitch(QWidget):
    """Fluent toggle switch used by the settings flyout."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(40, 20)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool) -> None:  # noqa: N802
        value = bool(value)
        if value != self._checked:
            self._checked = value
            self.update()
            self.toggled.emit(value)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        track = QRectF(0, 2, self.width(), self.height() - 4)
        if self._checked:
            painter.setBrush(QColor(palette.accent))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
            knob_color = QColor("#FFFFFF")
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = painter.pen()
            pen.setWidthF(1.4)
            pen.setColor(QColor(palette.text_secondary))
            painter.setPen(pen)
            painter.drawRoundedRect(track.adjusted(0.7, 0.7, -0.7, -0.7), track.height() / 2,
                                    track.height() / 2)
            knob_color = QColor(palette.text_secondary)
        radius = 5.0 if self._checked else 4.0
        cx = self.width() - 8 if self._checked else 8
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(cx - radius, self.height() / 2 - radius, radius * 2, radius * 2))
        painter.end()


class FluentComboBox(QComboBox):
    """QComboBox with a Fluent chevron and a properly themed popup.

    A QComboBox popup lives in a private ``QComboBoxPrivateContainer`` window
    that selectors such as ``QComboBox QAbstractItemView`` do not reliably
    reach: with a dark app theme the list drew light text on the unstyled white
    container and was effectively invisible.  The popup is therefore styled
    directly on the view and on its container every time it is shown.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFont(ui_font(13))
        self.setMinimumHeight(32)

    # ------------------------------------------------------------------ #
    def _popup_stylesheet(self) -> str:
        p = theme.palette
        item_hover = "rgba(255,255,255,0.07)" if p.dark else "rgba(0,0,0,0.045)"
        return f"""
        QListView {{
            background-color: {p.flyout_bg};
            color: {p.text_primary};
            border: none;
            padding: 4px;
            outline: none;
        }}
        QListView::item {{
            min-height: 26px;
            padding: 3px 8px;
            border-radius: 4px;
            color: {p.text_primary};
        }}
        QListView::item:selected, QListView::item:hover {{
            background-color: {item_hover};
            color: {p.text_primary};
        }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{
            background: {rgba(p.text_secondary, 0.4).name(QColor.NameFormat.HexArgb)};
            border-radius: 2px; min-height: 20px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        """

    def _style_popup(self) -> None:
        palette = theme.palette
        view = self.view()
        if view is None:
            return
        view.setStyleSheet(self._popup_stylesheet())
        container = view.window()
        if container is not None and container is not self:
            container.setStyleSheet(
                f"QFrame {{ background-color: {palette.flyout_bg};"
                f" border: 1px solid {palette.flyout_border}; border-radius: 6px; }}"
            )
            container.setContentsMargins(0, 0, 0, 0)

    # ------------------------------------------------------------------ #
    def showPopup(self) -> None:  # noqa: N802
        self._style_popup()
        super().showPopup()

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(theme.palette.text_secondary if self.isEnabled()
                       else theme.palette.text_disabled)
        size = 12
        icons.paint_icon(
            painter, "chevron_down",
            QRectF(self.width() - size - 10, (self.height() - size) / 2.0, size, size), color,
        )
        painter.end()


class PopupMenuItem(QWidget):
    """One row of a :class:`FluentMenu`."""

    def __init__(self, label: str, parent: QWidget | None = None, *, icon_name: str | None = None,
                 checked: bool = False, enabled: bool = True, indent: int = 0,
                 on_activate=None, height: int = 34) -> None:
        super().__init__(parent)
        self.label = label
        self.icon_name = icon_name
        self.checked = checked
        self.indent = indent
        self._enabled = enabled
        self._on_activate = on_activate
        self._hover = False
        self._pressed = False
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802
        self._enabled = bool(enabled)
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def isEnabled(self) -> bool:  # noqa: N802
        return self._enabled

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(ui_font(14))
        width = 24 + self.indent
        if self.icon_name:
            width += 26
        width += metrics.horizontalAdvance(self.label) + 40
        return QSize(width, self.height())

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._enabled and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was = self._pressed
        self._pressed = False
        self.update()
        if was and self._enabled and self.rect().contains(event.position().toPoint()):
            if self._on_activate is not None:
                self._on_activate()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        if self._enabled and (self._hover or self._pressed):
            alpha = 0.075 if self._pressed else 0.05
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", alpha))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 1, -4, -1), 5, 5)

        x = 12 + self.indent
        color = QColor(palette.text_primary if self._enabled else palette.text_disabled)
        if self.icon_name:
            icons.paint_icon(
                painter, self.icon_name,
                QRectF(x, (self.height() - 16) / 2.0, 16, 16),
                color if self._enabled else QColor(palette.text_disabled),
            )
            x += 26
        painter.setPen(color)
        painter.setFont(ui_font(14))
        painter.drawText(
            QRectF(x, 0, self.width() - x - 34, self.height()),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.label,
        )
        if self.checked:
            icons.paint_icon(painter, "check",
                             QRectF(self.width() - 26, (self.height() - 16) / 2.0, 16, 16),
                             QColor(palette.accent))
        painter.end()


class FluentMenu(FluentWindow):
    """A rounded Fluent flyout menu (replaces QMenu for in-app menus).

    Menus are shown non-modally, so the caller usually holds the only Python
    reference.  ``_open`` keeps a strong reference from the moment the menu is
    shown until it closes -- without it CPython would garbage-collect the menu
    (it has no Qt parent) and it would vanish before the user saw it.
    """

    _open: set["FluentMenu"] = set()

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 200) -> None:
        super().__init__(None, tint_strength=0.93, margin=14, open_slide=8)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._min_width = min_width
        self._items: list[QWidget] = []
        self._layout = QVBoxLayout(self)
        margin = self._margin
        self._layout.setContentsMargins(margin + 4, margin + 4, margin + 4, margin + 4)
        self._layout.setSpacing(1)

    # ------------------------------------------------------------------ #
    def add_item(self, label: str, *, icon_name: str | None = None, checked: bool = False,
                 enabled: bool = True, indent: int = 0, on_activate=None) -> PopupMenuItem:
        def run() -> None:
            try:
                if on_activate is not None:
                    on_activate()
            finally:
                # A Qt.Popup only closes itself on an outside click, so choosing
                # an entry has to dismiss the menu explicitly.
                self.close()

        item = PopupMenuItem(label, self, icon_name=icon_name, checked=checked, enabled=enabled,
                             indent=indent, on_activate=run)
        self._layout.addWidget(item)
        self._items.append(item)
        return item

    def add_header(self, text: str) -> QLabel:
        label = QLabel(text, self)
        label.setFont(ui_font(12))
        label.setContentsMargins(14, 10, 14, 2)
        self._layout.addWidget(label)
        self._items.append(label)
        self._headers = getattr(self, "_headers", [])
        self._headers.append(label)
        return label

    def add_separator(self) -> None:
        line = Separator(self, vertical=False)
        line.setFixedHeight(1)
        holder = QWidget(self)
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(12, 5, 12, 5)
        holder_layout.addWidget(line)
        self._layout.addWidget(holder)
        self._items.append(holder)

    # ------------------------------------------------------------------ #
    def finalize(self) -> None:
        self._layout.activate()
        width = self._min_width
        for widget in self._items:
            width = max(width, widget.sizeHint().width() + 2 * self._margin + 12)
        height = sum(widget.sizeHint().height() for widget in self._items) \
            + self._layout.spacing() * max(0, len(self._items) - 1) \
            + 2 * self._margin + 8
        for label in getattr(self, "_headers", []):
            label.setStyleSheet(f"color: {theme.palette.text_secondary};")
        self.set_card_size(int(width), int(height))

    def popup(self, global_pos: QPoint) -> None:  # noqa: N802
        self.finalize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x, y = global_pos.x(), global_pos.y()
        width, height = self.width(), self.height()
        if x + width > available.right():
            x = max(available.left(), available.right() - width)
        if y + height > available.bottom():
            y = max(available.top(), global_pos.y() - height)
        self.move_card_to(x, y)
        FluentMenu._open.add(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def exec_at(self, global_pos: QPoint) -> None:  # noqa: N802
        """Show the menu and wait until it closes (replaces QMenu.exec)."""
        from PySide6.QtCore import QEventLoop

        loop = QEventLoop()
        self.destroyed.connect(loop.quit)
        self.popup(global_pos)
        loop.exec()

    def closeEvent(self, event) -> None:  # noqa: N802
        FluentMenu._open.discard(self)
        super().closeEvent(event)


# --------------------------------------------------------------------------- #
# Title bar
# --------------------------------------------------------------------------- #
class TitleBar(QWidget):
    """Draggable caption bar with the app icon, title and caption buttons."""

    def __init__(self, title: str, parent: QWidget | None = None, *,
                 show_caption_buttons: bool = True, height: int = 44) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(8)

        self.icon_label = QLabel(self)
        self.icon_label.setFixedSize(16, 16)
        self.icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.icon_label)

        self.title_label = QLabel(title, self)
        self.title_label.setFont(ui_font(12))
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.title_label)
        layout.addStretch(1)

        self.caption_buttons: dict[str, CaptionButton] = {}
        if show_caption_buttons:
            for kind in ("min", "max", "close"):
                button = CaptionButton(kind, self)
                self.caption_buttons[kind] = button
                layout.addWidget(button)
            layout.addSpacing(4)
        self.refresh()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        # Windows 10 draws a clear line between the caption bar and the content;
        # Windows 11 merges the two, so this only appears in the win10 style.
        if theme.is_win10:
            painter = QPainter(self)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba("#000000" if not theme.dark else "#FFFFFF",
                                  0.10 if not theme.dark else 0.08))
            painter.drawRect(0, self.height() - 1, self.width(), 1)
            painter.end()

    def refresh(self) -> None:
        palette = theme.palette
        self.title_label.setStyleSheet(f"color: {palette.text_primary};")
        self.title_label.setFont(ui_font(12))

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and not getattr(self.window(), "is_maximized", lambda: False)():
                handle.startSystemMove()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        window = self.window()
        if hasattr(window, "toggle_maximized"):
            window.toggle_maximized()


class ClickableWidget(QWidget):
    """A widget that behaves like a button (used for list rows and cards)."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None, *, radius: int | None = None) -> None:
        super().__init__(parent)
        self._radius_override = radius
        self._hover = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pressed and event.button() == Qt.MouseButton.LeftButton:
            self._pressed = False
            self.update()
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not (self._hover or self._pressed):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        alpha = 0.06 if self._pressed else 0.04
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", alpha))
        painter.drawRoundedRect(QRectF(self.rect()), control_radius(self), control_radius(self))
        paint_reveal_on(self, painter, float(control_radius(self)))
        painter.end()


# --------------------------------------------------------------------------- #
# Toast notification
# --------------------------------------------------------------------------- #
class Toast(FluentWindow):
    """Bottom-right Fluent notification that dismisses itself."""

    _active: list["Toast"] = []

    def __init__(self, title: str, message: str = "", icon_name: str = "check",
                 *, duration: int = 3200, on_click: Callable[[], None] | None = None) -> None:
        super().__init__(None, tint_strength=0.90, margin=16, open_slide=22)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._on_click = on_click
        self.setFixedSize(360 + 32, 76 + 32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(self._margin + 14, self._margin + 14,
                                  self._margin + 14, self._margin + 12)
        layout.setSpacing(12)
        self._icon_holder = QWidget(self)
        self._icon_holder.setFixedSize(24, 24)
        self._icon_name = icon_name
        layout.addWidget(self._icon_holder, 0, Qt.AlignmentFlag.AlignTop)
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self._title = QLabel(title)
        self._title.setFont(ui_font(14, 600))
        self._message = QLabel(message)
        self._message.setFont(ui_font(12))
        self._message.setWordWrap(True)
        text_layout.addWidget(self._title)
        text_layout.addWidget(self._message)
        layout.addLayout(text_layout, 1)

        from PySide6.QtCore import QTimer

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)
        self._timer.start(duration)
        self.refresh()

    def refresh(self) -> None:
        palette = theme.palette
        self._title.setStyleSheet(f"color: {palette.text_primary};")
        self._message.setStyleSheet(f"color: {palette.text_secondary};")
        self._icon_holder.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self.card_rect()
        accent = QColor(theme.palette.accent)
        icons.paint_icon(painter, self._icon_name,
                         QRectF(card.left() + 14, card.top() + 14, 24, 24), accent)
        painter.end()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        Toast._active = [t for t in Toast._active if t.isVisible()]
        index = len(Toast._active)
        Toast._active.append(self)
        x = available.right() - self.width() - 16 + self._margin
        y = available.bottom() - self.height() - 16 + self._margin - index * (self.height() + 8)
        self.move(x - self._margin, y - self._margin)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._on_click is not None:
            self._on_click()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self in Toast._active:
            Toast._active.remove(self)
        super().closeEvent(event)


def show_toast(title: str, message: str = "", icon_name: str = "check", **kwargs) -> None:
    toast = Toast(title, message, icon_name, **kwargs)
    toast.show()
