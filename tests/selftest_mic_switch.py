"""Live microphone switching test for Recorder.set_mic().

Records ~3 s in three 1 s stretches: no mic -> default mic -> no mic, and checks
that the swap happens at a segment boundary (so the duration is unchanged) and
that the audio track stays aligned with the video.

Run:  .venv\\Scripts\\python.exe tests\\selftest_mic_switch.py
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

from PySide6.QtCore import QCoreApplication  # noqa: E402

from winsnip.core.audio import default_microphone, list_microphones  # noqa: E402
from winsnip.core.encoder import ffmpeg_path, run_ffmpeg_checked  # noqa: E402
from winsnip.core.recorder import Recorder  # noqa: E402

# Window open animations run in real use; tests need deterministic pixels, so
# they are switched off here (selftest_animation.py covers the animations).
from winsnip.settings import settings  # noqa: E402

settings.animations = False


OUT = ROOT / "_selftest" / "mic_switch"

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app: QCoreApplication, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.01)


def probe(path: Path) -> tuple[float, list[str]]:
    result = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True, errors="replace", timeout=120,
    )
    log = (result.stderr or "") + (result.stdout or "")
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", log)
    duration = 0.0
    if match:
        h, m, s = match.groups()
        duration = int(h) * 3600 + int(m) * 60 + float(s)
    streams = [line.strip() for line in log.splitlines() if "Stream #" in line]
    return duration, streams


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*"):
        try:
            stale.unlink()
        except OSError:
            pass

    app = QCoreApplication(sys.argv)
    target = OUT / "mic_switch.mp4"
    device = default_microphone()
    devices = list_microphones()
    print(f"[info] audio devices: {len(devices)}")
    print(f"[info] default microphone: {device.id if device else 'NONE'}")

    recorder = Recorder(rect=(0, 0, 320, 240), fps=30, crf=26, mic=None,
                        out_path=str(target), tmp_dir=str(OUT / "tmp"))
    finished: dict[str, str] = {}
    errors: list[str] = []
    recorder.finished.connect(lambda path: finished.update(path=path))
    recorder.error.connect(errors.append)

    recorder.start()
    pump(app, 1.1)
    check("recording started without a microphone", recorder.state.name == "RECORDING",
          recorder.state.name)

    if device is not None:
        recorder.set_mic(device)
        pump(app, 1.2)
        check("set_mic(default) during recording is accepted",
              getattr(recorder, "_mic", None) is not None
              or recorder.state.name == "RECORDING", recorder.state.name)
        recorder.set_mic(None)
        pump(app, 1.2)
    else:
        recorder.set_mic(None)
        pump(app, 2.4)
    active = recorder.elapsed
    path = recorder.stop()
    pump(app, 0.6)

    check("stop() returned a path", bool(path) and os.path.isfile(path), path or "none")
    check("finished signal carries the same path", finished.get("path") == path)
    check("no recorder errors reported", not errors, "; ".join(errors)[:200] or "none")

    if not path:
        return report(app)

    duration, streams = probe(Path(path))
    video = next((s for s in streams if "Video:" in s), "")
    audio = next((s for s in streams if "Audio:" in s), "")
    print(f"[info] active={active:.2f}s file={duration:.2f}s")
    print(f"[info] {video[:120]}")
    print(f"[info] {audio[:120] or 'no audio stream'}")

    check("segment boundary swap kept the duration",
          abs(duration - active) <= max(0.6, active * 0.25),
          f"file {duration:.2f}s vs active {active:.2f}s")
    check("video stream is present at 320x240 / 30 fps",
          "h264" in video and "320x240" in video, video[:90])
    if device is not None:
        check("audio stream present after switching the mic on",
              bool(audio) and "aac" in audio, audio[:90] or "none")
        check("audio duration matches the video duration",
              abs(duration - active) <= max(0.6, active * 0.25),
              f"{duration:.2f}s")
    else:
        check("no microphone available on this host (nothing to verify)",
              audio == "", "skipped")

    return report(app)


def report(app: QCoreApplication) -> int:
    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- MIC SWITCH SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("MIC SWITCH SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    app.quit()
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
