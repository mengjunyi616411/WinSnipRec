"""Microphone (DirectShow) enumeration for WinSnipRec.

Devices are discovered by asking ffmpeg for its dshow device list and parsing
the ``(audio)`` lines from stderr.  Every function is failure tolerant: a
missing ffmpeg or a broken driver yields an empty list instead of an exception.
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import threading
import uuid
from dataclasses import dataclass

from . import encoder

__all__ = ["AudioDevice", "list_microphones", "default_microphone"]

_DEVICE_RE = re.compile(r'"([^"]*)"\s*\((audio|video)\)')

# ``dshow`` prints an extra footer line for every device; it is not a device.
_ALT_NAME_MARKER = "alternative name"


@dataclass(frozen=True)
class AudioDevice:
    """A capture device.

    ``name`` is a human readable label, ``id`` is the exact string ffmpeg
    expects after ``audio=`` for the dshow input format.
    """

    name: str
    id: str


def decode_output(data: bytes) -> str:
    """Decode ffmpeg output bytes (UTF-8 on Windows, with legacy fallbacks)."""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "mbcs", "gbk", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def _decode(data: bytes) -> str:
    return decode_output(data)


_DEVICE_CACHE: list[AudioDevice] | None = None
_DEVICE_LOCK = threading.Lock()
_DEVICE_THREAD: threading.Thread | None = None
_DEVICE_WAITERS: list = []

# ffmpeg's device listing has no timeout of its own; 25 s left the settings
# dialog frozen far past the point where Windows reports "not responding".
DEVICE_SCAN_TIMEOUT = 8


def cached_microphones() -> list[AudioDevice]:
    """Devices from the background scan. Never blocks; [] until it finishes."""
    with _DEVICE_LOCK:
        return list(_DEVICE_CACHE) if _DEVICE_CACHE is not None else []


def microphones_scanned() -> bool:
    with _DEVICE_LOCK:
        return _DEVICE_CACHE is not None


def scan_microphones_async(done=None, force: bool = False) -> threading.Thread | None:
    """Enumerate devices once, off the GUI thread.

    Calling this while a scan is already running *registers* ``done`` instead of
    silently dropping it, so a caller that arrives late still gets the result.

    ``done`` is called from the worker thread with the device list, so a Qt
    caller must marshal it back to its own thread (a signal does that). Returns
    the running thread, or None when a scan was already in flight.
    """
    global _DEVICE_THREAD
    with _DEVICE_LOCK:
        if _DEVICE_CACHE is not None and not force:
            # Already have an answer: hand it over right away so no caller can
            # subscribe after the fact and wait forever.
            devices = list(_DEVICE_CACHE)
            thread = None
        else:
            devices = None
            if done is not None:
                _DEVICE_WAITERS.append(done)
            if _DEVICE_THREAD is not None and _DEVICE_THREAD.is_alive():
                return None
            thread = threading.Thread(target=_device_scan_work,
                                      name="audio-device-scan", daemon=True)
            _DEVICE_THREAD = thread
            thread.start()
    if devices is not None and done is not None:
        try:
            done(devices)
        except Exception:
            pass
    return thread


def _device_scan_work() -> None:
    global _DEVICE_CACHE
    devices = list_microphones()
    with _DEVICE_LOCK:
        # Only remember a real result: an empty list usually means ffmpeg timed
        # out, and caching that would hide the devices for the whole session.
        if devices or _DEVICE_CACHE is None:
            _DEVICE_CACHE = devices
        waiters = list(_DEVICE_WAITERS)
        _DEVICE_WAITERS.clear()
    for callback in waiters:
        try:
            callback(devices)
        except Exception:
            pass


def list_microphones(ffmpeg: str | None = None) -> list[AudioDevice]:
    """Enumerate DirectShow audio capture devices.  Never raises.

    Blocks for several seconds: call it from a worker thread (see
    :func:`scan_microphones_async`) or read :func:`cached_microphones`.
    """
    exe = ffmpeg or encoder.ffmpeg_path()
    if not exe:
        return []

    args = [
        exe,
        "-hide_banner",
        "-list_devices",
        "true",
        "-f",
        "dshow",
        "-i",
        "dummy",
    ]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        proc = subprocess.run(args, timeout=DEVICE_SCAN_TIMEOUT, **kwargs)
    except Exception:
        return []

    text = _decode(proc.stderr or b"") + "\n" + _decode(proc.stdout or b"")
    devices: list[AudioDevice] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if _ALT_NAME_MARKER in line.lower():
            continue
        for match in _DEVICE_RE.finditer(line):
            name, kind = match.group(1), match.group(2)
            if kind != "audio":
                continue
            name = name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            devices.append(AudioDevice(name=name, id=name))
    return devices


def default_microphone(ffmpeg: str | None = None) -> AudioDevice | None:
    """The microphone Windows uses by default, else the first enumerated one.

    DirectShow enumerates capture filters in registration order, which is not
    the same as the user's default endpoint, so the MMDevice API is asked for
    the default capture device and matched against the dshow names.  Any
    failure falls back to the first enumerated device.
    """
    devices = list_microphones(ffmpeg)
    if not devices:
        return None
    friendly = _default_endpoint_friendly_name()
    if friendly:
        for device in devices:
            if device.id == friendly or device.name == friendly:
                return device
        lowered = friendly.casefold()
        for device in devices:
            if device.id.casefold().startswith(lowered):
                return device
        for device in devices:
            if lowered in device.id.casefold():
                return device
    return devices[0]


# ---------------------------------------------------------------------------
# Windows default capture endpoint (COM / MMDevice API)
# ---------------------------------------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", ctypes.c_ulong)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("r1", ctypes.c_ushort),
        ("r2", ctypes.c_ushort),
        ("r3", ctypes.c_ushort),
        ("data", ctypes.c_void_p),
    ]


_CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_PKEY_Device_FriendlyName = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)

_CLSCTX_ALL = 0x17
_COINIT_APARTMENTTHREADED = 0x2
_VT_LPWSTR = 31
_DEVICE_STATE_ACTIVE = 0x1
_EDATAFLOW_CAPTURE = 1  # EDataFlow: eRender = 0, eCapture = 1, eAll = 2
_EROLECONSOLE = 0  # ERole: eConsole = 0, eMultimedia = 1, eCommunications = 2


def _guid(text: str) -> _GUID:
    return _GUID.from_buffer_copy(uuid.UUID(text).bytes_le)


def _vtbl(pointer, index: int, restype, *argtypes):
    """Build a callable for vtable slot ``index`` of a COM interface."""
    table = ctypes.cast(
        pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))
    ).contents
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(table[index])


def _release(pointer) -> None:
    if not pointer:
        return
    try:
        _vtbl(pointer, 2, ctypes.c_long)(pointer)
    except Exception:
        pass


def _default_endpoint_friendly_name() -> str:
    """Friendly name of the default capture endpoint ("" when unavailable)."""
    if os.name != "nt":
        return ""
    ole32 = ctypes.windll.ole32
    enumerator = ctypes.c_void_p()
    device = ctypes.c_void_p()
    store = ctypes.c_void_p()
    initialized = False
    name = ""
    try:
        hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        initialized = hr in (0, 1)  # S_OK / S_FALSE
        clsid = _guid(_CLSID_MMDeviceEnumerator)
        iid = _guid(_IID_IMMDeviceEnumerator)
        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            _CLSCTX_ALL,
            ctypes.byref(iid),
            ctypes.byref(enumerator),
        )
        if hr != 0 or not enumerator:
            return ""

        # GetDefaultAudioEndpoint(eCapture, eConsole, &device)
        get_default = _vtbl(
            enumerator,
            4,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
        )
        if (
            get_default(enumerator, _EDATAFLOW_CAPTURE, _EROLECONSOLE, ctypes.byref(device))
            != 0
            or not device
        ):
            return ""

        open_store = _vtbl(
            device, 4, ctypes.c_long, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )
        if open_store(device, 0, ctypes.byref(store)) != 0 or not store:
            return ""

        key = _PROPERTYKEY(_guid(_PKEY_Device_FriendlyName[0]), _PKEY_Device_FriendlyName[1])
        value = _PROPVARIANT()
        get_value = _vtbl(
            store, 5, ctypes.c_long, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT)
        )
        if get_value(store, ctypes.byref(key), ctypes.byref(value)) == 0:
            try:
                if value.vt == _VT_LPWSTR and value.data:
                    name = ctypes.wstring_at(value.data) or ""
            finally:
                try:
                    ole32.PropVariantClear(ctypes.byref(value))
                except Exception:
                    pass
    except Exception:
        name = ""
    finally:
        _release(store)
        _release(device)
        _release(enumerator)
        if initialized:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass
    return name.strip()
