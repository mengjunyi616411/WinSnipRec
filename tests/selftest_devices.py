"""Audio device enumeration must never block the GUI thread.

Regression test for "设置打不开，有报错窗口，常无响应": SettingsWindow.__init__
called audio.list_microphones(), which shells out to ffmpeg. That takes ~4.7 s on
this machine (7 devices, several virtual) and up to the subprocess timeout when
a device misbehaves, so the window could not appear for that long and Windows
reported the app as not responding.

The direct assertion is therefore "list_microphones() is never called from the
main thread", not a wall-clock threshold: the first window built in a process
also pays a one-time Qt style-initialisation cost (~3.5 s), which in the real
app is already paid while the main window starts.

Run:  .venv\\Scripts\\python.exe tests\\selftest_devices.py
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_devices" / "_config"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import winapi  # noqa: E402
from winsnip.core import audio  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def time_call(func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    return result, time.perf_counter() - start


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from winsnip.settings import settings
    from winsnip.theme import apply_app_theme, theme

    settings.minimize_to_tray = False
    settings.animations = False
    theme.style = "win11"
    theme.refresh()
    apply_app_theme(app)

    # 记录每次真实枚举发生在哪个线程上——这才是这条 bug 的直接断言
    calls: list[str] = []
    real_list = audio.list_microphones

    def spy(*args, **kwargs):
        calls.append(threading.current_thread().name)
        return real_list(*args, **kwargs)

    audio.list_microphones = spy

    # ---------------- 1. 缓存读取绝不阻塞 ---------------- #
    audio._DEVICE_CACHE = None
    _, elapsed = time_call(audio.cached_microphones)
    check("冷缓存时 cached_microphones() 立即返回", elapsed < 0.05,
          f"{elapsed * 1000:.1f} ms")
    check("冷缓存时标记为未扫描", not audio.microphones_scanned())

    # ---------------- 2. 扫描在后台线程 ---------------- #
    seen: dict = {}

    def on_done(devices) -> None:
        seen["thread"] = threading.current_thread().name

    before = time.perf_counter()
    thread = audio.scan_microphones_async(done=on_done)
    start_elapsed = time.perf_counter() - before
    check("scan_microphones_async() 立刻返回（不阻塞调用方）", start_elapsed < 0.2,
          f"{start_elapsed * 1000:.1f} ms")
    check("扫描跑在非主线程上",
          thread is not None and thread is not threading.main_thread(),
          f"线程 {getattr(thread, 'name', '无')}")

    # ---------------- 3. 先起主窗口，把 Qt 样式一次性初始化付掉 ---------------- #
    # 真实流程就是先有主窗口再开设置；这样测的才是设置窗口自己的开销。
    from winsnip.ui.main_window import MainWindow, _cached_mics

    main_window = MainWindow()
    main_window.show()
    pump(app, 1.2)
    calls.clear()

    # ---------------- 4. 设置窗口不得在 GUI 线程枚举设备 ---------------- #
    from winsnip.ui.settings_dialog import SettingsWindow

    audio._DEVICE_CACHE = None      # 最坏情况：缓存是冷的
    window, build_elapsed = time_call(SettingsWindow)
    check("设置窗口构造不被设备枚举阻塞（< 2 秒）", build_elapsed < 2.0,
          f"{build_elapsed:.2f} s（同步枚举一次要 4~5 秒）")
    check("构造期间没有在主线程上枚举设备",
          all(name != "MainThread" for name in calls),
          f"枚举发生在 {calls or ['（还没开始）']}")
    check("构造期间枚举至多被启动一次（不是每个下拉各来一次）",
          len(calls) <= 1, f"{len(calls)} 次")

    window.show()
    pump(app, 0.4)
    check("设置窗口能显示出来", window.isVisible())
    check("下拉先给出占位项，不等枚举",
          window.mic_combo.count() == 1 and window.sound_combo.count() == 1,
          f"麦克风 {window.mic_combo.count()} 项 / 系统声音 {window.sound_combo.count()} 项")

    # ---------------- 5. 后台扫描完成后自动填好 ---------------- #
    deadline = time.perf_counter() + 40
    while time.perf_counter() < deadline and window.mic_combo.count() <= 1 \
            and window.sound_combo.count() <= 1:
        pump(app, 0.1)
    filled = window.mic_combo.count() + window.sound_combo.count()
    check("后台扫描完成后下拉被自动填充", filled > 2,
          f"麦克风 {window.mic_combo.count()} 项 / 系统声音 {window.sound_combo.count()} 项")
    check("回调也在工作线程触发（由信号切回主线程）",
          seen.get("thread") is not None and "audio-device-scan" in seen.get("thread", ""),
          f"回调线程 {seen.get('thread')}")
    check("所有枚举都发生在工作线程",
          all(name != "MainThread" for name in calls),
          f"线程 {sorted(set(calls))}")

    # ---------------- 6. 缓存命中后不再重复扫描 ---------------- #
    check("已有缓存时不再重复扫描", audio.scan_microphones_async() is None)
    check("扫描结果已进入缓存", audio.microphones_scanned(),
          f"{len(audio.cached_microphones())} 个设备")

    # ---------------- 7. 主窗口相关路径也不阻塞 ---------------- #
    _, mics_elapsed = time_call(_cached_mics)
    check("主窗口读取麦克风列表不阻塞", mics_elapsed < 0.2,
          f"{mics_elapsed * 1000:.1f} ms")

    audio.list_microphones = real_list
    window.close()
    main_window._quitting = True
    main_window.close()
    pump(app, 0.3)

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- DEVICE SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("DEVICE SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
