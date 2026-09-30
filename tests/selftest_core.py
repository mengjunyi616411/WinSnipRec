#!/usr/bin/env python
"""Self-test for the WinSnipRec recording core.

Run it with the project interpreter::

    python tests/selftest_core.py

It exercises monitor enumeration, PNG screenshots, a paused/resumed recording
(video only), a recording with the default microphone when one exists, and
verifies every produced MP4 with ffmpeg.  The script prints a per-check summary
and finishes with ``SELFTEST: PASS`` or ``SELFTEST: FAIL``.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WORK = os.path.join(ROOT, "_selftest")

_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    ok = bool(ok)
    _RESULTS.append((name, ok, detail))
    line = f"[{'PASS' if ok else 'FAIL'}] {name}"
    if detail:
        line += f"  ::  {detail}"
    print(line, flush=True)
    return ok


def info(message: str) -> None:
    print(f"[info] {message}", flush=True)


def skip(name: str, reason: str) -> None:
    _RESULTS.append((name, True, f"SKIPPED: {reason}"))
    print(f"[SKIP] {name}  ::  {reason}", flush=True)


def _prepare_workdir() -> None:
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)


# ---------------------------------------------------------------------------
# ffmpeg probing
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Video:\s*([A-Za-z0-9_]+)")
_AUDIO_RE = re.compile(r"Audio:\s*([A-Za-z0-9_]+)")
_SIZE_RE = re.compile(r"(\d{2,5})x(\d{2,5})")
_FPS_RE = re.compile(r"([\d.]+)\s*fps")


def probe(path: str) -> dict:
    """Decode ``path`` with ffmpeg and return the parsed stream facts."""
    from winsnip.core.audio import decode_output
    from winsnip.core.encoder import run_ffmpeg

    result = run_ffmpeg(["-hide_banner", "-i", path, "-f", "null", "-"], timeout=60)
    text = decode_output(result.stderr or b"")
    facts: dict = {"text": text, "duration": None, "video": None, "audio": None,
                   "size": None, "fps": None, "returncode": result.returncode}

    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        facts["duration"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    lines = text.splitlines()
    video_line = ""
    audio_line = ""
    for index, line in enumerate(lines):
        if "Stream #" in line:
            joined = line
            if index + 1 < len(lines):
                following = lines[index + 1]
                if "Stream #" not in following and following[:1].isspace():
                    joined = line + " " + following.strip()
            if "Video:" in line and not video_line:
                video_line = joined
            if "Audio:" in line and not audio_line:
                audio_line = joined
    facts["video_line"] = video_line
    facts["audio_line"] = audio_line

    if video_line:
        codec = _VIDEO_RE.search(video_line)
        facts["video"] = codec.group(1) if codec else None
        size = _SIZE_RE.search(video_line)
        if size:
            facts["size"] = f"{size.group(1)}x{size.group(2)}"
        fps = _FPS_RE.search(video_line)
        if fps:
            facts["fps"] = float(fps.group(1))
    if audio_line:
        codec = _AUDIO_RE.search(audio_line)
        facts["audio"] = codec.group(1) if codec else None
    return facts


def report_facts(label: str, facts: dict) -> None:
    print(f"--- ffmpeg verification: {label} ---", flush=True)
    duration_line = "Duration: (not reported)"
    match = _DURATION_RE.search(facts["text"])
    if match:
        duration_line = match.group(0)
    print(f"    {duration_line}", flush=True)
    print(f"    {facts.get('video_line') or 'Stream #0:0 (no video line)'}", flush=True)
    if facts.get("audio_line"):
        print(f"    {facts['audio_line']}", flush=True)


# ---------------------------------------------------------------------------
# Qt helpers
# ---------------------------------------------------------------------------


def pump(app, seconds: float) -> None:
    """Run the Qt event loop for ``seconds`` so queued signals are delivered."""
    deadline = time.perf_counter() + seconds
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        app.processEvents()
        time.sleep(min(0.01, max(0.0, remaining)))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_screenshot() -> None:
    from PySide6.QtGui import QImage

    from winsnip.core.screen import ScreenGrabber

    grabber = ScreenGrabber()
    try:
        png = grabber.grab_png((0, 0, 400, 300))
    finally:
        grabber.close()

    signature = png[:8] == b"\x89PNG\r\n\x1a\n"
    check("screenshot: PNG signature", signature, f"{len(png)} bytes")
    check("screenshot: size > 5 KB", len(png) > 5120, f"{len(png)} bytes")

    image = QImage.fromData(png) if png else QImage()
    check(
        "screenshot: decodes as 400x300 RGB",
        (not image.isNull()) and image.width() == 400 and image.height() == 300,
        f"{image.width()}x{image.height()}" if not image.isNull() else "null image",
    )
    check(
        "screenshot: not a blank frame",
        len(set(png[1000:4000])) > 8,
        f"{len(set(png[1000:4000]))} distinct byte values",
    )


def test_recording_video_only(app) -> dict:
    from winsnip.core.recorder import Recorder, RecorderState

    out_path = os.path.join(WORK, "a.mp4")
    recorder = Recorder(rect=(0, 0, 640, 480), fps=30, out_path=out_path,
                        capture_cursor=True)
    events = {"states": [], "elapsed": [], "errors": [], "finished": []}
    recorder.state_changed.connect(lambda state: events["states"].append(state))
    recorder.elapsed_changed.connect(lambda value: events["elapsed"].append(value))
    recorder.error.connect(lambda message: events["errors"].append(message))
    recorder.finished.connect(lambda path: events["finished"].append(path))

    wall_start = time.perf_counter()
    recorder.start()
    check("A: state is RECORDING after start()",
          recorder.state is RecorderState.RECORDING, f"state={recorder.state}")
    pump(app, 1.5)
    recorder.pause()
    check("A: state is PAUSED after pause()",
          recorder.state is RecorderState.PAUSED, f"state={recorder.state}")
    pump(app, 0.25)  # let the worker settle the segment (one in-flight frame write)
    elapsed_at_pause = recorder.elapsed
    pump(app, 0.75)
    elapsed_during_pause = recorder.elapsed
    check(
        "A: elapsed does not advance while paused",
        abs(elapsed_during_pause - elapsed_at_pause) < 0.1,
        f"{elapsed_at_pause:.2f}s -> {elapsed_during_pause:.2f}s over 0.75 s paused",
    )
    recorder.resume()
    pump(app, 1.5)
    active = recorder.elapsed
    stop_started = time.perf_counter()
    path = recorder.stop()
    stop_seconds = time.perf_counter() - stop_started
    wall = time.perf_counter() - wall_start
    pump(app, 0.25)  # deliver signals queued right before the worker exited

    check("A: stop() returned the output path", path == out_path and os.path.isfile(out_path),
          f"path={path!r}")
    check("A: stop() did not hang", stop_seconds < 10.0, f"stop() took {stop_seconds:.2f}s")
    size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
    check("A: file size > 20 KB", size > 20 * 1024, f"{size} bytes ({size / 1024:.1f} KB)")
    check("A: state is IDLE after stop()",
          recorder.state is RecorderState.IDLE, f"state={recorder.state}")
    check("A: no error signal", not events["errors"], "; ".join(events["errors"])[:300])
    check("A: finished signal emitted", events["finished"] == [out_path],
          f"{len(events['finished'])} emission(s)")
    check("A: elapsed_changed emitted ~10x/s",
          len(events["elapsed"]) >= 25, f"{len(events['elapsed'])} emissions")
    check("A: active recording time ~3.0 s", 2.5 <= active <= 3.6,
          f"active={active:.2f}s wall={wall:.2f}s frames={recorder.frames_recorded} "
          f"error={recorder.error_message!r}")
    return {"path": out_path, "active": active, "wall": wall,
            "frames": recorder.frames_recorded, "error": recorder.error_message,
            "stop_seconds": stop_seconds}


def test_recording_with_mic(app, mic) -> dict | None:
    from winsnip.core.recorder import Recorder

    out_path = os.path.join(WORK, "b.mp4")
    recorder = Recorder(rect=(0, 0, 640, 480), fps=30, out_path=out_path, mic=mic,
                        capture_cursor=False)
    events = {"errors": []}
    recorder.error.connect(lambda message: events["errors"].append(message))

    wall_start = time.perf_counter()
    recorder.start()
    pump(app, 1.6)
    active = recorder.elapsed
    stop_started = time.perf_counter()
    path = recorder.stop()
    stop_seconds = time.perf_counter() - stop_started
    wall = time.perf_counter() - wall_start
    pump(app, 0.25)

    check("B: output file exists", path == out_path and os.path.isfile(out_path),
          f"path={path!r}")
    check("B: stop() did not hang", stop_seconds < 10.0, f"stop() took {stop_seconds:.2f}s")
    size = os.path.getsize(out_path) if os.path.isfile(out_path) else 0
    check("B: file size > 20 KB", size > 20 * 1024, f"{size} bytes")
    if events["errors"]:
        info("B: error signal: " + "; ".join(events["errors"])[:300])
    return {"path": out_path, "active": active, "wall": wall}


def test_discard(app) -> None:
    from winsnip.core.recorder import Recorder

    out_path = os.path.join(WORK, "discarded.mp4")
    recorder = Recorder(rect=(0, 0, 320, 240), fps=30, out_path=out_path)
    recorder.start()
    pump(app, 0.4)
    recorder.discard()
    check("discard: no output file", not os.path.exists(out_path), f"exists={os.path.exists(out_path)}")
    check("discard: stop() afterwards returns ''", recorder.stop() == "",
          f"{recorder.stop()!r}")


def test_cursor_overlay(app) -> None:
    """The cursor overlay must composite the mouse pointer, or degrade cleanly."""
    import ctypes
    from ctypes import wintypes

    import numpy as np

    from winsnip.core.recorder import _CURSOR_SHOWING, _CURSORINFO, _CursorDrawer
    from winsnip.core.screen import ScreenGrabber, clamp_rect, virtual_rect

    cursor_info = _CURSORINFO()
    cursor_info.cbSize = ctypes.sizeof(_CURSORINFO)
    user32 = ctypes.windll.user32
    if not user32.GetCursorInfo(ctypes.byref(cursor_info)):
        skip("cursor overlay: composites the mouse cursor", "GetCursorInfo failed")
        return
    if not (cursor_info.flags & _CURSOR_SHOWING):
        skip("cursor overlay: composites the mouse cursor", "the cursor is hidden")
        return

    rect = clamp_rect(
        (int(cursor_info.ptScreenPos.x) - 100, int(cursor_info.ptScreenPos.y) - 100, 200, 200),
        virtual_rect(),
    )
    cursor_pos = (int(cursor_info.ptScreenPos.x), int(cursor_info.ptScreenPos.y))
    drawer = _CursorDrawer(rect)
    if not drawer.enabled:
        skip("cursor overlay: composites the mouse cursor", "GDI drawer unavailable")
        return

    # Deterministic check: draw the cursor over an opaque white frame; the
    # change must be non-empty and confined to a small area (a broken composite
    # would blank or smear the whole frame).
    width, height = rect[2], rect[3]
    blank = bytearray(b"\xff" * (width * height * 4))
    drawn = drawer.draw(bytearray(blank))
    before = np.frombuffer(bytes(blank), dtype=np.uint8)
    after = np.frombuffer(bytes(drawn), dtype=np.uint8)
    changed = int(np.count_nonzero(before != after))
    total = before.size
    check(
        "cursor overlay: composites the mouse cursor into the frame",
        changed > 0,
        f"{changed} of {total} bytes changed (cursor at {cursor_pos}, rect={rect})",
    )
    check(
        "cursor overlay: only touches a small region",
        changed < total // 10,
        f"{100.0 * changed / total:.2f}% of the frame changed",
    )
    check(
        "cursor overlay: keeps the frame size",
        len(drawn) == len(blank),
        f"{len(drawn)} bytes",
    )

    # Informational: the same composite over a real grabbed frame.
    grabber = ScreenGrabber()
    try:
        real = grabber.grab(rect)
    finally:
        grabber.close()
    real_after = drawer.draw(bytearray(real))
    info_msg = "changed" if bytes(real_after) != real else "unchanged"
    info(f"cursor overlay: real screen frame {info_msg} after compositing")


def test_edge_cases(app) -> None:
    """Rect clamping, even-dimension forcing and odd rect recording."""
    from winsnip.core.encoder import FfmpegVideoWriter
    from winsnip.core.recorder import Recorder
    from winsnip.core.screen import ScreenGrabber, clamp_rect, virtual_rect

    bounds = virtual_rect()
    check(
        "clamp_rect: negative and zero sizes are clamped",
        clamp_rect((-500, -500, 0, -10), bounds) == (0, 0, 1, 1),
        f"{clamp_rect((-500, -500, 0, -10), bounds)}",
    )
    check(
        "clamp_rect: even=True forces even width/height",
        clamp_rect((0, 0, 641, 481), bounds, even=True) == (0, 0, 640, 480),
        f"{clamp_rect((0, 0, 641, 481), bounds, even=True)}",
    )
    check(
        "clamp_rect: rectangles stay inside the virtual desktop",
        clamp_rect((bounds[0] + bounds[2] - 5, bounds[1] + bounds[3] - 5, 400, 400), bounds)
        == (bounds[0] + bounds[2] - 400, bounds[1] + bounds[3] - 400, 400, 400),
        f"{clamp_rect((bounds[0] + bounds[2] - 5, bounds[1] + bounds[3] - 5, 400, 400), bounds)}",
    )

    grabber = ScreenGrabber()
    try:
        raw = grabber.grab((0, 0, 33, 17))
        png = grabber.grab_png((0, 0, 33, 17))
    finally:
        grabber.close()
    check("grab: returns exactly w*h*4 BGRA bytes", len(raw) == 33 * 17 * 4, f"{len(raw)} bytes")
    check("grab_png: works for odd sizes", png[:8] == b"\x89PNG\r\n\x1a\n", f"{len(png)} bytes")

    path = os.path.join(WORK, "wrongsize.mp4")
    writer = FfmpegVideoWriter(path, 641, 481, fps=30)
    check(
        "FfmpegVideoWriter: forces even dimensions",
        (writer.width, writer.height) == (640, 480),
        f"{writer.width}x{writer.height}",
    )
    frame = bytes(640 * 480 * 4)
    for _ in range(5):
        writer.write(frame)
    writer.write(bytes(10))
    check(
        "FfmpegVideoWriter: drops wrong-size frames and records the error",
        writer.frames_written == 5 and writer.error is not None,
        f"frames={writer.frames_written} error={writer.error}",
    )
    writer.close()
    check("FfmpegVideoWriter: close() is idempotent", (writer.close(), writer.close()) == (None, None))
    if os.path.exists(path):
        os.remove(path)

    check("Recorder: stop() before start() returns ''", Recorder(rect=(0, 0, 64, 64)).stop() == "")

    odd_path = os.path.join(WORK, "odd.mp4")
    recorder = Recorder(rect=(10, 10, 321, 241), fps=30, out_path=odd_path)
    recorder.start()
    pump(app, 0.8)
    active = recorder.elapsed
    result = recorder.stop()
    check("Recorder: odd rect is reduced to 320x240", recorder.rect == (10, 10, 320, 240),
          f"{recorder.rect}")
    check("Recorder: odd rect recording produced a file", result == odd_path and os.path.isfile(odd_path),
          f"{result!r}")
    if os.path.isfile(odd_path):
        facts = probe(odd_path)
        check("Recorder: odd rect video is 320x240", facts["size"] == "320x240", f"{facts['size']}")
        check(
            "Recorder: odd rect duration matches active time",
            facts["duration"] is not None and abs(facts["duration"] - active) <= 0.35 * active,
            f"duration={facts['duration']}s active={active:.2f}s",
        )


def main() -> int:
    print("=" * 78)
    print("WinSnipRec core self-test")
    print("=" * 78)
    info(f"python     : {sys.executable}")
    info(f"workspace  : {WORK}")

    _prepare_workdir()

    try:
        from PySide6.QtCore import QCoreApplication
    except Exception as exc:  # pragma: no cover
        check("import PySide6", False, repr(exc))
        print("SELFTEST: FAIL")
        return 1

    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    try:
        from winsnip.core import audio as core_audio
        from winsnip.core import encoder as core_encoder
        from winsnip.core import screen as core_screen
    except Exception as exc:  # pragma: no cover
        check("import winsnip.core", False, repr(exc))
        print("SELFTEST: FAIL")
        return 1

    check("import winsnip.core", True)
    check("ffmpeg found", core_encoder.ffmpeg_available(), core_encoder.ffmpeg_path())

    # ---- 2. framebuffer facts -------------------------------------------
    print("\n--- monitors ---", flush=True)
    monitors = core_screen.list_monitors()
    rect = core_screen.virtual_rect()
    for monitor in monitors:
        print(
            f"    [{monitor.index}] {monitor.name}: "
            f"left={monitor.left} top={monitor.top} "
            f"{monitor.width}x{monitor.height}",
            flush=True,
        )
    print(f"    virtual_rect() = {rect}", flush=True)
    check("monitors: at least one enumerated", len(monitors) >= 1, f"{len(monitors)} monitor(s)")
    if monitors:
        check(
            "monitors: index 0 is the primary display",
            "(Primary)" in monitors[0].name or (monitors[0].left, monitors[0].top) == (0, 0),
            f"{monitors[0].name} @ ({monitors[0].left},{monitors[0].top})",
        )
        check(
            "monitors: virtual_rect covers every monitor",
            all(
                m.left >= rect[0] and m.top >= rect[1]
                and m.left + m.width <= rect[0] + rect[2]
                and m.top + m.height <= rect[1] + rect[3]
                for m in monitors
            ),
            f"virtual={rect}",
        )

    # ---- 3. screenshot ---------------------------------------------------
    print("\n--- checks ---", flush=True)
    test_screenshot()

    # ---- 4. recording A --------------------------------------------------
    result_a = test_recording_video_only(app)

    # ---- 5. recording B (mic) -------------------------------------------
    print("\n--- audio devices ---", flush=True)
    microphones = core_audio.list_microphones()
    for device in microphones:
        print(f"    {device.name}", flush=True)
    if not microphones:
        print("    (none enumerated)", flush=True)
    result_b = None
    if microphones:
        default = core_audio.default_microphone()
        info(f"default microphone: {default.name if default else None}")
        result_b = test_recording_with_mic(app, default)
    else:
        skip("B: microphone recording", "no DirectShow audio capture device found")

    # ---- 4b. discard -----------------------------------------------------
    test_discard(app)

    # ---- 4c. cursor overlay ----------------------------------------------
    test_cursor_overlay(app)

    # ---- 4d. edge cases ---------------------------------------------------
    print("\n--- edge cases ---", flush=True)
    test_edge_cases(app)

    # ---- 6. verify with ffmpeg -------------------------------------------
    if result_a:
        facts_a = probe(result_a["path"])
        report_facts("a.mp4 (video only, paused 1.0 s after 1.5 s)", facts_a)
        check("A: ffmpeg reads the file without error", facts_a["returncode"] == 0,
              f"returncode={facts_a['returncode']}")
        check("A: stream is H.264", facts_a["video"] == "h264", f"codec={facts_a['video']}")
        check("A: frame size is 640x480", facts_a["size"] == "640x480", f"size={facts_a['size']}")
        check("A: frame rate is 30 fps", facts_a["fps"] is not None and abs(facts_a["fps"] - 30) < 0.5,
              f"fps={facts_a['fps']}")
        duration_a = facts_a["duration"]
        ok_duration = duration_a is not None and abs(duration_a - result_a["active"]) <= 0.35 * result_a["active"]
        check(
            "A: duration within 35% of active time",
            ok_duration,
            f"duration={duration_a}s active={result_a['active']:.2f}s "
            f"delta={((duration_a or 0) - result_a['active']):+.2f}s",
        )
        if duration_a is not None:
            check(
                "A: the 1.0 s pause is NOT part of the duration",
                abs(duration_a - result_a["active"]) < abs(duration_a - result_a["wall"]),
                f"|duration-active|={abs(duration_a - result_a['active']):.2f}s "
                f"< |duration-wall|={abs(duration_a - result_a['wall']):.2f}s",
            )

    if result_b:
        facts_b = probe(result_b["path"])
        report_facts("b.mp4 (with microphone)", facts_b)
        check("B: ffmpeg reads the file without error", facts_b["returncode"] == 0,
              f"returncode={facts_b['returncode']}")
        check("B: stream is H.264", facts_b["video"] == "h264", f"codec={facts_b['video']}")
        check("B: an AAC audio stream is present", facts_b["audio"] == "aac",
              f"audio={facts_b['audio']}")
        duration_b = facts_b["duration"]
        check(
            "B: duration within 35% of active time",
            duration_b is not None and abs(duration_b - result_b["active"]) <= 0.35 * result_b["active"],
            f"duration={duration_b}s active={result_b['active']:.2f}s",
        )

    # ---- 7. summary ------------------------------------------------------
    print("\n" + "=" * 78)
    passed = sum(1 for _, ok, _ in _RESULTS if ok)
    failed = [(name, detail) for name, ok, detail in _RESULTS if not ok]
    skipped = [(name, detail) for name, ok, detail in _RESULTS if ok and detail.startswith("SKIPPED")]
    for name, ok, detail in _RESULTS:
        marker = "PASS" if ok else "FAIL"
        if ok and detail.startswith("SKIPPED"):
            marker = "SKIP"
        print(f"  {marker}  {name}" + (f"  ({detail})" if detail else ""))
    print("-" * 78)
    print(f"  {passed}/{len(_RESULTS)} checks passed, {len(failed)} failed, {len(skipped)} skipped")
    print("=" * 78)
    print("SELFTEST: PASS" if not failed else "SELFTEST: FAIL")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
