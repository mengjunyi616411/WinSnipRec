"""Reusable Fluent (Windows 11) widgets shared by every window in the app."""

from __future__ import annotations

import time

from collections.abc import Callable

import logging

from PySide6.QtCore import (
    QEvent, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRect,
    QRectF, QSize, Qt, QTimer, QVariantAnimation, Signal,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QIcon, QImage,
    QPainter, QPainterPath, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QApplication,
    QComboBox, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy,
    QStyle, QStyledItemDelegate, QVBoxLayout, QWidget,
)

from .. import anim, icons, winapi
from ..settings import settings
from ..theme import (
    CAPTION_BUTTON_SIZE, WIN10_CLOSE_HOVER, WIN10_CLOSE_PRESSED, mica, render_shadow, rgba,
    theme, ui_font,
)
from ..i18n import t as _t

#: Transparent band around the card, kept for a drop shadow. Zero: the shadow
#: rendered at ~8 % alpha, while the band turned into a black frame in every
#: window capture (transparent pixels composite onto black). Each window's root
#: layout still insets its content by 20px, so nothing else changes.
SHADOW_MARGIN = 0


def paint_reveal_border(widget, painter: QPainter, radius: float) -> None:
    """Windows 10 Reveal also lights the edge of the control under the pointer."""
    if not theme.is_win10:
        return
    colour = rgba("#FFFFFF" if theme.dark else "#000000",
                  0.13 if theme.dark else 0.16)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    pen = painter.pen()
    pen.setWidthF(1.0)
    pen.setColor(colour)
    painter.setPen(pen)
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def _native_backdrop_wanted() -> bool:
    """Ask the backdrop module; any failure means "use the classic material"."""
    try:
        from .. import backdrop

        return backdrop.wanted()
    except Exception:
        return False


