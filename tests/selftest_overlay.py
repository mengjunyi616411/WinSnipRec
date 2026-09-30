"""Interaction test for the capture overlay (region picking, confirm, cancel).

Run:  .venv\\Scripts\\python.exe tests\\selftest_overlay.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("WINSNIPREC_HOME", str(ROOT / "_selftest_overlay" / "_config"))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winsnip import winapi  # noqa: E402
from winsnip.core.screen import virtual_rect  # noqa: E402
from winsnip.theme import application_stylesheet, theme  # noqa: E402

# Window open animations run in real use; tests need deterministic pixels, so
# they are switched off here (selftest_animation.py covers the animations).
from winsnip.settings import settings  # noqa: E402

settings.animations = False


checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def pump(app: QApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    winapi.enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    theme.mode = "light"
    app.setStyleSheet(application_stylesheet())

    from winsnip.ui.overlay import CaptureOverlay

    # ---------------- rectangle drag + confirm ---------------- #
    # confirm=True keeps the selection adjustable before committing.
    overlay = CaptureOverlay(mode="video", shape="rectangle", confirm=True)
    got: dict = {}
    overlay.finished.connect(lambda rect, shape, mode: got.update(rect=rect, shape=shape, mode=mode))
    overlay.cancelled.connect(lambda: got.update(cancelled=True))
    overlay.start()
    pump(app, 0.7)
    check("overlay is shown full screen",
          overlay.isVisible() and overlay.width() > 200,
          f"{overlay.width()}x{overlay.height()}")
    check("frozen screenshot captured",
          overlay._screen_image is not None and not overlay._screen_image.isNull(),
          f"{overlay._screen_image.width()}x{overlay._screen_image.height()}"
          if overlay._screen_image else "none")
    check("mode bar is inside the overlay",
          overlay._bar.isVisible() and overlay._bar.width() > 100,
          f"{overlay._bar.width()}x{overlay._bar.height()}")

    start = QPoint(220, 260)
    end = QPoint(700, 620)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    steps = 8
    for index in range(1, steps + 1):
        point = QPoint(start.x() + (end.x() - start.x()) * index // steps,
                       start.y() + (end.y() - start.y()) * index // steps)
        QTest.mouseMove(overlay, point)
        app.processEvents()
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    pump(app, 0.3)

    selection = overlay._selection
    check("drag produced a selection",
          not selection.isNull() and selection.width() > 100,
          f"{selection.width()}x{selection.height()}")
    check("selection matches the dragged area",
          abs(selection.width() - (end.x() - start.x())) <= 3
          and abs(selection.height() - (end.y() - start.y())) <= 3,
          f"{selection.width()}x{selection.height()} vs {end.x() - start.x()}x{end.y() - start.y()}")
    check("nothing emitted before confirming", "rect" not in got)

    # adjusting the selection with the keyboard keeps it alive
    before_x = overlay._selection.x()
    QTest.keyClick(overlay, Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier)
    pump(app, 0.1)
    check("arrow key nudges the selection",
          overlay._selection.x() == before_x + 1,
          f"x {before_x} -> {overlay._selection.x()}")
    width_before = overlay._selection.width()
    QTest.keyClick(overlay, Qt.Key.Key_Right)
    pump(app, 0.1)
    check("unmodified arrow key nudges by 10px",
          overlay._selection.x() == before_x + 11 and overlay._selection.width() == width_before,
          f"x {overlay._selection.x()}")

    # double click confirms
    QTest.mouseDClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                      QPoint(overlay._selection.center()))
    pump(app, 0.5)
    check("confirm emits finished", "rect" in got, str(got.get("rect")))
    if "rect" in got:
        left, top, width, height = virtual_rect()
        rect: QRect = got["rect"]
        from winsnip.core.screen import list_monitors

        monitors = list_monitors()
        import ctypes
        user32 = ctypes.windll.user32
        origin = (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))  # SM_X/YVIRTUALSCREEN
        expected_left = origin[0] + int(round(overlay._selection.x() * overlay._dpr))
        expected_top = origin[1] + int(round(overlay._selection.y() * overlay._dpr))
        check("physical rect is offset by the virtual desktop origin",
              abs(rect.x() - expected_left) <= 3 and abs(rect.y() - expected_top) <= 3,
              f"got ({rect.x()},{rect.y()}) expected ({expected_left},{expected_top}) "
              f"virtual origin {origin}")
        check("physical rect keeps the aspect ratio",
              rect.width() > rect.height(),
              f"{rect.width()}x{rect.height()}")
        check("shape/mode round-trip", got.get("shape") == "rectangle" and got.get("mode") == "video",
              f"{got.get('shape')}/{got.get('mode')}")

    # ---------------- cancel ---------------- #
    overlay2 = CaptureOverlay(mode="camera", shape="rectangle")
    state: dict = {}
    overlay2.finished.connect(lambda *_: state.update(finished=True))
    overlay2.cancelled.connect(lambda: state.update(cancelled=True))
    overlay2.start()
    pump(app, 0.5)
    QTest.keyClick(overlay2, Qt.Key.Key_Escape)
    pump(app, 0.4)
    check("escape cancels", state.get("cancelled") is True and not state.get("finished"),
          str(state))
    try:
        still_visible = overlay2.isVisible()
    except RuntimeError:
        still_visible = False  # WA_DeleteOnClose already destroyed it
    check("cancelled overlay is closed", not still_visible)

    # ---------------- fullscreen auto-select ---------------- #
    overlay3 = CaptureOverlay(mode="video", shape="fullscreen")
    result: dict = {}
    overlay3.finished.connect(lambda rect, shape, mode: result.update(rect=rect, shape=shape))
    overlay3.start()
    pump(app, 0.6)
    check("fullscreen preselects a monitor",
          not overlay3._selection.isNull() and overlay3._selection.width() > 400,
          f"{overlay3._selection.width()}x{overlay3._selection.height()}")
    QTest.mouseClick(overlay3, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(overlay3.width() // 2, overlay3.height() // 2))
    pump(app, 0.4)
    check("fullscreen confirms on click", "rect" in result and result.get("shape") == "fullscreen",
          str(result.get("rect")))

    # ---------------- window mode ---------------- #
    overlay4 = CaptureOverlay(mode="camera", shape="window")
    windows: dict = {}
    overlay4.finished.connect(lambda rect, shape, mode: windows.update(rect=rect, shape=shape))
    overlay4.start()
    pump(app, 0.6)
    from winsnip import winapi as wa

    found = wa.list_windows()
    check("window enumeration finds real windows", len(found) > 0,
          f"{len(found)} windows, top={found[0].title[:28] if found else '-'}")
    if found:
        from PySide6.QtGui import QCursor

        target = None
        point = None
        for candidate in found:
            local = overlay4._from_physical(
                QRect(candidate.left, candidate.top, candidate.width, candidate.height))
            centre = local.center()
            if not overlay4.rect().contains(centre):
                continue
            QCursor.setPos(overlay4.mapToGlobal(centre))
            pump(app, 0.25)
            overlay4._update_hover_window(QCursor.pos())
            hovered = overlay4._hover_window
            if hovered is not None and hovered.width > 100 and hovered.height > 100:
                target, point = candidate, centre
                break
        check("hovering picks the window under the cursor",
              target is not None,
              (overlay4._hover_window.title[:30] if overlay4._hover_window else "none"))
        if target is not None and point is not None:
            hovered_before = overlay4._hover_window
            QTest.mouseClick(overlay4, Qt.MouseButton.LeftButton,
                             Qt.KeyboardModifier.NoModifier, point)
            pump(app, 0.5)
            check("window mode confirms on click", "rect" in windows,
                  f"{windows.get('rect')} shape={windows.get('shape')}")
            if "rect" in windows and hovered_before is not None:
                rect = windows["rect"]
                check("picked window rect matches the hovered window",
                      abs(rect.width() - hovered_before.width) <= 4
                      and abs(rect.height() - hovered_before.height) <= 4
                      and abs(rect.x() - hovered_before.left) <= 4
                      and abs(rect.y() - hovered_before.top) <= 4,
                      f"{rect.x()},{rect.y()} {rect.width()}x{rect.height()} vs "
                      f"{hovered_before.left},{hovered_before.top} "
                      f"{hovered_before.width}x{hovered_before.height} ({hovered_before.title[:20]})")

    # ---------------- immediate start (Windows 11 behaviour) ---------------- #
    overlay5 = CaptureOverlay(mode="video", shape="rectangle")  # confirm=False is the default
    instant: dict = {}
    overlay5.finished.connect(
        lambda rect, shape, mode: instant.update(rect=rect, shape=shape, mode=mode))
    overlay5.start()
    pump(app, 0.6)
    start5, end5 = QPoint(260, 300), QPoint(820, 640)
    QTest.mousePress(overlay5, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start5)
    for index in range(1, 6):
        QTest.mouseMove(overlay5, QPoint(start5.x() + (end5.x() - start5.x()) * index // 5,
                                         start5.y() + (end5.y() - start5.y()) * index // 5))
        app.processEvents()
    QTest.mouseRelease(overlay5, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end5)
    pump(app, 0.5)
    check("默认：松开鼠标立即开始（与 Win11 一致）",
          "rect" in instant and instant.get("mode") == "video",
          str(instant.get("rect")))

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- OVERLAY SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("OVERLAY SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
