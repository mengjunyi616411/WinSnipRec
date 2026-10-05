"""Full screen dimmed overlay used to pick a screen region, window or monitor."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QImage, QKeySequence, QPainter,
    QPainterPath, QPixmap,
)
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMenu, QWidget

from .. import anim, icons, winapi
from ..theme import mica, rgba, theme, ui_font
from .widgets import FluentMenu, IconButton, Separator
from ..i18n import t as _t

HANDLE_SIZE = 8
MIN_SIZE = 8
BAR_HEIGHT = 48


class CaptureBar(QWidget):
    """The floating mode bar shown at the top of the overlay."""

    modeChanged = Signal(str)
    shapeRequested = Signal(str)
    cancelRequested = Signal()

    def __init__(self, parent: QWidget, mode: str, shape: str) -> None:
        super().__init__(parent)
        self.setFixedHeight(BAR_HEIGHT)
        self._mode = mode
        self._shape = shape
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        from .widgets import SegmentedControl

        self.segmented = SegmentedControl(
            [("camera", _t("截图")), ("video", _t("录屏"))], item_width=48, height=36
        )
        self.segmented.set_current(0 if mode == "camera" else 1)
        self.segmented.currentChanged.connect(self._on_mode)
        layout.addWidget(self.segmented)

        self.shape_button = IconButton("add_rect", self, width=64, height=36, with_chevron=True,
                                       tooltip=_t("选择捕获区域"))
        self.shape_button.clicked.connect(self._show_shape_menu)
        layout.addWidget(self.shape_button)

        layout.addWidget(Separator(self, height=20))

        self.cancel_button = IconButton("close", self, width=40, height=36, tooltip=_t("取消 (Esc)"))
        self.cancel_button.clicked.connect(self.cancelRequested.emit)
        layout.addWidget(self.cancel_button)

        self.setFixedWidth(layout.sizeHint().width())
        self._update_shape_icon()

    def _on_mode(self, index: int) -> None:
        self._mode = "camera" if index == 0 else "video"
        self.modeChanged.emit(self._mode)

    def _update_shape_icon(self) -> None:
        self.shape_button.set_icon_name({
            "rectangle": "add_rect", "window": "window",
            "fullscreen": "fullscreen", "freeform": "freeform",
        }.get(self._shape, "add_rect"))

    def set_shape(self, shape: str) -> None:
        self._shape = shape
        self._update_shape_icon()
        self.update()

    def _show_shape_menu(self) -> None:
        menu = FluentMenu(self, min_width=200)
        options = [
            ("rectangle", _t("矩形区域"), "add_rect", True),
            ("window", _t("窗口"), "window", True),
            ("fullscreen", _t("全屏"), "fullscreen", True),
            ("freeform", _t("自由绘制"), "freeform", self._mode == "camera"),
        ]
        for key, label, icon_name, enabled in options:
            menu.add_item(label, icon_name=icon_name, checked=(key == self._shape), enabled=enabled,
                          radio=True, keep_open=False,
                          on_activate=lambda k=key: self.shapeRequested.emit(k))
        menu.popup(self.shape_button.mapToGlobal(QPoint(0, self.shape_button.height() // 2)),
                   centred=True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0, 0, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.palette.overlay_chip_bg))
        painter.drawRoundedRect(rect, theme.radius_window, theme.radius_window)
        pen = painter.pen()
        pen.setWidthF(1.0)
        pen.setColor(QColor(theme.palette.flyout_border))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, theme.radius_window, theme.radius_window)
        painter.end()


class CaptureOverlay(QWidget):
    """Frozen-screen overlay with region, window, monitor and freeform picking."""

    finished = Signal(QRect, str, str)   # physical rect, shape, capture type
    cancelled = Signal()
    modeChanged = Signal(str)

    def __init__(self, mode: str = "camera", shape: str = "rectangle",
                 type_hint: str | None = None, confirm: bool = False) -> None:
        super().__init__(None)
        self._open_animated = False
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._mode = mode
        self._shape = shape
        self._type_hint = type_hint
        # Win11 starts the capture the moment the drag ends; when True the
        # selection stays adjustable and the user confirms with the chip/Enter.
        self._confirm = confirm
        self._screen_image: QImage | None = None
        self._virtual_rect = QRect(0, 0, 1920, 1080)
        self._dpr = 1.0

        self._selecting = False
        self._origin = QPoint()
        self._selection = QRect()
        self._committed_selection = False
        self._hover_window: winapi.WindowInfo | None = None
        self._drag_mode: str | None = None       # move | resize-<edge> | select
        self._drag_start = QPoint()
        self._drag_rect = QRect()
        self._freeform_points: list[QPoint] = []
        self._pointer = QPoint()

        self._bar = CaptureBar(self, mode, shape)
        self._bar.modeChanged.connect(self._on_mode_changed)
        self._bar.shapeRequested.connect(self._on_shape_requested)
        self._bar.cancelRequested.connect(self.cancel)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._open_animated:
            return
        self._open_animated = True
        if not anim.animations_enabled():
            self.setWindowOpacity(1.0)
            return
        # The frozen desktop dims in rather than snapping on, like the real
        # Snipping Tool. No slide: this window is the whole screen.
        self.setWindowOpacity(0.0)
        QTimer.singleShot(0, lambda: anim.play_window_open(
            self, fade_only=True, duration=anim.DURATION_FAST))

    def start(self) -> None:
        self._capture_screen()
        self.setGeometry(self._virtual_rect)
        self.show()
        self.raise_()
        # Take the foreground explicitly: Windows grants foreground rights to the
        # process that just handled a hotkey, and without it Esc/Enter would go to
        # whatever application was active instead of this overlay.
        try:
            winapi.force_foreground(int(self.winId()))
        except Exception:
            pass
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._position_bar()
        if self._shape == "fullscreen":
            self._select_monitor_at(QCursor.pos())
        elif self._shape == "window":
            self._update_hover_window(QCursor.pos())

    def _capture_screen(self) -> None:
        """Freeze the desktop into a QImage.

        Uses the raw BGRA grab and wraps it directly: encoding to PNG and
        decoding it again used to cost ~1-2 s for a 1920x1080 screen, which made
        the overlay appear seconds after the hotkey was pressed.
        """
        from ..core.screen import ScreenGrabber, virtual_rect

        self._virtual_rect, self._dpr = self._compute_virtual_rect()
        left, top, width, height = virtual_rect()
        grabber = ScreenGrabber()
        try:
            raw = grabber.grab((left, top, width, height))
        except Exception:
            raw = b""
        finally:
            grabber.close()

        image = QImage()
        if raw and len(raw) >= width * height * 4:
            image = QImage(raw, width, height, width * 4, QImage.Format.Format_ARGB32).copy()
        if image.isNull():
            try:
                png = ScreenGrabber().grab_png((left, top, width, height))
                image.loadFromData(png, "PNG")
            except Exception:
                pass
        if image.isNull():
            image = QImage(width, height, QImage.Format.Format_RGB32)
            image.fill(QColor(theme.palette.window_bg))
        self._screen_image = image

    def frozen_crop(self, physical: QRect) -> QImage | None:
        """Crop the frozen desktop to a physical rect (used for screenshots)."""
        if self._screen_image is None or self._screen_image.isNull():
            return None
        from ..core.screen import virtual_rect

        left, top, _, _ = virtual_rect()
        source = QRect(physical.x() - left, physical.y() - top,
                       physical.width(), physical.height())
        source = source.intersected(self._screen_image.rect())
        if source.isEmpty():
            return None
        return self._screen_image.copy(source)

    def _compute_virtual_rect(self) -> tuple[QRect, float]:
        screens = QGuiApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080), 1.0
        geometry = screens[0].geometry()
        dpr = screens[0].devicePixelRatio()
        for screen in screens[1:]:
            geometry = geometry.united(screen.geometry())
            dpr = max(dpr, screen.devicePixelRatio())
        return geometry, dpr

    def _position_bar(self) -> None:
        card = self.rect()
        x = card.left() + (card.width() - self._bar.width()) // 2
        self._bar.move(max(card.left() + 8, x), card.top() + 14)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_bar()

    def cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # Coordinate helpers
    # ------------------------------------------------------------------ #
    def _to_image(self, point: QPoint) -> QPointF:
        if not self._screen_image:
            return QPointF(point)
        sx = self._screen_image.width() / max(1, self.width())
        sy = self._screen_image.height() / max(1, self.height())
        return QPointF(point.x() * sx, point.y() * sy)

    def _to_physical(self, rect: QRect) -> QRect:
        top_left = self._to_image(rect.topLeft())
        bottom_right = self._to_image(rect.bottomRight() + QPoint(1, 1))
        from ..core.screen import virtual_rect

        left, top, _, _ = virtual_rect()
        return QRect(
            left + int(round(top_left.x())), top + int(round(top_left.y())),
            max(2, int(round(bottom_right.x() - top_left.x()))),
            max(2, int(round(bottom_right.y() - top_left.y()))),
        )

    def _from_physical(self, rect: QRect) -> QRect:
        """Physical desktop rect -> overlay-local logical rect (inverse of above)."""
        from ..core.screen import virtual_rect

        left, top, _, _ = virtual_rect()
        dpr = self._dpr or 1.0
        x = (rect.x() - left) / dpr - self._virtual_rect.left()
        y = (rect.y() - top) / dpr - self._virtual_rect.top()
        width = rect.width() / dpr
        height = rect.height() / dpr
        return QRect(int(round(x)), int(round(y)), max(2, int(round(width))),
                     max(2, int(round(height))))

    # ------------------------------------------------------------------ #
    # Interaction
    # ------------------------------------------------------------------ #
    def _on_mode_changed(self, mode: str) -> None:
        self._mode = mode
        if mode == "video" and self._shape == "freeform":
            self._shape = "rectangle"
            self._bar.set_shape(self._shape)
        self.modeChanged.emit(mode)

    def _on_shape_requested(self, shape: str) -> None:
        self._shape = shape
        self._bar.set_shape(shape)
        self._committed_selection = False
        self._selection = QRect()
        self._freeform_points.clear()
        if shape == "fullscreen":
            self._select_monitor_at(QCursor.pos())
        else:
            self._hover_window = None
        self.update()

    def _select_monitor_at(self, global_pos: QPoint) -> None:
        screen = QGuiApplication.screenAt(global_pos) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.geometry()
        self._selection = QRect(self.mapFromGlobal(geometry.topLeft()), geometry.size())
        self._committed_selection = False

    def _update_hover_window(self, global_pos: QPoint) -> None:
        physical = self._to_physical(QRect(self.mapFromGlobal(global_pos), QSize(1, 1)))
        hwnd = winapi.window_at_point(physical.x(), physical.y())
        info = winapi.window_info(hwnd) if hwnd else None
        if info is not None:
            try:
                if int(self.winId()) == hwnd:
                    info = None
            except Exception:
                pass
        self._hover_window = info

    def _hover_window_rect(self) -> QRect | None:
        if self._hover_window is None:
            return None
        info = self._hover_window
        return self._from_physical(QRect(info.left, info.top, info.width, info.height))

    def _handle_at(self, pos: QPoint) -> str | None:
        if self._selection.isNull() or self._committed_selection:
            return None
        rect = self._selection
        hs = HANDLE_SIZE
        if not rect.adjusted(-hs, -hs, hs, hs).contains(pos):
            return None
        left = abs(pos.x() - rect.left()) <= hs
        right = abs(pos.x() - rect.right()) <= hs
        top = abs(pos.y() - rect.top()) <= hs
        bottom = abs(pos.y() - rect.bottom()) <= hs
        if left and top:
            return "top-left"
        if right and top:
            return "top-right"
        if left and bottom:
            return "bottom-left"
        if right and bottom:
            return "bottom-right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        if rect.contains(pos):
            return "move"
        return None

    def _in_bar(self, pos: QPoint) -> bool:
        return self._bar.geometry().contains(pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._in_bar(pos):
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)

        if self._shape == "window":
            if self._hover_window is None:
                # The hover can be cleared by a keyboard action or a synthetic
                # event; fall back to the real cursor position before giving up.
                self._update_hover_window(QCursor.pos())
            rect = self._hover_window_rect()
            if rect is not None:
                self._selection = rect
                self._commit()
            return

        if self._shape == "fullscreen":
            self._commit()
            return

        if self._shape == "freeform":
            self._freeform_points = [pos]
            self._origin = pos
            self._selection = QRect(pos, pos)
            self._selecting = True
            self.update()
            return

        handle = self._handle_at(pos)
        if handle in ("move", "left", "right", "top", "bottom",
                      "top-left", "top-right", "bottom-left", "bottom-right"):
            self._drag_mode = handle
            self._drag_start = pos
            self._drag_rect = QRect(self._selection)
            return

        self._selecting = True
        self._committed_selection = False
        self._origin = pos
        self._selection = QRect(pos, pos)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        self._pointer = pos
        if self._shape == "window":
            self._update_hover_window(QCursor.pos())
        elif self._shape != "freeform" and not self._selecting and self._drag_mode is None:
            handle = self._handle_at(pos)
            self.setCursor({
                "move": Qt.CursorShape.SizeAllCursor,
                "left": Qt.CursorShape.SizeHorCursor, "right": Qt.CursorShape.SizeHorCursor,
                "top": Qt.CursorShape.SizeVerCursor, "bottom": Qt.CursorShape.SizeVerCursor,
                "top-left": Qt.CursorShape.SizeFDiagCursor,
                "bottom-right": Qt.CursorShape.SizeFDiagCursor,
                "top-right": Qt.CursorShape.SizeBDiagCursor,
                "bottom-left": Qt.CursorShape.SizeBDiagCursor,
            }.get(handle, Qt.CursorShape.CrossCursor))

        if self._selecting:
            if self._shape == "freeform":
                if not self._freeform_points or (pos - self._freeform_points[-1]).manhattanLength() > 3:
                    self._freeform_points.append(pos)
                rect = QRect(self._origin, pos).normalized()
                self._selection = rect
            else:
                self._selection = QRect(self._origin, pos).normalized()
        elif self._drag_mode is not None:
            delta = pos - self._drag_start
            rect = QRect(self._drag_rect)
            if self._drag_mode == "move":
                rect.translate(delta)
            else:
                if "left" in self._drag_mode:
                    rect.setLeft(min(rect.left() + delta.x(), rect.right() - MIN_SIZE))
                if "right" in self._drag_mode:
                    rect.setRight(max(rect.right() + delta.x(), rect.left() + MIN_SIZE))
                if "top" in self._drag_mode:
                    rect.setTop(min(rect.top() + delta.y(), rect.bottom() - MIN_SIZE))
                if "bottom" in self._drag_mode:
                    rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + MIN_SIZE))
            self._selection = rect
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._selecting:
            self._selecting = False
            if self._shape == "freeform":
                rect = QRect(self._origin, event.position().toPoint()).normalized()
                self._selection = rect
            if self._selection.width() < MIN_SIZE or self._selection.height() < MIN_SIZE:
                self._selection = QRect()
            self.update()
            # Windows 11 starts the capture as soon as the drag ends.
            if not self._confirm and not self._selection.isNull():
                self._commit()
        elif self._drag_mode is not None:
            self._drag_mode = None
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if not self._selection.isNull():
            self._commit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit()
        elif key == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._select_monitor_at(QCursor.pos())
            self.update()
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            if self._selection.isNull():
                return
            step = 1 if event.modifiers() & Qt.KeyboardModifier.ControlModifier else 10
            delta = {
                Qt.Key.Key_Left: QPoint(-step, 0), Qt.Key.Key_Right: QPoint(step, 0),
                Qt.Key.Key_Up: QPoint(0, -step), Qt.Key.Key_Down: QPoint(0, step),
            }[key]
            self._selection.translate(delta)
            self.update()

    def _commit(self) -> None:
        if self._selection.isNull() or self._selection.width() < MIN_SIZE:
            return
        physical = self._to_physical(self._selection)
        self.finished.emit(physical, self._shape, self._type_hint or self._mode)
        self.close()

    # ------------------------------------------------------------------ #
    # Painting
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        palette = theme.palette
        if self._screen_image is not None:
            painter.drawImage(self.rect(), self._screen_image)

        dim = QColor(0, 0, 0, 46 if not palette.dark else 92)
        active: QRect | None = None
        if self._shape == "window":
            active = self._hover_window_rect()
        elif not self._selection.isNull():
            active = self._selection

        if active is not None and self._shape == "freeform":
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.WindingFill)
            path.addRect(QRectF(self.rect()))
            if len(self._freeform_points) >= 3:
                polygon = QPainterPath()
                polygon.moveTo(QPointF(self._freeform_points[0]))
                for point in self._freeform_points[1:]:
                    polygon.lineTo(QPointF(point))
                polygon.closeSubpath()
                path = path.subtracted(polygon)
                painter.fillPath(path, dim)
                painter.setPen(QColor(palette.accent))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(polygon)
            else:
                painter.fillRect(self.rect(), dim)
        else:
            if active is not None:
                outer = QPainterPath()
                outer.addRect(QRectF(self.rect()))
                inner = QPainterPath()
                inner.addRect(QRectF(active))
                painter.fillPath(outer.subtracted(inner), dim)
            else:
                painter.fillRect(self.rect(), dim)

        if active is not None:
            self._paint_selection(painter, active)

        if active is None and self._shape != "window":
            self._paint_magnifier(painter, self._pointer)

        if active is not None and active.width() > 24 and active.height() > 24 and not self._selecting:
            self._paint_confirm_chip(painter, active)
        painter.end()

    def _paint_selection(self, painter: QPainter, rect: QRect) -> None:
        palette = theme.palette
        pen = painter.pen()
        pen.setWidthF(1.4)
        pen.setColor(QColor(palette.accent))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5))

        if self._committed_selection or self._selecting or self._shape in ("window", "fullscreen"):
            return
        for point in self._handle_points(rect):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#FFFFFF"))
            painter.drawEllipse(QPointF(point), 4.5, 4.5)
            pen = painter.pen()
            pen.setWidthF(1.2)
            pen.setColor(QColor(palette.accent))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(point), 4.5, 4.5)

    def _handle_points(self, rect: QRect) -> list[QPoint]:
        return [
            rect.topLeft(), QPoint(rect.center().x(), rect.top()), rect.topRight(),
            QPoint(rect.left(), rect.center().y()), QPoint(rect.right(), rect.center().y()),
            rect.bottomLeft(), QPoint(rect.center().x(), rect.bottom()), rect.bottomRight(),
        ]

    def _paint_confirm_chip(self, painter: QPainter, rect: QRect) -> None:
        palette = theme.palette
        label = _t("开始录屏") if self._mode == "video" else _t("截图")
        size_text = f"{self._selection.width()} × {self._selection.height()}"
        font = ui_font(12)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_width = metrics.horizontalAdvance(label) + 34
        chip_w = max(text_width, metrics.horizontalAdvance(size_text) + 24)
        chip_h = 32
        x = rect.right() - chip_w
        y = rect.bottom() + 10
        if y + chip_h > self.height() - 8:
            y = rect.bottom() - chip_h - 10
        if x < 8:
            x = 8
        if y < self._bar.geometry().bottom() + 8:
            y = self._bar.geometry().bottom() + 8
        chip = QRect(int(x), int(y), int(chip_w), chip_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.accent))
        painter.drawRoundedRect(QRectF(chip), theme.radius_control, theme.radius_control)
        icons.paint_icon(painter, "record" if self._mode == "video" else "add_rect",
                         QRectF(chip.left() + 10, chip.top() + 8, 16, 16), QColor("#FFFFFF"))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(chip.adjusted(30, 0, -8, 0),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), label)
        # size badge
        painter.setFont(ui_font(12))
        painter.setPen(QColor(palette.text_secondary))
        painter.drawText(QRect(rect.left(), rect.top() - 22, 200, 18),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), size_text)

    def _paint_magnifier(self, painter: QPainter, pos: QPoint) -> None:
        if self._screen_image is None or self._in_bar(pos):
            return
        radius = 60
        zoom = 3.0
        source = QRectF(self._to_image(pos), QSize(1, 1))
        painter.save()
        circle = QPainterPath()
        circle.addEllipse(QPointF(pos), radius, radius)
        painter.setClipPath(circle)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        target = QRectF(pos.x() - radius * zoom / 2, pos.y() - radius * zoom / 2,
                        radius * zoom, radius * zoom)
        painter.drawImage(target, self._screen_image,
                          QRectF(size=QSize(int(radius * 2 / 1.0), int(radius * 2 / 1.0))).translated(
                              self._to_image(pos) - QPointF(radius, radius)))
        painter.restore()
        pen = painter.pen()
        pen.setWidthF(1.6)
        pen.setColor(QColor(255, 255, 255, 230))
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(pos), radius, radius)
        # crosshair
        pen.setWidthF(1.0)
        pen.setColor(QColor(0, 0, 0, 150))
        painter.setPen(pen)
        painter.drawLine(QPointF(pos.x() - 6, pos.y()), QPointF(pos.x() + 6, pos.y()))
        painter.drawLine(QPointF(pos.x(), pos.y() - 6), QPointF(pos.x(), pos.y() + 6))

        physical = self._to_physical(QRect(pos, QSize(1, 1)))
        text = f"{physical.x()}, {physical.y()}"
        font = ui_font(11)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text_rect = QRect(pos.x() - metrics.horizontalAdvance(text) // 2 - 8, pos.y() + radius + 6,
                          metrics.horizontalAdvance(text) + 16, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 160))
        painter.drawRoundedRect(QRectF(text_rect), 4, 4)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(text_rect, int(Qt.AlignmentFlag.AlignCenter), text)
