"""Segmented screen recorder.

The recorder captures the screen on a background thread at a steady frame rate
and encodes straight into H.264/MP4 through ffmpeg pipes.  Pause/resume is
implemented with segments: every running stretch produces ``segNNN.mp4`` (and
``segNNN.wav`` when a microphone is configured); stopping concatenates the
segments and muxes the final MP4 without re-encoding the video.

None of :meth:`Recorder.start`, :meth:`pause`, :meth:`resume`, :meth:`stop` or
:meth:`discard` raises: failures are reported through the ``error`` signal.
"""

from __future__ import annotations

import ctypes
import enum
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from collections import deque
from ctypes import wintypes
from typing import Optional

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from .audio import AudioDevice
from .encoder import (
    CREATE_NO_WINDOW,
    FfmpegVideoWriter,
    concat_files,
    ffmpeg_available,
    ffmpeg_path,
    run_ffmpeg_checked,
)
from .screen import ScreenGrabber, clamp_rect
from ..i18n import t as _t

__all__ = ["RecorderState", "Recorder"]

_ELAPSED_INTERVAL = 0.1  # seconds between elapsed_changed emissions (~10 Hz)
# Frame slots the writer may run behind before slots are dropped.  A generous
# value lets a transient stall (scheduling hiccup, antivirus scan) be caught up
# frame by frame -- which keeps the output duration equal to the active
# recording time -- while a permanently too-slow encoder still degrades to a
# lower effective frame rate instead of building an unbounded backlog.
_MAX_DEADLINE_DEBT = 2.0
_MIC_RATE = 48000
_MIC_CHANNELS = 1
_MIC_SAMPLE_BYTES = 2


class RecorderState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PAUSED = "paused"
    STOPPING = "stopping"


# ---------------------------------------------------------------------------
# Cursor overlay
# ---------------------------------------------------------------------------

