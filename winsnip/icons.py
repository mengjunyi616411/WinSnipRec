"""Vector icon set drawn to match the Fluent System Icons used by Windows 11.

Drawing the glyphs ourselves means the app looks identical on Windows 10
(which ships Segoe MDL2 Assets) and Windows 11 (Segoe Fluent Icons), and keeps
the package free of font dependencies. Every glyph is authored on a 20x20 grid
with a 1.5 unit stroke, matching the official metric.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

GRID = 20.0
STROKE = 1.5

_DrawFn = Callable[[QPainter], None]
_ICONS: dict[str, _DrawFn] = {}


def _icon(name: str):
    def decorator(fn: _DrawFn) -> _DrawFn:
        _ICONS[name] = fn
        return fn
    return decorator


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #
# Painters pass the requested colour into paint_icon(); the drawing primitives
# below read it from here so every icon honours that colour (the hard-coded
# black made icons invisible on the dark theme).
_ACTIVE_COLOR = QColor(Qt.GlobalColor.black)


def _pen(width: float = STROKE) -> QPen:
    pen = QPen(_ACTIVE_COLOR)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _line(p: QPainter, x1: float, y1: float, x2: float, y2: float, width: float = STROKE) -> None:
    p.setPen(_pen(width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _poly(p: QPainter, points: list[tuple[float, float]], close: bool = False,
          fill: bool = False, width: float = STROKE) -> None:
    p.setPen(_pen(width) if not fill else QPen(Qt.PenStyle.NoPen))
    path = QPainterPath(QPointF(*points[0]))
    for x, y in points[1:]:
        path.lineTo(x, y)
    if close:
        path.closeSubpath()
    p.setBrush(QBrush(_ACTIVE_COLOR) if fill else Qt.BrushStyle.NoBrush)
    p.drawPath(path)


def _rounded(p: QPainter, x: float, y: float, w: float, h: float, r: float = 2.2,
             fill: bool = False, width: float = STROKE) -> None:
    p.setPen(_pen(width) if not fill else QPen(Qt.PenStyle.NoPen))
    p.setBrush(QBrush(_ACTIVE_COLOR) if fill else Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


def _circle(p: QPainter, cx: float, cy: float, r: float, fill: bool = False,
            width: float = STROKE) -> None:
    p.setPen(_pen(width) if not fill else QPen(Qt.PenStyle.NoPen))
    p.setBrush(QBrush(_ACTIVE_COLOR) if fill else Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)


# --------------------------------------------------------------------------- #
# Glyphs
# --------------------------------------------------------------------------- #
@_icon("add")
def _add(p: QPainter) -> None:
    _line(p, 10, 4.6, 10, 15.4)
    _line(p, 4.6, 10, 15.4, 10)


@_icon("remove")
def _remove(p: QPainter) -> None:
    _line(p, 4.6, 10, 15.4, 10)


@_icon("camera")
def _camera(p: QPainter) -> None:
    body = QPainterPath()
    body.addRoundedRect(QRectF(2.1, 6.0, 15.8, 10.2), 2.6, 2.6)
    hump = QPainterPath()
    hump.addRoundedRect(QRectF(5.0, 3.9, 5.4, 4.0), 1.4, 1.4)
    path = body.united(hump)
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _circle(p, 10.0, 11.1, 2.9)


@_icon("video")
def _video(p: QPainter) -> None:
    _rounded(p, 2.0, 6.0, 11.2, 9.0, 2.6)
    _poly(p, [(14.4, 9.3), (18.0, 6.8), (18.0, 14.2), (14.4, 11.7)], close=True, fill=True)


@_icon("video_off")
def _video_off(p: QPainter) -> None:
    _video(p)
    _line(p, 3.4, 3.4, 16.6, 16.6)


@_icon("chevron_down")
def _chevron_down(p: QPainter) -> None:
    _poly(p, [(6.6, 8.6), (10.0, 12.0), (13.4, 8.6)])


@_icon("chevron_up")
def _chevron_up(p: QPainter) -> None:
    _poly(p, [(6.6, 11.4), (10.0, 8.0), (13.4, 11.4)])


@_icon("chevron_right")
def _chevron_right(p: QPainter) -> None:
    _poly(p, [(8.6, 6.6), (12.0, 10.0), (8.6, 13.4)])


@_icon("add_rect")
def _add_rect(p: QPainter) -> None:
    _rounded(p, 2.3, 3.3, 11.4, 11.4, 2.2)
    _line(p, 12.6, 16.2, 17.4, 16.2, 1.4)
    _line(p, 15.0, 13.8, 15.0, 18.6, 1.4)


@_icon("window")
def _window(p: QPainter) -> None:
    _rounded(p, 2.4, 4.2, 15.2, 11.6, 2.2)
    _line(p, 2.4, 8.0, 17.6, 8.0, 1.3)


@_icon("fullscreen")
def _fullscreen(p: QPainter) -> None:
    _poly(p, [(3.2, 7.6), (3.2, 3.2), (7.6, 3.2)])
    _poly(p, [(12.4, 3.2), (16.8, 3.2), (16.8, 7.6)])
    _poly(p, [(16.8, 12.4), (16.8, 16.8), (12.4, 16.8)])
    _poly(p, [(7.6, 16.8), (3.2, 16.8), (3.2, 12.4)])


@_icon("freeform")
def _freeform(p: QPainter) -> None:
    path = QPainterPath(QPointF(4.0, 14.6))
    path.cubicTo(QPointF(2.2, 9.0), QPointF(6.4, 3.6), QPointF(11.2, 3.6))
    path.cubicTo(QPointF(16.4, 3.6), QPointF(18.4, 8.4), QPointF(15.2, 12.2))
    path.cubicTo(QPointF(12.6, 15.4), QPointF(7.6, 16.8), QPointF(4.0, 14.6))
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _circle(p, 4.0, 14.6, 1.5, fill=True)


@_icon("mic")
def _mic(p: QPainter) -> None:
    _rounded(p, 7.4, 2.6, 5.2, 9.6, 2.6)
    p.setPen(_pen())
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(5.0, 6.4, 10.0, 8.4), 180 * 16, 180 * 16)
    _line(p, 10.0, 14.6, 10.0, 17.4)
    _line(p, 7.2, 17.4, 12.8, 17.4)


@_icon("mic_off")
def _mic_off(p: QPainter) -> None:
    _mic(p)
    _line(p, 3.6, 3.6, 16.4, 16.4)


@_icon("pencil")
def _pencil(p: QPainter) -> None:
    path = QPainterPath(QPointF(13.1, 2.9))
    path.lineTo(17.1, 6.9)
    path.lineTo(7.5, 16.5)
    path.lineTo(2.9, 17.1)
    path.lineTo(3.5, 12.5)
    path.closeSubpath()
    p.setPen(_pen(1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _line(p, 11.3, 4.7, 15.3, 8.7, 1.3)


@_icon("highlighter")
def _highlighter(p: QPainter) -> None:
    _poly(p, [(12.6, 3.2), (16.8, 7.4), (9.6, 14.6), (5.4, 10.4)], close=True)
    _poly(p, [(5.4, 10.4), (9.6, 14.6), (7.0, 17.2), (4.4, 15.4)], close=True, fill=True)
    _line(p, 3.0, 18.4, 17.0, 18.4, 1.6)


@_icon("image_edit")
def _image_edit(p: QPainter) -> None:
    _rounded(p, 2.6, 3.6, 13.2, 11.2, 2.0)
    _poly(p, [(3.6, 13.4), (7.4, 8.8), (10.6, 12.4)])
    _circle(p, 6.6, 7.0, 1.2, fill=True)
    _poly(p, [(13.6, 12.4), (17.4, 16.2), (14.2, 17.4), (12.4, 13.6)], close=True, fill=True)


@_icon("scan_text")
def _scan_text(p: QPainter) -> None:
    _poly(p, [(3.4, 7.2), (3.4, 3.4), (7.2, 3.4)])
    _poly(p, [(12.8, 3.4), (16.6, 3.4), (16.6, 7.2)])
    _poly(p, [(16.6, 12.8), (16.6, 16.6), (12.8, 16.6)])
    _poly(p, [(7.2, 16.6), (3.4, 16.6), (3.4, 12.8)])
    _line(p, 7.0, 8.2, 13.0, 8.2, 1.3)
    _line(p, 7.0, 11.0, 13.0, 11.0, 1.3)
    _line(p, 7.0, 13.8, 10.6, 13.8, 1.3)


@_icon("more")
def _more(p: QPainter) -> None:
    for x in (4.9, 10.0, 15.1):
        _circle(p, x, 10.0, 1.45, fill=True)


@_icon("close")
def _close(p: QPainter) -> None:
    _line(p, 5.2, 5.2, 14.8, 14.8, 1.2)
    _line(p, 14.8, 5.2, 5.2, 14.8, 1.2)


@_icon("minimize")
def _minimize(p: QPainter) -> None:
    _line(p, 4.4, 10.0, 15.6, 10.0, 1.0)


@_icon("maximize")
def _maximize(p: QPainter) -> None:
    _rounded(p, 5.0, 5.0, 10.0, 10.0, 1.2, width=1.0)


@_icon("restore")
def _restore(p: QPainter) -> None:
    _rounded(p, 4.6, 7.4, 8.4, 8.4, 1.2, width=1.0)
    p.setPen(_pen(1.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(7.4, 7.4))
    path.lineTo(7.4, 5.6)
    path.quadTo(7.4, 4.2, 8.8, 4.2)
    path.lineTo(14.4, 4.2)
    path.quadTo(15.8, 4.2, 15.8, 5.6)
    path.lineTo(15.8, 11.2)
    path.quadTo(15.8, 12.6, 14.4, 12.6)
    path.lineTo(12.8, 12.6)
    p.drawPath(path)


@_icon("settings")
def _settings(p: QPainter) -> None:
    _circle(p, 10.0, 10.0, 5.6, width=1.4)
    _circle(p, 10.0, 10.0, 2.3, width=1.4)
    import math

    for i in range(8):
        angle = math.radians(i * 45)
        x1 = 10 + 5.6 * math.cos(angle)
        y1 = 10 + 5.6 * math.sin(angle)
        x2 = 10 + 7.7 * math.cos(angle)
        y2 = 10 + 7.7 * math.sin(angle)
        _line(p, x1, y1, x2, y2, 1.5)


@_icon("folder")
def _folder(p: QPainter) -> None:
    path = QPainterPath(QPointF(2.8, 15.8))
    path.lineTo(2.8, 5.6)
    path.quadTo(2.8, 4.2, 4.2, 4.2)
    path.lineTo(7.6, 4.2)
    path.lineTo(9.4, 6.6)
    path.lineTo(15.8, 6.6)
    path.quadTo(17.2, 6.6, 17.2, 8.0)
    path.lineTo(17.2, 15.8)
    path.quadTo(17.2, 17.2, 15.8, 17.2)
    path.lineTo(4.2, 17.2)
    path.quadTo(2.8, 17.2, 2.8, 15.8)
    path.closeSubpath()
    p.setPen(_pen(1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


@_icon("play")
def _play(p: QPainter) -> None:
    _poly(p, [(7.4, 5.2), (15.4, 10.0), (7.4, 14.8)], close=True, fill=True)


@_icon("pause")
def _pause(p: QPainter) -> None:
    _rounded(p, 6.4, 5.0, 2.9, 10.0, 1.3, fill=True)
    _rounded(p, 10.7, 5.0, 2.9, 10.0, 1.3, fill=True)


@_icon("stop")
def _stop(p: QPainter) -> None:
    _rounded(p, 6.0, 6.0, 8.0, 8.0, 1.5, fill=True)


@_icon("record")
def _record(p: QPainter) -> None:
    _circle(p, 10.0, 10.0, 3.4, fill=True)


@_icon("record_ring")
def _record_ring(p: QPainter) -> None:
    _circle(p, 10.0, 10.0, 5.6)
    _circle(p, 10.0, 10.0, 3.0, fill=True)


@_icon("timer")
def _timer(p: QPainter) -> None:
    _circle(p, 10.0, 11.2, 6.0)
    _line(p, 10.0, 11.2, 10.0, 7.6, 1.4)
    _line(p, 10.0, 11.2, 12.6, 11.2, 1.4)
    _line(p, 8.2, 4.0, 11.8, 4.0, 1.4)


@_icon("trash")
def _trash(p: QPainter) -> None:
    _line(p, 3.6, 6.0, 16.4, 6.0, 1.4)
    _poly(p, [(8.0, 6.0), (8.0, 4.2), (12.0, 4.2), (12.0, 6.0)])
    path = QPainterPath(QPointF(5.4, 6.0))
    path.lineTo(6.4, 16.4)
    path.quadTo(6.5, 17.4, 7.5, 17.4)
    path.lineTo(12.5, 17.4)
    path.quadTo(13.5, 17.4, 13.6, 16.4)
    path.lineTo(14.6, 6.0)
    p.setPen(_pen(1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    _line(p, 8.6, 8.8, 8.9, 14.6, 1.2)
    _line(p, 11.4, 8.8, 11.1, 14.6, 1.2)


@_icon("copy")
def _copy(p: QPainter) -> None:
    _rounded(p, 3.0, 3.0, 9.6, 9.6, 2.0, width=1.4)
    p.setPen(_pen(1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(7.4, 7.4))
    path.lineTo(15.0, 7.4)
    path.quadTo(17.0, 7.4, 17.0, 9.4)
    path.lineTo(17.0, 15.0)
    path.quadTo(17.0, 17.0, 15.0, 17.0)
    path.lineTo(9.4, 17.0)
    path.quadTo(7.4, 17.0, 7.4, 15.0)
    path.closeSubpath()
    p.drawPath(path)


@_icon("save")
def _save(p: QPainter) -> None:
    _line(p, 10.0, 3.2, 10.0, 12.4, 1.5)
    _poly(p, [(6.4, 8.8), (10.0, 12.4), (13.6, 8.8)])
    p.setPen(_pen(1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath(QPointF(3.4, 12.8))
    path.lineTo(3.4, 16.6)
    path.lineTo(16.6, 16.6)
    path.lineTo(16.6, 12.8)
    p.drawPath(path)


@_icon("check")
def _check(p: QPainter) -> None:
    _poly(p, [(4.4, 10.6), (8.4, 14.6), (15.6, 5.8)])


@_icon("magnifier")
def _magnifier(p: QPainter) -> None:
    _circle(p, 9.0, 9.0, 5.2, width=1.5)
    _line(p, 12.9, 12.9, 17.0, 17.0, 1.6)


@_icon("monitor")
def _monitor(p: QPainter) -> None:
    _rounded(p, 2.4, 3.8, 15.2, 10.4, 2.0)
    _line(p, 7.6, 17.4, 12.4, 17.4, 1.4)
    _line(p, 10.0, 14.2, 10.0, 17.4, 1.4)


@_icon("edit_pen")
def _edit_pen(p: QPainter) -> None:
    _poly(p, [(12.8, 3.0), (17.0, 7.2), (8.2, 16.0), (3.4, 16.6), (4.0, 11.8)], close=True)


@_icon("grip")
def _grip(p: QPainter) -> None:
    for row in (7.0, 13.0):
        for col in (5.0, 10.0, 15.0):
            _circle(p, col, row, 1.15, fill=True)


@_icon("info")
def _info(p: QPainter) -> None:
    _circle(p, 10.0, 10.0, 7.0, width=1.4)
    _circle(p, 10.0, 6.6, 1.0, fill=True)
    _line(p, 10.0, 9.4, 10.0, 14.0, 1.5)


@_icon("sound")
def _sound(p: QPainter) -> None:
    _poly(p, [(3.2, 8.0), (6.4, 8.0), (10.4, 4.4), (10.4, 15.6), (6.4, 12.0), (3.2, 12.0)],
          close=True, fill=True)
    p.setPen(_pen(1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(QRectF(9.0, 6.0, 6.0, 8.0), -60 * 16, 120 * 16)
    p.drawArc(QRectF(10.8, 3.4, 7.0, 13.2), -55 * 16, 110 * 16)


@_icon("sound_off")
def _sound_off(p: QPainter) -> None:
    _poly(p, [(3.2, 8.0), (6.4, 8.0), (10.4, 4.4), (10.4, 15.6), (6.4, 12.0), (3.2, 12.0)],
          close=True, fill=True)
    _line(p, 12.6, 8.0, 17.4, 12.8, 1.5)
    _line(p, 17.4, 8.0, 12.6, 12.8, 1.5)


@_icon("cursor")
def _cursor(p: QPainter) -> None:
    _poly(p, [(5.0, 3.0), (15.6, 11.0), (10.8, 11.8), (13.4, 17.0), (11.0, 18.0), (8.6, 12.6),
              (5.0, 16.6)], close=True, fill=True)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def available() -> list[str]:
    return sorted(_ICONS)


def paint_icon(painter: QPainter, name: str, rect: QRectF, color: QColor) -> None:
    """Draw ``name`` inside ``rect`` using ``color``."""
    fn = _ICONS.get(name)
    if fn is None:
        return
    global _ACTIVE_COLOR
    size = min(rect.width(), rect.height())
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.translate(rect.center())
    painter.scale(size / GRID, size / GRID)
    painter.translate(-GRID / 2, -GRID / 2)
    previous = _ACTIVE_COLOR
    _ACTIVE_COLOR = QColor(color)
    painter.setPen(QPen(_ACTIVE_COLOR))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    try:
        fn(painter)
    finally:
        _ACTIVE_COLOR = previous
    painter.restore()


class _IconColor(QColor):
    pass


def icon_pixmap(name: str, size: int, color: QColor | str, dpr: float = 1.0) -> QPixmap:
    physical = max(1, int(round(size * dpr)))
    pixmap = QPixmap(physical, physical)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    c = QColor(color)
    c.setAlphaF(1.0)
    paint_icon(painter, name, QRectF(0, 0, physical, physical), c)
    painter.end()
    return pixmap


def icon(name: str, size: int = 20, color: QColor | str = "#1A1A1B",
         dpr: float = 1.0) -> QIcon:
    result = QIcon()
    result.addPixmap(icon_pixmap(name, size, color, dpr))
    for state, tint in (("disabled", 0.4),):
        pass
    return result


def app_icon(size: int = 256) -> QIcon:
    """The application icon: a Fluent-styled camera + record badge."""
    from .theme import theme

    result = QIcon()
    for px in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(px, px)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = px / 256.0
        painter.scale(scale, scale)
        radius = 56.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0F6CBD"))
        painter.drawRoundedRect(QRectF(6, 6, 244, 244), radius, radius)
        painter.setBrush(QColor(255, 255, 255, 36))
        painter.drawRoundedRect(QRectF(6, 6, 244, 120), radius, radius)
        painter.setBrush(QColor("#FFFFFF"))
        body = QPainterPath()
        body.addRoundedRect(QRectF(44, 96, 132, 90), 22, 22)
        hump = QPainterPath()
        hump.addRoundedRect(QRectF(70, 72, 52, 40), 12, 12)
        painter.drawPath(body.united(hump))
        painter.setBrush(QColor("#0F6CBD"))
        painter.drawEllipse(QPointF(110, 141), 26, 26)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(110, 141), 15, 15)
        painter.setBrush(QColor("#E81123"))
        painter.drawEllipse(QPointF(184, 168), 46, 46)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QPointF(184, 168), 34, 34)
        painter.setBrush(QColor("#E81123"))
        painter.drawEllipse(QPointF(184, 168), 24, 24)
        painter.end()
        result.addPixmap(pixmap)
    return result
