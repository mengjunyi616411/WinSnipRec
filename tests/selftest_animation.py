"""Animation / splash test.

Run:  .venv\\Scripts\\python.exe tests\\selftest_animation.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_anim" / "_config"))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import anim, winapi  # noqa: E402
from winsnip.settings import settings  # noqa: E402
from winsnip.theme import apply_app_theme, theme  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    theme.mode = "light"
    apply_app_theme(app)

    from winsnip.ui.main_window import MainWindow
    from winsnip.ui.splash import MIN_VISIBLE_MS, ProgressRing, SplashWindow

    # ---------------- setting gate ---------------- #
    original = settings.animations
    settings.animations = True
    check("开启时 animations_enabled() 为真（且受 Windows 设置约束）",
          anim.animations_enabled() == winapi.client_area_animations_enabled(),
          f"app=True, windows={winapi.client_area_animations_enabled()}")
    settings.animations = False
    check("设置里关闭后 animations_enabled() 为假", not anim.animations_enabled())
    check("Windows 的动画开关可读取", isinstance(winapi.client_area_animations_enabled(), bool),
          str(winapi.client_area_animations_enabled()))

    # ---------------- disabled: no animation ---------------- #
    window = MainWindow()
    final_geometry = QRect(window.geometry())
    window.setWindowOpacity(1.0)
    anim.show_window_animated(window)
    pump(app, 0.15)
    check("关闭动画时窗口立即完全显示",
          window.isVisible() and window.windowOpacity() == 1.0,
          f"opacity={window.windowOpacity()}")
    window.hide()
    pump(app, 0.1)

    # ---------------- enabled: fade + slide ---------------- #
    settings.animations = True
    window.hide()
    window.setWindowOpacity(1.0)
    window.move(final_geometry.x(), final_geometry.y() + 60)
    pump(app, 0.05)
    target_geometry = QRect(window.geometry())   # where the animation should land

    samples: list[float] = []
    anim.show_window_animated(window, slide=14, duration=240)
    started = time.perf_counter()
    while time.perf_counter() - started < 0.5:
        app.processEvents()
        samples.append(window.windowOpacity())
        time.sleep(0.008)

    check("动画期间透明度单调上升", all(b >= a - 0.02 for a, b in zip(samples, samples[1:])),
          f"{samples[:6]}")
    check("动画确实产生了中间帧（不是直接跳到 1）",
          any(0.05 < value < 0.95 for value in samples),
          f"{min(samples):.2f} ~ {max(samples):.2f}")
    check("动画结束后完全不透明", abs(window.windowOpacity() - 1.0) < 1e-6,
          f"{window.windowOpacity()}")
    check("动画结束后回到目标位置", window.geometry() == target_geometry,
          f"{window.geometry()} vs {target_geometry}")

    # Regression guard: moving a window before show() pins it to Qt's default
    # position, which made a freshly launched window appear in the top-left
    # corner instead of where Windows centres it.
    from PySide6.QtGui import QGuiApplication

    fresh = MainWindow()
    anim.show_window_animated(fresh)
    pump(app, 0.5)
    screen_centre = QGuiApplication.primaryScreen().availableGeometry().center()
    fresh_centre = fresh.geometry().center()
    check("首次显示的窗口动画后仍居中（没被挪到左上角）",
          abs(fresh_centre.x() - screen_centre.x()) < 80
          and abs(fresh_centre.y() - screen_centre.y()) < 120,
          f"窗口中心 {fresh_centre.x()},{fresh_centre.y()} / 桌面中心 "
          f"{screen_centre.x()},{screen_centre.y()}")
    fresh._quitting = True
    fresh.close()
    pump(app, 0.2)
    check("动画结束后解除 Mica 冻结", not getattr(window, "_freeze_backdrop", True))

    # ---------------- hide ---------------- #
    anim.hide_window_animated(window)
    pump(app, 0.4)
    check("淡出后窗口已隐藏", not window.isVisible())
    check("淡出后透明度复原", abs(window.windowOpacity() - 1.0) < 1e-6,
          f"{window.windowOpacity()}")

    # ---------------- progress ring ---------------- #
    ring = ProgressRing(None, 30, 3.0)
    ring.show()
    pump(app, 0.1)
    check("进度环启动后计时器在跑", ring._timer.isActive())
    angle_before = ring._angle
    pump(app, 0.25)
    check("进度环在旋转", abs(ring._angle - angle_before) > 1.0,
          f"{angle_before:.0f}° -> {ring._angle:.0f}°")
    sweep_before = ring._sweep
    pump(app, 0.3)
    check("进度环弧长会呼吸变化", abs(ring._sweep - sweep_before) > 1.0,
          f"{sweep_before:.0f}° -> {ring._sweep:.0f}°")
    ring.hide()
    pump(app, 0.1)
    check("隐藏后停止计时器（不空转 CPU）", not ring._timer.isActive())
    ring.deleteLater()

    # ---------------- 最小化动画 ---------------- #
    # 用快照浮层做动画：直接缩放真窗口会让 Qt 每帧重排内容（文字重新折行、
    # 按钮被压扁），完全不像系统的效果。所以真窗口立刻最小化，动的是那张快照。
    from winsnip.ui.main_window import MainWindow as _MainWindow

    window = _MainWindow()
    window.show()
    pump(app, 1.0)

    settings.animations = True
    origin = window.geometry()
    target = anim.minimize_target(window)
    check("最小化终点在屏幕底部（朝向任务栏）且更小",
          target.height() < origin.height() and target.width() < origin.width()
          and target.bottom() > origin.bottom(),
          f"{origin.width()}x{origin.height()} @y{origin.y()} -> "
          f"{target.width()}x{target.height()} @y{target.y()}")

    before_text = window.hint._lines if hasattr(window, "hint") else None
    window.minimize_animated()
    pump(app, 0.15)
    check("动画期间出现快照浮层", anim._minimize_ghost_count() > 0,
          f"浮层数 {anim._minimize_ghost_count()}")
    check("真窗口立刻最小化（不等动画跑完）", window.isMinimized())
    pump(app, 1.2)
    check("动画结束后快照浮层已清理", anim._minimize_ghost_count() == 0,
          f"浮层数 {anim._minimize_ghost_count()}")
    check("真窗口几何从未被改动（因此内容不会重排）",
          window.geometry() == origin,
          f"{window.geometry()} vs {origin}")
    if before_text is not None:
        check("提示文字在动画前后完全一致（没有重新折行）",
              window.hint._lines == before_text,
              f"{len(window.hint._lines)} 行")

    # 关闭动画时应立即最小化，不留浮层
    settings.animations = False
    window2 = _MainWindow()
    window2.show()
    pump(app, 0.8)
    window2.minimize_animated()
    pump(app, 0.15)
    check("关闭界面动画后立即最小化，且不产生浮层",
          window2.isMinimized() and anim._minimize_ghost_count() == 0,
          f"isMinimized={window2.isMinimized()} 浮层={anim._minimize_ghost_count()}")
    settings.animations = True

    for win in (window, window2):
        win._quitting = True
        win.close()
        win.deleteLater()
    pump(app, 0.4)

    # ---------------- splash handover ---------------- #
    # 首次解析自定义字族在这台机器上要 3~4 秒，而 Qt 是在窗口首次 polish 时
    # （show() 内部、showEvent 之前）做的。如果构造时就设好字体，启动画面会在这
    # 几秒里完全不可见——用户先看到几秒空白，然后启动画面一闪而过。所以字体必须
    # 等窗口显示出来之后再套上。
    splash = SplashWindow()
    check("启动画面构造时不预设字体（避免 show() 期间解析字族）",
          splash.title.font().family() != "Segoe UI Variable Text"
          and not getattr(splash, "_fonts_applied", False),
          f"title family = {splash.title.font().family()!r}")
    show_started = time.perf_counter()
    splash.start()
    show_elapsed = time.perf_counter() - show_started
    check("启动画面 show() 不被字体解析阻塞（< 1.5 秒）", show_elapsed < 1.5,
          f"{show_elapsed * 1000:.0f} ms（首次解析字族要 3000+ ms）")
    pump(app, 0.15)
    check("启动画面能显示", splash.isVisible())
    check("显示之后字体已套用", getattr(splash, "_fonts_applied", False),
          "字体在 showEvent 之后补齐")
    check("套用字体后标题仍然是「截图工具」", splash.title.text() == "截图工具")
    check("启动画面带应用图标与标题",
          not splash.icon.pixmap().isNull() and splash.title.text() == "截图工具",
          f"{splash.title.text()} / {splash.subtitle.text()}")

    target = MainWindow()
    target.hide()
    splash.finish(target)
    pump(app, 0.3)
    check("最短展示时间内启动画面仍在（不会一闪而过）", splash.isVisible(),
          f"MIN_VISIBLE_MS={MIN_VISIBLE_MS}")
    pump(app, MIN_VISIBLE_MS / 1000.0 + 0.8)
    check("交接后主窗口已显示", target.isVisible())
    check("交接后启动画面已关闭", not splash.isVisible())
    check("交接后主窗口不透明", abs(target.windowOpacity() - 1.0) < 1e-6,
          f"{target.windowOpacity()}")

    # ---------------- screenshot <-> recording mode switch ---------------- #
    settings.last_mode = "camera"
    main = MainWindow()
    main.show()
    pump(app, 0.6)
    segment = main.segmented

    def icon_luma(index: int) -> float:
        """Darkest pixel inside one segment's icon cell."""
        image = segment.grab().toImage()
        best = 255.0
        for x in range(index * 54 + 16, index * 54 + 38):
            for y in range(6, 28):
                colour = image.pixelColor(x, y)
                best = min(best, 0.299 * colour.red() + 0.587 * colour.green()
                           + 0.114 * colour.blue())
        return best

    check("初始停在截图档", main._mode == "camera" and segment.current() == 0,
          f"mode={main._mode} index={segment.current()}")
    camera_rest, video_rest = icon_luma(0), icon_luma(1)
    check("选中的图标更深（选中/未选中可区分）", camera_rest < video_rest,
          f"截图 {camera_rest:.0f} vs 录屏 {video_rest:.0f}")

    positions: list[float] = []
    hint_progress: list[float] = []
    mid_luma = None
    segment.itemClicked.emit(1)
    segment.set_current(1)
    for _ in range(40):
        app.processEvents()
        positions.append(segment.indicator_position())
        hint_progress.append(main.hint.transition_progress())
        if mid_luma is None and 0.2 < positions[-1] < 0.8:
            mid_luma = (icon_luma(0), icon_luma(1))
        time.sleep(0.008)

    check("切换时指示器滑动而不是瞬移",
          any(0.05 < value < 0.95 for value in positions),
          f"{[round(v, 2) for v in positions[:8]]}")
    check("切换时提示文字同时过渡",
          any(0.05 < value < 0.95 for value in hint_progress),
          f"{[round(v, 2) for v in hint_progress[:8]]}")
    if mid_luma is not None:
        check("图标颜色在过渡中交叉渐变（旧变浅、新变深）",
              mid_luma[0] > camera_rest + 3 and mid_luma[1] < video_rest - 3,
              f"截图 {camera_rest:.0f}->{mid_luma[0]:.0f} / 录屏 {video_rest:.0f}->{mid_luma[1]:.0f}")
    else:
        check("图标颜色在过渡中交叉渐变（旧变浅、新变深）", False, "没抓到中间帧")

    pump(app, 0.5)
    check("切换后指示器停在录屏档", segment.indicator_position() == 1.0,
          f"{segment.indicator_position()}")
    check("切换后模式与提示文字都是录屏",
          main._mode == "video" and "录屏" in main.hint._lines[0][0],
          main.hint._lines[0][0])

    segment.itemClicked.emit(0)
    segment.set_current(0)
    pump(app, 0.6)
    check("切回截图后提示文字正确",
          main._mode == "camera" and "截图" in main.hint._lines[0][0],
          main.hint._lines[0][0])
    check("切回后指示器回到拍照档", segment.indicator_position() == 0.0,
          f"{segment.indicator_position()}")

    settings.animations = False
    segment.itemClicked.emit(1)
    segment.set_current(1)
    pump(app, 0.05)
    check("关闭动画后立即到位（无中间态）",
          segment.indicator_position() == 1.0 and main.hint.transition_progress() == 1.0,
          f"indicator={segment.indicator_position()} hint={main.hint.transition_progress()}")
    settings.animations = True
    main._quitting = True
    main.close()
    pump(app, 0.2)

    # ---------------- every window opens with a transition ---------------- #
    from PySide6.QtCore import QPoint as QtPoint
    from PySide6.QtWidgets import QWidget as QtWidget

    from winsnip.ui.settings_dialog import AboutWindow, SettingsWindow
    from winsnip.ui.widgets import FluentMenu, FluentWindow as QtFluentWindow, Toast

    def ramp(show_call, widget, seconds: float = 0.7) -> list[float]:
        show_call()
        values: list[float] = []
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            app.processEvents()
            values.append(widget.windowOpacity())
            time.sleep(0.006)
        return values

    bare = QtFluentWindow()
    check("新窗口默认就带打开动画（基类默认 slide）",
          bare._open_animation == "slide",
          f"open_animation={bare._open_animation!r}")
    bare.deleteLater()

    # Settings window: fade + slide
    settings_window = SettingsWindow()
    values = ramp(settings_window.show, settings_window)
    check("设置窗口淡入（不是瞬间出现）",
          any(0.02 < value < 0.98 for value in values) and values[-1] == 1.0,
          f"{[round(v, 2) for v in values[:6]]}")
    settings_window.close()
    pump(app, 0.2)

    # About window
    about = AboutWindow()
    values = ramp(about.show, about)
    check("关于窗口淡入", any(0.02 < value < 0.98 for value in values) and values[-1] == 1.0,
          f"{[round(v, 2) for v in values[:6]]}")
    about.close()
    pump(app, 0.2)

    # Menu popup
    menu = FluentMenu(None, min_width=180)
    menu.add_item("测试项", icon_name="settings")
    values = ramp(lambda: menu.popup(QtPoint(300, 300)), menu)
    check("弹出菜单淡入", any(0.02 < value < 0.98 for value in values) and values[-1] == 1.0,
          f"{[round(v, 2) for v in values[:6]]}")
    menu.close()
    pump(app, 0.2)

    # Toast notification
    toast = Toast("测试通知", "淡入检查")
    values = ramp(toast.show, toast)
    check("通知横幅淡入", any(0.02 < value < 0.98 for value in values) and values[-1] == 1.0,
          f"{[round(v, 2) for v in values[:6]]}")
    toast.close()
    pump(app, 0.2)

    # Full-screen overlay: fade only, never slides
    from winsnip.ui.overlay import CaptureOverlay

    overlay = CaptureOverlay("camera", "rectangle")
    values = ramp(overlay.start, overlay, seconds=0.5)
    check("区域选择浮层淡入（不滑动）",
          any(0.02 < value < 0.98 for value in values) and values[-1] == 1.0,
          f"{[round(v, 2) for v in values[:6]]}")
    check("浮层用纯淡入（滑动会让整屏位移）",
          getattr(overlay, "_open_animated", False) and not hasattr(overlay, "_open_slide"),
          "CaptureOverlay 自行控制为 fade")
    overlay.close()
    pump(app, 0.2)

    settings.animations = False
    plain = SettingsWindow()
    plain.show()
    pump(app, 0.05)
    check("关闭动画后所有窗口立即显示", plain.windowOpacity() == 1.0,
          f"{plain.windowOpacity()}")
    plain.close()
    settings.animations = True
    pump(app, 0.2)

    # ---------------- easing ---------------- #
    check("Fluent 缓动曲线可获取",
          anim.curve("out").type() == anim.QEasingCurve.Type.OutCubic
          and anim.curve("in").type() == anim.QEasingCurve.Type.InCubic,
          f"{anim.curve('out').type()}")

    settings.animations = original
    for widget in (target, window):
        widget._quitting = True
        widget.close()
    return report(app)


def report(app: QApplication) -> int:
    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- ANIMATION SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("ANIMATION SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
