"""Headless-ish UI render harness: builds every window and saves screenshots.

Run with:  python app.py --selftest-ui
Artifacts land in <project>/docs/screenshots/.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout

OUT = Path(__file__).resolve().parents[2] / "docs" / "screenshots"
# NOTE: app.py sets WINSNIPREC_HOME before importing winsnip.settings when it is
# started with --selftest-ui, so the fallback below only matters for direct use.

from ..settings import settings  # noqa: E402
from ..theme import theme  # noqa: E402


def _save(widget, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pixmap = widget.grab()
    path = OUT / f"{name}.png"
    pixmap.save(str(path), "PNG")
    print(f"saved {path} ({pixmap.width()}x{pixmap.height()})")


def _pump(app: QApplication, ms: int = 260) -> None:
    deadline = ms
    while deadline > 0:
        app.processEvents()
        QApplication.processEvents()
        import time

        time.sleep(0.02)
        deadline -= 20


def run_ui_selftest(app: QApplication) -> int:
    from .control_bar import RecordControlBar
    from .main_window import MainWindow
    from .preview import ImagePreviewWindow
    from .settings_dialog import AboutWindow, SettingsWindow
    from .widgets import FluentButton, FluentWindow, ToggleSwitch
    from .. import icons
    from ..theme import ui_font

    failures: list[str] = []
    shots: list[str] = []

    # Deterministic for a render harness: never hide into the tray.
    settings.minimize_to_tray = False
    settings.open_folder_when_done = False

    # ---- light theme -------------------------------------------------- #
    theme.mode = "light"
    theme.refresh()
    app.setStyleSheet(__import__("winsnip.theme", fromlist=["application_stylesheet"]).application_stylesheet())

    window = MainWindow()
    window.show()
    _pump(app, 500)
    _save(window, "01_main_light")
    shots.append("01_main_light")

    window._set_mode("camera")
    _pump(app, 200)
    _save(window, "02_main_camera")
    window._set_mode("video")

    bar = RecordControlBar(mic_available=True, mic_enabled=True)
    bar.show()
    bar.set_elapsed(72)
    _pump(app, 400)
    bar.move_card_to(100, 100)
    _pump(app, 200)
    _save(bar, "03_control_bar_light")
    shots.append("03_control_bar_light")

    bar.set_paused(True)
    _pump(app, 300)
    _save(bar, "04_control_bar_paused")

    settings_window = SettingsWindow()
    settings_window.show()
    _pump(app, 500)
    _save(settings_window, "05_settings_light")
    shots.append("05_settings_light")

    about = AboutWindow()
    about.show()
    _pump(app, 300)
    _save(about, "06_about")

    image = QImage(640, 400, QImage.Format.Format_RGB32)
    image.fill(QColor("#2C6FA8"))
    painter = QPainter(image)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(40, 80, "WinSnipRec preview")
    painter.end()
    preview = ImagePreviewWindow("C:/tmp/截图 2026-09-29 231500.png", image)
    preview.show()
    _pump(app, 400)
    _save(preview, "07_preview_light")

    # ---- dark theme --------------------------------------------------- #
    theme.mode = "dark"
    theme.refresh()
    for widget in (window, bar, settings_window, preview, about):
        widget.invalidate_backdrop()
        if hasattr(widget, "refresh_theme"):
            widget.refresh_theme()
    app.setStyleSheet(__import__("winsnip.theme", fromlist=["application_stylesheet"]).application_stylesheet())
    _pump(app, 400)
    _save(window, "08_main_dark")
    shots.append("08_main_dark")
    _save(bar, "09_control_bar_dark")
    _save(settings_window, "10_settings_dark")

    # ---- splash screen (dark) ----------------------------------------- #
    from .splash import SplashWindow

    splash = SplashWindow()
    splash.show()
    _pump(app, 400)
    splash.setWindowOpacity(1.0)
    splash.invalidate_backdrop()
    splash.refresh_theme()
    _pump(app, 200)
    _save(splash, "16_splash_dark")
    shots.append("16_splash_dark")
    splash.close()

    # ---- capture overlay ---------------------------------------------- #
    from .overlay import CaptureOverlay

    theme.mode = "light"
    theme.refresh()
    overlay = CaptureOverlay(mode="video", shape="rectangle", confirm=True)
    try:
        overlay.start()
        _pump(app, 500)
        # draw a plausible selection so the handles/confirm chip/size badge render
        from PySide6.QtCore import QPoint, QRect

        overlay._selection = QRect(QPoint(260, 250), QPoint(1000, 700))
        overlay._pointer = QPoint(700, 560)
        overlay._committed_selection = False
        _pump(app, 300)
        _save(overlay, "11_overlay_light")
        shots.append("11_overlay_light")
    except Exception as exc:  # pragma: no cover - reported, not fatal
        failures.append(f"overlay: {exc!r}")
    finally:
        overlay.close()

    # ---- flyout menu ---------------------------------------------------- #
    from .widgets import FluentMenu, IconButton, Toast

    menu = FluentMenu(min_width=200)
    for key, label, icon_name in (("rectangle", "矩形区域", "add_rect"),
                                  ("window", "窗口", "window"),
                                  ("fullscreen", "全屏", "fullscreen"),
                                  ("freeform", "自由绘制", "freeform")):
        menu.add_item(label, icon_name=icon_name, checked=(key == "rectangle"))
    menu.add_separator()
    menu.add_item("禁用项", icon_name="info", enabled=False)
    menu.show()
    menu.finalize()
    _pump(app, 300)
    _save(menu, "12_flyout_menu")
    shots.append("12_flyout_menu")
    menu.close()

    toast = Toast("录制已保存", "屏幕录制 2026-09-30 000000.mp4 · 4.2 MB", "check")
    toast.show()
    _pump(app, 400)
    _save(toast, "13_toast")
    shots.append("13_toast")
    toast.close()

    button_demo = FluentWindow(None, radius=8)
    button_demo.set_card_size(360, 150)
    demo_layout = QVBoxLayout(button_demo)
    demo_layout.setContentsMargins(40, 40, 40, 40)
    demo_layout.setSpacing(10)
    demo_row = QHBoxLayout()
    demo_row.addWidget(FluentButton("标准", button_demo, variant="standard", icon_name="copy"))
    demo_row.addWidget(FluentButton("主要", button_demo, variant="accent", icon_name="save"))
    demo_row.addWidget(FluentButton("次要", button_demo, variant="subtle", icon_name="folder"))
    demo_row.addWidget(IconButton("mic", button_demo))
    demo_layout.addLayout(demo_row)
    demo_row2 = QHBoxLayout()
    demo_row2.addWidget(ToggleSwitch(True, button_demo))
    demo_row2.addWidget(ToggleSwitch(False, button_demo))
    switch_label = QLabel("开关控件", button_demo)
    switch_label.setFont(ui_font(12))
    demo_row2.addWidget(switch_label)
    demo_layout.addLayout(demo_row2)
    button_demo.show()
    _pump(app, 300)
    _save(button_demo, "14_controls")
    shots.append("14_controls")
    button_demo.close()

    # ---- splash screen (light) ----------------------------------------- #
    from .splash import SplashWindow

    splash = SplashWindow()
    splash.show()
    _pump(app, 400)
    splash.setWindowOpacity(1.0)
    _save(splash, "15_splash_light")
    shots.append("15_splash_light")

    for widget in (window, bar, settings_window, preview, about):
        widget.close()
    _pump(app, 200)

    print("--- UI SELFTEST ---")
    print(f"screenshots: {len(shots)}")
    for failure in failures:
        print(f"FAIL {failure}")
    print("UI SELFTEST: " + ("PASS" if not failures else "FAIL"))
    QTimer.singleShot(50, app.quit)
    app.exec()
    return 0 if not failures else 1