def _native_tint(colour, strength: float, dark: bool) -> int:
    """Pack the card tint as the 0xAABBGGRR the accent API expects."""
    value = QColor(colour)
    alpha = int(max(0, min(255, round((170 if dark else 150) * strength))))
    return (alpha << 24) | (value.blue() << 16) | (value.green() << 8) | value.red()


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
class RevealOverlay(QWidget):
    """The Windows 10 'Reveal' light, drawn above every control.

    Keeping it on its own layer means the light can move without repainting the
    window or its children. The settings dialog has dozens of controls and costs
    ~45 ms for a full repaint, which no in-place tuning could make smooth.
    """

    def __init__(self, parent) -> None:
        super().__init__(parent)
        # Pure decoration: never takes input, never paints an opaque background.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._glow: QPixmap | None = None
        self._glow_key: tuple | None = None
        self.hide()

    def local_centre(self) -> QPointF:
        window = self.parentWidget()
        pointer = getattr(window, "_pointer", None)
        if pointer is None:
            return QPointF(-1.0, -1.0)
        return pointer - QPointF(self.pos())

    def glow_pixmap(self, radius: float) -> QPixmap:
        """The radial light, baked once per (radius, theme, strength)."""
        strength = theme.reveal_strength
        key = (int(radius), theme.dark, round(strength, 3))
        if self._glow is not None and self._glow_key == key:
            return self._glow
        size = max(2, int(radius))
        pixmap = QPixmap(size * 2, size * 2)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        gradient = QRadialGradient(QPointF(size, size), size)
        if theme.dark:
            light = QColor("#FFFFFF")
            peak = 0.15 * strength
        else:
            # The light card is #F3F3F3: 12 levels of headroom before white, so
            # ANY tint reads as a stain rather than as light. Stay neutral; the
            # control border highlight is what makes the pointer feel connected.
            light = QColor("#FFFFFF")
            peak = 0.50 * strength
        # A tighter falloff keeps the light near the pointer instead of washing
        # the whole surface, which is what made it feel too bright.
        gradient.setColorAt(0.0, rgba(light, min(1.0, peak)))
        gradient.setColorAt(0.30, rgba(light, min(1.0, peak * 0.42)))
        gradient.setColorAt(0.65, rgba(light, min(1.0, peak * 0.10)))
        gradient.setColorAt(1.0, rgba(light, 0.0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(0, 0, size * 2, size * 2)

        # An 8-bit radial falloff over 300 px bands into visible rings; a little
        # grain breaks them, the same trick Acrylic uses on its surfaces.
        circle = QPainterPath()
        circle.addEllipse(QRectF(0, 0, size * 2, size * 2))
        painter.setClipPath(circle)
        painter.setOpacity(0.6)
        painter.drawTiledPixmap(QRectF(0, 0, size * 2, size * 2),
                                mica.noise_tile())
        painter.setOpacity(1.0)
        painter.end()
        self._glow = pixmap
        self._glow_key = key
        return pixmap

    def paintEvent(self, event) -> None:  # noqa: N802
        window = self.parentWidget()
        reveal = getattr(window, "_reveal", 0.0)
        if not theme.uses_reveal or reveal <= 0.02:
            return
        centre = self.local_centre()
        if centre.x() < -self.width() or centre.y() < -self.height():
            return
        radius = min(max(self.width(), self.height()) * 0.34, 300.0)
        if radius <= 1:
            return
        glow = self.glow_pixmap(radius)
        painter = QPainter(self)
        painter.setOpacity(max(0.0, min(1.0, reveal)))
        # Clip to the card so the light stops at the window border the way a real
        # surface would, instead of being cut by the layer's own bounds.
        card = None
        card_rect = getattr(window, "card_rect", None)
        if callable(card_rect):
            try:
                card = QRectF(card_rect())
            except Exception:
                card = None
        if card is not None:
            path = QPainterPath()
            path.addRoundedRect(card, theme.radius_window, theme.radius_window)
            painter.setClipPath(path)
        painter.drawPixmap(QPointF(centre.x() - radius, centre.y() - radius), glow)
        painter.setOpacity(1.0)
        painter.end()


# 用户："在 win10 风格下，设置能不能也做成背景高斯模糊（真实屏幕内容）"。
# 窗口本身是半透明的，直接抓屏会抓到自己；所以在窗口**出现之前**先抓一张整屏，
# 之后 _ensure_backdrop 从这张图里裁出窗口那块做高斯。
_DESKTOP_SHOT = None


def capture_desktop_shot() -> None:
    """在窗口出现前抓一张整屏快照（供设置窗口做高斯底使用）。

    抓屏偶尔会失败（返回空），失败时**保留上一张成功的**，并重试几次 ——
    否则背景会退回壁纸材质，而在不支持的机器上那就是"不透明纯色"，
    看起来就是用户说的"背景不是透明的"（Win11 风格）。
    """
    global _DESKTOP_SHOT
    for _ in range(3):
        try:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                continue
            pm = screen.grabWindow(0)
            if pm is not None and not pm.isNull():
                img = pm.toImage()
                if not img.isNull():
                    _DESKTOP_SHOT = img
                    return
        except Exception:
            continue


def desktop_shot():
    return _DESKTOP_SHOT



class FluentWindow(QWidget):
    """A frameless window painted with a Mica backdrop, rounded corners and a
    soft drop shadow. Works identically on Windows 10 and 11."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        resizable: bool = False,
        radius: int | None = None,        # None = follow the active style
        shadow: bool = False,      # no margin left to draw one in
        tint_strength: float = 0.90,
        margin: int = SHADOW_MARGIN,
        open_animation: str = "slide",        # slide | fade | none
        open_slide: int = 14,
        native_backdrop: bool | None = None,   # None = ask backdrop.wanted()
    ) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        # A real DWM backdrop cannot coexist with a layered window, and a layered
        # window is what gives us the transparent shadow margin - so the native
        # path drops the margin and shapes the window with a region instead.
        self._native_backdrop = (_native_backdrop_wanted() if native_backdrop is None
                                 else native_backdrop)
        if self._native_backdrop:
            margin = 0
            shadow = False
        else:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._radius = radius
        self._shadow = shadow
        self._wants_shadow = shadow   # 回退路径要尊重这个原始请求
        self._tint_strength = tint_strength
        self._margin = margin
        self._resizable = resizable
        self._open_animation = open_animation
        self._open_slide = open_slide
        self._open_animation_running = False
        self._suppress_open_animation = False
        self._backdrop: QPixmap | None = None
        # 只有设置窗口用"真实屏幕内容"做底；主窗口/控制条仍走壁纸材质。
        self._real_screen_backdrop = False
        self._shadow_pixmap: QPixmap | None = None
        self._resize_edges: Qt.Edge | None = None
        self._normal_geometry: QRect | None = None
        self._maximized = False
        # Windows 10 'Reveal': a soft light that follows the pointer.
        self._pointer = QPointF(-1.0, -1.0)
        self._reveal = 0.0
        self._reveal_timer: QTimer | None = None
        self._reveal_anim: QVariantAnimation | None = None
        self._reveal_band = QRect()
        self._frame_ms = 0.0
        self._reveal_overlay = RevealOverlay(self)
        self._static_card: QPixmap | None = None
        self._static_key: tuple | None = None
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
        """标记背景需要重建。

        注意：这里**不清空** self._backdrop —— 清了之后下一次绘制还没有新背景，
        就会露出透明的中间态，看起来就是"闪烁"（用户反馈）。保留旧图，
        等 _ensure_backdrop 生成好新图再替换。
        """
        self._backdrop_stale = True

    def _ensure_backdrop(self) -> None:
        # 用户："win11风格背景不是透明的" —— 窗口开启动画会 _freeze_backdrop=True，
        # 而 Win11 风格据此跳过整块背景生成，回退成不透明纯色。
        # 真实屏幕内容走的是"快照"，与窗口位置无关，不需要冻结，这里只对原生路径生效。
        if self._freeze_backdrop and not self._real_screen_backdrop:
            return
        if self._backdrop is not None and not getattr(self, "_backdrop_stale", False):
            return
            return
        card = self.card_rect()
        handle = self.windowHandle()
        dpr = handle.devicePixelRatio() if handle else 1.0
        physical = QRect(
            int(card.x() * dpr), int(card.y() * dpr),
            max(1, int(card.width() * dpr)), max(1, int(card.height() * dpr)),
        )
        try:
            shot = desktop_shot()
            if self._real_screen_backdrop and shot is not None:
                # Win10：从"窗口出现前抓的整屏"里裁出窗口这块，再高斯模糊 ——
                # 这样糊出来的是真实屏幕内容（桌面、其它窗口），而不是壁纸。
                gtl = self.mapToGlobal(card.topLeft())
                crop = shot.copy(int(gtl.x() * dpr), int(gtl.y() * dpr),
                                  max(1, int(card.width() * dpr)),
                                  max(1, int(card.height() * dpr)))
                blurred = QPixmap.fromImage(crop)
                if blurred.isNull():
                    blurred = mica.backdrop(physical, 0, dpr, self._tint_strength,
                                            acrylic=theme.uses_acrylic)
                else:
                    blurred = FluentComboBox._gaussian_pixmap(
                        blurred, max(8.0, 14.0 * dpr))
                # 压一层窗底色，避免背景太忙影响读字；仍能看出是真实内容的模糊。
                try:
                    _src = blurred.toImage().convertToFormat(
                        QImage.Format.Format_ARGB32_Premultiplied)
                    _out = QImage(_src.size(), QImage.Format.Format_ARGB32_Premultiplied)
                    _out.fill(QColor(theme.palette.window_bg))
                    _pp = QPainter(_out)
                    try:
                        _pp.setOpacity(max(0.0, min(1.0,
                            float(getattr(settings, "backdrop_opacity", 45)) / 100.0)))
                        _pp.drawImage(0, 0, _src)
                    finally:
                        _pp.end()
                    blurred = QPixmap.fromImage(_out)
                except Exception:
                    pass
                self._backdrop = blurred
            else:
                self._backdrop = mica.backdrop(physical, 0, dpr, self._tint_strength,
                                               acrylic=theme.uses_acrylic)
        except Exception:
            import logging as _lg

            _lg.getLogger(__name__).exception(
                "backdrop 生成失败（style=%s, real_screen=%s）",
                theme.resolved_style, getattr(self, "_real_screen_backdrop", None))
            self._backdrop = None
            self._backdrop_stale = False

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

    def _static_card_key(self) -> tuple:
        return (self.width(), self.height(), self.radius, theme.dark,
                theme.resolved_style, self._tint_strength, self._shadow,
                id(self._backdrop))

    def static_card(self) -> QPixmap:
        """Shadow + backdrop + border, rendered once and reused.

        The Reveal light repaints at up to 30 Hz; re-blitting the shadow and
        the Acrylic backdrop on every one of those frames is what made the
        settings window judder (51 ms/frame before the light was even drawn).
        """
        self._ensure_backdrop()
        key = self._static_card_key()
        if self._static_card is not None and self._static_key == key:
            return self._static_card

        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_static_card(painter)
        painter.end()
        self._static_card = pixmap
        self._static_key = key
        return pixmap

    def _paint_static_card(self, painter: QPainter) -> None:
        """Everything in the card that does not change between frames."""
        if self._native_backdrop:
            # DWM draws the material behind the window; anything opaque painted
            # here would hide it. Only the hairline border is ours.
            self._paint_native_border(painter)
            return
        card = self.card_rect()
        if self._shadow and self._margin > 0:
            if self._shadow_pixmap is None or self._shadow_pixmap.size() != self.size():
                self._shadow_pixmap = render_shadow(self.size(), max(1, self.radius * 2),
                                                    spread=self._margin,
                                                    opacity=theme.shadow_opacity)
            painter.drawPixmap(0, 0, self._shadow_pixmap)

        path_rect = QRectF(card)
        if self._backdrop is not None:
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

        border = rgba("#000000" if not theme.dark else "#FFFFFF",
                      0.10 if not theme.dark else 0.09)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(border)
        painter.setPen(pen)
        painter.drawRoundedRect(QRectF(card).adjusted(0.5, 0.5, -0.5, -0.5),
                                self.radius, self.radius)

    def _paint_card(self, painter: QPainter) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self.card_rect()
        painter.drawPixmap(0, 0, self.static_card())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.invalidate_backdrop()
        self._apply_native_rounding()
        self._start_open_animation()
        self._start_reveal_tracking()
        self.sync_reveal_overlay()
        self._apply_native_backdrop()
        if self._native_backdrop:
            QTimer.singleShot(200, self._verify_native_backdrop)

    def minimize_animated(self) -> None:
        """Minimize using the Windows animation itself.

        ShowWindow(SW_MINIMIZE) lets DWM play the real minimize motion, which is
        always a better match than anything drawn by hand. The self-drawn snapshot
        animation is only kept for when the system's own "Animate windows when
        minimizing and maximizing" option is off — in that case Windows plays
        nothing at all and the window would just vanish.

        Which path was taken is logged, so "I don't see any animation" can be
        answered from app.log instead of guessed at.
        """
        if self.isMinimized():
            return
        log = logging.getLogger("winsnip.ui")
        native_ok = False
        try:
            native_ok = winapi.native_minimize_animation_enabled()
        except Exception:
            native_ok = False
        if native_ok:
            try:
                if winapi.minimize_window_native(int(self.winId())):
                    log.info("minimize: 原生（ShowWindow SW_MINIMIZE，由 DWM 播动画）")
                    return
                log.warning("minimize: ShowWindow(SW_MINIMIZE) 返回失败，改用自绘回退")
            except Exception as exc:
                log.warning("minimize: 原生调用异常 %r，改用自绘回退", exc)
        else:
            log.info("minimize: 自绘回退（系统关闭了「最小化/最大化时动画显示窗口」）")
        anim.minimize_window_animated(self)

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
            # 用 FAST：合成慢的机器上 240ms 会被拉长到一秒多，而淡入期间窗口是半透明的，
            # 拖得越久越像"发灰"。缩短时长，观感上是干净利落的一次落位。
            duration=anim.DURATION_FAST,
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
        self._stop_reveal_animation()

    def sync_reveal_overlay(self) -> None:
        """Keep the light's layer covering the window, and on top.

        The layer spans the whole window rather than just the card: a 300 px
        light clipped to card_rect() left a straight colour block along the card
        edge. RevealOverlay clips the light to the card's rounded shape instead,
        so it fades out naturally and stops cleanly at the window border.
        """
        overlay = self._reveal_overlay
        overlay.setGeometry(self.rect())
        if theme.uses_reveal:
            overlay.show()
            # LOWER, not raise: the light belongs on top of the card but BELOW
            # the controls. Raised, it washed over the hint text and any label it
            # passed, which read as the light "covering" the text.
            overlay.lower()
        else:
            overlay.hide()

    def set_reveal(self, pointer: QPointF | None, reveal: float) -> None:
        """Move the light. The only path that marks the overlay dirty.

        Both the cursor tracker and the self-tests go through here, so there
        is no way to change the light without it actually being redrawn.
        """
        overlay = self._reveal_overlay
        if theme.uses_reveal and not overlay.isVisible():
            # The style or the animation switch may have changed since show().
            self.sync_reveal_overlay()
        old_band = self.reveal_band(self._pointer)
        if pointer is not None:
            self._pointer = QPointF(pointer)
        self._reveal = float(reveal)
        overlay.update(old_band.united(self.reveal_band()).translated(-overlay.pos()))

    def reveal_band(self, centre: QPointF | None = None) -> QRect:
        """The area the light can touch — the only part worth repainting."""
        point = self._pointer if centre is None else centre
        if point.x() < 0:
            return QRect()
        card = self.card_rect()
        # Only the inner part needs repainting: at 62% of the radius the glow is
        # already down to ~14% of its peak, so the outer falloff moves by well
        # under one colour level between frames. A translucent band this size
        # costs roughly a third of the full square on a software renderer.
        extent = int(min(max(card.width(), card.height()) * 0.34, 300.0) * 0.62) + 4
        return QRect(int(point.x()) - extent, int(point.y()) - extent,
                     extent * 2, extent * 2)

    def _track_pointer(self) -> None:
        """Poll the cursor: child widgets swallow mouseMoveEvent."""
        if not theme.uses_reveal:
            return
        started = time.perf_counter()
        local = self.mapFromGlobal(QCursor.pos())
        inside = self.rect().contains(local)
        moved = (QPointF(local) - self._pointer).manhattanLength() >= 3.0
        new_pointer = QPointF(local) if inside else self._pointer
        target = 1.0 if inside else 0.0
        if abs(self._reveal - target) > 0.02:
            self._animate_reveal(target)
        if inside and moved:
            # Only the overlay repaints, never the window or its controls:
            # that is what took the settings window from 18 fps to ~58.
            self.set_reveal(new_pointer, self._reveal)
            self._adapt_rate(time.perf_counter() - started)
        elif inside:
            self._pointer = new_pointer

    def _adapt_rate(self, elapsed: float) -> None:
        """Ease off the tick rate when frames are more expensive than the tick."""
        if self._reveal_timer is None:
            return
        self._frame_ms = self._frame_ms * 0.7 + elapsed * 1000.0 * 0.3
        wanted = int(max(33, min(90, self._frame_ms * 1.6)))
        if abs(self._reveal_timer.interval() - wanted) >= 8:
            self._reveal_timer.setInterval(wanted)

    def _animate_reveal(self, target: float) -> None:
        self._stop_reveal_animation()
        animation = QVariantAnimation(self)
        animation.setDuration(anim.DURATION_NORMAL)
        animation.setStartValue(self._reveal)
        animation.setEndValue(target)
        animation.setEasingCurve(anim.curve("out"))
        animation.valueChanged.connect(self._on_reveal_tick)
        animation.finished.connect(lambda: self._on_reveal_finished(animation))
        self._reveal_anim = animation
        # KeepWhenStopped: with DeleteWhenStopped Qt frees the C++ object the
        # moment the fade ends, and the stale Python reference then raised
        # "Internal C++ object already deleted" on the next fade.
        animation.start()

    def _on_reveal_finished(self, animation) -> None:
        if self._reveal_anim is animation:
            self._reveal_anim = None
        animation.deleteLater()

    def _stop_reveal_animation(self) -> None:
        animation = self._reveal_anim
        self._reveal_anim = None
        if animation is None:
            return
        try:
            animation.stop()
        except RuntimeError:
            # The C++ side is already gone; nothing to stop.
            return
        animation.deleteLater()

    def _on_reveal_tick(self, value) -> None:
        self._reveal = float(value)
        self._reveal_overlay.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._stop_reveal_tracking()
        super().hideEvent(event)

    def _paint_native_border(self, painter: QPainter) -> None:
        card = QRectF(self.card_rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        border = rgba("#000000" if not theme.dark else "#FFFFFF",
                      0.10 if not theme.dark else 0.09)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(border)
        painter.setPen(pen)
        painter.drawRoundedRect(card, self.radius, self.radius)

    def _apply_native_backdrop(self) -> None:
        """Hand the window over to DWM and clip it to the card's shape."""
        if not self._native_backdrop:
            return
        handle = self.windowHandle()
        if handle is None:
            return
        hwnd = int(handle.winId())
        if not hwnd:
            return
        if winapi.is_layered(hwnd):
            self._fallback_from_native(_t("窗口是分层窗口，DWM 背景会被绕过"))
            return
        tint = _native_tint(theme.palette.window_bg, self._tint_strength, theme.dark)
        applied = winapi.set_accent_blur(hwnd, winapi.ACCENT_ENABLE_ACRYLICBLURBEHIND, tint)
        if not applied:
            applied = winapi.set_system_backdrop(hwnd, winapi.DWMSBT_TRANSIENTWINDOW)
        if not applied:
            self._fallback_from_native(_t("系统拒绝了背景材质请求"))
            return
        self._sync_native_region()

    def _sync_native_region(self) -> None:
        if not self._native_backdrop:
            return
        handle = self.windowHandle()
        if handle is None:
            return
        winapi.set_rounded_region(int(handle.winId()), self.width(), self.height(),
                                  self.radius * 2)

    def _fallback_from_native(self, reason: str) -> None:
        """Give up on the native material and go back to the wallpaper one."""
        if not self._native_backdrop:
            return
        import logging

        logging.getLogger(__name__).warning(
            "native backdrop off, using the wallpaper material instead: %s", reason)

        # Remember the card before the margins come back: with margin=0 the card
        # is the whole window.
        old_margin = self._margin
        card_width = max(1, self.width() - 2 * old_margin)
        card_height = max(1, self.height() - 2 * old_margin)
        try:
            card_origin = self.mapToGlobal(QPoint(old_margin, old_margin))
        except Exception:
            card_origin = None

        self._native_backdrop = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._margin = SHADOW_MARGIN
        self._shadow = getattr(self, "_wants_shadow", False)
        try:
            handle = self.windowHandle()
            if handle is not None:
                winapi.clear_backdrop(int(handle.winId()))
                # The native path shaped this window with SetWindowRgn, which
                # clips it. clear_backdrop does not touch the region, and after
                # this fallback _sync_native_region() returns early - so without
                # this the window stayed clipped to its old size and the caption
                # buttons and footer were cut off.
                winapi.clear_rounded_region(int(handle.winId()))
        except Exception:
            pass
        self._static_card = None
        self._static_key = None

        # Grow the window around the card by the margin that just came back.
        # Without this the card ended up smaller than the window and the whole
        # layout was squeezed - the "main window cannot display properly" report.
        if self._margin != old_margin:
            self.set_card_size(card_width, card_height)
            if card_origin is not None:
                self.move(card_origin.x() - self._margin, card_origin.y() - self._margin)
        self.invalidate_backdrop()

    def _verify_native_backdrop(self) -> None:
        """Catch the accent API's known failure: a black client area.

        NOTE: this must capture the SCREEN, not self.grab(). A native-backdrop
        window paints nothing in its client area on purpose, so grab() renders it
        offscreen and always comes back near-black - the check would then revert
        on every machine and silently disable the very feature it guards.
        """
        if not self._native_backdrop:
            return
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        try:
            card = self.card_rect()
            origin = self.mapToGlobal(card.topLeft())
            image = screen.grabWindow(0, origin.x(), origin.y(),
                                      card.width(), card.height()).toImage()
        except Exception:
            return

        step = max(4, card.width() // 40)
        total = 0
        darkest = 255
        samples = 0
        for x in range(step, image.width() - step, step):
            for y in range(step, image.height() - step, step):
                value = image.pixelColor(x, y).lightness()
                total += value
                darkest = min(darkest, value)
                samples += 1
        if not samples:
            return
        if total / samples < 12 and darkest < 6:
            self._fallback_from_native(_t("背景渲染为纯黑（accent API 的已知故障）"))

    def _apply_native_rounding(self) -> None:
        try:
            handle = self.windowHandle()
            if handle is not None and theme.radius_window > 0 and winapi.is_windows_11():
                winapi.set_rounded_corners(int(handle.winId()), 2)
        except Exception:
            pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_native_region()
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
def _mix_colour(first: QColor, second: QColor, amount: float) -> QColor:
    """Linear blend between two colours, alpha included."""
    amount = max(0.0, min(1.0, amount))
    return QColor(
        int(first.red() + (second.red() - first.red()) * amount),
        int(first.green() + (second.green() - first.green()) * amount),
        int(first.blue() + (second.blue() - first.blue()) * amount),
        int(first.alpha() + (second.alpha() - first.alpha()) * amount))


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
        # Choice rows drive the look through _selection so that picking an option
        # can fade; elsewhere the variant alone decides and nothing changes.
        self._choice = False
        self._selection = 0.0
        self._selection_anim: QVariantAnimation | None = None
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

    # -- animated selection (used by the first-run guide's choice rows) ----- #
    def set_choice_mode(self, on: bool) -> None:
        """Let _selection drive the appearance instead of the variant."""
        self._choice = bool(on)
        self.update()

    def selection(self) -> float:
        """0 = standard appearance, 1 = accent (exposed for the tests)."""
        return self._selection

    def set_selection(self, value: float) -> None:
        self._selection = max(0.0, min(1.0, float(value)))
        self.update()

    def animate_selection(self, target: float, *, animate: bool = True,
                          duration: int | None = None) -> None:
        """Fade between the standard and accent appearances."""
        target = max(0.0, min(1.0, float(target)))
        if self._selection_anim is not None:
            self._selection_anim.stop()
            self._selection_anim = None
        if not animate or not anim.animations_enabled() \
                or abs(self._selection - target) < 0.001:
            self.set_selection(target)
            return
        timeline = QVariantAnimation(self)
        timeline.setDuration(duration or anim.DURATION_FAST)
        timeline.setStartValue(self._selection)
        timeline.setEndValue(target)
        timeline.setEasingCurve(anim.curve("out"))
        timeline.valueChanged.connect(self.set_selection)
        timeline.finished.connect(lambda: setattr(self, "_selection_anim", None))
        self._selection_anim = timeline
        timeline.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)

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

        # Blend standard -> accent by the animated selection, so picking an
        # option in a choice row fades instead of snapping.
        if self._choice and self._selection > 0.0:
            amount = self._selection
            accent = QColor(palette.accent)
            bg = accent if bg is None else _mix_colour(bg, accent, amount)
            if border is not None:
                border = QColor(border)
                border.setAlpha(int(border.alpha() * (1.0 - amount)))
            text_color = _mix_colour(text_color, QColor("#FFFFFF"), amount)
            icon_color = _mix_colour(icon_color, QColor("#FFFFFF"), amount)
            if bg is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(bg)
                painter.drawRoundedRect(rect, control_radius(self), control_radius(self))

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

        if self._hover and enabled:
            paint_reveal_border(self, painter, float(control_radius(self)))

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


#: Caption-button tooltips, keyed by kind.
_CAPTION_TITLES = {
    "min": "最小化",
    "max": "最大化",
    "restore": "还原",
    "close": "关闭",
}


def retranslate_windows() -> None:
    """Re-apply the labels of every top-level window that supports it.

    Called after the interface language changes. A window opts in by defining
    retranslate(), so a new window cannot be silently left behind.
    """
    app = QApplication.instance()
    if app is None:
        return
    for widget in app.topLevelWidgets():
        method = getattr(widget, "retranslate", None)
        if not callable(method):
            continue
        try:
            method()
        except Exception:
            logging.getLogger(__name__).exception(
                "failed to retranslate %s", type(widget).__name__)


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
        self.retranslate()

    def retranslate(self) -> None:
        """Re-apply the tooltip after an interface-language change."""
        self.setToolTip(_t(_CAPTION_TITLES.get(self.kind, _CAPTION_TITLES["close"])))

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
                 *, item_width: int = 54, height: int = 36,
                 duration: int | None = None) -> None:
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
        # 专用时长：这是命令栏上的模式切换，比通用动效慢一点。
        self._anim.setDuration(duration or anim.DURATION_MODE_SWITCH)
        self._anim.setEasingCurve(anim.curve("decelerate"))
        self._anim.valueChanged.connect(self._on_progress)
        self.setFixedSize(item_width * len(items), height)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        for index, (_, tooltip) in enumerate(items):
            if tooltip:
                self.setToolTip(tooltip)

    def set_labels(self, labels: list[str]) -> None:
        """Re-label the segments in place (used when the language changes)."""
        for index, label in enumerate(labels):
            if index < len(self._items):
                self._items[index] = (self._items[index][0], label)
        self.update()

    def animation_duration(self) -> int:
        """The mode-switch animation length in ms (exposed for the tests)."""
        return self._anim.duration()

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
        # Windows 10 的截图工具没有这条蓝条，只靠图标变色区分选中；Win11 保持原样。
        if not theme.is_win10:
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
    """Fluent toggle switch used by the settings flyout.

    开关有动画：_t 是 0（关）到 1（开）的进度，滑块位置、圆角、以及轨道/边框/滑块的
    颜色都按它插值，所以拨动时是**滑过去 + 渐变色**，不是瞬间跳。进度用
    QVariantAnimation 推进，并且尊重设置里的"界面动画"开关（关掉就直接跳）。
    """

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self._t = 1.0 if checked else 0.0
        self._anim = QVariantAnimation(self)
        # 240ms（DURATION_NORMAL）：150ms 太快，滑块一闪就到，看不出"滑过去"。
        self._anim.setDuration(anim.DURATION_NORMAL)
        self._anim.setEasingCurve(anim.curve("decelerate"))
        self._anim.valueChanged.connect(self._on_anim)
        # 44x26：宽度由 50 收到 44（用户要"短一点"），高度保持 26。
        # 内部所有尺寸都按比例算，只改这一个数字即可。
        self.setFixedSize(44, 26)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked

    def setChecked(self, value: bool, *, animate: bool = True) -> None:  # noqa: N802
        value = bool(value)
        if value == self._checked:
            return
        self._checked = value
        target = 1.0 if value else 0.0
        self._anim.stop()
        if not animate or not anim.animations_enabled():
            self._t = target
            self.update()
        else:
            self._anim.setStartValue(float(self._t))
            self._anim.setEndValue(target)
            self._anim.start()
        self.toggled.emit(value)

    def _on_anim(self, value) -> None:
        # 控件可能在动画跑完前就被销毁（设置窗口关闭），回调晚到不能崩。
        try:
            self._t = float(value)
            self.update()
        except RuntimeError:
            pass

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        # 内部尺寸全部按控件尺寸算，改 setFixedSize 不用再逐个调数字。
        # 比例取自原来 40x20 时的取值：轨道高 16（占高 80%）、滑块内缩 8（高×0.4）、
        # 半径 4 / 5（轨道高×0.25 / ×0.31）。
        w, h = float(self.width()), float(self.height())
        track = QRectF(0, h * 0.1, w, h * 0.8)
        inset = h * 0.4
        # _t 是 0（关）-> 1（开）的进度，位置和颜色都按它插值，所以拨动是滑过去 + 渐变色。
        t = max(0.0, min(1.0, float(self._t)))

        def _mix(a: QColor, b: QColor, k: float) -> QColor:
            return QColor(int(round(a.red() + (b.red() - a.red()) * k)),
                          int(round(a.green() + (b.green() - a.green()) * k)),
                          int(round(a.blue() + (b.blue() - a.blue()) * k)),
                          int(round(a.alpha() + (b.alpha() - a.alpha()) * k)))

        # 关：轨道近白填充 + 浅灰细边 + 深灰滑块。参考 Windows 取值
        # 轨道 #F4F6F7、边框 #D9DBDC、滑块 #5D5E5E。
        off_track = rgba("#000000" if not palette.dark else "#FFFFFF", 0.03)
        off_border = rgba(palette.text_primary, 0.16)
        off_knob = QColor(palette.text_secondary)
        # 开态轨道**直接用强调色**（用户："风格统一下"）。
        # 从设置窗口截图里量过：完成按钮 #0068B8 = 强调色，而开关当时是 #00508E
        # （之前把强调色调深三成，调过头了），两者的蓝明显不一样。Windows 11 的强调色
        # 按钮本身就是强调色，所以"统一"与"和 win11 按钮一样深"是同一个答案。
        on_track = QColor(palette.accent)
        on_knob = QColor("#FFFFFF")

        painter.setBrush(_mix(off_track, on_track, t))
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(_mix(off_border, on_track, t))
        painter.setPen(pen)
        painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), track.height() / 2,
                                track.height() / 2)

        radius = track.height() * (0.25 + (0.31 - 0.25) * t)
        cx = inset + ((w - inset) - inset) * t
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_mix(off_knob, on_knob, t))
        painter.drawEllipse(QRectF(cx - radius, h / 2 - radius, radius * 2, radius * 2))
        painter.end()


