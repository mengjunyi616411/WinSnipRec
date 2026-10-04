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

from PySide6.QtCore import QPoint, QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import icons, winapi  # noqa: E402
from winsnip.settings import settings  # noqa: E402
from winsnip.theme import (  # noqa: E402
    WIN10_CLOSE_HOVER, apply_app_theme, application_stylesheet, theme,
)

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

    theme.style = "win11"
    check("win11：不用 Acrylic（那是 Win10 的材质）", not theme.uses_acrylic)
    check("win11：没有 Reveal 光效（Win10 才有）", not theme.uses_reveal)

    # 浅色底色离纯白只剩 12 级余量，光越淡越不像染色，所以默认给最低档。
    from winsnip.settings import Settings as _Settings

    check("光效强度默认是最低档（低）",
          _Settings().reveal_strength == "weak",
          f"Settings().reveal_strength={_Settings().reveal_strength!r}")
    _default_level = _Settings().reveal_strength
    settings.reveal_strength = _default_level
    theme.refresh()
    lowest = theme.reveal_strength
    settings.reveal_strength = "strong"
    theme.refresh()
    highest = theme.reveal_strength
    settings.reveal_strength = _default_level
    theme.refresh()
    check("默认档位的倍率是三者中最低的", lowest < highest,
          f"默认({_default_level}) 倍率 {lowest} < 高 倍率 {highest}")

    theme.style = "win10"
    check("win10：使用 Acrylic 亚克力材质", theme.uses_acrylic and not theme.uses_mica)
    # 本套件为了像素确定性默认关掉动画，而 Reveal 属于动效，先打开再断言。
    settings_backup = settings.animations
    settings.animations = True
    check("win10：启用 Reveal 跟随鼠标光效", theme.uses_reveal)
    settings.animations = False
    check("关闭界面动画后 Reveal 也停用", not theme.uses_reveal)
    settings.animations = settings_backup

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
    check("win10 背景用 Acrylic 材质（同样有壁纸层，但模糊更重）", backdrop_win10,
          f"win10 backdrop={'有' if backdrop_win10 else '无'}")

    # 标题栏分隔线：win10 有，win11 没有
    # ---- Acrylic：重模糊 + 噪点，与 Mica 的平滑渐层可区分 ----
    def grain_count(window) -> int:
        """Distinct colours in a flat strip — Acrylic's noise shows up here."""
        image = grab_image(window)
        ratio = dpr_of(image, window)
        card = window.card_rect()
        seen = set()
        # 命令栏下方一段没有控件的空白区
        for y in range(int((card.y() + 200) * ratio), int((card.y() + 250) * ratio), 2):
            for x in range(int((card.x() + 60) * ratio), int((card.right() - 60) * ratio), 2):
                if 0 <= x < image.width() and 0 <= y < image.height():
                    colour = image.pixelColor(x, y)
                    seen.add((colour.red(), colour.green(), colour.blue()))
        return len(seen)

    for style, window in windows.items():
        theme.style = style
        theme.refresh()
        window.invalidate_backdrop()
        window.repaint()
        pump(app, 0.3)

    grain_win10 = grain_count(windows["win10"])
    grain_win11 = grain_count(windows["win11"])
    check("win10 Acrylic 带噪点颗粒（平坦区域也有色彩抖动）", grain_win10 >= 8,
          f"win10 平坦区出现 {grain_win10} 种颜色")
    check("win11 Mica 是平滑渐层（噪点明显更少）", grain_win11 < grain_win10,
          f"win11 {grain_win11} vs win10 {grain_win10}")

    from winsnip.ui.settings_dialog import SettingsWindow

    # ---- Reveal：光随指针移动 ----
    # 这个测试套件为了像素确定性把动画关了，而 Reveal 属于动效，测之前先打开。
    settings.animations = True
    theme.refresh()

    def reveal_probe(window, logical_x: float, logical_y: float) -> tuple[QImage, QImage]:
        window._stop_reveal_tracking()          # 用固定指针做确定性测量
        # 走正式接口：光斑现在画在独立浮层上，直接改内部字段不会触发重绘
        window.set_reveal(QPointF(-1.0, -1.0), 0.0)
        window.repaint()
        pump(app, 0.2)
        before = window.grab().toImage()
        window.set_reveal(QPointF(logical_x, logical_y), 1.0)
        window.repaint()
        pump(app, 0.25)
        after = window.grab().toImage()
        return before, after

    def delta_at(before: QImage, after: QImage, window, lx: float, ly: float) -> int:
        ratio = dpr_of(before, window)
        x = min(before.width() - 1, int(lx * ratio))
        y = min(before.height() - 1, int(ly * ratio))
        a = before.pixelColor(x, y)
        b = after.pixelColor(x, y)
        return (abs(a.red() - b.red()) + abs(a.green() - b.green())
                + abs(a.blue() - b.blue()))

    # 标题栏要贴着窗口边缘：根布局一旦重新加上边距，标题按钮就会被推离右上角。
    for name, window in windows.items():
        bar = window.title_bar
        close = bar.caption_buttons["close"]
        right_gap = window.width() - bar.x() - bar.width()
        check(f"{name} 标题栏铺满窗口宽度", bar.x() == 0 and right_gap == 0,
              f"x={bar.x()} 宽={bar.width()} 右边距={right_gap}")
        gap = window.width() - close.x() - close.width()
        check(f"{name} 关闭按钮贴着右上角", gap == 0, f"距右边 {gap}px")

    # 设置 / 关于窗口是同一套结构，根布局一旦重新加上边距它们也会被推离边缘。
    from winsnip.ui.settings_dialog import AboutWindow, SettingsWindow

    for name, factory in (("设置", SettingsWindow), ("关于", AboutWindow)):
        extra = factory()
        extra.show()
        pump(app, 0.6)
        bar = extra.title_bar
        close = bar.caption_buttons["close"]
        gap = extra.width() - close.x() - close.width()
        check(f"{name}窗口 标题栏铺满窗口宽度",
              bar.x() == 0 and extra.width() - bar.x() - bar.width() == 0,
              f"x={bar.x()} 宽={bar.width()} 窗口={extra.width()}")
        check(f"{name}窗口 关闭按钮贴着右上角", gap == 0, f"距右边 {gap}px")
        extra.close()
        pump(app, 0.2)

    window10 = windows["win10"]
    spot_x, spot_y = window10.width() * 0.30, window10.height() * 0.40
    before, after = reveal_probe(window10, spot_x, spot_y)
    near = delta_at(before, after, window10, spot_x, spot_y)
    far = delta_at(before, after, window10, window10.width() * 0.95,
                   window10.height() * 0.92)
    check("win10 指针处出现光效", near >= 12, f"指针处色差 {near}")
    check("光效是局部的（远处不受影响）", far <= 3, f"远处色差 {far}")

    # 把指针移到别处，光斑应该跟着走
    before2, after2 = reveal_probe(window10, window10.width() * 0.72,
                                   window10.height() * 0.72)
    moved_there = delta_at(before2, after2, window10, window10.width() * 0.72,
                           window10.height() * 0.72)
    moved_old = delta_at(before2, after2, window10, spot_x, spot_y)
    # 阈值跟随光效亮度：用户反馈"太亮"后峰值被调低（深色 0.26->0.15、浅色 0.85->0.50），
    # 加上窗口几何变更，采样点色差从 ~14 降到 ~11。这里要保证的是"光斑确实跟着走"
    # （新位置有、旧位置没有），而不是具体幅度。
    check("光斑会跟着指针移动",
          moved_there >= 8 and moved_old < near,
          f"新位置色差 {moved_there}，旧位置 {moved_old}（原为 {near}）")

    # 按钮也要被光照到（子控件画在窗口之上）
    before3, after3 = reveal_probe(window10, window10.width() * 0.24,
                                   window10.height() * 0.30)
    bar_delta = 0
    samples = 0
    for lx in range(50, 600, 6):
        bar_delta += delta_at(before3, after3, window10, lx, window10.height() * 0.30)
        samples += 1
    bar_average = bar_delta / max(1, samples)
    # 契约变了：光现在画在控件下面，所以命令栏的平均变化应当很小 ——
    # 它照亮的是按钮之间的表面，而不是把按钮本身罩白。
    check("光不会把命令栏的按钮罩白（光在控件下层）",
          0.0 <= bar_average <= 6.0,
          f"命令栏平均色差 {bar_average:.2f}")

    # win11 不应该有光效（先把主题切回 win11，否则窗口仍按 win10 规则绘制）
    theme.style = "win11"
    theme.refresh()
    window11 = windows["win11"]
    before4, after4 = reveal_probe(window11, window11.width() * 0.3,
                                   window11.height() * 0.4)
    check("win11 下不出现 Reveal 光效",
          delta_at(before4, after4, window11, window11.width() * 0.3,
                   window11.height() * 0.4) <= 3,
          "win11 无变化")

    # ---- 流畅度回归：移动光斑时窗口和控件都不应该重绘 ----
    # 这是"设置窗口里光效不流畅"的根因：以前每帧都让整窗 + 所有控件重绘
    # （实测 54.5 ms/帧，18 fps），现在只有浮层重绘（~17 ms/帧，58 fps）。
    from PySide6.QtCore import QEvent, QObject

    class PaintCounter(QObject):
        """Counts repaints and remembers the largest area asked for."""

        def __init__(self, widget) -> None:
            super().__init__()
            self.count = 0
            self.max_area = 0
            self.widget = widget
            widget.installEventFilter(self)

        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() == QEvent.Type.Paint:
                self.count += 1
                rect = event.rect()
                self.max_area = max(self.max_area, rect.width() * rect.height())
            return False

    theme.style = "win10"
    theme.refresh()
    probe_window = windows["win10"]
    probe_window.set_reveal(QPointF(-1.0, -1.0), 0.0)
    pump(app, 0.2)

    window_counter = PaintCounter(probe_window)
    overlay_counter = PaintCounter(probe_window._reveal_overlay)
    button = probe_window.title_bar.caption_buttons["close"]
    button_counter = PaintCounter(button)
    pump(app, 0.1)
    window_counter.count = overlay_counter.count = button_counter.count = 0

    for step in range(6):
        probe_window.set_reveal(
            QPointF(probe_window.width() * (0.25 + 0.05 * step),
                    probe_window.height() * 0.4), 1.0)
        pump(app, 0.08)

    # 浮层是半透明的，父窗口要为它补底，所以窗口仍会重绘——但只重绘光斑所在
    # 的那一块（约 27 万像素），而不是整窗（约 43 万像素）；控件则完全不重绘。
    window_area = probe_window.width() * probe_window.height()
    check("移动光斑时窗口只重绘光斑那一小块，不重绘整窗",
          window_counter.max_area < window_area * 0.55,
          f"最大重绘区 {window_counter.max_area} / 整窗 {window_area} "
          f"({window_counter.max_area / window_area:.0%})")
    check("移动光斑时子控件不重绘", button_counter.count == 0,
          f"标题栏按钮重绘 {button_counter.count} 次")
    check("光斑确实在重绘（浮层更新了）", overlay_counter.count > 0,
          f"浮层重绘 {overlay_counter.count} 次")
    check("光斑绘制预算够用（不超过 1 帧的脏区）",
          probe_window.reveal_band().width() < probe_window.width(),
          f"脏区 {probe_window.reveal_band().width()}px / 窗口 {probe_window.width()}px")

    # ---- 光效强度 ----
    strengths = {}
    for name in ("weak", "normal", "strong"):
        settings.reveal_strength = name
        theme.refresh()
        probe_window.set_reveal(QPointF(-1.0, -1.0), 0.0)
        probe_window.repaint()
        pump(app, 0.2)
        plain = probe_window.grab().toImage()
        probe_window.set_reveal(QPointF(probe_window.width() * 0.3,
                                        probe_window.height() * 0.4), 1.0)
        probe_window.repaint()
        pump(app, 0.25)
        lit = probe_window.grab().toImage()
        strengths[name] = delta_at(plain, lit, probe_window,
                                   probe_window.width() * 0.3,
                                   probe_window.height() * 0.4)
    settings.reveal_strength = "weak"
    theme.refresh()
    check("光效强度可调（低 < 中 < 高）",
          strengths["weak"] < strengths["normal"] < strengths["strong"],
          f"低 {strengths['weak']} / 中 {strengths['normal']} / 高 {strengths['strong']}")

    # ---- 按钮悬停的 Reveal 边框 ----
    def hover_border_edge(style: str) -> float:
        theme.style = style
        theme.refresh()
        button = probe_window.title_bar.caption_buttons["close"]
        button._hover = False
        button.repaint()
        pump(app, 0.15)
        plain = button.grab().toImage()
        button._hover = True
        button.repaint()
        pump(app, 0.15)
        hovered = button.grab().toImage()
        # 按钮下边缘：悬停时应该出现一条更亮的描边
        samples = [
            abs(hovered.pixelColor(x, hovered.height() - 2).lightness()
                - plain.pixelColor(x, plain.height() - 2).lightness())
            for x in range(8, hovered.width() - 8, 2)
        ]
        button._hover = False
        button.repaint()
        return sum(samples) / max(1, len(samples))

    win10_edge = hover_border_edge("win10")
    win11_edge = hover_border_edge("win11")
    check("win10 按钮悬停有 Reveal 描边", win10_edge >= 2.0,
          f"win10 边缘亮度变化 {win10_edge:.1f}")
    check("win11 按钮悬停没有这条描边", win11_edge < win10_edge,
          f"win11 {win11_edge:.1f} vs win10 {win10_edge:.1f}")

    # ---- 浅色模式的光不能是色块 ----
    # 回归"在浅色模式下 Reveal 光效的色块明显"。三个成因都测：
    #   a) 浮层原来只有卡片大小，300px 的光在卡片边缘被硬切成直角色块
    #   b) 浅色模式用饱和强调色打光，在近白底上就是一块蓝
    #   c) 300px 的 8bit 径向渐变会出色带
    from winsnip.ui.widgets import FluentWindow

    def bare_card(mode: str, pointer: QPointF | None):
        theme.style = "win10"
        theme.mode = mode
        theme.refresh()
        apply_app_theme(app)
        card_window = FluentWindow(None, shadow=False)
        card_window.set_card_size(560, 300)
        card_window.show()
        card_window._stop_reveal_tracking()
        pump(app, 0.45)
        card_window.repaint()
        pump(app, 0.15)
        plain = card_window.grab().toImage()
        if pointer is None:
            card_window.close()
            card_window.deleteLater()
            return plain, plain, None
        card_window.set_reveal(pointer, 1.0)
        card_window.repaint()
        pump(app, 0.25)
        lit = card_window.grab().toImage()
        rect = card_window.card_rect()
        card_window.close()
        card_window.deleteLater()
        pump(app, 0.12)
        return plain, lit, rect

    # 用出厂默认档位测浅色模式 —— 这是用户实际看到的强度
    settings.reveal_strength = _Settings().reveal_strength
    theme.refresh()
    probe = QPointF(300.0, 180.0)
    plain_light, lit_light, card_light = bare_card("light", probe)
    ratio_light = lit_light.width() / (card_light.width() + card_light.x() * 2)

    def sample(image, rect, lx: float, ly: float):
        return image.pixelColor(min(image.width() - 1, int(lx * ratio_light)),
                                min(image.height() - 1, int(ly * ratio_light)))

    light_at = sample(lit_light, card_light, probe.x(), probe.y())
    light_before = sample(plain_light, card_light, probe.x(), probe.y())
    # 不能只看绝对色：浅色卡片的底是 Acrylic 透出的偏蓝壁纸，光越弱底色越明显。
    # 要判断"光是不是中性"，看的是光**带来的变化量**三通道是否一致。
    d_red = light_at.red() - light_before.red()
    d_green = light_at.green() - light_before.green()
    d_blue = light_at.blue() - light_before.blue()
    # 白光叠加在偏蓝底色上：result = bg*(1-a) + 255*a，所以 Δ = a*(255-bg)。
    # 底色偏蓝时 ΔR 本来就应该大于 ΔB —— 这不是偏色，恰恰是纯白的特征。
    # 判据是三通道反推出的 a 一致；蓝色块则会表现为 ΔB 明显大于 ΔR。
    alphas = []
    for delta, base in ((d_red, light_before.red()),
                        (d_green, light_before.green()),
                        (d_blue, light_before.blue())):
        alphas.append(delta / max(1.0, 255.0 - base))
    alpha_spread = max(alphas) - min(alphas)
    check("浅色模式的光是纯白（三通道反推的不透明度一致）",
          alpha_spread <= 0.05,
          f"ΔR={d_red} ΔG={d_green} ΔB={d_blue} → "
          f"α={['%.3f' % a for a in alphas]}，差 {alpha_spread:.3f}")
    plain_spread = light_before.blue() - light_before.red()
    lit_spread = light_at.blue() - light_at.red()
    check("光不会让画面更蓝（不是蓝色块）", lit_spread <= plain_spread + 1,
          f"无光时蓝红差 {plain_spread} → 有光时 {lit_spread}")
    check("光斑比无光时亮（是光不是污渍）", d_red >= 2, f"亮了 {d_red} 级")

    ray_steps = []
    previous = None
    for offset in range(0, 260, 2):
        value = sample(lit_light, card_light, probe.x() + offset, probe.y()).red()
        if previous is not None:
            ray_steps.append(abs(value - previous))
        previous = value
    check("浅色模式的渐变没有色带", max(ray_steps) <= 2,
          f"最大相邻跳变 {max(ray_steps)} 级")

    edge_values = [sample(lit_light, card_light, card_light.x() + d, probe.y()).red()
                   for d in (2, 6, 12, 24, 40)]
    edge_drops = [abs(edge_values[i] - edge_values[i + 1])
                  for i in range(len(edge_values) - 1)]
    check("光在卡片边缘没有被硬切出色块", max(edge_drops) <= 3,
          f"边缘内侧跳变 {edge_drops}")

    _, lit_dark, card_dark = bare_card("dark", probe)
    ratio_dark = lit_dark.width() / (card_dark.width() + card_dark.x() * 2)
    dark_at = lit_dark.pixelColor(min(lit_dark.width() - 1, int(probe.x() * ratio_dark)),
                                  min(lit_dark.height() - 1, int(probe.y() * ratio_dark)))
    check("深色模式的光仍接近白色",
          abs(dark_at.blue() - dark_at.red()) <= 24,
          f"R={dark_at.red()} G={dark_at.green()} B={dark_at.blue()}")

    # 恢复这一小节的默认状态：后面的标题栏分隔线是在浅色背景下量的
    theme.style = "win10"
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)
    for window in windows.values():
        window.invalidate_backdrop()
        window.repaint()
    pump(app, 0.3)

    # ---- 三处用户反馈的回归 ----
    # a) 光画在所有控件上层 -> 移动时把文字罩白了
    # b) 原生 QMenu 没被样式表覆盖 -> 深色模式下弹出白色菜单
    # c) 光太亮
    theme.style = "win10"
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    light_window = windows["win10"]
    overlay = light_window._reveal_overlay
    siblings = [child for child in light_window.children()]
    overlay_index = siblings.index(overlay) if overlay in siblings else -1
    check("Reveal 浮层在子控件栈的最底层（光在控件下面，不会罩住文字）",
          overlay_index == 0,
          f"浮层 index={overlay_index} / 共 {len(siblings)} 个子对象")

    # 光停在文字上时，文字区域不应该被明显提亮
    light_window._stop_reveal_tracking()
    light_window.set_reveal(QPointF(-1.0, -1.0), 0.0)
    light_window.repaint()
    pump(app, 0.25)
    before = light_window.grab().toImage()
    spot = QPointF(light_window.width() * 0.50, light_window.height() * 0.47)
    light_window.set_reveal(spot, 1.0)
    light_window.repaint()
    pump(app, 0.35)
    after = light_window.grab().toImage()

    card_box = light_window.card_rect()
    ratio_win = before.width() / light_window.width()
    brightest_before = brightest_after = 0
    for y in range(int((card_box.y() + card_box.height() * 0.40) * ratio_win),
                   int((card_box.y() + card_box.height() * 0.56) * ratio_win)):
        for x in range(int((card_box.x() + card_box.width() * 0.28) * ratio_win),
                       int((card_box.x() + card_box.width() * 0.72) * ratio_win)):
            brightest_before = max(brightest_before, before.pixelColor(x, y).lightness())
            brightest_after = max(brightest_after, after.pixelColor(x, y).lightness())
    check("光经过文字时不会把文字罩白", brightest_after - brightest_before <= 30,
          f"文字区最亮像素 {brightest_before} -> {brightest_after}"
          f"（+{brightest_after - brightest_before}）")

    # c) 亮度：光斑中心相对无光时的提升应当是克制的
    centre_lift = 0
    plain_bare, lit_bare, card_bare = bare_card("dark", QPointF(280.0, 150.0))
    ratio_bare = lit_bare.width() / (card_bare.width() + card_bare.x() * 2)

    def bare_pixel(image, lx: float, ly: float):
        return image.pixelColor(min(image.width() - 1, int(lx * ratio_bare)),
                                min(image.height() - 1, int(ly * ratio_bare)))

    centre_lift = (bare_pixel(lit_bare, 280.0, 150.0).red()
                   - bare_pixel(plain_bare, 280.0, 150.0).red())
    check("光斑中心提升是克制的（不再过亮）", 2 <= centre_lift <= 26,
          f"提升 {centre_lift} 级")

    # b) 原生 QMenu 必须跟随主题，否则深色下是白底菜单
    from PySide6.QtWidgets import QMenu as _QMenu

    menu_colours = {}
    for mode in ("dark", "light"):
        theme.mode = mode
        theme.refresh()
        apply_app_theme(app)
        menu = _QMenu()
        menu.addAction("新建截图")
        menu.addAction("设置")
        menu.show()
        pump(app, 0.25)
        image = menu.grab().toImage()
        sample = image.pixelColor(image.width() // 2, image.height() - 14)
        menu_colours[mode] = (sample.red(), sample.green(), sample.blue())
        menu.close()
        menu.deleteLater()
        pump(app, 0.15)

    check("QMenu 深色模式是深底（不再是白底菜单）",
          sum(menu_colours["dark"]) < 200,
          f"深色菜单底色 #{menu_colours['dark'][0]:02X}"
          f"{menu_colours['dark'][1]:02X}{menu_colours['dark'][2]:02X}")
    check("QMenu 浅色模式是浅底", sum(menu_colours["light"]) > 600,
          f"浅色菜单底色 #{menu_colours['light'][0]:02X}"
          f"{menu_colours['light'][1]:02X}{menu_colours['light'][2]:02X}")
    check("样式表里有 QMenu 规则", "QMenu {" in application_stylesheet())

    # 恢复浅色：后面的标题栏分隔线断言是在浅色背景下量的
    theme.style = "win10"
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)

    # ---- 动画生命周期：反复淡入淡出 + 关窗都不能崩 ----
    # 回归 "RuntimeError: libshiboken: Internal C++ object
    # (PySide6.QtCore.QVariantAnimation) already deleted."。
    # 成因：动画用 DeleteWhenStopped 启动，Qt 在动画一停就销毁 C++ 对象，而
    # self._reveal_anim 还留着失效引用，下一次淡入/淡出或关窗时 .stop() 就抛错。
    lifecycle_errors: list[str] = []
    probe_window = windows["win10"]
    probe_window._stop_reveal_tracking()
    pump(app, 0.2)
    for step in range(6):
        target = 1.0 if step % 2 == 0 else 0.0
        try:
            probe_window.set_reveal(QPointF(probe_window.width() * 0.3,
                                            probe_window.height() * 0.4),
                                    probe_window._reveal)
            probe_window._animate_reveal(target)
        except Exception as error:  # noqa: BLE001
            lifecycle_errors.append(f"第 {step} 次切换: {type(error).__name__}: {error}")
        # 等这次动画彻底结束（finished + deleteLater 都要跑完）
        end = time.perf_counter() + 0.45
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.005)
    check("Reveal 反复淡入淡出 6 次不再抛异常", not lifecycle_errors,
          lifecycle_errors[0] if lifecycle_errors else "6 次都干净")

    # 动画跑完后关窗（hideEvent 里会停动画，原崩溃也出现在这条路径上）
    try:
        probe_window._animate_reveal(1.0)
        pump(app, 0.5)
        probe_window.hide()
        probe_window.show()
        pump(app, 0.3)
        close_error = ""
    except Exception as error:  # noqa: BLE001
        close_error = f"{type(error).__name__}: {error}"
    check("动画结束后隐藏/再显示窗口不再抛异常", not close_error, close_error or "干净")

    # ---- 设置项 ----
    settings_window_probe = SettingsWindow()
    settings_window_probe.show()
    pump(app, 0.5)
    combo = settings_window_probe.reveal_combo
    labels = [combo.itemText(i) for i in range(combo.count())]
    check("设置里有「光效强度」下拉，档位为 低/中/高",
          labels == ["低", "中", "高"], f"{labels}")
    combo.setCurrentIndex(2)
    pump(app, 0.3)
    check("光效强度会写进设置", settings.reveal_strength == "strong",
          f"settings.reveal_strength={settings.reveal_strength}")
    combo.setCurrentIndex(0)
    pump(app, 0.2)
    check("选「低」写回 weak", settings.reveal_strength == "weak",
          f"settings.reveal_strength={settings.reveal_strength}")
    settings_window_probe.close()
    pump(app, 0.2)

    settings.animations = False
    theme.refresh()
    for window in windows.values():
        window._stop_reveal_tracking()

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

    # ---------------- 控件圆角必须跟着风格走 ---------------- #
    # 以前全局样式表和下拉弹窗里的圆角是写死的（3/4/5/6/8px），于是"设置"窗口在
    # Win10 风格下除了背景材质以外和 Win11 一模一样。
    import re as _re

    from winsnip.theme import application_stylesheet as _css

    radii = {}
    for _style in ("win11", "win10"):
        theme.style = _style
        theme.refresh()
        radii[_style] = [int(v) for v in _re.findall(r"border-radius:\s*(\d+)px", _css())]
    check("两种风格的控件圆角确实不同", radii["win11"] != radii["win10"],
          f"win11={radii['win11']} win10={radii['win10']}")

    theme.style = "win10"
    theme.refresh()
    check("Win10 样式表用的就是 Win10 的圆角 token",
          set(radii["win10"]) <= {theme.radius_control, theme.radius_flyout},
          f"{sorted(set(radii['win10']))} vs 控件 {theme.radius_control} / 浮出 {theme.radius_flyout}")
    theme.style = "win11"
    theme.refresh()
    check("Win11 样式表用的就是 Win11 的圆角 token",
          set(radii["win11"]) <= {theme.radius_control, theme.radius_flyout},
          f"{sorted(set(radii['win11']))} vs 控件 {theme.radius_control} / 浮出 {theme.radius_flyout}")

    # 下拉弹窗（QComboBox 的列表）同样不能写死
    from winsnip.ui.widgets import FluentComboBox

    popup_css = FluentComboBox._popup_stylesheet(FluentComboBox())
    popup_radii = [int(v) for v in _re.findall(r"border-radius:\s*(\d+)px", popup_css)]
    check("下拉弹窗的圆角也来自 token",
          popup_radii and all(v in (theme.radius_control, theme.radius_flyout) for v in popup_radii),
          f"{popup_radii} vs 控件 {theme.radius_control} / 浮出 {theme.radius_flyout}")

    # ---------------- 菜单/下拉的选中样式（Win11 的左侧强调竖条） ---------------- #
    # Win11 的菜单在选中项左侧有一条强调色竖条，配浅色圆角底；Win10 没有这条。
    # 未选中时用同宽的透明边框占位，否则选中瞬间文字会向左跳 3px。
    from winsnip.theme import application_stylesheet as _menu_css

    menu_rules = {}
    for _style in ("win11", "win10"):
        theme.style = _style
        theme.refresh()
        _css = _menu_css()
        _menu = _css[_css.index("QMenu::item {"):_css.index("QMenu::item:disabled")]
        _popup = FluentComboBox._popup_stylesheet(FluentComboBox())
        menu_rules[_style] = (
            _re.findall(r"border-left:\s*([^;]+);", _menu),
            _re.findall(r"border-left:\s*([^;]+);", _popup),
            _re.findall(r"margin:\s*([^;]+);", _menu),
            _re.findall(r"margin:\s*([^;]+);", _popup),
        )

    w11_menu, w11_popup, w11_menu_margin, w11_popup_margin = menu_rules["win11"]
    w10_menu, w10_popup, _w10_mm, _w10_pm = menu_rules["win10"]

    def _colour(decl: str) -> str:
        return decl.split()[-1] if decl else ""

    def _width(decl: str) -> str:
        return decl.split()[0] if decl else ""

    check("Win11 菜单选中项有强调色左竖条",
          len(w11_menu) == 2 and _colour(w11_menu[0]) == "transparent"
          and _colour(w11_menu[1]) not in ("", "transparent"),
          f"{w11_menu}")
    check("Win11 下拉选中项也有强调色左竖条",
          len(w11_popup) == 2 and _colour(w11_popup[0]) == "transparent"
          and _colour(w11_popup[1]) not in ("", "transparent"),
          f"{w11_popup}")
    check("Win11 竖条宽度固定（未选中用透明边框占位，文字不会跳）",
          all(_width(decl) == "3px" for decl in w11_menu + w11_popup),
          f"菜单 {w11_menu} / 下拉 {w11_popup}")
    # 竖条要短于整行：border-left 本身占满项高，所以靠 item 的上下 margin 收短。
    # （下拉弹窗里滚动条也有 margin，所以按"包含"判断而不是全等。）
    check("Win11 竖条比整行短（item 有上下 margin）",
          "4px 0" in w11_menu_margin and "4px 0" in w11_popup_margin,
          f"菜单 margin={w11_menu_margin} / 下拉 margin={w11_popup_margin}")
    check("Win10 菜单与下拉都没有这条竖条",
          not w10_menu and not w10_popup,
          f"菜单 {w10_menu} / 下拉 {w10_popup}")
    theme.style = "win11"
    theme.refresh()

    # ---------------- 截图/录屏 切换的蓝条 ---------------- #
    # Win10 的截图工具没有这条 accent 下划线，只靠图标变色。Win11 必须保留。
    from PySide6.QtGui import QColor as _QColor

    def _accent_hits(window) -> int:
        accent = _QColor(theme.palette.accent)
        segment = window.segmented
        image = segment.grab().toImage()
        hits = 0
        for y in range(max(0, image.height() - 6), image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                if (abs(c.red() - accent.red()) + abs(c.green() - accent.green())
                        + abs(c.blue() - accent.blue())) < 90:
                    hits += 1
        return hits

    theme.style = "win11"
    theme.refresh()
    window_bar11 = MainWindow()
    window_bar11.show()
    pump(app, 0.8)
    win11_hits = _accent_hits(window_bar11)
    check("Win11 下 截图/录屏 保留 accent 蓝条", win11_hits > 20, f"accent 像素 {win11_hits}")
    window_bar11._quitting = True
    window_bar11.close()
    pump(app, 0.3)

    theme.style = "win10"
    theme.refresh()
    window_bar10 = MainWindow()
    window_bar10.show()
    pump(app, 0.8)
    win10_hits = _accent_hits(window_bar10)
    check("Win10 下 截图/录屏 没有蓝条", win10_hits == 0, f"accent 像素 {win10_hits}")
    check("Win10 下仍然靠图标变色表示选中",
          window_bar10.segmented.current() == 1
          and window_bar10.segmented.indicator_position() == 1.0,
          f"current={window_bar10.segmented.current()}")
    window_bar10._quitting = True
    window_bar10.close()
    pump(app, 0.3)
    theme.style = "win11"
    theme.refresh()

    # ---------------- 明暗切换：交叉淡变 + 背景真的会变 ---------------- #
    from winsnip.anim import _ThemeFadeOverlay

    def _overlays() -> int:
        return sum(len(w.findChildren(_ThemeFadeOverlay))
                   for w in app.topLevelWidgets())

    # 淡变只在动画开启时才播（套件其余部分把动画关了），这里先打开再恢复。
    animations_before = settings.animations
    settings.animations = True
    settings.theme = "light"
    theme.style = "win11"
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)
    switch = MainWindow()
    switch.show()
    pump(app, 0.8)

    def _card_luma() -> int:
        image = switch.grab().toImage()
        c = image.pixelColor(image.width() // 2, int(image.height() * 0.55))
        return c.red() + c.green() + c.blue()

    light_luma = _card_luma()
    settings.theme = "dark"
    switch._on_settings_applied()
    # 浮层是同步创建的：这里不能再 pump，慢机器上 30ms 就可能已经淡完销毁了。
    mid_overlays = _overlays()
    check("切换明暗时出现交叉淡变浮层", mid_overlays >= 1, f"{mid_overlays} 个")
    pump(app, 1.2)
    check("淡变结束后浮层被销毁", _overlays() == 0, f"{_overlays()} 个")

    dark_luma = _card_luma()
    # 背景来自缓存的 static_card()：不清缓存的话实时切换后底色仍是旧的
    # （实测过：以深色启动是 #303233，但实时切到深色后仍停在 #F0F2F4）
    check("实时切换到深色后窗口底色真的变暗", dark_luma < light_luma - 300,
          f"浅色 {light_luma} -> 深色 {dark_luma}")

    # 改一个跟明暗无关的设置项：不应该闪
    settings.fps = 24
    switch._on_settings_applied()
    pump(app, 0.05)
    check("改非明暗设置项不会出现淡变浮层", _overlays() == 0, f"{_overlays()} 个")

    switch._quitting = True
    switch.close()
    pump(app, 0.3)
    settings.animations = animations_before
    theme.style = "win11"
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- STYLE SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("STYLE SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
