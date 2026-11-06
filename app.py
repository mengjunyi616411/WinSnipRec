"""WinSnipRec - Windows 10 screen recorder with a Windows 11 Snipping Tool UI.

Run with:  python app.py            (normal launch)
           python app.py --tray     (start hidden in the notification area)
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The UI render harness must never touch a real installation's settings.
if "--selftest-ui" in sys.argv:
    os.environ.setdefault("WINSNIPREC_HOME",
                          str(Path(__file__).resolve().parent / "_selftest_config"))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from winsnip import __app_name__, __version__, anim, icons, winapi  # noqa: E402
from winsnip.settings import app_data_dir, settings  # noqa: E402
from winsnip.theme import apply_app_theme, theme  # noqa: E402
from winsnip.ui import hotkeys  # noqa: E402
from winsnip.ui.main_window import MainWindow  # noqa: E402
from winsnip.ui.splash import SplashWindow  # noqa: E402
from winsnip.ui.widgets import show_toast  # noqa: E402

LOG_PATH = app_data_dir() / "app.log"


def _setup_logging() -> None:
    """Start file logging, but never let it stop the app.

    app.log is opened by whichever instance is running, so a second launch gets
    PermissionError. Logging is a diagnostic, not a prerequisite: fall back to a
    per-process file, then to console only.
    """
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    for candidate in (LOG_PATH, app_data_dir() / f"app-{os.getpid()}.log"):
        try:
            logging.basicConfig(filename=str(candidate), filemode="a", level=logging.INFO,
                                format=fmt, encoding="utf-8", force=True)
        except OSError:
            continue
        break
    else:
        logging.basicConfig(level=logging.INFO, format=fmt, force=True)
        logging.warning("log file not writable, continuing without file logging")
    logging.info("---- WinSnipRec %s starting (python %s) ----", __version__,
                 sys.version.split()[0])


def _single_instance() -> bool:
    """True when this is the only running copy."""
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW(None, False, "Global\\WinSnipRec.SingleInstance")
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _install_excepthook(app: QApplication) -> None:
    def hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.error("Unhandled exception:\n%s", "".join(
            traceback.format_exception(exc_type, exc_value, exc_tb)))
        try:
            show_toast("程序遇到问题", f"{exc_type.__name__}: {exc_value}", "info", duration=6000)
        except Exception:
            pass

    sys.excepthook = hook


def _register_hotkeys(window: MainWindow) -> None:
    """Bind the global shortcuts, falling back when Windows owns the keys."""
    plan = [
        ("snip", settings.hotkey_snip, "camera", "截图", ["Ctrl+Alt+S", "Ctrl+Shift+S"]),
        ("record", settings.hotkey_record, "video", "录屏", ["Ctrl+Alt+R", "Ctrl+Shift+R"]),
    ]
    changed = False
    for name, spec, mode, label, fallbacks in plan:
        handler = (lambda m=mode: window.start_capture(m))
        if hotkeys.register(name, spec, handler):
            logging.info("hotkey %s bound to %s", name, spec)
            continue
        bound = None
        for candidate in fallbacks:
            if hotkeys.register(name, candidate, handler):
                bound = candidate
                break
        if bound:
            logging.warning("hotkey %s: %s unavailable, using %s", name, spec, bound)
            if name == "snip":
                settings.hotkey_snip = bound
            else:
                settings.hotkey_record = bound
            changed = True
            show_toast(
                f"{label}快捷键已更换",
                f"{spec} 已被系统或其他程序占用，现使用 {bound}",
                "info", duration=6000,
            )
        else:
            logging.error("hotkey %s could not be registered", name)
            show_toast(f"{label}快捷键不可用",
                       f"{spec} 被占用，请点击“新建”按钮手动{label}", "info", duration=6000)
    if changed:
        settings.save()
        window._update_hint()


def _check_autostart(window: MainWindow) -> None:
    """Repoint a logon entry whose target no longer exists (program moved)."""
    from winsnip import startup

    if not startup.is_enabled():
        return
    previous = startup.registered_command()
    if startup.refresh_if_stale():
        logging.info("autostart entry repointed from %s to %s",
                     previous, startup.registered_command())
        show_toast("已修复开机自启", "之前指向的程序已不存在，现已指向当前版本", "check",
                   duration=5200)
    elif not startup.is_current():
        logging.info("autostart points at another copy: %s", previous)


def _watch_system_theme(app: QApplication, window: MainWindow) -> None:
    """Follow Windows light/dark switches while running."""
    state = {"dark": theme.dark}

    timer = QTimer(app)
    timer.setInterval(2000)

    def poll() -> None:
        current = winapi.is_dark_mode()
        if current != state["dark"]:
            state["dark"] = current
            theme.refresh()
            apply_app_theme(app)
            window.refresh_theme()
            for widget in app.topLevelWidgets():
                if hasattr(widget, "refresh_theme"):
                    try:
                        widget.refresh_theme()
                    except Exception:
                        pass
                widget.update()

    timer.timeout.connect(poll)
    timer.start()


def _show_first_run_guide() -> None:
    """Show the first-run guide, unless it has already been dismissed."""
    try:
        from winsnip.ui.onboarding import show_onboarding

        show_onboarding()
    except Exception:
        logging.getLogger("winsnip").exception(
            "failed to show the first-run guide")


def main() -> int:
    # 单实例检查要排在日志之前：已在运行的实例占着 app.log，先开日志会抛
    # PermissionError，用户看到的是崩溃窗口而不是"已经在运行"的提示。
    # （这里不弹窗，因为还没有 QApplication；真正的提示在下面 QApplication 之后。）
    winapi.enable_per_monitor_dpi_awareness()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationDisplayName("截图工具")
    app.setOrganizationName("WinSnipRec")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(icons.app_icon())

    if not any(flag.startswith("--selftest") for flag in sys.argv) and not _single_instance():
        QMessageBox.information(None, "截图工具", "截图工具已经在运行。\n可在任务栏通知区域找到它。")
        return 0

    _setup_logging()
    # 动画能力自检：最小化看不到动画时，先看这行日志就知道是系统没开、还是别的原因。
    try:
        logging.getLogger("winsnip").info(
            "animation self-check: %s", winapi.describe_animation_capabilities())
    except Exception:
        pass
    from winsnip import i18n

    i18n.set_language(getattr(settings, "language", "system"))
    theme.mode = settings.theme
    theme.style = getattr(settings, "style", "win11")
    apply_app_theme(app)
    _install_excepthook(app)

    # Self-test runs must never be blocked by a running copy of the app (they
    # would otherwise sit on a modal "already running" dialog forever).
    settings.ensure_dirs()

    if "--selftest-ui" in sys.argv:
        from winsnip.ui.selftest_ui import run_ui_selftest

        return run_ui_selftest(app)

    if "--selftest-record" in sys.argv:
        from winsnip.ui.selftest_frozen import run_recording_selftest

        return run_recording_selftest(app)

    if "--selftest-quit" in sys.argv:
        from winsnip.ui.selftest_frozen import run_quit_selftest

        return run_quit_selftest(app)

    if "--selftest-minimize" in sys.argv:
        from winsnip.ui.selftest_minimize import run_minimize_selftest

        return run_minimize_selftest(app)

    window = MainWindow()
    silent = "--tray" in sys.argv
    if silent:
        window.hide()
    if "--open-settings" in sys.argv:
        window.open_settings()

    # Launch animation: splash -> the main window opens with its own Fluent
    # enter transition (FluentWindow plays it in showEvent). Skipped entirely
    # for a silent tray start, where no window should appear at all.
    if silent:
        window.tray.show()
        _after_startup(app, window)
    else:
        if anim.animations_enabled():
            splash = SplashWindow()
            splash.start()
            window.tray.show()
            QTimer.singleShot(120, lambda: splash.finish(window))
            app._splash = splash   # keep a reference for the process lifetime
        else:
            window.show()
            window.tray.show()
        _after_startup(app, window)

    # First run: show the guide once the main window is up, so the user has
    # something to come back to while going through it.
    if not silent and not getattr(settings, "onboarded", False):
        QTimer.singleShot(400, _show_first_run_guide)

    logging.info("ready")
    return app.exec()


def _after_startup(app: QApplication, window: MainWindow) -> None:
    # 音频设备枚举要 4~5 秒，放后台线程跑，别让界面等它。
    from winsnip.core.audio import scan_microphones_async

    QTimer.singleShot(50, scan_microphones_async)
    QTimer.singleShot(400, lambda: _register_hotkeys(window))
    QTimer.singleShot(1500, lambda: _check_autostart(window))
    _watch_system_theme(app, window)


if __name__ == "__main__":
    raise SystemExit(main())