class _SelectionBarDelegate(QStyledItemDelegate):
    """Draws the Win11 accent bar on the **current value**, sliding between rows.

    The bar marks the checked/current entry, not the hovered one: hovering only
    shows the rounded background.

    A slide needs a single thing that travels, so the position is kept here as a
    float in row units and animated; each row then clips the (possibly straddling)
    bar to its own rect. Painting it per row without the shared position could
    only ever make it jump.
    """

    def __init__(self, parent=None, *, current_row: int = -1) -> None:
        super().__init__(parent)
        self._current_row = current_row      # 当前值那一行（锚点）
        self._anim_row = float(current_row)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(anim.DURATION_NORMAL)
        self._anim.setEasingCurve(anim.curve("decelerate"))
        self._anim.valueChanged.connect(self._on_anim)

    # ------------------------------------------------------------------ #
    def set_current_row(self, row: int, *, animate: bool = True) -> None:
        """The chosen value changed: slide the bar from where it was to ``row``.

        Selection-driven, not hover-driven: the pointer moving over rows must not
        move the bar (hovering only shows that row's background).
        """
        self._current_row = row
        start = self._anim_row
        self._anim.stop()
        if not animate or not anim.animations_enabled() or start < 0 or row < 0:
            self._anim_row = float(row)
            self._refresh()
        else:
            self._anim.setStartValue(float(start))
            self._anim.setEndValue(float(row))
            self._anim.start()

    def _refresh(self) -> None:
        view = self.parent()
        if view is not None and hasattr(view, "viewport"):
            view.viewport().update()

    def _on_anim(self, value) -> None:
        self._anim_row = float(value)
        self._refresh()

    # ------------------------------------------------------------------ #
    def paint(self, painter, option, index) -> None:  # noqa: N802
        super().paint(painter, option, index)
        # 弹窗整体走 Win10 风格，选中项左侧那条强调色竖条是 Win11 才有的，这里不画。
        if theme.is_win10 or self._anim_row < 0:
            return
        view = self.parent()
        model = index.model()
        if view is None or model is None or not hasattr(view, "visualRect"):
            return
        rows = model.rowCount()
        if rows <= 0:
            return
        low = max(0, min(rows - 1, int(self._anim_row)))
        high = max(0, min(rows - 1, low + 1))
        frac = self._anim_row - int(self._anim_row)
        top_rect = view.visualRect(model.index(low, 0))
        bottom_rect = view.visualRect(model.index(high, 0))
        if not top_rect.isValid():
            return
        centre = top_rect.center().y() + (bottom_rect.center().y() - top_rect.center().y()) * frac
        # 高度按行高比例（参考图 20px / 46px 行 = 43%），宽 4px。之前写死 14px、宽 3px，
        # 比 Windows 矮一截细一截。左边距保持 6 不动。
        bar_height = min(top_rect.height() * 0.45, top_rect.height() - 10.0)
        if bar_height <= 3.0:
            return
        painter.save()
        # 只画落在本行内的那一段：动画中途竖条会跨在两行之间。
        painter.setClipRect(QRectF(option.rect))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.palette.accent))
        rect = option.rect
        painter.drawRoundedRect(
            QRectF(rect.x() + 6.0, centre - bar_height / 2.0, 4.0, bar_height),
            2.0, 2.0)
        painter.restore()


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
        # 点击某个条目后弹窗**不关闭**：选完立刻关闭的话，蓝条滑向新值的过程根本看不到。
        # 关键在于把鼠标释放事件吞掉 —— QComboBox 的弹窗容器就是靠这个事件自行关闭的。
        self._keep_popup_open = True
        self._popup_backdrop = None
        self._backdrop_key = None
        self._screen_shot = None
        self._popup_backdrop = None
        self.view().viewport().installEventFilter(self)

    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        """弹窗事件：Show 时摆到居中位置；点选项时自己应用，不让 Qt 关掉弹窗。"""
        try:
            view0 = self.view()
            container0 = view0.window() if view0 is not None else None
        except Exception:
            container0 = None
        if (container0 is not None and container0 is not self
                and obj is container0 and event.type() == QEvent.Type.Paint):
            try:
                self._paint_popup_container(container0)
                return True
            except Exception:
                return False
        if container0 is not None and container0 is not self and obj is container0:
            if event.type() == QEvent.Type.Show:
                # Show 发生在第一次绘制之前，在这里把几何改成居中的，屏幕上不会先闪一下
                # "在下面"再跳上来（用户："打开就在中间"）。
                try:
                    # 用户："在 win10 风格下，菜单在弹出一瞬间没有高斯模糊" —— 模糊底要几十毫秒才
                    # 生成好，而 Win10 是瞬间弹出，那一瞬间露出的就是没糊的画面。
                    # 这里先把自己设为全透明，等模糊底生成完再显示，第一帧就是糊好的。
                    if theme.is_win10:
                        try:
                            container0.setWindowOpacity(0.0)
                        except Exception:
                            pass
                    container0.setGeometry(self._centred_geometry(container0))
                    # 用户："不要有圆边" —— 我们自己画的 clip 已是直角，但 Windows 11 的 DWM
                    # 默认会给顶层窗口加圆角，这里显式要求不圆角。
                    try:
                        if theme.is_win10:
                            # Win10：直角 + 把 DWM 的 1px 边框并进客户区（否则有黑边）。
                            winapi.set_rounded_corners(
                                int(container0.winId()), winapi.DWMWCP_DONOTROUND)
                            winapi.extend_frame_into_client(int(container0.winId()))
                        else:
                            # Win11：保持系统默认圆角，不并边框（圆角本身会盖住边框）。
                            winapi.set_rounded_corners(
                                int(container0.winId()), winapi.DWMWCP_ROUND)
                        winapi.extend_frame_into_client(int(container0.winId()))
                    except Exception:
                        pass
                    # 用户："这个在 win11 风格下改回去" —— Win11 风格回到纯色底，只给 Win10 做模糊。
                    if theme.is_win10:
                        self._refresh_popup_backdrop(container0)
                except Exception:
                    pass
                # 模糊底生成完之后再恢复不透明 —— 这样第一帧看到的就是糊好的画面。
                if theme.is_win10:
                    try:
                        container0.setWindowOpacity(1.0)
                    except Exception:
                        pass
        try:
            view = self.view()
            if (self._keep_popup_open and view is not None
                    and obj is view.viewport()
                    and event.type() == QEvent.Type.MouseButtonRelease):
                index = view.indexAt(event.position().toPoint())
                if index.isValid():
                    self.setCurrentIndex(index.row())
                    delegate = view.itemDelegate()
                    if isinstance(delegate, _SelectionBarDelegate):
                        # 让蓝条从旧位置滑到新位置（弹窗还开着，所以看得见）
                        delegate.set_current_row(index.row())
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------ #
    def _popup_stylesheet(self) -> str:
        p = theme.palette
        item_hover = "rgba(255,255,255,0.07)" if p.dark else "rgba(0,0,0,0.045)"
        # 竖条由 _SelectionBarDelegate 自绘（样式表的 border-left 只能占满整行，
        # 做不出 Win11 那种"比高亮底更矮"的短竖条）。这里只让高亮底内缩成胶囊形。
        # 用户："改成 win10 风格的" —— 下拉弹窗统一按 Win10 实心菜单处理：
        # 不透明底、小圆角、细边框，没有 Win11 那种选中项上下留白。
        item_margin = "" if theme.is_win10 else "margin: 4px 0;"
        # Win11 的选项左边要留 18px 给强调色竖条；Win10 没有竖条，
        # 留着就是多余缩进，字看起来像居中（用户："在win10风格下字要左对齐"）。
        item_pad = "3px 8px 3px 8px" if theme.is_win10 else "3px 8px 3px 18px"
        return f"""
        QListView {{
            background-color: transparent;
            color: {p.text_primary};
            border: none;
            padding: 4px;
            outline: none;
        }}
        QListView::item {{
            min-height: 26px;
            padding: {item_pad};
            border-radius: {theme.radius_control}px;
            color: {p.text_primary};
            {item_margin}
        }}
        QListView::item:selected, QListView::item:hover {{
            background-color: {item_hover};
            color: {p.text_primary};
            {item_margin}
        }}
        QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
        QScrollBar::handle:vertical {{
            background: {rgba(p.text_secondary, 0.4).name(QColor.NameFormat.HexArgb)};
            border-radius: {theme.radius_control}px; min-height: 20px;
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
        # 竖条只画在**当前值**那一行（不是悬停行）。delegate 复用同一个实例，
        # 这样值变化时它能从旧位置滑到新位置，而不是每次弹出都新建、直接跳过去。
        try:
            delegate = view.itemDelegate()
            if not isinstance(delegate, _SelectionBarDelegate):
                delegate = _SelectionBarDelegate(view)
                view.setItemDelegate(delegate)
            delegate.set_current_row(self.currentIndex())
            # Win10 风格下**显式**左对齐（不依赖样式表默认值）。
            if theme.is_win10 and view.model() is not None:
                from PySide6.QtCore import Qt as _QtA

                model = view.model()
                for row in range(model.rowCount()):
                    model.setData(
                        model.index(row, 0),
                        int(_QtA.AlignmentFlag.AlignLeft
                            | _QtA.AlignmentFlag.AlignVCenter),
                        _QtA.ItemDataRole.TextAlignmentRole)
        except Exception:
            pass
        container = view.window()
        if container is not None and container is not self:
            # 弹窗在 show 时 Qt 会先把它摆到控件正下方。装一个事件过滤器，在 Show 事件里
            # 就把几何改成居中的 —— Show 发生在第一次绘制之前，所以屏幕上不会先闪一下
            # "在下面"再跳上来（"打开就在中间"）。
            try:
                container.removeEventFilter(self)
                container.installEventFilter(self)
            except Exception:
                pass
            # 弹窗容器默认是**不透明方窗口** —— 圆角会被背景填满、根本看不出来，边框也是
            # 实色，整体显得硬。开半透明之后 QFrame 的 border-radius 才真正切出圆角，
            # 再配一条半透明描边，观感接近 Windows 的浮出菜单。
            try:
                container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                # 用户："不要有黑边" —— 弹窗外面那圈灰黑晕影是 Windows 给无边框顶层
                # 窗口加的系统投影，不是我们画的描边（描边已经去掉了）。这里一并关掉。
                try:
                    container.setWindowFlags(
                        container.windowFlags() | Qt.WindowType.NoDropShadowWindowHint)
                except Exception:
                    pass
            except Exception:
                pass
            # 用户："改成 win10 风格的" —— Win10 的下拉是**不透明实心**菜单：
            # 纯色底 + 1px 细边框 + 小圆角（4px），没有模糊也没有亚克力。
            container.setStyleSheet(
                f"QFrame {{ background-color: transparent; border: none; }}"
                
                
            )
            container.setContentsMargins(0, 0, 0, 0)

    # ------------------------------------------------------------------ #
    def _centred_geometry(self, container) -> QRect:
        """The popup geometry with its vertical centre on the combo's centre.

        Qt puts a QComboBox popup directly below the control; the user wants the
        control's centre line to meet the popup's centre line (half above, half
        below). Clamped into the screen's available area.
        """
        final = container.geometry()
        try:
            centre_y = self.mapToGlobal(QPoint(0, self.height() // 2)).y()
            wanted_y = centre_y - final.height() // 2
            # 用户："是正方形不要接近" —— 宽高严格相等，取两者较大值（上限 320）。
            # 高的菜单（语言下拉）会被拉宽；矮而宽的菜单（主题下拉）会被拉高，
            # 多出来的高度在列表下面留白，换来的是真正的正方形卡片。
            # 用户："菜单要和控件一样宽度" —— 不再把宽度拉成正方形，直接用容器原始宽度
            # （Qt 给的弹窗宽度就等于控件宽度）；高度保持列表内容需要的高度。
            wanted_w = final.width()
            wanted_h = final.height()
            wanted_x = final.x()
            wanted_y = final.y()
            screen = QGuiApplication.screenAt(QPoint(final.x(), final.y()))
            area = screen.availableGeometry() if screen is not None else None
            if area is not None:
                # 行数多的时候可能超出屏幕底边，往上收。
                wanted_y = max(area.top() + 4,
                               min(wanted_y, area.bottom() - wanted_h - 4))
                wanted_x = max(area.left() + 4,
                               min(wanted_x, area.right() - wanted_w - 4))
            final = QRect(wanted_x, wanted_y, wanted_w, wanted_h)
        except Exception:
            pass
        return final

    @staticmethod
    @staticmethod
    def _gaussian_pixmap(pixmap, radius: float):
        """真高斯模糊（QGraphicsBlurEffect）。

        性能优化：
          · 先把图缩到一半再做高斯，做完再放大回去 —— 视觉上几乎一样，耗时降到 1/4；
          · 用 PerformanceHint 而不是 QualityHint（Quality 很慢，菜单这点模糊看不出差别）。
        """
        from PySide6.QtWidgets import (QGraphicsBlurEffect, QGraphicsPixmapItem,
                                       QGraphicsScene)

        w, h = pixmap.width(), pixmap.height()
        pad = max(2, int(radius))
        source = pixmap.toImage()
        edge = source.pixelColor(0, 0)
        padded_img = QImage(w + pad * 2, h + pad * 2,
                            QImage.Format.Format_ARGB32_Premultiplied)
        padded_img.fill(edge)
        pp = QPainter(padded_img)
        pp.drawImage(pad, pad, source)
        pp.end()

        # 降采样再做高斯
        scale = 0.5
        small = padded_img.scaled(max(1, int(padded_img.width() * scale)),
                                  max(1, int(padded_img.height() * scale)),
                                  Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(QPixmap.fromImage(small))
        effect = QGraphicsBlurEffect()
        effect.setBlurRadius(max(1.0, radius * scale))
        effect.setBlurHints(QGraphicsBlurEffect.BlurHint.PerformanceHint)
        item.setGraphicsEffect(effect)
        scene.addItem(item)
        out = QPixmap(small.size())
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        scene.render(painter)
        painter.end()
        # 放大回原尺寸并裁掉扩边
        out = out.scaled(padded_img.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
        return out.copy(pad, pad, w, h)


    def _refresh_popup_backdrop(self, container, rect=None) -> None:
        """抓弹窗背后那块屏幕 -> 高斯模糊 -> 保留颜色叠到浮出层底色上。

        性能：结果按"几何 + 主题"缓存。菜单每次都从同一位置弹出，所以第二次打开是
        直接复用，完全不卡（用户反馈"下拉不流畅"就是每次同步抓屏+高斯导致的）。
        """
        import time as _time

        started = _time.perf_counter()
        try:
            handle = container.windowHandle()
            dpr = handle.devicePixelRatio() if handle else container.devicePixelRatioF()
            dpr = dpr or 1.0
            g = rect if rect is not None else container.geometry()
            key = (g.x(), g.y(), g.width(), g.height(), dpr,
                   theme.style, theme.mode, theme.palette.flyout_bg,
                   getattr(theme, 'uses_acrylic', False))
            if getattr(self, '_backdrop_key', None) == key and \
                    getattr(self, '_popup_backdrop', None) is not None:
                logging.getLogger(__name__).debug("popup backdrop: cache hit")
                return
            physical = QRect(int(g.x() * dpr), int(g.y() * dpr),
                             max(1, int(g.width() * dpr)), max(1, int(g.height() * dpr)))
            # radius=0：不要让 mica 做圆角，否则高斯会把透明边糊成灰边。
            # 分风格：Win11 用设计 token 的圆角，Win10 是直角（用户："不要有圆边"）。
            radius = 0 if theme.is_win10 else theme.radius_flyout + 2
            shot = getattr(self, "_screen_shot", None)
            if shot is not None:
                # 从弹出前抓到的屏幕图里裁出弹窗区域 —— 这就是"下面的内容"。
                crop = shot.copy(physical.x(), physical.y(),
                                physical.width(), physical.height())
                blurred = QPixmap.fromImage(crop)
                if blurred.isNull():
                    blurred = mica.backdrop(physical, radius, dpr, 0.45,
                                            acrylic=theme.uses_acrylic)
            else:
                blurred = mica.backdrop(physical, radius, dpr, 0.45,
                                        acrylic=theme.uses_acrylic)
            blurred = self._gaussian_pixmap(blurred, max(8.0, 14.0 * dpr))
            try:
                source = blurred.toImage().convertToFormat(
                    QImage.Format.Format_ARGB32_Premultiplied)
                tinted = QImage(source.size(),
                                QImage.Format.Format_ARGB32_Premultiplied)
                tinted.fill(QColor(theme.palette.flyout_bg))
                painter = QPainter(tinted)
                painter.setOpacity(0.85)
                painter.drawImage(0, 0, source)
                painter.end()
                self._popup_backdrop = QPixmap.fromImage(tinted)
            except Exception:
                self._popup_backdrop = blurred
            self._popup_backdrop.setDevicePixelRatio(dpr)
            self._backdrop_key = key
            logging.getLogger(__name__).info(
                "popup backdrop: ok %sx%s dpr=%.2f in %.0f ms",
                self._popup_backdrop.width(), self._popup_backdrop.height(), dpr,
                (_time.perf_counter() - started) * 1000)
        except Exception as exc:
            self._popup_backdrop = None
            logging.getLogger(__name__).warning(
                "popup backdrop FAILED: %s: %s", type(exc).__name__, exc)


    def _paint_popup_container(self, container) -> None:
        from PySide6.QtGui import QPainterPath, QPen

        painter = QPainter(container)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            # 用户："不要有圆边" —— 弹窗四角改成直角。
            radius = 0
            rect = QRectF(container.rect())
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            painter.setClipPath(path)
            # Win11 风格用纯色底（用户要求改回去）；Win10 风格用高斯模糊底。
            pixmap = (getattr(self, '_popup_backdrop', None)
                      if theme.is_win10 else None)
            if pixmap is not None and not pixmap.isNull():
                painter.drawPixmap(0, 0, pixmap)
            else:
                painter.fillRect(container.rect(), QColor(theme.palette.flyout_bg))
            painter.setClipping(False)
            pen = QPen(rgba(theme.palette.flyout_border, 0.75))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # 用户："不要有黑边" —— 不画描边（之前那条 1px 的 flyout_border 在磨砂底上
            # 看着像一圈黑边）。圆角仍由上面的 clipPath 保证。
            pass
        finally:
            painter.end()

    def showPopup(self) -> None:  # noqa: N802
        self._style_popup()
        # 用户："要高斯模糊出下面的内容" —— 在弹窗出现**之前**先抓一张真实屏幕，
        # 之后再从中裁出弹窗那块做模糊，这样糊出来的是设置窗口里的内容，而不是壁纸。
        try:
            # mss 在这个环境里抓全屏会硬崩，改用 Qt 自己的屏幕截图。
            _scr = QGuiApplication.primaryScreen()
            _shot = _scr.grabWindow(0) if _scr is not None else None
            self._screen_shot = _shot.toImage() if _shot is not None else None
        except Exception:
            self._screen_shot = None
        # 用户："人眼还是能看出来了" —— 之前是在窗口出现**之后**才生成模糊底（约 23ms），
        # 那一点点准备期肉眼可见。改成在窗口出现**之前**就把它算好，这样窗口一出来
        # 就是最终画面，没有任何"准备中"的中间态。
        if theme.is_win10:
            try:
                _cont = self.view().window() if self.view() is not None else None
                if _cont is not None and _cont is not self:
                    self._refresh_popup_backdrop(
                        _cont, self._centred_geometry(_cont))
            except Exception:
                pass
        super().showPopup()
        self._animate_popup_open()

    def _animate_popup_open(self) -> None:
        """下拉弹窗的展开动画 —— 按参考录屏实测出来的 Windows 观感。

        用户发了一段 Windows 自己的菜单录屏（196x206 @30fps）。逐帧量下来：
          · 整个过渡只占 1~2 帧（约 60~100ms），非常快；
          · 把中间帧和完全打开帧逐行对比，**只有菜单底部（y=136~160）有差异**，
            顶部（y=0~40，第一行）已经完全一致 —— 也就是说
            **宽度不变、顶边固定，高度从顶部往下擦出来**，逐行露出；
          · 没有任何整体位移，也没有从中心缩放。

        之前的实现是以控件中心缩放（顶边会往上跑），方向错了，所以观感对不上。

        现在：起点 = 最终几何但高度只有 80%、**左上角不动**，动画到全高。窗口变矮时
        内容被裁切，列表自然一行行露出来。时长用 DURATION_FAST（150ms），接近录屏里
        那 1~2 帧的观感。

        三件套照旧：幂等 finished()、兜底 QTimer、碰容器的操作包 RuntimeError；
        展开期间临时关掉滚动条（尺寸在变，否则中间帧会闪一根滚动条）。
        """
        try:
            if not anim.animations_enabled():
                return
            # 用户："在 win10 风格下，菜单的弹出要采用 win10 的动画"。
            # Windows 10 的下拉是**瞬间出现**的，没有展开/淡入过程，所以这里直接返回，
            # 保持 Show 事件里已经设好的最终几何与不透明度。
            if theme.is_win10:
                return
            view = self.view()
            container = view.window() if view is not None else None
            if container is None or container is self:
                return
            final = self._centred_geometry(container)
            # 录屏逐帧实测（y 上边..下边）：
            #     关  84..110 | 中 54..126 | 中 38..152 | ... | 全部到位 38..174
            # 上边往上走了 16px、下边往下走了 48px —— 是**上下同时长**，但下边占 75%、
            # 上边只占 25%。等价于"以距顶边 25% 处为锚点缩放到 80%"。
            # （之前做成"顶边完全固定"是错的；做成"以弹窗中心缩放"则上下各半，也不对。）
            # 分风格决定展开方向：
            #   Win11 —— 像系统那样"从控件方向往下展开"：顶边固定、高度从 8px 长到全高；
            #   Win10 —— 以距顶边 25% 处为锚点、高度 80% -> 100%（下边占大部分）。
            if theme.is_win10:
                H_START = 0.80
                ANCHOR = 0.25
                start_h = max(1, int(round(final.height() * H_START)))
                start_y = final.y() + int(round((final.height() - start_h) * ANCHOR))
            else:
                # Win11：从控件那一侧往下展开，顶边不动
                # Win11：**不改变高度**（改成从 9px 长到全高看起来像"板子往下滑"，不是系统那种展开），
                # 整块一开始就是全尺寸，配合淡入 + 4px 的极轻微位移进来。
                start_h = final.height()
                start_y = final.y() - 4
            start = QRect(final.x(), start_y, final.width(), start_h)

            scrollbars = None
            try:
                scrollbars = (view.verticalScrollBarPolicy(), view.horizontalScrollBarPolicy())
                view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            except Exception:
                scrollbars = None

            if theme.is_win10:
                _dur = 360
                _fade_from = 0.55
            else:
                # Win11：系统的展开更快、淡入更彻底
                _dur = 260
                _fade_from = 0.15
            import time as _t_anim

            _anim_started = _t_anim.perf_counter()
            container.setGeometry(start)
            container.setWindowOpacity(_fade_from)
            group = QParallelAnimationGroup(container)
            fade = QPropertyAnimation(container, b"windowOpacity", group)
            # 时长按录屏实测：下边一直长到 t=933ms 才停（567ms 开始），约 370ms。
            # 之前按"帧间变化峰值"估的 100~135ms 是错的 —— 那个方法只看到第一波变化。
            # 关闭仍是瞬间完成（Qt 默认行为），不用动。
            fade.setDuration(_dur)
            fade.setStartValue(_fade_from)      # 录屏里中途亮度掉得比 0.92 更多，淡入要更明显
            fade.setEndValue(1.0)
            fade.setEasingCurve(anim.curve("out"))
            grow = QPropertyAnimation(container, b"geometry", group)
            grow.setDuration(_dur)
            grow.setStartValue(start)
            grow.setEndValue(final)
            grow.setEasingCurve(anim.curve("decelerate"))

            settled = {"done": False}

            def finished() -> None:
                if settled["done"]:
                    return
                settled["done"] = True
                try:
                    container.setWindowOpacity(1.0)
                    container.setGeometry(final)
                    if scrollbars:
                        view.setVerticalScrollBarPolicy(scrollbars[0])
                        view.setHorizontalScrollBarPolicy(scrollbars[1])
                except RuntimeError:
                    pass          # 弹窗已经关了，什么都不用做

            def _log_anim_done() -> None:
                import time as _t2
                logging.getLogger(__name__).info(
                    "popup open anim: %s in %.0f ms",
                    "win10" if theme.is_win10 else "win11",
                    (_t2.perf_counter() - _anim_started) * 1000)

            group.finished.connect(_log_anim_done)
            group.finished.connect(finished)
            group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)
            QTimer.singleShot(1400, finished)
        except Exception:
            pass

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
        width = 30 + self.indent
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
        # 当前值（checked）也有底色，只是比悬停淡一些 —— Win11 里选中项始终是"选中"的样子。
        highlighted = self._enabled and (self._hover or self._pressed)
        if self._enabled and self.checked and not highlighted:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", 0.035))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 1, -4, -1), 5, 5)
        if highlighted:
            alpha = 0.075 if self._pressed else 0.05
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(rgba("#000000" if not palette.dark else "#FFFFFF", alpha))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(4, 1, -4, -1), 5, 5)
        # 当前选中值（checked）左侧的强调色竖条。位置由 FluentMenu 统一持有 —— 逐项自绘
        # 各自为政的话，动画中途跨在两行之间就接不上，所以这里只画"落在本行内的那一段"。
        menu = self.parent()
        centre = None
        getter = getattr(menu, "bar_centre_y", None)
        if callable(getter):
            centre = getter()
        if centre is not None:
            # bar_centre_y() 给的是**菜单坐标**，而这里的 painter 是**行坐标** ——
            # 不减掉 self.y() 的话竖条会画在错误的高度，表现为每一行左边都露出一小段蓝条。
            centre = centre - self.y()
            bar_height = min(self.height() * 0.45, self.height() - 8.0)
            if bar_height > 3.0:
                painter.save()
                painter.setClipRect(QRectF(self.rect()))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(palette.accent))
                painter.drawRoundedRect(
                    QRectF(6.0, centre - bar_height / 2.0, 4.0, bar_height), 2.0, 2.0)
                painter.restore()

        # 竖条占 x 6..9，文字从 18 开始 —— 留出 9px 间隔，之前只有 3px 太挤。
        x = 18 + self.indent
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
        # 单选组（形状 / 倒计时 / 设备）在 Win11 下不画右侧对号：左侧那条短蓝条已经是
        # "当前值"的指示，两个标记同时出现是重复的。但 **Win10 下没有那条蓝条**，对号是
        # 唯一的选中标记，必须保留。开关型（录制麦克风 / 系统声音 / 开机自启）没有单选
        # 语义，两种风格下都用对号表示开或关。
        if self.checked and (theme.is_win10 or not getattr(self, "radio", False)):
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

    The selection bar's position lives here rather than in each row: animating it
    needs one thing that travels, and each row then clips the straddling bar to
    itself. Per-row state could only ever jump.
    """

    _open: set["FluentMenu"] = set()

    def _init_bar(self) -> None:
        self._bar_row = -1.0          # 浮点，行单位
        self._bar_anchor = -1         # 当前值那一行
        self._bar_anim = QVariantAnimation(self)
        self._bar_anim.setDuration(anim.DURATION_NORMAL)
        self._bar_anim.setEasingCurve(anim.curve("decelerate"))
        self._bar_anim.valueChanged.connect(self._on_bar_anim)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Stop the bar animation and drop the strong reference before we die.

        The menu is WA_DeleteOnClose, so Qt destroys the C++ object the moment it
        closes — while ``_open`` (and the running QVariantAnimation) keep the Python
        wrapper alive. Any later callback then raises

            RuntimeError: libshiboken: Internal C++ object (FluentMenu) already deleted.

        Stopping the animation and discarding ourselves from ``_open`` here removes
        both ways that could happen.
        """
        try:
            self._bar_anim.stop()
        except Exception:
            pass
        FluentMenu._open.discard(self)
        super().closeEvent(event)

    def _on_bar_anim(self, value) -> None:
        # 动画有可能在窗口已经开始销毁时回调到最后一帧，这里必须容错。
        try:
            self._bar_row = float(value)
            for item in getattr(self, "_items", []):
                item.update()
        except RuntimeError:
            pass

    def set_bar_anchor(self, row: int, *, animate: bool = True) -> None:
        """The chosen value changed: slide the bar to ``row``.

        Selection-driven on purpose — the bar marks the current value and does NOT
        follow the pointer. Hovering only shows the row's own background.
        """
        try:
            if row < 0:
                self._bar_row = -1.0
                return
            self._bar_anchor = row
            start = self._bar_row
            self._bar_anim.stop()
            if not animate or not anim.animations_enabled() or start < 0:
                self._bar_row = float(row)
                for item in getattr(self, "_items", []):
                    item.update()
                return
            self._bar_anim.setStartValue(float(start))
            self._bar_anim.setEndValue(float(row))
            self._bar_anim.start()
        except RuntimeError:
            # 菜单已经关了（WA_DeleteOnClose 把 C++ 对象销毁了），静默忽略即可。
            pass

    def bar_centre_y(self) -> float | None:
        """Where the bar's centre is, in this menu's coordinates (or None)."""
        try:
            items = getattr(self, "_items", [])
            if theme.is_win10 or self._bar_row < 0 or not items:
                return None
            low = max(0, min(len(items) - 1, int(self._bar_row)))
            high = max(0, min(len(items) - 1, low + 1))
            frac = self._bar_row - int(self._bar_row)
            low_centre = items[low].geometry().center().y()
            high_centre = items[high].geometry().center().y()
            return low_centre + (high_centre - low_centre) * frac
        except RuntimeError:
            return None

    def __init__(self, parent: QWidget | None = None, *, min_width: int = 200) -> None:
        # shadow=True：菜单是浮出层，有投影才有层次感。这里的 14px 边距正是留给阴影的
        # （native_backdrop=False 才保得住这段边距；原生 DWM 背景会把它吃掉）。
        super().__init__(None, tint_strength=0.93, margin=14, open_slide=8,
                         native_backdrop=False, shadow=True)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._min_width = min_width
        self._items: list[QWidget] = []
        self._init_bar()
        self._layout = QVBoxLayout(self)
        margin = self._margin
        self._layout.setContentsMargins(margin + 4, margin + 4, margin + 4, margin + 4)
        self._layout.setSpacing(1)

    # ------------------------------------------------------------------ #
    def add_item(self, label: str, *, icon_name: str | None = None,
                 checked: bool | None = None, enabled: bool = True, indent: int = 0,
                 radio: bool = False, keep_open: bool | None = None,
                 on_activate=None) -> PopupMenuItem:
        """Add a row.

        ``checked`` given a value marks this as a *choice* row, and by default a
        choice row keeps the menu open after being picked — so the accent bar is
        actually seen sliding to the new value (a menu that closes instantly can
        never show that). Passing no ``checked`` means an action row — 设置 / 关于 /
        打开文件夹 — which always dismisses the menu. ``radio=True`` makes it
        exclusive within the menu.

        ``keep_open=False`` overrides the default and closes after choosing, for
        menus whose whole point is to pick something and get out of the way — the
        shape menu in the main window is one: 选完形状就该收起，不然还要再点一下外面。
        """
        is_choice = checked is not None
        stays_open = is_choice if keep_open is None else bool(keep_open)

        def run() -> None:
            try:
                if on_activate is not None:
                    on_activate()
            finally:
                if is_choice:
                    self._choose(item)
                if not stays_open:
                    # A Qt.Popup only closes itself on an outside click, so choosing
                    # an entry has to dismiss the menu explicitly.
                    self.close()

        item = PopupMenuItem(label, self, icon_name=icon_name, checked=bool(checked),
                             enabled=enabled, indent=indent, on_activate=run)
        item.is_choice = is_choice
        item.radio = radio
        item.keep_open = stays_open
        self._layout.addWidget(item)
        self._items.append(item)
        if checked and self._bar_anchor < 0:
            # 锚点 = 当前值那一行；指针移出菜单后竖条回到这里
            self._bar_anchor = len(self._items) - 1
            self._bar_row = float(self._bar_anchor)
        return item

    def _choose(self, item: "PopupMenuItem") -> None:
        """A choice row was picked: move the check and slide the bar, keep open."""
        if item.radio:
            for other in self._items:
                if getattr(other, "radio", False) and other is not item:
                    other.checked = False
                    other.update()
        item.checked = True
        item.update()
        try:
            self.set_bar_anchor(self._items.index(item))
        except ValueError:
            pass

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

    def popup(self, global_pos: QPoint, *, centred: bool = False) -> None:  # noqa: N802
        """Show the menu.

        ``centred=True`` treats ``global_pos`` as the **vertical centre** the card
        should straddle, instead of its top-left corner — 菜单打开就在中间，而不是挂在
        按钮下面。传入的 y 应当是按钮的中线。位置在 show() 之前就摆好，所以不会先出现
        在别处再跳过来。
        """
        self.finalize()
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x, y = global_pos.x(), global_pos.y()
        width, height = self.width(), self.height()
        if centred:
            # 卡片比窗口小 2*margin（外边距留给阴影）。move_card_to 收的是**卡片**位置，
            # 所以按窗口高度算完中心还要补回 margin，否则卡片会整体偏上 14px。
            y = global_pos.y() - height // 2 + self._margin
        if x + width > available.right():
            x = max(available.left(), available.right() - width)
        if y + height > available.bottom():
            y = max(available.top(), available.bottom() - height)
        if y < available.top():
            y = available.top()
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
            # 不再在右侧留 4px：标题按钮贴到窗口右上角
            layout.addSpacing(0)
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

    def retranslate(self) -> None:
        for button in self.caption_buttons.values():
            button.retranslate()

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
        painter.end()


# --------------------------------------------------------------------------- #
# Toast notification
# --------------------------------------------------------------------------- #
class Toast(FluentWindow):
    """Bottom-right Fluent notification that dismisses itself."""

    _active: list["Toast"] = []

    def __init__(self, title: str, message: str = "", icon_name: str = "check",
                 *, duration: int = 3200, on_click: Callable[[], None] | None = None) -> None:
        super().__init__(None, tint_strength=0.90, margin=16, open_slide=22,
                         native_backdrop=False)
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
