"""Interface style test: Windows 11 look vs Windows 10 look.

Asserts the differences that actually define the two styles rather than just the
token values: corner radius, opaque-vs-Mica background, caption button hover
geometry/colour, title bar separator, and that switching takes effect live.

Run:  .venv\\Scripts\\python.exe tests\\selftest_style.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_style" / "_config"))

from PySide6.QtCore import QPoint, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import icons, winapi  # noqa: E402
from winsnip.settings import settings  # noqa: E402
from winsnip.theme import WIN10_CLOSE_HOVER, apply_app_theme, theme  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def grab_image(widget) -> QImage:
    """grab() returns device pixels; keep the ratio so probes can use logical coords."""
    return widget.grab().toImage()


def dpr_of(image: QImage, widget) -> float:
    return image.width() / max(1, widget.width())


def pixel(image: QImage, widget, logical_x: float, logical_y: float) -> QColor:
    ratio = dpr_of(image, widget)
    x = min(image.width() - 1, max(0, int(logical_x * ratio)))
    y = min(image.height() - 1, max(0, int(logical_y * ratio)))
    return image.pixelColor(x, y)


def corner_alpha(widget, inset: int = 3) -> int:
    """Alpha of a pixel just inside the card's top-left corner.

    0 (transparent) means the corner was rounded away; 255 means a square corner.
    """
    image = grab_image(widget)
    card = widget.card_rect()
    return pixel(image, widget, card.x() + inset, card.y() + inset).alpha()


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from winsnip.ui.main_window import MainWindow

    # ---------------- 1. tokens ---------------- #
    theme.style = "win11"
    check("win11：窗口有圆角、控件圆角 5",
          theme.radius_window == 8 and theme.radius_control == 5,
          f"window={theme.radius_window} control={theme.radius_control}")
    check("win11：使用 Mica 材质", theme.uses_mica)
    check("win11：标题栏按钮悬停内缩 2px", theme.caption_inset == 2)

    theme.style = "win10"
    check("win10：窗口是直角、控件圆角 2",
          theme.radius_window == 0 and theme.radius_control == 2,
          f"window={theme.radius_window} control={theme.radius_control}")
    check("win10：不使用 Mica（纯色背景）", not theme.uses_mica)
    check("win10：标题栏按钮悬停铺满整格", theme.caption_inset == 0)
    check("win10：阴影更紧更深",
          theme.shadow_opacity > 0.3 and theme.shadow_spread < 22,
          f"opacity={theme.shadow_opacity} spread={theme.shadow_spread}")

    theme.style = "system"
    check("跟随系统可解析为具体风格", theme.resolved_style in ("win11", "win10"),
          f"resolved={theme.resolved_style}  (本机 win11={winapi.is_windows_11()})")

    # ---------------- 2. rendering ---------------- #
    settings.minimize_to_tray = False
    settings.animations = False
    settings.last_mode = "video"

    windows = {}
    for style in ("win11", "win10"):
        theme.style = style
        theme.mode = "light"
        theme.refresh()
        apply_app_theme(app)
        window = MainWindow()
        window.show()
        pump(app, 0.8)
        windows[style] = window

    # 圆角：用不带投影的裸窗口量角落，否则投影会盖住被切掉的角
    from winsnip.ui.widgets import FluentWindow

    corners = {}
    for style in ("win11", "win10"):
        theme.style = style
        theme.refresh()
        probe_window = FluentWindow(None, shadow=False)
        probe_window.set_card_size(200, 120)
        probe_window.show()
        pump(app, 0.35)
        probe_window.repaint()
        corners[style] = corner_alpha(probe_window, inset=2)
        probe_window.close()
        probe_window.deleteLater()
        pump(app, 0.1)

    check("win11 窗口角落是圆的（角落被切掉）", corners["win11"] < 200,
          f"角落 alpha={corners['win11']}")
    check("win10 窗口角落是方的（角落实心）", corners["win10"] == 255,
          f"角落 alpha={corners['win10']}")

    # 材质：win11 用 Mica（壁纸模糊层），win10 直接绘制不透明底色
    for style, window in windows.items():
        theme.style = style
        theme.refresh()
        window.invalidate_backdrop()
        window.repaint()          # 同步重绘，确保 _ensure_backdrop 跑过
        pump(app, 0.35)
    backdrop_win11 = windows["win11"]._backdrop is not None
    backdrop_win10 = windows["win10"]._backdrop is not None
    check("win11 背景用 Mica 材质（有壁纸层）", backdrop_win11)
    check("win10 背景不用 Mica（走纯色分支）", not backdrop_win10,
          f"win10 backdrop={'有' if backdrop_win10 else '无'}")

    # 标题栏分隔线：win10 有，win11 没有
    # 分隔线：在干净背景下单独测 TitleBar。
    # 整窗里量不出来——命令栏本身在两种风格下都会形成一条同样明显的边界。
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from winsnip.ui.widgets import TitleBar

    def bar_bottom_edge(style: str) -> float:
        theme.style = style
        theme.refresh()
        host = QWidget()
        host.resize(620, 140)
        host.setStyleSheet("background: #F3F3F3;")
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        bar = TitleBar("测试")
        layout.addWidget(bar)
        layout.addStretch(1)
        host.show()
        pump(app, 0.35)
        image = bar.grab().toImage()
        samples = []
        for x in range(40, image.width() - 40, 4):
            samples.append(image.pixelColor(x, image.height() - 3).lightness()
                           - image.pixelColor(x, image.height() - 1).lightness())
        host.close()
        host.deleteLater()
        pump(app, 0.1)
        return sum(samples) / max(1, len(samples))

    win10_edge = bar_bottom_edge("win10")
    win11_edge = bar_bottom_edge("win11")
    check("win10 标题栏下方有一条分隔线", win10_edge >= 10,
          f"底边比上方暗 {win10_edge:.1f} 个亮度点")
    check("win11 没有这条分隔线（标题栏与内容融为一体）", win11_edge < 3,
          f"win11 底边变暗 {win11_edge:.1f}")

    # 标题栏按钮：win10 悬停铺满整格且用 #E81123
    def close_hover_size(window, style: str) -> tuple[int, tuple[int, int, int]]:
        theme.style = style
        theme.refresh()
        pump(app, 0.2)
        button = window.title_bar.caption_buttons["close"]
        button._hover = True
        button.repaint()
        pump(app, 0.1)
        image = button.grab().toImage()
        coloured = 0
        for x in range(image.width()):
            for y in range(image.height()):
                colour = image.pixelColor(x, y)
                if colour.red() > 150 and colour.green() < 90:
                    coloured += 1
        centre = image.pixelColor(image.width() // 2, 3)
        button._hover = False
        button.repaint()
        return coloured, (centre.red(), centre.green(), centre.blue())

    win11_area, _ = close_hover_size(windows["win11"], "win11")
    win10_area, win10_colour = close_hover_size(windows["win10"], "win10")
    close_button = windows["win10"].title_bar.caption_buttons["close"]
    close_image = close_button.grab().toImage()
    total = close_image.width() * close_image.height()
    check("win10 关闭键悬停铺满整格（win11 是内缩的）", win10_area > win11_area,
          f"win10 红色像素 {win10_area} vs win11 {win11_area}（整格 {total}）")
    check("win10 关闭键用经典红 #E81123",
          win10_colour == (0xE8, 0x11, 0x23),
          f"实测 #{win10_colour[0]:02X}{win10_colour[1]:02X}{win10_colour[2]:02X}")

    # ---------------- 3. live switch ---------------- #
    window = windows["win11"]
    theme.style = "win10"
    theme.refresh()
    apply_app_theme(app)
    window.invalidate_backdrop()
    pump(app, 0.5)
    check("切换后窗口立刻变直角（无需重启）",
          corner_alpha(window) == 255,
          f"角落 alpha={corner_alpha(window)}")

    # ---------------- 4. setting ---------------- #
    from winsnip.ui.settings_dialog import SettingsWindow

    settings_window = SettingsWindow()
    settings_window.show()
    pump(app, 0.6)
    combo = settings_window.style_combo
    check("设置里有「界面风格」下拉且默认 Windows 11",
          combo.count() == 3 and combo.currentIndex() == 1,
          f"index={combo.currentIndex()} items={combo.count()}")
    combo.setCurrentIndex(2)
    pump(app, 0.4)
    check("下拉切换会写进设置", settings.style == "win10", f"settings.style={settings.style}")
    check("下拉切换会立即改变主题",
          theme.resolved_style == "win10", theme.resolved_style)
    combo.setCurrentIndex(1)
    pump(app, 0.3)
    check("切回 Windows 11 也生效",
          settings.style == "win11" and theme.resolved_style == "win11",
          f"{settings.style}/{theme.resolved_style}")

    # 图标在两种风格下都要用主题色绘制（防止风格改动破坏图标）
    for style in ("win11", "win10"):
        theme.style = style
        theme.refresh()
        probe = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
        probe.fill(QColor("#FFFFFF"))
        painter = QPainter(probe)
        icons.paint_icon(painter, "camera", QRectF(0, 0, 40, 40), QColor("#FF0000"))
        painter.end()
        reds = sum(1 for x in range(40) for y in range(40)
                   if probe.pixelColor(x, y).red() > 200 and probe.pixelColor(x, y).green() < 90)
        check(f"{style} 风格下图标仍按主题色绘制", reds > 100, f"红色像素 {reds}")

    settings_window.close()
    for window in windows.values():
        window._quitting = True
        window.close()
    pump(app, 0.2)

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- STYLE SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("STYLE SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
