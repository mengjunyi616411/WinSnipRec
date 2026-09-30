"""ffmpeg discovery plus a raw-BGRA -> H.264 MP4 pipe writer.

The writer is deliberately paranoid: every public method swallows errors and
records them instead, because it is driven from a recording thread that must
never die from an encoder hiccup.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import threading
from collections import deque
from typing import Iterable, Optional, Sequence

__all__ = [
    "ffmpeg_path",
    "ffmpeg_available",
    "run_ffmpeg",
    "FfmpegVideoWriter",
    "CREATE_NO_WINDOW",
]

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

_FFMPEG_LOCK = threading.Lock()
_FFMPEG_CACHE: Optional[str] = None
_FFMPEG_RESOLVED = False

_COMMON_PATHS = (
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
)


def _candidate_paths() -> list[str]:
    candidates: list[str] = []

    # Frozen (PyInstaller) bundle: the ffmpeg payload may sit next to the
    # executable, in the extraction root, or under imageio_ffmpeg/binaries.
    roots = [root for root in (getattr(sys, "_MEIPASS", None),
                               os.path.dirname(sys.executable)) if root]
    for root in roots:
        for pattern in ("ffmpeg.exe", "ffmpeg*.exe",
                        os.path.join("imageio_ffmpeg", "binaries", "*.exe")):
            try:
                candidates.extend(sorted(glob.glob(os.path.join(root, pattern))))
            except Exception:
                continue

    try:  # bundled binary shipped with the imageio-ffmpeg wheel
        import imageio_ffmpeg  # type: ignore

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            candidates.append(os.fspath(exe))
    except Exception:
        pass

    which = shutil.which("ffmpeg")
    if which:
        candidates.append(which)

    for base in _COMMON_PATHS:
        candidates.append(base)

    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
        candidates.append(os.path.join(local, "Programs", "ffmpeg", "bin", "ffmpeg.exe"))
    profile = os.environ.get("USERPROFILE")
    if profile:
        candidates.append(os.path.join(profile, "scoop", "shims", "ffmpeg.exe"))
    pf = os.environ.get("ProgramFiles")
    if pf:
        candidates.append(os.path.join(pf, "ffmpeg", "bin", "ffmpeg.exe"))
    return candidates


def _resolve(explicit: str | None = None) -> str:
    if explicit:
        path = os.fspath(explicit)
        if os.path.isfile(path):
            return os.path.abspath(path)
        found = shutil.which(path)
        if found:
            return found
    for candidate in _candidate_paths():
        try:
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)
        except Exception:
            continue
    return ""


def ffmpeg_path() -> str:
    """Resolved path to a usable ``ffmpeg`` executable ("" when missing)."""
    global _FFMPEG_CACHE, _FFMPEG_RESOLVED
    with _FFMPEG_LOCK:
        if not _FFMPEG_RESOLVED:
            _FFMPEG_CACHE = _resolve(None)
            _FFMPEG_RESOLVED = True
        return _FFMPEG_CACHE or ""


def ffmpeg_available() -> bool:
    return bool(ffmpeg_path())


def run_ffmpeg(args: list[str], **kw) -> subprocess.CompletedProcess:
    """Run ffmpeg with ``args``.

    Returns a synthetic failed ``CompletedProcess`` when no executable is
    available instead of raising, so callers can inspect ``returncode``.
    """
    cmd_args = [str(a) for a in args]
    exe = ffmpeg_path()
    if not exe:
        return subprocess.CompletedProcess(
            args=["ffmpeg", *cmd_args],
            returncode=127,
            stdout=b"",
            stderr=b"ffmpeg executable not found",
        )

    kw.setdefault("stdin", subprocess.DEVNULL)
    if not kw.get("capture_output"):
        kw.setdefault("stdout", subprocess.PIPE)
        kw.setdefault("stderr", subprocess.PIPE)
    if CREATE_NO_WINDOW:
        kw.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run([exe, *cmd_args], **kw)


class FfmpegVideoWriter:
    """Streams raw BGRA frames into an H.264 MP4 through a pipe.

    Every public method is exception safe.  Frames whose size differs from the
    configured (even adjusted) size are dropped and recorded in :attr:`error`.
    """

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: int = 30,
        crf: int = 20,
        preset: str = "veryfast",
        ffmpeg: str | None = None,
    ) -> None:
        self._path = os.path.abspath(os.fspath(path))
        self._width = max(2, int(width) - int(width) % 2)
        self._height = max(2, int(height) - int(height) % 2)
        self._fps = max(1, int(fps))
        self._crf = int(crf)
        self._preset = str(preset)
        self._frames = 0
        self._error: Optional[str] = None
        self._closed = False
        self._proc: Optional[subprocess.Popen] = None
        self._stderr: deque[str] = deque(maxlen=40)
        self._drain: Optional[threading.Thread] = None

        try:
            exe = ffmpeg or ffmpeg_path()
            if not exe:
                self._error = "ffmpeg executable not found"
                return
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            args = [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "bgra",
                "-s",
                f"{self._width}x{self._height}",
                "-r",
                str(self._fps),
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                self._preset,
                "-crf",
                str(self._crf),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-y",
                self._path,
            ]
            kwargs: dict = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.PIPE,
            }
            if CREATE_NO_WINDOW:
                kwargs["creationflags"] = CREATE_NO_WINDOW
            self._proc = subprocess.Popen(args, **kwargs)
            self._drain = threading.Thread(
                target=self._drain_stderr, name="winsnip-ffmpeg-log", daemon=True
            )
            self._drain.start()
        except Exception as exc:  # pragma: no cover - depends on host state
            self._error = f"cannot start ffmpeg: {exc!r}"
            self._proc = None

    # -- internals ---------------------------------------------------------
    def _drain_stderr(self) -> None:
        proc = self._proc
        if proc is None or proc.stderr is None:
            return
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._stderr.append(line)
        except Exception:
            pass

    def _tail(self) -> str:
        return " | ".join(self._stderr)

    # -- public API --------------------------------------------------------
    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def path(self) -> str:
        return self._path

    @property
    def frames_written(self) -> int:
        return self._frames

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def closed(self) -> bool:
        return self._closed

    def write(self, frame: bytes) -> None:
        """Write one raw BGRA frame.  Never raises."""
        if self._closed or self._proc is None or self._error is not None:
            return
        expected = self._width * self._height * 4
        if len(frame) != expected:
            self._error = f"frame size mismatch: got {len(frame)}, expected {expected}"
            return
        try:
            stdin = self._proc.stdin
            if stdin is None:
                self._error = "encoder stdin is closed"
                return
            stdin.write(frame)
            self._frames += 1
            if self._frames == 1:
                stdin.flush()
        except Exception as exc:
            self._error = f"write failed: {exc!r}"

    def close(self, timeout: float = 20.0) -> None:
        """Finalize the file.  Idempotent and exception safe."""
        if self._closed:
            return
        self._closed = True
        proc = self._proc
        if proc is None:
            return

        try:
            if proc.stdin is not None:
                proc.stdin.close()
        except Exception:
            pass

        returncode: Optional[int] = None
        try:
            returncode = proc.wait(timeout=max(1.0, float(timeout)))
        except Exception:
            try:
                proc.terminate()
                returncode = proc.wait(timeout=5.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            if self._error is None:
                self._error = "ffmpeg did not exit in time and was terminated"

        if self._drain is not None:
            try:
                self._drain.join(timeout=2.0)
            except Exception:
                pass

        if returncode not in (0, None) and self._error is None:
            tail = self._tail()
            self._error = f"ffmpeg exited with code {returncode}" + (
                f": {tail}" if tail else ""
            )

    def __enter__(self) -> "FfmpegVideoWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        try:
            self.close(timeout=5.0)
        except Exception:
            pass


def concat_files(list_path: str, paths: Sequence[str]) -> None:
    """Write an ffmpeg concat-demuxer list using relative file names."""
    directory = os.path.dirname(os.path.abspath(list_path))
    lines = []
    for path in paths:
        name = os.path.relpath(os.path.abspath(path), directory).replace("\\", "/")
        name = name.replace("'", "'\\''")
        lines.append(f"file '{name}'")
    with open(list_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")


def run_ffmpeg_checked(args: Iterable[str], timeout: float = 60.0, **kw):
    """Run ffmpeg, returning ``(ok, stderr_text)``."""
    try:
        result = run_ffmpeg(list(args), timeout=timeout, **kw)
    except Exception as exc:
        return False, f"{exc!r}"
    stderr = result.stderr or b""
    if isinstance(stderr, str):
        text = stderr
    else:
        text = stderr.decode("utf-8", "replace")
    return result.returncode == 0, text
