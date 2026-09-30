"""Screen enumeration and pixel grabbing for WinSnipRec.

Only Windows APIs that have been available since Windows 10 1809 are used.

Pixels are grabbed through ``mss`` and returned as tightly packed, top-down
BGRA rows, which is exactly the layout ffmpeg's ``-pix_fmt bgra`` raw video
input expects (no row padding, no vertical flip).
"""

from __future__ import annotations

import ctypes
import zlib
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable, Optional

import mss

__all__ = [
    "Monitor",
    "list_monitors",
    "virtual_rect",
    "clamp_rect",
    "ScreenGrabber",
]

# GetSystemMetrics indices used as a fallback when mss cannot be created.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79

_MONITOR_DEFAULTTOPRIMARY = 1


@dataclass(frozen=True)
class Monitor:
    """A single physical/virtual display."""

    index: int
    left: int
    top: int
    width: int
    height: int
    name: str

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)


# ---------------------------------------------------------------------------
# Win32 helpers (all of them are best-effort: failures degrade to defaults)
# ---------------------------------------------------------------------------


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    ctypes.c_void_p,  # HMONITOR
    ctypes.c_void_p,  # HDC
    ctypes.POINTER(_RECT),
    wintypes.LPARAM,
)


def _user32():
    return ctypes.windll.user32


def _display_device_names() -> dict[tuple[int, int, int, int], str]:
    """Map monitor rectangles to device names such as ``\\\\.\\DISPLAY1``."""
    names: dict[tuple[int, int, int, int], str] = {}
    try:
        user32 = _user32()

        def _cb(hmon, hdc, lprc, lparam):  # pragma: no cover - Win32 callback
            try:
                info = _MONITORINFOEXW()
                info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
                if user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
                    r = info.rcMonitor
                    key = (r.left, r.top, r.right - r.left, r.bottom - r.top)
                    names[key] = info.szDevice or ""
            except Exception:
                pass
            return True

        proc = _MONITORENUMPROC(_cb)
        user32.EnumDisplayMonitors(None, None, proc, 0)
    except Exception:
        pass
    return names


def _primary_rect() -> Optional[tuple[int, int, int, int]]:
    """Rectangle of the primary monitor, or ``None`` when unavailable."""
    try:
        user32 = _user32()
        user32.MonitorFromPoint.restype = ctypes.c_void_p
        pt = wintypes.POINT(0, 0)
        hmon = user32.MonitorFromPoint(pt, _MONITOR_DEFAULTTOPRIMARY)
        if not hmon:
            return None
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
            r = info.rcMonitor
            return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        pass
    return None


def _metrics_rect() -> Optional[tuple[int, int, int, int]]:
    try:
        user32 = _user32()
        left = int(user32.GetSystemMetrics(_SM_XVIRTUALSCREEN))
        top = int(user32.GetSystemMetrics(_SM_YVIRTUALSCREEN))
        width = int(user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN))
        height = int(user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN))
        if width > 0 and height > 0:
            return (left, top, width, height)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public enumeration API
# ---------------------------------------------------------------------------


def _mss_monitors() -> list[dict]:
    """Raw monitor dictionaries from mss (index 0 is the virtual desktop)."""
    with mss.mss() as sct:
        return [dict(m) for m in sct.monitors]


def list_monitors() -> list[Monitor]:
    """Enumerate monitors; index 0 is always the primary display.

    Returns an empty list when the display stack cannot be queried.
    """
    try:
        raw = _mss_monitors()
    except Exception:
        return []

    entries: list[tuple[int, int, int, int]] = []
    for m in raw[1:]:
        entries.append(
            (int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"]))
        )
    if not entries:
        # Some sessions expose only the virtual monitor.
        for m in raw:
            entries.append(
                (int(m["left"]), int(m["top"]), int(m["width"]), int(m["height"]))
            )
    if not entries:
        return []

    names = _display_device_names()
    primary = _primary_rect()

    ordered = list(entries)
    if primary is not None and primary in ordered:
        ordered.remove(primary)
        ordered.insert(0, primary)

    monitors: list[Monitor] = []
    for index, rect in enumerate(ordered):
        device = names.get(rect) or ""
        if device:
            label = device.rsplit("\\", 1)[-1]
        else:
            label = f"Monitor {index + 1}"
        if index == 0 and primary is not None:
            label = f"{label} (Primary)"
        monitors.append(
            Monitor(
                index=index,
                left=rect[0],
                top=rect[1],
                width=rect[2],
                height=rect[3],
                name=label,
            )
        )
    return monitors


def virtual_rect() -> tuple[int, int, int, int]:
    """``(left, top, width, height)`` bounding box of every monitor."""
    try:
        raw = _mss_monitors()
        if raw:
            m = raw[0]
            width = int(m["width"])
            height = int(m["height"])
            if width > 0 and height > 0:
                return (int(m["left"]), int(m["top"]), width, height)
    except Exception:
        pass

    rect = _metrics_rect()
    if rect is not None:
        return rect
    return (0, 0, 1, 1)


def clamp_rect(
    rect: Iterable[int], bounds: Optional[tuple[int, int, int, int]] = None, even: bool = False
) -> tuple[int, int, int, int]:
    """Clamp ``(left, top, width, height)`` to the virtual desktop.

    Width/height are at least 1 (2 when ``even`` is requested, which is what
    libx264 requires) and the rectangle always stays inside ``bounds``.
    """
    try:
        left, top, width, height = (int(v) for v in tuple(rect)[:4])
    except Exception:
        left, top, width, height = 0, 0, 1, 1

    if bounds is None:
        bounds = virtual_rect()
    bleft, btop, bwidth, bheight = (int(v) for v in bounds)
    bwidth = max(1, bwidth)
    bheight = max(1, bheight)

    width = max(1, min(width, bwidth))
    height = max(1, min(height, bheight))
    left = max(bleft, min(left, bleft + bwidth - width))
    top = max(btop, min(top, btop + bheight - height))

    if even:
        width = max(2, width - width % 2)
        height = max(2, height - height % 2)
        width = min(width, bwidth)
        height = min(height, bheight)
    return (left, top, width, height)


# ---------------------------------------------------------------------------
# PNG encoding (stdlib only; avoids a Pillow dependency)
# ---------------------------------------------------------------------------


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        len(payload).to_bytes(4, "big")
        + tag
        + payload
        + (zlib.crc32(tag + payload) & 0xFFFFFFFF).to_bytes(4, "big")
    )


