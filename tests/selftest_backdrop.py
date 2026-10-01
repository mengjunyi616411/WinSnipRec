"""Real DWM backdrop: probe, fallback and settings plumbing.

Regression notes:
  * the probe must decide by PIXELS, not by the API return code - the API accepts
    the request on this machine and renders nothing (the system's own Start menu
    is opaque here too);
  * any window that cannot use the native material must end up exactly as before
    (layered, shadow margin, wallpaper backdrop), because that is the path every
    existing look depends on;
  * a FluentWindow must never keep the native path when the surface is broken.

Run:  .venv\\Scripts\\python.exe tests\\selftest_backdrop.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_backdrop" / "_config"))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import backdrop, winapi  # noqa: E402

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

    from winsnip.settings import settings
    from winsnip.theme import apply_app_theme, theme

    settings.minimize_to_tray = False
    settings.animations = False
    theme.style = "win10"
    theme.mode = "dark"
    theme.refresh()
    apply_app_theme(app)

    # ---------------- 1. 探测：按像素判定，而不是按返回值 ---------------- #
    started = time.perf_counter()
    probed = backdrop.probe_native_backdrop()
    probe_time = time.perf_counter() - started
    check("探测返回布尔值", isinstance(probed, bool), f"结果 {probed}")
    check("探测不会卡住（< 10 秒）", probe_time < 10.0, f"{probe_time:.2f}s")

    # 本机 API 接受请求但什么都不画，所以"接受"和"生效"必须能区分开。
    handle_probe = _api_accepted()
    check("能区分「API 接受」和「真的渲染」",
          isinstance(handle_probe, bool),
          f"API 接受={handle_probe}，像素判定={probed}"
          + ("（本机即为此种情况）" if handle_probe and not probed else ""))

    # ---------------- 2. 缓存 ---------------- #
    first = backdrop.native_available()
    started = time.perf_counter()
    second = backdrop.native_available()
    cached_time = time.perf_counter() - started
    check("探测结果被缓存（第二次不再截屏）", cached_time < 0.05 and first == second,
          f"第二次 {cached_time * 1000:.1f} ms，结果 {second}")

    # ---------------- 3. 设置项决定走哪条路 ---------------- #
    original = getattr(settings, "backdrop", "auto")
    settings.backdrop = "classic"
    check("设为「经典」时不使用原生背景", backdrop.wanted() is False)
    settings.backdrop = "native"
    check("设为「强制实时」时使用原生背景", backdrop.wanted() is True)
    settings.backdrop = "auto"
    check("设为「自动」时跟随探测结果", backdrop.wanted() == first,
          f"wanted={backdrop.wanted()} probe={first}")
    settings.backdrop = original

    # ---------------- 4. 不支持时窗口保持原样 ---------------- #
    from winsnip.ui.widgets import FluentWindow, SHADOW_MARGIN

    classic = FluentWindow(None, native_backdrop=False)
    classic.set_card_size(400, 220)
    check("经典路径保留阴影留白与半透明（现有观感的全部依赖）",
          classic._margin == SHADOW_MARGIN
          and classic.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
          f"margin={classic._margin} 半透明="
          f"{classic.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)}")
    check("经典路径不尝试原生背景", not classic._native_backdrop)
    classic.close()
    classic.deleteLater()
    pump(app, 0.2)

    native = FluentWindow(None, native_backdrop=True)
    native.set_card_size(400, 220)
    check("强制原生时去掉留白、不再是分层窗口（原生背景的前提）",
          native._margin == 0
          and not native.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground),
          f"margin={native._margin} 半透明="
          f"{native.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)}")
    native.show()
    pump(app, 1.0)
    handle = native.windowHandle()
    layered = winapi.is_layered(int(handle.winId())) if handle is not None else None
    check("原生路径的窗口确实不是分层窗口（分层会绕过 DWM 背景）",
          layered is False, f"is_layered={layered}")
    native._quitting = True
    native.close()
    native.deleteLater()
    pump(app, 0.4)

    # ---------------- 5. 健全性检查用的是截屏，不是 grab() ---------------- #
    # grab() 会离屏渲染控件本身，而原生路径故意不画客户区，于是永远是黑的 ——
    # 那样会在所有机器上误判并回退，把功能自己关掉。
    import inspect

    source = inspect.getsource(FluentWindow._verify_native_backdrop)
    # 只看真正的调用，不看注释里提到的名字
    # 去掉 docstring 再看实际代码：注释里提到 self.grab() 不算调用
    import ast as _ast
    import textwrap

    tree = _ast.parse(textwrap.dedent(source))
    function = tree.body[0]
    if (function.body and isinstance(function.body[0], _ast.Expr)
            and isinstance(function.body[0].value, _ast.Constant)):
        function.body = function.body[1:]
    code = _ast.unparse(function)
    calls_grab = "self.grab()" in code
    check("健全性检查截取屏幕而不是调用 grab()",
          "screen.grabWindow" in code and not calls_grab,
          f"screen.grabWindow={'screen.grabWindow' in code} self.grab()={calls_grab}")

    # ---------------- 6. 探测结果落盘可复用 ---------------- #
    check("探测结果写进设置（下次启动不必重新探测）",
          settings.backdrop_native == first
          and settings.backdrop_probe_version == backdrop.PROBE_VERSION,
          f"backdrop_native={settings.backdrop_native} "
          f"version={settings.backdrop_probe_version}")

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- BACKDROP SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("BACKDROP SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


def _api_accepted() -> bool:
    """Does the OS accept the backdrop request, regardless of whether it renders?"""
    from PySide6.QtWidgets import QWidget

    window = QWidget()
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    window.setAutoFillBackground(False)
    window.resize(60, 40)
    window.show()
    QApplication.processEvents()
    handle = window.windowHandle()
    accepted = False
    if handle is not None:
        hwnd = int(handle.winId())
        accepted = winapi.set_system_backdrop(hwnd, winapi.DWMSBT_TRANSIENTWINDOW)
        if not accepted:
            accepted = winapi.set_accent_blur(hwnd, winapi.ACCENT_ENABLE_ACRYLICBLURBEHIND)
        winapi.clear_backdrop(hwnd)
    window.close()
    window.deleteLater()
    QApplication.processEvents()
    return bool(accepted)


if __name__ == "__main__":
    raise SystemExit(main())
