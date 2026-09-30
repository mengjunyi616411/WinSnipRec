"""Turn the measured performance data into charts.

Run:  .venv\\Scripts\\python.exe tools\\make_perf_charts.py
Out:  <project>/perf/*.png  (一张汇总信息图 + 5 张单图)

All numbers come from tools/bench_encode.py and tools/bench_runtime.py, run on
an i7-6700HQ (4C/8T @2.6GHz) / 16GB with the app's own ffmpeg settings.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor, QFont, QFontMetrics, QImage, QLinearGradient, QPainter, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import winapi  # noqa: E402
from winsnip.theme import theme  # noqa: E402

OUT = ROOT / "perf"

# --------------------------------------------------------------------------- #
# Measured data
# --------------------------------------------------------------------------- #
# cores = CPU-seconds per second of video (1.0 = exactly realtime)
ENCODE_MOTION = [("1280x720@30", 2.30), ("1920x1080@30", 4.62), ("1920x1080@60", 8.70),
                 ("2560x1440@30", 7.85), ("3840x2160@30", 17.77)]
ENCODE_STATIC = [("1920x1080@30", 2.14), ("1920x1080@60", 4.25)]
CONTENT_COMPARE = [("1920x1080@30", 2.14, 4.62), ("1920x1080@60", 4.25, 8.70)]
ENCODERS = [("libx264 软编", 4.62), ("MediaFoundation", 3.12),
            ("QuickSync 集显", 2.78), ("NVENC 独显", 0.14)]
DISK = [("1280x720@30", 0.41, 1.64), ("1920x1080@30", 0.82, 3.26),
        ("1920x1080@60", 1.21, 4.82), ("2560x1440@30", 1.39, 5.55),
        ("3840x2160@30", 3.08, 12.30)]
CAPTURE = [("640x480", 29.0), ("1280x720", 56.9), ("1920x1080", 112.2)]

CPU_NAME = "i7-6700HQ（4 核 8 线程 / 2.6GHz）"
CPU_THREADS = 8

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #
def c(hex_value: str, alpha: float = 1.0) -> QColor:
    colour = QColor(hex_value)
    colour.setAlphaF(alpha)
    return colour


ACCENT = "#3FACFF"
ACCENT_SOFT = "#1E6FA8"
MUTED = "#8FA3B8"
GOOD = "#4ADE80"
WARN = "#FBBF24"
BAD = "#F87171"
TEXT = "#F2F6FA"
TEXT_DIM = "#93A2B3"
GRID = "#FFFFFF"

CJK = ["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI Variable Display", "Segoe UI"]


def font(size: int, weight: int = 400) -> QFont:
    f = QFont()
    f.setFamilies(CJK)
    f.setPixelSize(size)
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return f


def text(painter: QPainter, value: str, rect: QRectF, size: int, colour: QColor,
         weight: int = 400, align=Qt.AlignmentFlag.AlignLeft) -> None:
    painter.setFont(font(size, weight))
    painter.setPen(colour)
    painter.drawText(rect, int(align | Qt.AlignmentFlag.AlignVCenter), value)


# --------------------------------------------------------------------------- #
# Chart primitives
# --------------------------------------------------------------------------- #
def grid_and_axis(painter: QPainter, plot: QRectF, top: float, ticks: int,
                  unit: str = "") -> None:
    painter.setFont(font(14))
    for index in range(ticks + 1):
        value = top * index / ticks
        y = plot.bottom() - plot.height() * index / ticks
        pen = QPen(c(GRID, 0.10 if index else 0.22))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        painter.setPen(c(TEXT_DIM))
        painter.drawText(QRectF(plot.left() - 62, y - 11, 54, 22),
                         int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                         f"{value:g}{unit}")


def vbars(painter: QPainter, plot: QRectF, groups: list[str],
          series: list[tuple[str, list[float], str]], top: float,
          value_fmt: str = "{:.2f}") -> None:
    count = len(groups)
    slot = plot.width() / count
    bar_w = min(64.0, slot * 0.62 / max(1, len(series)))
    for gi, group in enumerate(groups):
        centre = plot.left() + slot * (gi + 0.5)
        total_w = bar_w * len(series) + 8 * (len(series) - 1)
        x = centre - total_w / 2
        for name, values, colour in series:
            value = values[gi]
            height = plot.height() * value / top
            rect = QRectF(x, plot.bottom() - height, bar_w, height)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(c(colour))
            painter.drawRoundedRect(rect, 5, 5)
            painter.setBrush(c(colour, 0.28))
            painter.drawRoundedRect(QRectF(rect.x(), rect.bottom() - 5, rect.width(), 5), 4, 4)
            text(painter, value_fmt.format(value),
                 QRectF(rect.x() - 12, rect.y() - 26, rect.width() + 24, 22), 15, TEXT, 500,
                 Qt.AlignmentFlag.AlignHCenter)
            x += bar_w + 8
        text(painter, group, QRectF(centre - slot / 2, plot.bottom() + 8, slot, 24), 15,
             TEXT_DIM, 400, Qt.AlignmentFlag.AlignHCenter)


def hbars(painter: QPainter, plot: QRectF, items: list[tuple[str, float]],
          top: float, colours: list[str], unit: str = " 核",
          note_for: dict[str, str] | None = None) -> None:
    height = plot.height() / max(1, len(items))
    bar_h = min(30.0, height * 0.52)
    for index, (label, value) in enumerate(items):
        y = plot.top() + height * (index + 0.5)
        text(painter, label, QRectF(plot.left() - 250, y - 14, 236, 28), 16, TEXT, 400,
             Qt.AlignmentFlag.AlignRight)
        width = plot.width() * value / top
        rect = QRectF(plot.left(), y - bar_h / 2, max(3.0, width), bar_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colours[index % len(colours)]))
        painter.drawRoundedRect(rect, 5, 5)
        note = (note_for or {}).get(label, "")
        text(painter, f"{value:g}{unit}{note}",
             QRectF(rect.right() + 10, y - 14, plot.width() - width + 150, 28), 16,
             TEXT, 500)


def legend(painter: QPainter, x: float, y: float,
           entries: list[tuple[str, str]]) -> None:
    for name, colour in entries:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colour))
        painter.drawRoundedRect(QRectF(x, y + 5, 14, 14), 4, 4)
        text(painter, name, QRectF(x + 22, y, 240, 24), 15, TEXT_DIM)
        x += 34 + QFontMetrics(font(15)).horizontalAdvance(name)


def chart_title(painter: QPainter, title: str, subtitle: str, x: float, y: float) -> None:
    text(painter, title, QRectF(x, y, 1100, 34), 24, TEXT, 600)
    if subtitle:
        text(painter, subtitle, QRectF(x, y + 30, 1200, 26), 15, TEXT_DIM)


# --------------------------------------------------------------------------- #
# Individual charts
# --------------------------------------------------------------------------- #
def render_encode_cpu(width: int = 1400, height: int = 640) -> QImage:
    image = blank(width, height, "编码 CPU 消耗（越高越吃性能）",
                  f"{CPU_NAME} · libx264 veryfast CRF20 · 数值 = CPU 秒 / 每秒视频")
    painter = QPainter(image)
    plot = QRectF(360, 190, width - 470, height - 290)
    top = 20.0

    # zone shading: comfortable / tight / impossible
    for lo, hi, colour, label in ((0, 1.5, GOOD, "富余"), (1.5, 3.0, WARN, "吃紧"),
                                  (3.0, top, BAD, "低端机跑不动")):
        x0 = plot.left() + plot.width() * lo / top
        x1 = plot.left() + plot.width() * min(hi, top) / top
        if x0 >= plot.right():
            continue
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colour, 0.10))
        painter.drawRect(QRectF(x0, plot.top(), x1 - x0, plot.height()))
        if x1 - x0 > 90:
            text(painter, label, QRectF(x0 + 10, plot.top() + 6, x1 - x0 - 20, 24), 14,
                 c(colour, 0.9))
    for value, label in ((1.0, "1 核 = 刚好实时"), (float(CPU_THREADS), "本机 8 线程")):
        x = plot.left() + plot.width() * value / top
        pen = QPen(c(TEXT, 0.5) if value == 1 else c(BAD, 0.85))
        pen.setWidthF(1.4)
        pen.setDashPattern([6, 4])
        painter.setPen(pen)
        painter.drawLine(QPointF(x, plot.top() - 6), QPointF(x, plot.bottom() + 6))
        text(painter, label, QRectF(x + 6, plot.top() - 34, 220, 24), 14,
             c(TEXT, 0.75) if value == 1 else c(BAD))
    for index in range(5):
        x = plot.left() + plot.width() * index / 5
        pen = QPen(c(GRID, 0.10))
        painter.setPen(pen)
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(c(TEXT_DIM))
        painter.drawText(QRectF(x - 24, plot.bottom() + 8, 48, 22),
                         int(Qt.AlignmentFlag.AlignHCenter), f"{index * 4}")

    painter.setPen(Qt.PenStyle.NoPen)
    for index, (label, value) in enumerate(ENCODE_MOTION):
        slot = plot.height() / len(ENCODE_MOTION)
        y = plot.top() + slot * (index + 0.5)
        colour = GOOD if value < 1.5 else (WARN if value < 3 else BAD)
        text(painter, label, QRectF(plot.left() - 250, y - 14, 236, 28), 16, TEXT, 400,
             Qt.AlignmentFlag.AlignRight)
        bar = QRectF(plot.left(), y - 15, max(3.0, plot.width() * value / top), 30)
        painter.setBrush(c(colour))
        painter.drawRoundedRect(bar, 5, 5)
        text(painter, f"{value:g} 核", QRectF(bar.right() + 12, y - 14, 160, 28), 16, TEXT, 500)
    painter.end()
    return image


def render_content(width: int = 1400, height: int = 620) -> QImage:
    image = blank(width, height, "内容复杂度的影响",
                  "同样的分辨率，画面动得越厉害越吃 CPU —— 静态桌面只有全动态的一半不到")
    painter = QPainter(image)
    plot = QRectF(200, 200, width - 300, height - 320)
    grid_and_axis(painter, plot, 10.0, 5, " 核")
    vbars(painter, plot, [g for g, _s, _m in CONTENT_COMPARE],
          [("静止桌面", [s for _g, s, _m in CONTENT_COMPARE], ACCENT_SOFT),
           ("全动态", [m for _g, _s, m in CONTENT_COMPARE], ACCENT)], 10.0)
    legend(painter, 200, height - 74,
           [("静止桌面（挂机/看文档）", ACCENT_SOFT), ("全动态（播视频/滚动）", ACCENT)])
    painter.end()
    return image


def render_encoders(width: int = 1400, height: int = 560) -> QImage:
    image = blank(width, height, "软编 vs 硬编（1920x1080@30 全动态）",
                  "同一素材、同一帧率，只换编码器：独显硬件编码几乎不占 CPU")
    painter = QPainter(image)
    plot = QRectF(380, 200, width - 500, height - 300)
    values = [v for _n, v in ENCODERS]
    top = 5.0
    colours = [BAD, WARN, WARN, GOOD]
    for index in range(6):
        x = plot.left() + plot.width() * index / 5
        pen = QPen(c(GRID, 0.10))
        painter.setPen(pen)
        painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        painter.setPen(c(TEXT_DIM))
        painter.drawText(QRectF(x - 20, plot.bottom() + 8, 40, 22),
                         int(Qt.AlignmentFlag.AlignHCenter), f"{index}")
    text(painter, "核", QRectF(plot.left() - 46, plot.top() - 30, 40, 22), 14, TEXT_DIM,
         align=Qt.AlignmentFlag.AlignRight)
    hbars(painter, plot, ENCODERS, top, colours, unit=" 核",
          note_for={"NVENC 独显": "（≈ 不占 CPU）"})
    painter.end()
    return image


def render_disk(width: int = 1400, height: int = 640) -> QImage:
    image = blank(width, height, "每小时占用磁盘",
                  "CRF20 质量档，码率随内容变化：日常操作取实测上下限的中位估计")
    painter = QPainter(image)
    plot = QRectF(200, 200, width - 300, height - 330)
    grid_and_axis(painter, plot, 15.0, 5, " GB")
    vbars(painter, plot, [g for g, _d, _m in DISK],
          [("日常操作", [d for _g, d, _m in DISK], ACCENT_SOFT),
           ("播视频", [m for _g, _d, m in DISK], ACCENT)], 15.0, value_fmt="{:.1f}")
    legend(painter, 200, height - 78,
           [("日常操作（写文档/看网页）", ACCENT_SOFT), ("播视频/游戏画面", ACCENT)])
    painter.end()
    return image


def render_capture(width: int = 1400, height: int = 620) -> QImage:
    image = blank(width, height, "抓屏开销（单帧耗时）",
                  "本机是虚拟机 + 虚拟显示适配器，GDI 抓屏异常慢；普通显卡约 20~40 倍于此")
    painter = QPainter(image)
    plot = QRectF(200, 200, width - 300, height - 330)
    top = 120.0
    grid_and_axis(painter, plot, top, 4, " ms")
    labels = [label for label, _v in CAPTURE]
    values = [value for _l, value in CAPTURE]
    slot = plot.width() / len(labels)
    for index, (label, value) in enumerate(CAPTURE):
        x = plot.left() + slot * (index + 0.5) - 60
        height_px = plot.height() * value / top
        rect = QRectF(x, plot.bottom() - height_px, 120, height_px)
        colour = BAD if value > 90 else (WARN if value > 40 else GOOD)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colour))
        painter.drawRoundedRect(rect, 6, 6)
        text(painter, f"{value:g} ms", QRectF(rect.x() - 20, rect.y() - 28, 160, 24), 16, TEXT,
             500, Qt.AlignmentFlag.AlignHCenter)
        fps = 1000 / value
        text(painter, f"上限 {fps:.0f} fps", QRectF(rect.x() - 20, rect.bottom() + 6, 160, 24),
             14, TEXT_DIM, 400, Qt.AlignmentFlag.AlignHCenter)
        text(painter, label, QRectF(rect.x() - 20, plot.bottom() + 34, 160, 26), 16, TEXT, 400,
             Qt.AlignmentFlag.AlignHCenter)
    # normal-hardware reference band
    ref_y = plot.bottom() - plot.height() * 6 / top
    pen = QPen(c(GOOD, 0.9))
    pen.setWidthF(1.6)
    pen.setDashPattern([7, 5])
    painter.setPen(pen)
    painter.drawLine(QPointF(plot.left(), ref_y), QPointF(plot.right(), ref_y))
    text(painter, "虚线 = 普通显卡（独显 / 集显）1920x1080 参考 ≈ 2~6 ms",
         QRectF(plot.left() + 6, plot.top() + 6, 460, 24), 15, GOOD)
    painter.end()
    return image


# --------------------------------------------------------------------------- #
def blank(width: int, height: int, title: str, subtitle: str) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gradient = QLinearGradient(0, 0, width * 0.4, height)
    gradient.setColorAt(0.0, QColor("#0C1118"))
    gradient.setColorAt(0.5, QColor("#121A24"))
    gradient.setColorAt(1.0, QColor("#080B10"))
    painter.fillRect(0, 0, width, height, gradient)
    glow = QRadialGradient(QPointF(width * 0.85, height * 0.1), width * 0.5)
    glow.setColorAt(0.0, c(ACCENT, 0.14))
    glow.setColorAt(1.0, c(ACCENT, 0.0))
    painter.fillRect(0, 0, width, height, glow)
    chart_title(painter, title, subtitle, 76, 62)
    painter.end()
    return image


def render_overview() -> QImage:
    """One infographic with every chart stacked."""
    width = 1400
    parts = [(render_encode_cpu(width), 0), (render_content(width), 0),
             (render_encoders(width), 0), (render_disk(width), 0),
             (render_capture(width), 0)]
    header = 250
    footer = 330
    gap = 18
    total = header + footer + sum(image.height() + gap for image, _ in parts)

    image = QImage(width, total, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    gradient = QLinearGradient(0, 0, width * 0.5, total)
    gradient.setColorAt(0.0, QColor("#0B1017"))
    gradient.setColorAt(0.45, QColor("#121A24"))
    gradient.setColorAt(1.0, QColor("#080B10"))
    painter.fillRect(0, 0, width, total, gradient)
    glow = QRadialGradient(QPointF(width * 0.86, 120), width * 0.6)
    glow.setColorAt(0.0, c(ACCENT, 0.16))
    glow.setColorAt(1.0, c(ACCENT, 0.0))
    painter.fillRect(0, 0, width, 900, glow)

    text(painter, "性能实测 · 截图工具 WinSnipRec", QRectF(76, 58, 1100, 54), 42, TEXT, 600)
    text(painter, "全部数字为本机实测（不是估算）：i7-6700HQ 4 核 8 线程 / 2.6GHz · 16GB · "
                  "libx264 veryfast CRF20", QRectF(76, 116, 1200, 30), 17, TEXT_DIM)
    text(painter, "“核” = 编码消耗的 CPU 秒 / 每秒视频，1.0 核代表刚好能实时录制",
         QRectF(76, 146, 1200, 30), 17, TEXT_DIM)
    x = 78
    for label, colour in (("富余 <1.5 核", GOOD), ("吃紧 1.5~3 核", WARN), ("跑不动 >3 核", BAD)):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colour, 0.20))
        w = QFontMetrics(font(16)).horizontalAdvance(label) + 42
        painter.drawRoundedRect(QRectF(x, 190, w, 36), 18, 18)
        painter.setBrush(c(colour))
        painter.drawEllipse(QRectF(x + 14, 200, 16, 16))
        text(painter, label, QRectF(x + 36, 190, w - 40, 36), 16, TEXT, 500)
        x += w + 14

    y = header
    for chart, _ in parts:
        painter.drawImage(76, y, chart, 76, 0, width - 152, chart.height())
        y += chart.height() + gap

    # footer: recommendations
    box = QRectF(76, y + 8, width - 152, footer - 40)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(c("#FFFFFF", 0.05))
    painter.drawRoundedRect(box, 16, 16)
    pen = QPen(c("#FFFFFF", 0.12))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(box, 16, 16)
    text(painter, "结论与配置建议", QRectF(box.left() + 28, box.top() + 22, 400, 32), 22, TEXT, 600)

    rows = [
        ("最低", "双核四线程 · 4GB", "720p30 任意内容；1080p30 只适合静态/轻量操作", WARN),
        ("推荐", "4 核 8 线程 · 8GB", "1080p30 任意内容流畅，1080p60 静态可用", GOOD),
        ("舒适", "6~8 核现代 CPU · 16GB", "1080p60 / 1440p30 无压力；带独显可 4K30", GOOD),
    ]
    ry = box.top() + 74
    for tag, spec, detail, colour in rows:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c(colour, 0.18))
        painter.drawRoundedRect(QRectF(box.left() + 28, ry, 74, 34), 9, 9)
        text(painter, tag, QRectF(box.left() + 28, ry, 74, 34), 16, colour, 600,
             Qt.AlignmentFlag.AlignHCenter)
        text(painter, spec, QRectF(box.left() + 118, ry, 320, 34), 17, TEXT, 500)
        text(painter, detail, QRectF(box.left() + 440, ry, 700, 34), 16, TEXT_DIM)
        ry += 48
    text(painter, "瓶颈是 H.264 软编码：界面空转 ≈0% CPU，内存 126MB（录制 1080p 峰值 185MB）。"
                  "现代桌面 CPU 比本机快 2~3 倍，上表核数按此换算。",
         QRectF(box.left() + 28, ry + 6, box.width() - 56, 28), 15, TEXT_DIM)
    painter.end()
    return image


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)  # noqa: F841
    theme.mode = "dark"
    theme.refresh()
    OUT.mkdir(parents=True, exist_ok=True)

    outputs = {
        "chart_encode_cpu.png": render_encode_cpu(),
        "chart_content.png": render_content(),
        "chart_encoder.png": render_encoders(),
        "chart_disk.png": render_disk(),
        "chart_capture.png": render_capture(),
        "perf_overview.png": render_overview(),
    }
    for name, image in outputs.items():
        path = OUT / name
        image.save(str(path), "PNG")
        print(f"[ok] {path.relative_to(ROOT)}  {image.width()}x{image.height()}  "
              f"{path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