_CURSOR_SHOWING = 0x00000001
_DI_NORMAL = 0x0003
_BI_RGB = 0


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", wintypes.POINT),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class _CursorDrawer:
    """Composites the mouse cursor into grabbed BGRA frames via GDI.

    A top-down 32bpp DIB section is kept alive for the rectangle being
    recorded; each frame is copied in, ``DrawIconEx`` performs the alpha/mask
    blending, and the result is copied back out.  If anything about this fails
    the drawer disables itself and recording continues without a cursor.
    """

    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self._ok = False
        self._rect = rect
        self._dc = None
        self._bitmap = None
        self._old = None
        self._address = 0
        self._size = 0
        self._user32 = None
        self._gdi32 = None
        self._draw_icon_ex = None
        self._get_cursor_info = None
        self._get_icon_info = None
        try:
            self._setup()
        except Exception:
            self._ok = False
            self._release()

    # -- setup/teardown ----------------------------------------------------
    def _setup(self) -> None:
        width, height = int(self._rect[2]), int(self._rect[3])
        if width <= 0 or height <= 0 or width * height > 8192 * 8192:
            return
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # Resolve the entry points up front so a missing symbol disables the
        # overlay instead of silently doing nothing at draw time.
        draw_icon_ex = user32.DrawIconEx
        get_cursor_info = user32.GetCursorInfo
        get_icon_info = user32.GetIconInfo
        bmi = _BITMAPINFO()
        header = bmi.bmiHeader
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # negative => top-down rows
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = _BI_RGB

        screen_dc = user32.GetDC(None)
        dc = gdi32.CreateCompatibleDC(ctypes.c_void_p(screen_dc))
        if screen_dc:
            user32.ReleaseDC(None, ctypes.c_void_p(screen_dc))
        if not dc:
            return

        address = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            ctypes.c_void_p(dc),
            ctypes.byref(bmi),
            0,
            ctypes.byref(address),
            None,
            0,
        )
        if not bitmap or not address.value:
            gdi32.DeleteDC(ctypes.c_void_p(dc))
            return

        self._user32 = user32
        self._gdi32 = gdi32
        self._draw_icon_ex = draw_icon_ex
        self._get_cursor_info = get_cursor_info
        self._get_icon_info = get_icon_info
        self._dc = dc
        self._bitmap = bitmap
        self._address = int(address.value)
        self._old = gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(bitmap))
        self._size = width * height * 4
        self._ok = True

    def _release(self) -> None:
        try:
            if self._dc and self._old:
                self._gdi32.SelectObject(
                    ctypes.c_void_p(self._dc), ctypes.c_void_p(self._old)
                )
        except Exception:
            pass
        try:
            if self._bitmap:
                self._gdi32.DeleteObject(ctypes.c_void_p(self._bitmap))
        except Exception:
            pass
        try:
            if self._dc:
                self._gdi32.DeleteDC(ctypes.c_void_p(self._dc))
        except Exception:
            pass
        self._bitmap = None
        self._dc = None
        self._old = None
        self._address = 0

    # -- drawing -----------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return self._ok

    def draw(self, frame: bytearray) -> bytearray:
        """Return ``frame`` with the cursor composited in (best effort)."""
        if not self._ok or len(frame) != self._size:
            return frame
        icon_info = None
        try:
            user32, gdi32 = self._user32, self._gdi32
            info = _CURSORINFO()
            info.cbSize = ctypes.sizeof(_CURSORINFO)
            if not self._get_cursor_info(ctypes.byref(info)):
                return frame
            if not (info.flags & _CURSOR_SHOWING) or not info.hCursor:
                return frame

            icon_info = _ICONINFO()
            hotspot_x = hotspot_y = 0
            if self._get_icon_info(ctypes.c_void_p(info.hCursor), ctypes.byref(icon_info)):
                hotspot_x = int(icon_info.xHotspot)
                hotspot_y = int(icon_info.yHotspot)

            size = self._size
            left, top, width, height = self._rect
            x = int(info.ptScreenPos.x) - hotspot_x - left
            y = int(info.ptScreenPos.y) - hotspot_y - top
            if x <= -64 or y <= -64 or x >= width + 64 or y >= height + 64:
                return frame

            # Opaque alpha keeps GDI's alpha blending predictable.
            frame[3::4] = b"\xff" * (size // 4)
            ctypes.memmove(
                ctypes.c_void_p(self._address),
                (ctypes.c_char * size).from_buffer(frame),
                size,
            )
            drawn = self._draw_icon_ex(
                ctypes.c_void_p(self._dc),
                int(x),
                int(y),
                ctypes.c_void_p(info.hCursor),
                0,
                0,
                0,
                None,
                _DI_NORMAL,
            )
            if not drawn:
                return frame
            frame[:] = ctypes.string_at(ctypes.c_void_p(self._address), size)
            return frame
        except Exception:
            return frame
        finally:
            if icon_info is not None:
                for handle in (icon_info.hbmColor, icon_info.hbmMask):
                    if handle:
                        try:
                            self._gdi32.DeleteObject(ctypes.c_void_p(handle))
                        except Exception:
                            pass


def _move_file(src: str, dst: str) -> None:
    """Move ``src`` onto ``dst``, replacing an existing destination."""
    if os.path.abspath(src) == os.path.abspath(dst):
        return
    try:
        os.replace(src, dst)
        return
    except OSError:
        pass
    try:
        if os.path.exists(dst):
            os.remove(dst)
    except OSError:
        pass
    shutil.move(src, dst)


def _patch_wav(path: str, pad_to_bytes: int = 0) -> None:
    """Repair RIFF/data sizes after an abruptly terminated capture.

    ffmpeg only rewrites the sizes when it shuts down cleanly, so a killed
    capture leaves stale values behind.  Optionally appends silence so the
    track matches the video segment duration.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size < 12:
        return
    try:
        with open(path, "r+b") as handle:
            head = handle.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return
            pos = 12
            data_pos = None
            while True:
                handle.seek(pos)
                chunk = handle.read(8)
                if len(chunk) < 8:
                    break
                chunk_id = chunk[:4]
                chunk_size = struct.unpack("<I", chunk[4:8])[0]
                if chunk_id == b"data":
                    data_pos = pos + 8
                    break
                step = 8 + chunk_size + (chunk_size & 1)
                if step <= 8:
                    break
                pos += step
            if data_pos is None:
                return
            actual = max(0, size - data_pos)
            if pad_to_bytes and actual < pad_to_bytes:
                handle.seek(0, os.SEEK_END)
                handle.write(b"\x00" * (pad_to_bytes - actual))
                actual = pad_to_bytes
            handle.seek(4)
            handle.write(struct.pack("<I", data_pos - 8 + actual))
            handle.seek(data_pos - 4)
            handle.write(struct.pack("<I", actual))
    except OSError:
        return


def _write_silence_wav(path: str, data_bytes: int, rate: int = _MIC_RATE,
                       channels: int = _MIC_CHANNELS) -> bool:
    """Write a silent PCM WAV of exactly ``data_bytes`` payload bytes."""
    if data_bytes <= 0:
        return False
    try:
        header = (
            b"RIFF"
            + struct.pack("<I", 36 + data_bytes)
            + b"WAVE"
            + b"fmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                          rate * channels * _MIC_SAMPLE_BYTES,
                          channels * _MIC_SAMPLE_BYTES, 16)
            + b"data"
            + struct.pack("<I", data_bytes)
        )
        chunk = b"\x00" * min(65536, data_bytes)
        with open(path, "wb") as handle:
            handle.write(header)
            remaining = data_bytes
            while remaining > 0:
                piece = chunk if remaining >= len(chunk) else chunk[:remaining]
                handle.write(piece)
                remaining -= len(piece)
        return True
    except OSError:
        return False


def _wav_data_size(path: str) -> int:
    """Number of PCM payload bytes in ``path`` (0 when unknown)."""
    try:
        size = os.path.getsize(path)
        if size < 12:
            return 0
        with open(path, "rb") as handle:
            head = handle.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return 0
            pos = 12
            while True:
                handle.seek(pos)
                chunk = handle.read(8)
                if len(chunk) < 8:
                    break
                chunk_id = chunk[:4]
                chunk_size = struct.unpack("<I", chunk[4:8])[0]
                if chunk_id == b"data":
                    if chunk_size == 0 or chunk_size >= size:
                        return max(0, size - (pos + 8))
                    return chunk_size
                step = 8 + chunk_size + (chunk_size & 1)
                if step <= 8:
                    break
                pos += step
    except OSError:
        return 0
    return 0


# ---------------------------------------------------------------------------
# Recorder
# ---------------------------------------------------------------------------


class Recorder(QObject):
    """Screen recorder writing an H.264 MP4, pause/resume aware."""

    state_changed = Signal(object)  # RecorderState
    elapsed_changed = Signal(float)  # active (unpaused) seconds
    error = Signal(str)
    finished = Signal(str)  # absolute path of the produced MP4

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        fps: int = 30,
        crf: int = 20,
        mic: AudioDevice | None = None,
        out_path: str | None = None,
        tmp_dir: str | None = None,
        capture_cursor: bool = True,
        ffmpeg: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._fps = max(1, int(fps))
        self._crf = int(crf)
        self._mic = mic
        self._ffmpeg = ffmpeg or ""
        self._capture_cursor = bool(capture_cursor)

        stamp = time.strftime("%Y%m%d_%H%M%S")
        if out_path:
            self._out_path = os.path.abspath(os.fspath(out_path))
        else:
            self._out_path = os.path.abspath(
                os.path.join(tempfile.gettempdir(), f"WinSnipRec_{stamp}.mp4")
            )
        if tmp_dir:
            self._tmp_dir = os.path.abspath(os.fspath(tmp_dir))
        else:
            self._tmp_dir = os.path.join(
                tempfile.gettempdir(), f"winsnip_rec_{stamp}_{os.getpid()}"
            )

        self._rect = clamp_rect(rect, even=True)
        self._state = RecorderState.IDLE
        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._pause_evt = threading.Event()
        self._resume_evt = threading.Event()
        self._capture_stop = threading.Event()
        # Requests a segment boundary so the microphone can be swapped without
        # desynchronising the concatenated audio and video tracks.
        self._split_evt = threading.Event()
        self._pending_mic: Optional[AudioDevice] = None
        self._pending_mic_set = False
        self._thread: Optional[threading.Thread] = None
        self._measured_segment_seconds: Optional[float] = None
        self._pause_at: Optional[float] = None
        self._frame_lock = threading.Lock()
        self._frame: Optional[bytes] = None
        # Last frame ever captured. Unlike _frame it survives pause/resume and
        # mic-split boundaries: without it a segment that starts before the
        # capture thread has produced its first frame has nothing to write,
        # and a zero-frame segment used to be dropped -- silently shortening
        # the movie (a 3 s recording could come out as 1.2 s).
        self._last_frame: Optional[bytes] = None
        self._frame_seq = 0

        self._writer: Optional[FfmpegVideoWriter] = None
        self._mic_proc: Optional[subprocess.Popen] = None
        self._mic_log: deque[str] = deque(maxlen=20)
        self._mic_disabled = mic is None
        self._segment: Optional[dict] = None
        self._segment_index = 0
        self._segments: list[dict] = []

        self._seg_start: Optional[float] = None
        self._seg_base = 0.0
        self._elapsed_total = 0.0
        self._last_emit = 0.0
        self._error: Optional[str] = None
        self._error_reported = False
        self._discarded = False
        self._started = False
        self._elapsed_timer: Optional[QTimer] = None

    # -- properties --------------------------------------------------------
    @property
    def state(self) -> RecorderState:
        with self._lock:
            return self._state

    @property
    def elapsed(self) -> float:
        with self._lock:
            total = self._elapsed_total
            started = self._seg_start
        if started is not None:
            total += max(0.0, time.perf_counter() - started)
        return total

    @property
    def output_path(self) -> str:
        return self._out_path

    @property
    def error_message(self) -> Optional[str]:
        return self._error

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return self._rect

    @property
    def frames_recorded(self) -> int:
        with self._lock:
            return sum(int(s.get("frames", 0)) for s in self._segments)

    # -- helpers -----------------------------------------------------------
    def _set_state(self, state: RecorderState) -> None:
        with self._lock:
            if self._state is state:
                return
            self._state = state
        try:
            self.state_changed.emit(state)
        except Exception:
            pass

    def _report_error(self, message: str, once: bool = False) -> None:
        message = str(message)
        with self._lock:
            if once and self._error_reported:
                return
            self._error = message
            self._error_reported = True
        try:
            self.error.emit(message)
        except Exception:
            pass

    def _emit_elapsed(self, force: bool = False) -> None:
        value = self.elapsed
        if not force and value - self._last_emit < _ELAPSED_INTERVAL:
            return
        self._last_emit = value
        try:
            self.elapsed_changed.emit(value)
        except Exception:
            pass

    # -- elapsed timer (owner thread) --------------------------------------
    def _elapsed_timer_start(self) -> None:
        """Drive ``elapsed_changed`` at ~10 Hz from the owning thread.

        Falls back to emissions from the writer thread when there is no Qt
        event loop to run the timer.
        """
        try:
            if QCoreApplication.instance() is None:
                return
            if self._elapsed_timer is None:
                timer = QTimer(self)
                timer.setInterval(max(10, int(_ELAPSED_INTERVAL * 1000)))
                timer.timeout.connect(self._on_elapsed_tick)
                self._elapsed_timer = timer
            self._elapsed_timer.start()
        except Exception:
            self._elapsed_timer = None

    def _elapsed_timer_stop(self) -> None:
        try:
            if self._elapsed_timer is not None:
                self._elapsed_timer.stop()
        except Exception:
            pass

    def _on_elapsed_tick(self) -> None:
        try:
            value = self.elapsed
            self._last_emit = value
            self.elapsed_changed.emit(value)
        except Exception:
            pass

    def _ffmpeg_exe(self) -> str:
        return self._ffmpeg or ffmpeg_path()

    def _accumulate_elapsed(self) -> None:
        with self._lock:
            measured, self._measured_segment_seconds = self._measured_segment_seconds, None
            if measured is not None:
                # Frozen when the segment started closing: the time spent
                # writing catch-up frames is not recording time.
                self._elapsed_total += measured
                self._seg_start = None
            elif self._seg_start is not None:
                self._elapsed_total += max(0.0, time.perf_counter() - self._seg_start)
                self._seg_start = None

    def _mark_segment_start(self) -> None:
        with self._lock:
            self._seg_base = self._elapsed_total
            self._seg_start = time.perf_counter()

    def _current_segment_seconds(self) -> float:
        """Active seconds of the current segment (exact once paused)."""
        with self._lock:
            if self._seg_start is not None:
                return max(0.0, time.perf_counter() - self._seg_start)
            return max(0.0, self._elapsed_total - self._seg_base)

    # -- segment handling (worker thread only) -----------------------------
    def _open_segment(self) -> None:
        index = self._segment_index
        self._segment_index += 1
        video_path = os.path.join(self._tmp_dir, f"seg{index:03d}.mp4")
        writer = FfmpegVideoWriter(
            video_path,
            self._rect[2],
            self._rect[3],
            fps=self._fps,
            crf=self._crf,
            ffmpeg=self._ffmpeg_exe() or None,
        )
        if writer.error is not None:
            raise RuntimeError(writer.error)
        self._writer = writer
        segment: dict = {"video": video_path, "wav": None, "frames": 0, "seconds": 0.0}

        if self._mic is not None and not self._mic_disabled:
            wav_path = os.path.join(self._tmp_dir, f"seg{index:03d}.wav")
            proc = self._start_mic(wav_path)
            if proc is not None:
                self._mic_proc = proc
                segment["wav"] = wav_path
            else:
                self._mic_disabled = True
        self._segment = segment

    def _start_mic(self, wav_path: str) -> Optional[subprocess.Popen]:
        exe = self._ffmpeg_exe()
        if not exe or self._mic is None:
            return None
        args = [
            exe,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "dshow",
            "-audio_buffer_size",
            "50",
            "-i",
            f"audio={self._mic.id}",
            "-ac",
            str(_MIC_CHANNELS),
            "-ar",
            str(_MIC_RATE),
            "-c:a",
            "pcm_s16le",
            "-y",
            wav_path,
        ]
        kwargs: dict = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
        }
        if CREATE_NO_WINDOW:
            kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            proc = subprocess.Popen(args, **kwargs)
        except Exception as exc:
            self._report_error(f"cannot start microphone capture: {exc!r}", once=True)
            return None
        thread = threading.Thread(
            target=self._drain_mic, args=(proc,), name="winsnip-mic-log", daemon=True
        )
        thread.start()
        return proc

    def _drain_mic(self, proc: subprocess.Popen) -> None:
        try:
            if proc.stderr is None:
                return
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._mic_log.append(line)
        except Exception:
            pass

    def _stop_mic(self, proc: Optional[subprocess.Popen]) -> None:
        if proc is None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.write(b"q")
                proc.stdin.flush()
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=4.0)
            return
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
            return
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass

    def _close_segment(self) -> None:
        with self._lock:
            writer, proc, segment = self._writer, self._mic_proc, self._segment
            self._writer = None
            self._mic_proc = None
            self._segment = None
        if proc is not None:
            self._stop_mic(proc)
        if writer is None:
            return

        writer.close(timeout=15.0)
        frames = writer.frames_written
        if writer.error is not None:
            self._report_error(f"encoder: {writer.error}")
        if segment is None:
            return
        segment["frames"] = frames
        segment["seconds"] = frames / float(self._fps)

        wav = segment.get("wav")
        if wav:
            # Align the audio segment with the video segment length so that
            # ``-shortest`` cannot truncate the movie to the dshow warm-up.
            pad = int(segment["seconds"] * _MIC_RATE * _MIC_CHANNELS * _MIC_SAMPLE_BYTES)
            _patch_wav(wav, pad_to_bytes=pad)
            if _wav_data_size(wav) < _MIC_RATE * _MIC_CHANNELS * _MIC_SAMPLE_BYTES // 20:
                log = " | ".join(self._mic_log)
                self._report_error(
                    "microphone produced no audio" + (f": {log}" if log else ""),
                    once=True,
                )
                segment["wav"] = None
                self._mic_disabled = True

        if frames > 0 and not self._discarded:
            with self._lock:
                self._segments.append(segment)

    # -- capture thread ----------------------------------------------------
    def _capture_loop(self) -> None:
        """Grab frames as fast as the display allows into a single-slot mailbox.

        Capturing is the slow part on software-rendered desktops (a BitBlt of
        640x480 can take ~33 ms), so it runs in its own thread and the writer
        loop never blocks on it: the mailbox always holds the newest frame and
        older ones are dropped instead of queueing up.
        """
        grabber: Optional[ScreenGrabber] = None
        try:
            grabber = ScreenGrabber()
            drawer = _CursorDrawer(self._rect) if self._capture_cursor else None
            interval = 1.0 / self._fps
            next_at = time.perf_counter()
            while not self._capture_stop.is_set():
                if self._pause_evt.is_set():
                    self._capture_stop.wait(0.02)
                    next_at = time.perf_counter()
                    continue

                frame = grabber.grab(self._rect)
                if drawer is not None and drawer.enabled:
                    try:
                        frame = bytes(drawer.draw(bytearray(frame)))
                    except Exception:
                        pass
                with self._frame_lock:
                    self._frame = frame
                    self._last_frame = frame
                    self._frame_seq += 1

                next_at += interval
                now = time.perf_counter()
                if next_at <= now:
                    next_at = now + interval  # fell behind; resync, never queue
                else:
                    self._capture_stop.wait(next_at - now)
        except Exception as exc:
            self._report_error(f"capture thread failed: {exc!r}")
        finally:
            if grabber is not None:
                grabber.close()

    def _latest_frame(self) -> Optional[bytes]:
        with self._frame_lock:
            return self._frame if self._frame is not None else self._last_frame

    def _clear_frame(self) -> None:
        # Only the *current* frame is dropped; the last frame stays available so
        # a segment opened right after a pause always has something to write.
        with self._frame_lock:
            self._frame = None

    def _start_capture(self) -> threading.Thread:
        self._capture_stop.clear()
        self._clear_frame()
        thread = threading.Thread(
            target=self._capture_loop, name="winsnip-capture", daemon=True
        )
        thread.start()
        return thread

    def _rebase_settled_segment(self) -> None:
        """Re-open a segment whose clock ``pause()`` already froze.

        ``pause()`` settles the elapsed clock the instant the user clicks, so
        the UI freezes immediately.  If the writer was blocked in a frame write
        it may only notice the flag a few hundred milliseconds later -- and the
        frames it wrote in the meantime are real.  Re-basing the segment start
        to the pause instant keeps the reported length in step with the file.
        """
        with self._lock:
            if self._seg_start is None and self._pause_at is not None:
                self._seg_start = self._pause_at
            self._pause_at = None

    def _pad_deadline_debt(self, writer, frames_in_segment: int, interval: float) -> int:
        """Cover frame slots the encoder still owes when a segment ends.

        If the machine stalled (scheduling hiccup, virus scanner, cold ffmpeg
        start) the deadline scheduler is behind by up to ``_MAX_DEADLINE_DEBT``
        seconds.  Repeating the newest frame for those slots keeps the produced
        video exactly as long as the active recording period instead of
        silently truncating it.
        """
        if writer is None or writer.closed or writer.error is not None:
            return frames_in_segment
        frame = self._latest_frame()
        if frame is None:
            return frames_in_segment
        # Freeze the measured length *before* padding: writing the catch-up
        # frames takes wall-clock time on slow machines and must not be
        # mistaken for time that was recorded.
        seconds = self._current_segment_seconds()
        with self._lock:
            # pause() settles the segment itself (and clears _seg_start) before
            # the worker gets here.  Only freeze when this thread is the one
            # closing the segment, otherwise the time would be counted twice.
            if self._seg_start is not None:
                self._measured_segment_seconds = seconds
        owed = int(seconds / interval) - frames_in_segment
        owed = min(owed, int(_MAX_DEADLINE_DEBT / interval))
        for _ in range(max(0, owed)):
            writer.write(frame)
            frames_in_segment += 1
            if writer.error is not None:
                break
        return frames_in_segment

    # -- writer thread -----------------------------------------------------
    def _run(self) -> None:
        capture: Optional[threading.Thread] = None
        try:
            interval = 1.0 / self._fps
            capture = self._start_capture()

            self._open_segment()
            self._mark_segment_start()
            writer = self._writer

            t0 = time.perf_counter()
            frames_in_segment = 0
            self._emit_elapsed(force=True)

            while True:
                if self._stop_evt.is_set():
                    self._rebase_settled_segment()
                    frames_in_segment = self._pad_deadline_debt(
                        writer, frames_in_segment, interval
                    )
                    break

                if self._pause_evt.is_set():
                    self._rebase_settled_segment()
                    frames_in_segment = self._pad_deadline_debt(
                        writer, frames_in_segment, interval
                    )
                    self._flush_segment()
                    self._emit_elapsed(force=True)
                    self._clear_frame()
                    while not self._stop_evt.is_set() and self._pause_evt.is_set():
                        self._resume_evt.wait(0.05)
                    if self._stop_evt.is_set():
                        break
                    self._open_segment()
                    self._mark_segment_start()
                    writer = self._writer
                    t0 = time.perf_counter()
                    frames_in_segment = 0
                    self._clear_frame()
                    continue

                if self._split_evt.is_set():
                    # The microphone changed: close the current video+audio
                    # segment pair and open the next one so both tracks split at
                    # the same instant (keeps the concat in sync).
                    self._split_evt.clear()
                    self._flush_segment()
                    with self._lock:
                        if self._pending_mic_set:
                            self._mic = self._pending_mic
                            self._pending_mic = None
                            self._pending_mic_set = False
                        self._mic_disabled = self._mic is None
                    self._open_segment()
                    self._mark_segment_start()
                    writer = self._writer
                    t0 = time.perf_counter()
                    frames_in_segment = 0
                    self._clear_frame()
                    continue

                if writer is None or writer.closed:
                    break

                target = t0 + frames_in_segment * interval
                now = time.perf_counter()
                if now < target:
                    self._stop_evt.wait(min(target - now, 0.05))
                    continue

                frame = self._latest_frame()
                if frame is None:
                    # Nothing captured yet (first frame or right after resume).
                    self._stop_evt.wait(0.005)
                    continue

                writer.write(frame)
                frames_in_segment += 1

                now = time.perf_counter()
                behind = now - (t0 + frames_in_segment * interval)
                if behind > _MAX_DEADLINE_DEBT:
                    # The encoder cannot keep the requested rate at all (as
                    # opposed to a short warm-up stall): skip the excess slots
                    # so the deadline debt stays bounded instead of growing
                    # into a backlog.
                    frames_in_segment += int(
                        (behind - _MAX_DEADLINE_DEBT) / interval
                    )

                if writer.error is not None:
                    break
                if self._elapsed_timer is None:
                    self._emit_elapsed()

        except Exception as exc:
            self._report_error(f"recorder thread failed: {exc!r}")
        finally:
            self._capture_stop.set()
            if capture is not None:
                try:
                    capture.join(timeout=3.0)
                except Exception:
                    pass
            try:
                self._flush_segment()
            except Exception:
                pass
            self._emit_elapsed(force=True)

    def _flush_segment(self) -> None:
        """Close the current segment and accumulate its active duration."""
        self._accumulate_elapsed()
        self._close_segment()

    # -- public API --------------------------------------------------------
    def start(self) -> None:
        """Begin recording.  Never raises."""
        try:
            with self._lock:
                if self._state is not RecorderState.IDLE or self._started:
                    return
                self._started = True
                self._discarded = False
                self._error = None
                self._error_reported = False
                self._segments = []
                self._segment_index = 0
                self._elapsed_total = 0.0
                self._seg_base = 0.0
                self._seg_start = None
                self._measured_segment_seconds = None
                self._pause_at = None
                with self._frame_lock:
                    self._frame = None
                    self._last_frame = None
                self._last_emit = 0.0
                self._mic_disabled = self._mic is None

            if not ffmpeg_available() and not self._ffmpeg:
                raise RuntimeError(
                    "ffmpeg was not found (install imageio-ffmpeg or put ffmpeg on PATH)"
                )
            os.makedirs(self._tmp_dir, exist_ok=True)

            self._stop_evt.clear()
            self._pause_evt.clear()
            self._resume_evt.clear()
            self._thread = threading.Thread(
                target=self._run, name="winsnip-recorder", daemon=True
            )
            self._thread.start()
            self._set_state(RecorderState.RECORDING)
            self._emit_elapsed(force=True)
            self._elapsed_timer_start()
        except Exception as exc:
            with self._lock:
                self._started = False
            self._report_error(f"cannot start recording: {exc}")
            self._set_state(RecorderState.IDLE)

    def pause(self) -> None:
        """Suspend capture; the current segment is finalized.  Never raises."""
        try:
            if self.state is not RecorderState.RECORDING:
                return
            self._pause_evt.set()
            self._resume_evt.clear()
            # Freeze the active clock at the moment the user asked to pause;
            # the worker pads the segment to exactly this instant.  Remember the
            # instant too: if the writer is busy it may only see the flag much
            # later, and the frames it wrote in between still happened.
            self._pause_at = time.perf_counter()
            self._accumulate_elapsed()
            self._set_state(RecorderState.PAUSED)
            self._elapsed_timer_stop()
            self._emit_elapsed(force=True)
        except Exception as exc:
            self._report_error(f"pause failed: {exc!r}")

    def resume(self) -> None:
        """Continue recording into a new segment.  Never raises."""
        try:
            if self.state is not RecorderState.PAUSED:
                return
            self._pause_evt.clear()
            self._resume_evt.set()
            with self._lock:
                if self._seg_start is None and self._state is RecorderState.PAUSED:
                    # The worker has not observed the pause yet, so it will
                    # keep recording into the current segment: restart the
                    # clock here to avoid losing that time.
                    self._seg_base = self._elapsed_total
                    self._seg_start = time.perf_counter()
            self._set_state(RecorderState.RECORDING)
            self._elapsed_timer_start()
        except Exception as exc:
            self._report_error(f"resume failed: {exc!r}")

    def set_mic(self, device: Optional[AudioDevice]) -> None:
        """Swap the microphone while recording.  Never raises.

        The change is applied at a segment boundary: the current video+audio
        segment pair is finalized and the next pair is opened with the new
        device, so both tracks split at the same instant and the concatenated
        result stays in sync (and keeps the same duration).  Passing ``None``
        stops capturing audio from that boundary onwards; the earlier audio is
        preserved and the remaining time is filled with silence at finalize.
        """
        try:
            with self._lock:
                if self._state is not RecorderState.RECORDING:
                    return
                current = self._mic
                current_id = current.id if current is not None else None
                new_id = device.id if device is not None else None
                if new_id == current_id:
                    return
                self._pending_mic = device
                self._pending_mic_set = True
            self._split_evt.set()
        except Exception as exc:
            self._report_error(f"set_mic failed: {exc!r}")

    def stop(self) -> str:
        """Finalize and mux; returns the produced path ("" on failure)."""
        try:
            with self._lock:
                if self._discarded:
                    return ""
                started = self._started
            if not started:
                return ""
            self._elapsed_timer_stop()
            self._set_state(RecorderState.STOPPING)
            self._stop_evt.set()
            self._resume_evt.set()
            self._pause_evt.clear()

            thread = self._thread
            if thread is not None:
                thread.join(timeout=6.0)
                if thread.is_alive():
                    self._report_error(
                        "recording thread did not stop in time; finalizing what was captured"
                    )
            self._flush_segment()
            self._emit_elapsed(force=True)

            self._verify_produced_length()

            with self._lock:
                self._started = False
                self._discarded = True  # stop() is terminal for this instance
            path = self._finalize()
            self._cleanup_tmp()
            self._set_state(RecorderState.IDLE)
            if path:
                try:
                    self.finished.emit(path)
                except Exception:
                    pass
            return path
        except Exception as exc:
            self._report_error(f"stop failed: {exc!r}")
            try:
                self._cleanup_tmp()
                self._set_state(RecorderState.IDLE)
            except Exception:
                pass
            return ""

    def discard(self) -> None:
        """Abort the recording and delete every temporary file.  Never raises."""
        try:
            with self._lock:
                was_started = self._started
            if not was_started:
                return
            self._elapsed_timer_stop()
            self._discarded = True
            self._stop_evt.set()
            self._resume_evt.set()
            self._pause_evt.clear()
            thread = self._thread
            if thread is not None:
                thread.join(timeout=6.0)
            self._flush_segment()
            with self._lock:
                self._segments = []
                self._started = False
            self._cleanup_tmp()
            self._set_state(RecorderState.IDLE)
        except Exception as exc:
            self._report_error(f"discard failed: {exc!r}")

    # -- finalize ----------------------------------------------------------
    def _verify_produced_length(self) -> None:
        """Compare what was written against how long we actually recorded.

        Duration is the one property a recording must never lose silently: a
        short file plays back fast *and* cuts off, and it desyncs any audio.
        If the encoder could not keep up we say so instead of shipping a
        quietly truncated movie.
        """
        try:
            with self._lock:
                produced = sum(float(s.get("seconds", 0.0)) for s in self._segments)
                expected = self._elapsed_total
            if expected < 0.5:
                return
            if produced >= expected * 0.9:
                return
            missing = expected - produced
            self._report_error(
                _t("本机编码速度跟不上：实际录制 {0:.1f}s，写入成片 {1:.1f}s"
                   "（少 {2:.1f}s）。建议降低帧率或缩小录制区域。").format(
                    expected, produced, missing),
                once=True,
            )
        except Exception:
            pass

    def _finalize(self) -> str:
        with self._lock:
            segments = [dict(s) for s in self._segments]
        if not segments:
            self._report_error("nothing was recorded", once=True)
            return ""

        tmp = self._tmp_dir
        out_path = self._out_path
        try:
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        except OSError:
            pass

        # ---- video ------------------------------------------------------
        if len(segments) == 1:
            video_src = segments[0]["video"]
        else:
            listing = os.path.join(tmp, "video_concat.txt")
            concat_files(listing, [s["video"] for s in segments])
            joined = os.path.join(tmp, "video_joined.mp4")
            ok, log = run_ffmpeg_checked(
                [
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    listing,
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    "-y",
                    joined,
                ],
                timeout=30.0,
            )
            if ok and os.path.isfile(joined) and os.path.getsize(joined) > 1024:
                video_src = joined
            else:
                self._report_error(
                    "video concatenation failed, only the first segment is kept: "
                    + (log or "").strip()[:300]
                )
                video_src = segments[0]["video"]

        # ---- audio ------------------------------------------------------
        # The microphone can be switched on or off between segments, so each
        # segment contributes either its captured audio (padded to the segment
        # length) or an equal length of silence.  That keeps the concatenated
        # audio aligned with the video instead of dropping it entirely.
        audio_parts: list[str] = []
        any_audio = False
        for index, segment in enumerate(segments):
            seconds = float(segment.get("seconds") or 0.0)
            needed = int(seconds * _MIC_RATE * _MIC_CHANNELS * _MIC_SAMPLE_BYTES)
            wav = segment.get("wav")
            usable = bool(wav) and os.path.isfile(wav) and _wav_data_size(wav) > 0
            if usable:
                _patch_wav(wav, pad_to_bytes=needed)
                audio_parts.append(wav)
                any_audio = True
            elif needed > 0:
                silent = os.path.join(tmp, f"silence{index:03d}.wav")
                if _write_silence_wav(silent, needed):
                    audio_parts.append(silent)

        audio_src: Optional[str] = None
        if any_audio and audio_parts:
            if len(audio_parts) == 1:
                audio_src = audio_parts[0]
            else:
                listing = os.path.join(tmp, "audio_concat.txt")
                concat_files(listing, audio_parts)
                joined_wav = os.path.join(tmp, "audio_joined.wav")
                ok, log = run_ffmpeg_checked(
                    [
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        listing,
                        "-c",
                        "copy",
                        "-y",
                        joined_wav,
                    ],
                    timeout=30.0,
                )
                if ok and os.path.isfile(joined_wav):
                    _patch_wav(joined_wav)
                    if _wav_data_size(joined_wav) > 0:
                        audio_src = joined_wav
                if audio_src is None:
                    self._report_error(
                        "audio concatenation failed, writing a video-only file: "
                        + (log or "").strip()[:300]
                    )

        # ---- mux --------------------------------------------------------
        if audio_src is not None:
            ok, log = run_ffmpeg_checked(
                [
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    video_src,
                    "-i",
                    audio_src,
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "160k",
                    "-shortest",
                    "-movflags",
                    "+faststart",
                    "-y",
                    out_path,
                ],
                timeout=45.0,
            )
            if ok and os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
                return out_path
            self._report_error(
                "muxing audio failed, writing a video-only file: "
                + (log or "").strip()[:300]
            )

        try:
            _move_file(video_src, out_path)
        except Exception as exc:
            self._report_error(f"cannot write the output file: {exc!r}")
            return ""
        if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
            self._report_error("the output file is empty")
            return ""
        return out_path

    def _cleanup_tmp(self) -> None:
        try:
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
        except Exception:
            pass
