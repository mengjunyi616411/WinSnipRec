"""Live test for the Settings dropdowns.

Launches the real application, opens 设置, clicks the 主题 combo box and inspects
the pixels actually painted on screen -- this is the check that the combo popup
is readable (it used to render dark-on-dark).

Run:  .venv\\Scripts\\python.exe tests\\selftest_settings_live.py
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_settings" / "_config"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import winapi  # noqa: E402

# Window open animations run in real use; tests need deterministic pixels, so
# they are switched off here (selftest_animation.py covers the animations).
from winsnip.settings import settings  # noqa: E402

settings.animations = False


user32 = ctypes.windll.user32
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def click(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.25)


def find_window(title: str, timeout: float = 45.0):
    """Qt appends the application display name, so match on a substring."""
    end = time.time() + timeout
    while time.time() < end:
        for window in winapi.list_windows():
            if title in window.title:
                return window
        time.sleep(0.4)
    return None


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _app_pids() -> set[int]:
    pids: set[int] = set()
    for image in ("pythonw.exe", "截图工具.exe"):
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].lower().startswith(image.split(".")[0].lower()):
                try:
                    pids.add(int(parts[1]))
                except (ValueError, IndexError):
                    pass
    return pids


def enum_app_windows(pids: set[int]):
    """Every window owned by the app, including Qt popups (tool windows)."""
    results: list[tuple[int, str, str, tuple[int, int, int, int], bool]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        rect = _RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        results.append((int(hwnd), buf.value, class_name.value,
                        (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                        bool(user32.IsWindowVisible(hwnd))))
        return True

    user32.EnumWindows(callback, 0)
    return results


def find_popup(pids: set[int], timeout: float = 8.0):
    """The Qt popup window of the combo box (class contains 'Popup').

    Note that Qt gives the popup the *application* name as its title, so the
    class name is the only reliable discriminator.
    """
    end = time.time() + timeout
    while time.time() < end:
        for hwnd, title, class_name, rect, visible in enum_app_windows(pids):
            if not visible or "Popup" not in class_name:
                continue
            left, top, width, height = rect
            if width < 40 or height < 30 or width > 900 or height > 900:
                continue
            return rect
        time.sleep(0.3)
    return None


def run_round(app: QApplication, theme_mode: str, label: str) -> None:
    """Launch the app with ``theme_mode``, open 设置 and inspect the dropdown."""
    packaged = os.environ.get("WINSNIPREC_TEST_EXE")
    if packaged and Path(packaged).is_file():
        command = [packaged, "--open-settings"]
        print(f"[info] target: packaged executable {packaged}")
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        interpreter = str(pythonw if pythonw.exists() else sys.executable)
        command = [interpreter, "app.py", "--open-settings"]
        print(f"[info] target: source tree via {interpreter}")

    home = Path(os.environ["WINSNIPREC_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    (home / "settings.json").write_text(
        json.dumps({"theme": theme_mode, "minimize_to_tray": False}, ensure_ascii=False),
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["WINSNIPREC_HOME"] = str(home)
    print(f"[info] {label}: launching with theme={theme_mode}")
    process = subprocess.Popen(command, cwd=str(ROOT), env=env)
    try:
        window = find_window("设置", timeout=60)
        check(f"{label}：设置窗口出现", window is not None,
              f"{window.width}x{window.height}" if window else "未找到")
        if window is None:
            return

        # A frozen build needs several seconds before its event loop is really
        # pumping; clicking too early silently does nothing.
        time.sleep(3.0)
        winapi.force_foreground(window.hwnd)
        time.sleep(1.0)
        refreshed = find_window("设置", timeout=5)
        if refreshed is not None:
            window = refreshed

        pids = {process.pid}
        combo_x = window.left + int(window.width * 0.85)
        combo_y = window.top + int(window.height * 0.188)

        popup = None
        for _attempt in range(3):
            click(combo_x, combo_y)
            popup = find_popup(pids, timeout=3.0)
            if popup is not None:
                break
            time.sleep(1.0)
        time.sleep(0.6)

        screen = app.primaryScreen().grabWindow(0)
        screen.save(str(ROOT / "docs" / "screenshots" /
                    f"live_settings_open_{theme_mode}.png"), "PNG")

        check(f"{label}：下拉列表窗口已弹出", popup is not None,
              f"{popup[2]}x{popup[3]} @ ({popup[0]},{popup[1]})" if popup else "未找到")
        if popup is None:
            return

        region = screen.copy(popup[0], popup[1], popup[2], popup[3])
        image = region.toImage()
        counts: dict[tuple[int, int, int], int] = {}
        for y in range(0, image.height(), 2):
            for x in range(0, image.width(), 2):
                colour = image.pixelColor(x, y)
                key = (colour.red(), colour.green(), colour.blue())
                counts[key] = counts.get(key, 0) + 1
        dominant, dominant_count = max(counts.items(), key=lambda kv: kv[1])

        def luma(c: tuple[int, int, int]) -> float:
            return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

        strongest = max(counts, key=lambda c: abs(luma(c) - luma(dominant)))
        contrast = abs(luma(strongest) - luma(dominant))
        total = sum(counts.values())

        check(f"{label}：下拉列表文字对比度足够（不是黑底黑字/白底白字）",
              contrast > 100,
              f"背景 luma {luma(dominant):.0f}，文字 luma {luma(strongest):.0f}，对比 {contrast:.0f}")
        expected = (249, 249, 249) if theme_mode == "light" else (44, 44, 44)
        check(f"{label}：下拉列表底色符合主题",
              all(abs(dominant[i] - expected[i]) <= 8 for i in range(3)),
              f"实测 #{dominant[0]:02X}{dominant[1]:02X}{dominant[2]:02X}，"
              f"期望 #{expected[0]:02X}{expected[1]:02X}{expected[2]:02X}")
        check(f"{label}：下拉列表确实渲染了条目（不只是纯色块）",
              dominant_count < total * 0.9,
              f"背景占比 {dominant_count}/{total} = {dominant_count / total:.0%}")
        user32.keybd_event(0x1B, 0, 0, 0)
        user32.keybd_event(0x1B, 0, 0x0002, 0)
    finally:
        try:
            process.terminate()
            process.wait(timeout=10)
        except Exception:
            pass
        subprocess.run(["taskkill", "/F", "/IM", "pythonw.exe"], capture_output=True)
        subprocess.run(["taskkill", "/F", "/IM", "截图工具.exe"], capture_output=True)
        time.sleep(1.0)


def main() -> int:
    app = QApplication(sys.argv)  # needed for screen grabbing
    for theme_mode, label in (("dark", "深色"), ("light", "浅色")):
        run_round(app, theme_mode, label)
    return report(app, None)


def report(app: QApplication, process) -> int:
    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- SETTINGS LIVE SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("SETTINGS LIVE SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