def _bgra_to_png(raw: bytes, width: int, height: int, level: int = 6) -> bytes:
    """Encode tightly packed BGRA rows as an 8-bit RGB PNG."""
    width = max(1, int(width))
    height = max(1, int(height))
    expected = width * height * 4
    if len(raw) < expected:
        raw = bytes(raw) + b"\x00" * (expected - len(raw))

    # Filter type 0 (None) for every row; BGRX -> RGB.
    stride = width * 4
    out = bytearray((width * 3 + 1) * height)
    pos = 0
    for y in range(height):
        base = y * stride
        out[pos] = 0
        pos += 1
        row = raw[base : base + stride]
        out[pos : pos + width * 3] = _bgra_row_to_rgb(row, width)
        pos += width * 3

    ihdr = (
        width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + bytes((8, 2, 0, 0, 0))
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(out), level))
        + _png_chunk(b"IEND", b"")
    )


def _bgra_row_to_rgb(row: bytes, width: int) -> bytes:
    """Convert one BGRA row into an RGB row."""
    try:
        import numpy as np

        arr = np.frombuffer(row, dtype=np.uint8, count=width * 4).reshape(width, 4)
        return arr[:, [2, 1, 0]].tobytes()
    except Exception:
        out = bytearray(width * 3)
        for x in range(width):
            i = x * 4
            out[x * 3] = row[i + 2]
            out[x * 3 + 1] = row[i + 1]
            out[x * 3 + 2] = row[i]
        return bytes(out)


def _downscale_bgra(raw: bytes, width: int, height: int, new_width: int) -> tuple[bytes, int, int]:
    """Nearest-neighbour horizontal+vertical downscale (keeps aspect ratio)."""
    new_width = max(1, int(new_width))
    if new_width >= width:
        return raw, width, height
    new_height = max(1, int(round(height * (new_width / float(width)))))
    try:
        import numpy as np

        src = np.frombuffer(raw, dtype=np.uint8, count=width * height * 4).reshape(
            height, width, 4
        )
        ys = (np.arange(new_height) * height // new_height).astype("intp")
        xs = (np.arange(new_width) * width // new_width).astype("intp")
        dst = src[ys][:, xs]
        return dst.tobytes(), new_width, new_height
    except Exception:
        return raw, width, height


# ---------------------------------------------------------------------------
# Grabber
# ---------------------------------------------------------------------------


class ScreenGrabber:
    """Grabs pixels.  One instance is used from a single worker thread."""

    def __init__(self) -> None:
        self._sct = None
        self._bounds = virtual_rect()
        self._closed = False
        try:
            self._sct = mss.mss()
        except Exception:
            self._sct = None

    # -- internals ---------------------------------------------------------
    def _shot(self, rect: tuple[int, int, int, int]):
        if self._sct is None:
            raise RuntimeError("screen capture backend (mss) is unavailable")
        left, top, width, height = rect
        return self._sct.grab(
            {"left": left, "top": top, "width": width, "height": height}
        )

    # -- public API --------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._sct is not None and not self._closed

    def grab(self, rect: tuple[int, int, int, int]) -> bytes:
        """Return raw BGRA bytes for ``rect`` (``len == w * h * 4``).

        Never raises: on failure a correctly sized black frame is returned.
        """
        left, top, width, height = clamp_rect(rect, self._bounds)
        size = width * height * 4
        if self._closed or self._sct is None:
            return bytes(size)
        try:
            shot = self._shot((left, top, width, height))
            raw = bytes(shot.raw)
            if len(raw) != size:
                # Defensive: mss should always hand back tightly packed rows.
                if len(raw) > size:
                    raw = raw[:size]
                else:
                    raw = raw + bytes(size - len(raw))
            return raw
        except Exception:
            return bytes(size)

    def grab_png(
        self, rect: tuple[int, int, int, int], max_width: int | None = None
    ) -> bytes:
        """Return a PNG screenshot of ``rect``, optionally downscaled."""
        left, top, width, height = clamp_rect(rect, self._bounds)
        raw = self.grab((left, top, width, height))
        if max_width is not None and width > max_width:
            raw, width, height = _downscale_bgra(raw, width, height, int(max_width))
        try:
            return _bgra_to_png(raw, width, height)
        except Exception:
            return b""

    def close(self) -> None:
        self._closed = True
        sct, self._sct = self._sct, None
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass

    def __enter__(self) -> "ScreenGrabber":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
