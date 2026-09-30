"""Global hotkey test: registers a real hotkey and injects real keystrokes.

Verifies the whole chain (RegisterHotKey -> WM_HOTKEY -> native event filter ->
dispatcher) rather than calling the handler directly.

Run:  .venv\\Scripts\\python.exe tests\\selftest_hotkeys.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_hotkeys" / "_config"))

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from winsnip import winapi  # noqa: E402
from winsnip.ui import hotkeys  # noqa: E402

# Window open animations run in real use; tests need deterministic pixels, so
# they are switched off here (selftest_animation.py covers the animations).
from winsnip.settings import settings  # noqa: E402

settings.animations = False


user32 = ctypes.windll.user32
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_F9 = 0x78

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def key(vk: int, up: bool = False) -> None:
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def press_combo() -> None:
    key(VK_CONTROL)
    key(VK_MENU)
    key(VK_F9)
    time.sleep(0.05)
    key(VK_F9, True)
    key(VK_MENU, True)
    key(VK_CONTROL, True)


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.resize(240, 120)
    window.show()
    pump(app, 0.5)

    check("hotkey name parses",
          winapi.parse_hotkey("Ctrl+Alt+F9") is not None,
          str(winapi.parse_hotkey("Ctrl+Alt+F9")))
    check("Win+Shift+R parses to MOD_WIN|MOD_SHIFT|'R'",
          winapi.parse_hotkey("Win+Shift+R") == (winapi.MOD_WIN | winapi.MOD_SHIFT | winapi.MOD_NOREPEAT,
                                                 ord("R")),
          str(winapi.parse_hotkey("Win+Shift+R")))

    fired: list[float] = []
    ok = hotkeys.register("test", "Ctrl+Alt+F9", lambda: fired.append(time.perf_counter()))
    check("Ctrl+Alt+F9 registered with Windows", ok,
          "ok" if ok else "RegisterHotKey refused (already taken on this host)")
    if not ok:
        return report(app)
    check("hotkeys.registered() reflects the binding", hotkeys.registered("test"))

    # Inject the real keystroke; Windows should post WM_HOTKEY to our queue.
    for _ in range(3):
        press_combo()
        pump(app, 0.7)
    check("WM_HOTKEY reached the native event filter and dispatched",
          len(fired) >= 1, f"{len(fired)} activations")

    # A second injection round to make sure the binding is not one-shot.
    before = len(fired)
    press_combo()
    pump(app, 0.8)
    check("hotkey still fires on a later press", len(fired) > before,
          f"{before} -> {len(fired)}")

    hotkeys.unregister("test")
    fired.clear()
    press_combo()
    pump(app, 0.8)
    check("unregister() releases the hotkey", not fired, f"{len(fired)} activations after unregister")

    return report(app)


def report(app: QApplication) -> int:
    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- HOTKEY SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("HOTKEY SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
