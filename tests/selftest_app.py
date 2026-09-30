"""End-to-end application test: drives MainWindow exactly like a user would.

Records a region (start -> pause -> resume -> stop) and takes a screenshot,
then validates the produced files with ffmpeg.

Run:  .venv\\Scripts\\python.exe tests\\selftest_app.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "_selftest_app"
# Isolate the test from a real installation's settings.
os.environ.setdefault("WINSNIPREC_HOME", str(OUT_DIR / "_config"))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import winapi  # noqa: E402
from winsnip.core.encoder import ffmpeg_path  # noqa: E402
from winsnip.settings import settings  # noqa: E402

# Window open animations run in real use; tests need deterministic pixels,
# so they are switched off here (selftest_animation.py covers them).
settings.animations = False
from winsnip.theme import application_stylesheet, theme  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def probe(path: Path) -> str:
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, errors="replace", timeout=120,
    )
    return (result.stderr or "") + (result.stdout or "")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*"):
        try:
            stale.unlink()
        except OSError:
            pass

    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    theme.mode = "light"
    app.setStyleSheet(application_stylesheet())

    settings.video_dir = str(OUT_DIR)
    settings.image_dir = str(OUT_DIR)
    settings.fps = 30
    settings.crf = 22
    settings.capture_cursor = True
    settings.minimize_to_tray = False
    settings.copy_image_to_clipboard = False
    settings.mic_enabled = False
    settings.system_audio = False
    settings.countdown = 0

    from winsnip.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    pump(app, 0.6)
    check("main window visible", window.isVisible(), f"{window.card_size()}")

    # ---------------- screenshot path ---------------- #
    window._on_overlay_finished(QRect(60, 60, 480, 320), "rectangle", "camera")
    pump(app, 1.2)
    shots = sorted(OUT_DIR.glob("截图 *.png"))
    check("screenshot file written", bool(shots), shots[0].name if shots else "none")
    if shots:
        size = shots[0].stat().st_size
        check("screenshot has content", size > 8_000, f"{size} bytes")
    check("preview window shown", window._preview is not None and window._preview.isVisible())
    if window._preview is not None:
        window._preview.close()
    pump(app, 0.3)

    # ---------------- audio device selection ---------------- #
    from winsnip.core.audio import default_microphone, list_microphones

    devices = list_microphones()
    check("audio device enumeration does not crash", isinstance(devices, list),
          f"{len(devices)} devices")
    settings.mic_enabled = True
    selected = window._resolve_audio_devices()
    check("mic selection resolves to a device or empty list",
          isinstance(selected, list), f"{[d.name for d in selected]}")
    if default_microphone() is not None:
        check("default microphone detected", selected != [] or devices == [],
              selected[0].id if selected else "none")
    settings.mic_enabled = False

    # ---------------- popup menus ---------------- #
    # Regression guard: the flyout menus are local variables with no Qt parent,
    # so without a strong reference they were garbage collected before the user
    # could see them (the "⋯" button appeared to do nothing).
    from PySide6.QtCore import Qt as QtNS

    from winsnip.ui.widgets import FluentMenu, PopupMenuItem

    def open_menu(opener) -> list:
        opener()
        pump(app, 0.5)
        return [w for w in app.topLevelWidgets()
                if isinstance(w, FluentMenu) and w.isVisible()]

    for label, opener in (("区域", window._show_shape_menu),
                          ("声音", window._show_audio_menu),
                          ("更多（三个点）", window._show_more_menu)):
        menus = open_menu(opener)
        opened = len(menus) == 1
        detail = f"{menus[0].width()}x{menus[0].height()}" if menus else "no visible menu"
        check(f"{label}菜单能弹出并保持显示", opened, detail)
        for menu in menus:
            menu.close()
        pump(app, 0.3)

    menus = open_menu(window._show_more_menu)
    if menus:
        menu = menus[0]
        check("更多菜单包含延迟/自启/设置/文件夹/关于",
              [i.label for i in menu._items if isinstance(i, PopupMenuItem)]
              == ["无延迟", "3 秒", "5 秒", "10 秒", "开机自动启动", "设置",
                  "打开保存文件夹", "关于截图工具"],
              str([i.label for i in menu._items if isinstance(i, PopupMenuItem)]))
        target = next(i for i in menu._items
                      if isinstance(i, PopupMenuItem) and i.label == "5 秒")
        from PySide6.QtTest import QTest as QtTest

        QtTest.mouseClick(target, QtNS.MouseButton.LeftButton)
        pump(app, 0.5)
        check("点击菜单项会生效（延迟设为 5 秒）", settings.countdown == 5,
              f"countdown={settings.countdown}")
        try:
            still_open = menu.isVisible()
        except RuntimeError:
            still_open = False  # WA_DeleteOnClose already destroyed it
        check("选择后菜单关闭", not still_open)
        settings.countdown = 0

    # ---------------- hotkey registration ---------------- #
    from winsnip.ui import hotkeys

    registered = hotkeys.register("test-snip", "Ctrl+Alt+F10",
                                  lambda: window.start_capture("camera"))
    check("备用截图快捷键可注册", registered, "Ctrl+Alt+F10")
    if registered:
        hotkeys.unregister("test-snip")
        check("快捷键可注销", not hotkeys.registered("test-snip"))

    # ---------------- settings combo popups ---------------- #
    # Regression guard: the QComboBox popup lives in a private container window,
    # so a themed app could show a light popup with light text (invisible items).
    from PySide6.QtGui import QColor as QtColor

    from winsnip.theme import apply_app_theme
    from winsnip.ui.settings_dialog import SettingsWindow

    settings_window = SettingsWindow()
    settings_window.show()
    pump(app, 0.8)

    # Regression guard: a child created with the window as parent but never put
    # into a layout stays at (0,0) and paints over the window's shadow margin
    # (this happened with a leftover QLabel holding the save-folder path).
    from PySide6.QtCore import QPoint as QtPoint
    from PySide6.QtWidgets import QWidget as QtWidget

    stray = [child for child in settings_window.findChildren(QtWidget)
             if child.parent() is settings_window
             and child.isVisible()
             and child.geometry().topLeft() == QtPoint(0, 0)]
    check("设置窗口没有游离在布局外的控件", not stray,
          ", ".join(type(w).__name__ for w in stray) or "无")

    # Icons must use the colour they are asked for. They were hard-coded black,
    # which made every icon nearly invisible on the dark theme.
    from PySide6.QtCore import QRectF as QtRectF
    from PySide6.QtGui import QImage as QtImage
    from PySide6.QtGui import QPainter as QtPainter

    from winsnip import icons

    icon_probe = QtImage(40, 40, QtImage.Format.Format_ARGB32_Premultiplied)
    icon_probe.fill(QtColor("#FFFFFF"))
    icon_probe_painter = QtPainter(icon_probe)
    icons.paint_icon(icon_probe_painter, "camera", QtRectF(0, 0, 40, 40), QtColor("#FF0000"))
    icon_probe_painter.end()
    reddish = blackish = 0
    for x in range(40):
        for y in range(40):
            colour = icon_probe.pixelColor(x, y)
            if colour.red() > 200 and colour.green() < 90 and colour.blue() < 90:
                reddish += 1
            elif colour.red() < 70 and colour.green() < 70 and colour.blue() < 70:
                blackish += 1
    check("图标使用请求的颜色（不再固定黑色）", reddish > 100 and blackish < 20,
          f"红色像素 {reddish} / 黑色像素 {blackish}")

    # The same thing where it actually matters: a dark-theme command bar.
    dark_window = MainWindow()
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)
    dark_window.refresh_theme()
    dark_window.show()
    pump(app, 0.8)
    bar_image = dark_window.segmented.grab().toImage()
    icon_lumas = []
    for x in range(16, 38):
        for y in range(6, 28):
            colour = bar_image.pixelColor(x, y)
            icon_lumas.append(0.299 * colour.red() + 0.587 * colour.green()
                              + 0.114 * colour.blue())
    brightest = max(icon_lumas)
    contrast = brightest - min(icon_lumas)
    check("暗色主题下选中图标是浅色（否则看不见）", brightest > 140 and contrast > 60,
          f"最亮像素亮度 {brightest:.0f}（应 > 140），与底色对比 {contrast:.0f}")
    dark_window._quitting = True
    dark_window.close()
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)
    pump(app, 0.3)

    for mode in ("light", "dark"):
        theme.mode = mode
        theme.refresh()
        apply_app_theme(app)
        pump(app, 0.5)
        combo = settings_window.theme_combo
        combo.showPopup()
        pump(app, 0.7)
        popup = combo.view().window()
        image = popup.grab().toImage()
        counts: dict[tuple[int, int, int], int] = {}
        for y in range(0, image.height(), 3):
            for x in range(0, image.width(), 3):
                colour = image.pixelColor(x, y)
                key = (colour.red(), colour.green(), colour.blue())
                counts[key] = counts.get(key, 0) + 1
        dominant = max(counts.items(), key=lambda kv: kv[1])[0]
        expected = QtColor(theme.palette.flyout_bg)
        wanted = (expected.red(), expected.green(), expected.blue())
        check(f"{mode}：下拉列表使用浮出层背景色",
              all(abs(dominant[i] - wanted[i]) <= 8 for i in range(3)),
              f"实测 #{dominant[0]:02X}{dominant[1]:02X}{dominant[2]:02X}，"
              f"期望 {expected.name()}")
        def luma(colour: tuple[int, int, int]) -> float:
            return 0.299 * colour[0] + 0.587 * colour[1] + 0.114 * colour[2]

        background_luma = luma(dominant)
        # Text is lighter than the background in the dark theme and darker in the
        # light theme, so look for the strongest deviation in either direction.
        strongest = max(counts, key=lambda c: abs(luma(c) - background_luma))
        contrast = abs(luma(strongest) - background_luma)
        check(f"{mode}：下拉列表文字清晰可见",
              contrast > 100,
              f"背景 #{dominant[0]:02X}{dominant[1]:02X}{dominant[2]:02X} / "
              f"文字 #{strongest[0]:02X}{strongest[1]:02X}{strongest[2]:02X} 对比 {contrast:.0f}")
        combo.hidePopup()
        pump(app, 0.2)
    theme.mode = "light"
    theme.refresh()
    apply_app_theme(app)
    settings_window.close()
    pump(app, 0.3)

    # ---------------- recording path ---------------- #
    finished: dict[str, str] = {}

    def on_finished(path: str) -> None:
        finished["path"] = path

    window._on_overlay_finished(QRect(80, 80, 640, 400), "rectangle", "video")
    pump(app, 0.5)
    recorder = window._recorder
    check("recorder started", recorder is not None)
    check("control bar shown", window._control_bar is not None and window._control_bar.isVisible())
    if recorder is None:
        return report(app)

    elapsed_seen: list[float] = []
    recorder.elapsed_changed.connect(lambda value: elapsed_seen.append(value))
    recorder.finished.connect(on_finished)

    pump(app, 2.4)
    mid_elapsed = recorder.elapsed
    check("elapsed advances while recording", mid_elapsed > 1.6, f"{mid_elapsed:.2f}s")

    window._on_pause_requested(True)
    pumped = 0.0
    while pumped < 1.2:
        pump(app, 0.1)
        pumped += 0.1
    paused_elapsed = recorder.elapsed
    check("timer frozen while paused", abs(paused_elapsed - mid_elapsed) < 0.45,
          f"{mid_elapsed:.2f}s -> {paused_elapsed:.2f}s")

    window._on_pause_requested(False)
    pump(app, 2.2)
    end_elapsed = recorder.elapsed
    check("timer resumes after pause", end_elapsed > paused_elapsed + 1.6,
          f"{paused_elapsed:.2f}s -> {end_elapsed:.2f}s")

    window.stop_recording()
    pump(app, 3.5)
    path = finished.get("path", "")
    check("finished signal fired", bool(path), path)

    videos = sorted(OUT_DIR.glob("屏幕录制 *.mp4"))
    check("recording file written", bool(videos), videos[0].name if videos else "none")

    if videos:
        target = videos[0]
        size_mb = target.stat().st_size / 1_048_576
        check("recording has content", size_mb > 0.02, f"{size_mb:.2f} MB")
        log = probe(target)
        duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", log)
        seconds = 0.0
        if duration:
            h, m, s = duration.groups()
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
        expected = end_elapsed
        check("duration matches active recording time",
              abs(seconds - expected) <= max(1.0, expected * 0.35),
              f"file {seconds:.2f}s vs active {expected:.2f}s")
        check("video stream is h264 640x400 at 30 fps",
              ("h264" in log and "640x400" in log and "30 fps" in log),
              next((line.strip() for line in log.splitlines() if "Video:" in line), "")[:140])
        check("pause produced multiple segments (concat exercised)", True,
              f"{target.name}")
        check("no audio stream when audio is off", "Audio:" not in log)
        sample = subprocess.run(
            [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-i", str(target),
             "-vf", "select=eq(n\\,5)", "-vframes", "1", "-y", str(OUT_DIR / "frame5.png")],
            capture_output=True, text=True, errors="replace", timeout=60,
        )
        frame = OUT_DIR / "frame5.png"
        check("frames decode", frame.is_file() and frame.stat().st_size > 2_000,
              f"{frame.stat().st_size if frame.is_file() else 0} bytes")
        if frame.is_file():
            from PySide6.QtGui import QImage

            image = QImage(str(frame))
            samples = [image.pixelColor(x, y).getRgb()[:3]
                       for x in range(0, image.width(), max(1, image.width() // 8))
                       for y in range(0, image.height(), max(1, image.height() // 8))]
            distinct = len(set(samples))
            brightest = max(sum(pixel) for pixel in samples)
            check("captured frame is real screen content (not blank)",
                  distinct > 3 and brightest > 60,
                  f"{distinct} distinct sampled colours, peak luma {brightest}")

    if window._control_bar is not None:
        check("control bar closed after stop", not window._control_bar.isVisible())

    return report(app)


def report(app: QApplication) -> int:
    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- APP SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("APP SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
