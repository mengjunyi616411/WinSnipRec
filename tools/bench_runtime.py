"""Measure WinSnipRec's own runtime footprint.

Reports RSS and CPU for: the idle GUI, a full-screen 1080p recording, and the
raw screen-grab cost per frame.

Run:  .venv\\Scripts\\python.exe tools\\bench_runtime.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


kernel32.GetCurrentProcess.restype = wintypes.HANDLE
psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                       ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                                       wintypes.DWORD]
psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                     ctypes.POINTER(wintypes.FILETIME),
                                     ctypes.POINTER(wintypes.FILETIME),
                                     ctypes.POINTER(wintypes.FILETIME)]
kernel32.GetProcessTimes.restype = wintypes.BOOL


def rss_mb() -> float:
    counters = PROCESS_MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(counters)
    ok = psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters),
                                    counters.cb)
    if not ok:
        raise OSError(f"GetProcessMemoryInfo failed: {ctypes.get_last_error()}")
    return counters.WorkingSetSize / 1_048_576


def cpu_seconds() -> float:
    creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
    ok = kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), ctypes.byref(creation),
                                  ctypes.byref(exit_), ctypes.byref(kernel),
                                  ctypes.byref(user))
    if not ok:
        raise OSError(f"GetProcessTimes failed: {ctypes.get_last_error()}")
    to_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime  # noqa: E731
    return (to_int(kernel) + to_int(user)) / 1e7


def main() -> int:
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from winsnip import winapi
    from winsnip.core.recorder import Recorder
    from winsnip.core.screen import ScreenGrabber, virtual_rect
    from winsnip.settings import settings
    from winsnip.theme import apply_app_theme, theme
    from winsnip.ui.main_window import MainWindow

    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    theme.mode = "light"
    apply_app_theme(app)

    print("=== 界面常驻占用 ===")
    baseline = rss_mb()
    print(f"启动 Python + Qt 后 RSS        : {baseline:6.1f} MB")

    settings.minimize_to_tray = False
    window = MainWindow()
    window.show()
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    idle = rss_mb()
    print(f"主窗口显示后 RSS               : {idle:6.1f} MB   (+{idle - baseline:.1f})")

    cpu_start = cpu_seconds()
    time.sleep(3.0)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    idle_cpu = (cpu_seconds() - cpu_start) / 3.4
    print(f"空转 CPU（主窗口开着不操作）   : {idle_cpu * 100:5.1f} %（单核为 100%）")

    print("\n=== 抓屏开销（mss / BitBlt）===")
    left, top, width, height = virtual_rect()
    print(f"虚拟桌面: {width}x{height}")
    grabber = ScreenGrabber()
    for label, rect in (("100x100", (0, 0, 100, 100)),
                        ("640x480", (0, 0, 640, 480)),
                        ("1280x720", (0, 0, 1280, 720)),
                        ("1920x1080", (0, 0, 1920, 1080))):
        samples = []
        for _ in range(6):
            t0 = time.perf_counter()
            grabber.grab(rect)
            samples.append(time.perf_counter() - t0)
        best = min(samples)
        print(f"{label:11s} 单帧 {best * 1000:6.1f} ms  → 理论上限 {1 / best:5.1f} fps")
    grabber.close()

    print("\n=== 录屏中的占用（1920x1080 @30fps）===")
    out = Path(ROOT / "_bench" / "runtime.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(rect=(0, 0, 1920, 1080), fps=30, crf=20, mic=None,
                        out_path=str(out), tmp_dir=str(ROOT / "_bench" / "tmp"))
    recorder.start()
    peak = rss_mb()
    cpu_start = cpu_seconds()
    started = time.perf_counter()
    while time.perf_counter() - started < 8.0:
        app.processEvents()
        peak = max(peak, rss_mb())
        time.sleep(0.02)
    elapsed = time.perf_counter() - started
    cpu_used = cpu_seconds() - cpu_start
    recorded = recorder.elapsed
    recorder.stop()
    print(f"录制中峰值 RSS                 : {peak:6.1f} MB   (+{peak - idle:.1f} 相对空窗口)")
    print(f"录制 8 秒实际 CPU              : {cpu_used:5.1f} 秒 → {cpu_used / elapsed:4.2f} 核")
    print(f"8 秒里实际录到                 : {recorded:4.2f} 秒（本机抓屏是瓶颈，见上）")
    print(f"输出大小                       : {out.stat().st_size / 1024:.0f} KB"
          if out.exists() else "无输出")

    print("\n=== 停止耗时 ===")
    for index in range(2):
        recorder = Recorder(rect=(0, 0, 1280, 720), fps=30, crf=20,
                            out_path=str(ROOT / "_bench" / f"stop{index}.mp4"),
                            tmp_dir=str(ROOT / "_bench" / f"tmp{index}"))
        recorder.start()
        end = time.perf_counter() + 2.0
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.02)
        t0 = time.perf_counter()
        recorder.stop()
        print(f"720p30 录 2 秒后 stop()        : {(time.perf_counter() - t0):5.2f} 秒")

    window._quitting = True
    window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
