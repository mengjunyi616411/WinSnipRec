"""Self-test that runs *inside the frozen executable*.

Launched with ``截图工具.exe --selftest-record``; writes a report next to the
executable (or to %TEMP% when that is not writable) because a windowed build has
no console.  Exit code 0 means ffmpeg was found, frames were captured, and the
produced MP4 decodes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication


def _report_paths() -> list[Path]:
    candidates: list[Path] = []
    try:
        candidates.append(Path(sys.executable).resolve().parent / "selftest_record.txt")
    except Exception:
        pass
    candidates.append(Path(tempfile.gettempdir()) / "winsnip_selftest_record.txt")
    return candidates


def _write(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    for path in _report_paths():
        try:
            path.write_text(text, encoding="utf-8")
            return
        except OSError:
            continue


def run_quit_selftest(app: QCoreApplication) -> int:
    """Verify the tray 'minimise to tray' path cannot block application exit.

    Regression guard: ``MainWindow.closeEvent`` used to ignore the close event
    whenever the tray icon was visible, which made ``QApplication::quit()``
    (and therefore the tray menu's 退出 entry) hang forever.
    """
    from PySide6.QtCore import QTimer

    from winsnip.settings import settings
    from winsnip.ui.main_window import MainWindow

    marker = Path(tempfile.gettempdir()) / "winsnip_quit_selftest.txt"
    try:
        marker.write_text("started\n", encoding="utf-8")
    except OSError:
        pass

    settings.minimize_to_tray = True
    window = MainWindow()
    window.show()
    lines = ["quit selftest: window shown with minimize_to_tray=True"]

    def finish() -> None:
        window._quit()

    QTimer.singleShot(2000, finish)
    app.exec()
    lines.append("event loop returned; process can exit")
    try:
        marker.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    for line in lines:
        try:
            print(line)
        except Exception:
            pass
    return 0


def run_recording_selftest(app: QCoreApplication) -> int:
    from winsnip.core.encoder import ffmpeg_available, ffmpeg_path
    from winsnip.core.recorder import Recorder
    from winsnip.core.screen import list_monitors, virtual_rect

    lines: list[str] = []
    failures: list[str] = []
    frozen = getattr(sys, "frozen", False)
    lines.append(f"frozen        : {frozen}")
    lines.append(f"executable    : {sys.executable}")
    lines.append(f"_MEIPASS      : {getattr(sys, '_MEIPASS', '-')}")

    exe = ffmpeg_path()
    lines.append(f"ffmpeg_path   : {exe or 'NOT FOUND'}")
    lines.append(f"ffmpeg_exists : {bool(exe) and os.path.isfile(exe)}")
    if not exe or not os.path.isfile(exe):
        failures.append("ffmpeg was not found inside the bundle")

    try:
        lines.append(f"virtual_rect  : {virtual_rect()}")
        lines.append(f"monitors      : {[(m.name, m.width, m.height) for m in list_monitors()]}")
    except Exception as exc:
        failures.append(f"screen enumeration failed: {exc!r}")

    target_dir = Path(tempfile.gettempdir()) / "winsnip_frozen_selftest"
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / "frozen.mp4"
    if out.exists():
        try:
            out.unlink()
        except OSError:
            pass

    recorder = Recorder(rect=(0, 0, 320, 240), fps=30, crf=28, mic=None,
                        out_path=str(out), tmp_dir=str(target_dir / "tmp"))
    errors: list[str] = []
    recorder.error.connect(errors.append)

    path = ""
    try:
        recorder.start()
        end = time.perf_counter() + 1.6
        while time.perf_counter() < end:
            app.processEvents()
            time.sleep(0.01)
        active = recorder.elapsed
        path = recorder.stop()
    except Exception as exc:
        failures.append(f"recording raised: {exc!r}")
        active = 0.0

    lines.append(f"active_seconds: {active:.2f}")
    lines.append(f"output        : {path or 'NONE'}")
    if errors:
        lines.append(f"recorder_errors: {'; '.join(errors)[:300]}")

    if not path or not os.path.isfile(path):
        failures.append("no output file was produced")
    else:
        size = os.path.getsize(path)
        lines.append(f"output_size   : {size} bytes")
        # A nearly static 320x240 desktop compresses to only a few kB at CRF 28;
        # this threshold only catches a genuinely empty/broken container.
        if size < 3_000:
            failures.append(f"output too small ({size} bytes)")

        if exe and os.path.isfile(exe):
            probe = subprocess.run(
                [exe, "-hide_banner", "-i", path, "-f", "null", "-"],
                capture_output=True, text=True, errors="replace", timeout=120,
            )
            log = (probe.stderr or "") + (probe.stdout or "")
            interesting = [line.strip() for line in log.splitlines()
                           if "Duration:" in line or "Stream #" in line]
            lines.extend(f"ffmpeg: {line}" for line in interesting)
            if "Video: h264" not in log:
                failures.append("the produced file has no h264 video stream")
            if "320x240" not in log:
                failures.append("the produced file is not 320x240")

    lines.append("")
    lines.append("FROZEN SELFTEST: " + ("PASS" if not failures else "FAIL: " + "; ".join(failures)))
    _write(lines)

    for line in lines:
        try:
            print(line)
        except Exception:
            pass
    return 0 if not failures else 1
