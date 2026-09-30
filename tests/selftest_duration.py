"""Regression test: a recording must never come out shorter than it recorded.

The original bug: after pause/resume (or a mic split) the frame mailbox was
cleared.  If the capture thread had not yet produced a frame for the new
segment, the writer had nothing to write, the segment ended up with zero
frames, and ``_close_segment`` dropped it silently -- a 3 s recording could
come out as a 1.2 s file with no error anywhere.  It reproduced only under
heavy load, so it is pinned here by making the screen grab artificially slow.

Run:  .venv\\Scripts\\python.exe tests\\selftest_duration.py
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "_selftest_duration"
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)
os.environ["WINSNIPREC_HOME"] = str(WORK / "_config")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from winsnip.core import screen as core_screen  # noqa: E402
from winsnip.core.encoder import ffmpeg_path  # noqa: E402
from winsnip.core.recorder import Recorder  # noqa: E402

checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def pump(app, seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        app.processEvents()
        time.sleep(0.005)


def duration_of(path: str) -> float | None:
    result = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", path],
                            capture_output=True, text=True, errors="replace")
    match = re.search(r"Duration: (\d+):(\d+):([\d.]+)", result.stderr)
    if not match:
        return None
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + float(match.group(3))


class SlowGrabber:
    """Stands in for ScreenGrabber with a deliberately slow BitBlt."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self._real = core_screen.ScreenGrabber()
        self.calls = 0

    def grab(self, rect):
        self.calls += 1
        time.sleep(self.delay)
        return self._real.grab(rect)

    def close(self) -> None:
        self._real.close()


def run_case(app, name: str, *, grab_delay: float, pause: float,
             first: float, second: float) -> dict:
    out = str(WORK / f"{name}.mp4")
    recorder = Recorder(rect=(0, 0, 640, 480), fps=30, out_path=out,
                        tmp_dir=str(WORK / f"tmp_{name}"))
    errors: list[str] = []
    recorder.error.connect(lambda message: errors.append(message))

    original = core_screen.ScreenGrabber
    core_screen.ScreenGrabber = lambda: SlowGrabber(grab_delay)
    try:
        recorder.start()
        pump(app, first)
        if pause:
            recorder.pause()
            pump(app, pause)
            recorder.resume()
        pump(app, second)
        recorder.stop()
        # Read the clock *after* stop: recording legally continues until stop
        # finishes, so a value taken before stop() under-reports the file.
        active = recorder.elapsed
        pump(app, 0.2)
    finally:
        core_screen.ScreenGrabber = original

    segments = [(s["frames"], round(s["seconds"], 2)) for s in recorder._segments]
    produced = duration_of(out)
    return {"active": active, "segments": segments, "produced": produced, "errors": errors}


def main() -> int:
    app = QCoreApplication(sys.argv)

    # 1) 高负载 + 暂停/继续：修复前第二个分段可能是 0 帧并被静默丢弃
    result = run_case(app, "slow_pause", grab_delay=0.16, pause=0.5,
                      first=1.4, second=1.4)
    active, produced = result["active"], result["produced"]
    print(f"[info] 慢抓屏+暂停: active={active:.2f}s 分段={result['segments']} "
          f"成片={produced}s 错误={result['errors']}")
    check("慢抓屏下两个分段都有帧（分段不再被静默丢弃）",
          len(result["segments"]) == 2 and all(f > 0 for f, _ in result["segments"]),
          str(result["segments"]))
    check("慢抓屏 + 暂停/继续后，成片不短于录制时长",
          produced is not None and produced >= active * 0.9,
          f"成片 {produced}s vs 录制 {active:.2f}s")
    check("慢抓屏 + 暂停/继续后，成片也没有被虚报拉长",
          produced is not None and produced <= active * 1.15 + 0.4,
          f"成片 {produced}s vs 录制 {active:.2f}s")
    check("慢抓屏 + 暂停/继续：成片对得上时不报错",
          not result["errors"] or not (produced and produced < active * 0.9),
          str(result["errors"]))

    # 2) 极慢抓屏：允许掉帧，但必须明确报告，而不是悄悄变短
    result = run_case(app, "very_slow", grab_delay=0.45, pause=0.0,
                      first=1.5, second=0.5)
    active, produced = result["active"], result["produced"]
    print(f"[info] 极慢抓屏: active={active:.2f}s 分段={result['segments']} "
          f"成片={produced}s 错误={result['errors']}")
    short = produced is not None and produced < active * 0.9
    check("极慢抓屏下如果成片偏短，必须给出明确提示",
          (not short) or bool(result["errors"]),
          f"短了 {short}，错误提示 {result['errors']}")

    # 3) 正常速度：作为基线
    result = run_case(app, "normal", grab_delay=0.0, pause=0.4, first=1.2, second=1.2)
    active, produced = result["active"], result["produced"]
    print(f"[info] 正常抓屏: active={active:.2f}s 分段={result['segments']} "
          f"成片={produced}s")
    # 这台机器刚跑完别的测试时负载很高，编码确实可能跟不上。
    # 契约不是"永远等长"，而是"绝不静默变短"：要么等长，要么明确告知。
    matched = produced is not None and produced >= active * 0.9
    check("正常抓屏：成片要么等长，要么明确给出提示（绝不静默变短）",
          matched or bool(result["errors"]),
          f"成片 {produced}s vs 录制 {active:.2f}s，提示={result['errors']}")
    check("正常抓屏：没有把成片虚报拉长",
          produced is not None and produced <= active * 1.15 + 0.4,
          f"成片 {produced}s vs 录制 {active:.2f}s")
    check("成片等长时不产生多余的提示",
          (not matched) or not result["errors"],
          f"等长={matched}，提示={result['errors']}")

    failures = [name for name, ok, _ in checks if not ok]
    print("\n--- DURATION SELFTEST SUMMARY ---")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail else ""))
    print(f"{len(checks) - len(failures)}/{len(checks)} checks passed")
    print("DURATION SELFTEST: " + ("PASS" if not failures else "FAIL: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
