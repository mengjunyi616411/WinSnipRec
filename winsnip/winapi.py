"""Thin, dependency-free Win32 / DWM interop used by the UI layer.

Everything here degrades gracefully: if a call is unavailable (for example the
Win11-only rounded-corner attribute on Windows 10) the helper simply reports
failure instead of raising.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from dataclasses import dataclass

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover - dwmapi exists on every supported Windows
    dwmapi = None

# --------------------------------------------------------------------------- #
# DWM
# --------------------------------------------------------------------------- #
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

DWMWCP_DEFAULT = 0
DWMWCP_DONOTROUND = 1
DWMWCP_ROUND = 2
DWMWCP_ROUNDSMALL = 3

# Windows 11 22H2+ system backdrop (attribute 38).
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_AUTO = 0
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2        # Mica
DWMSBT_TRANSIENTWINDOW = 3   # Acrylic
DWMSBT_TABBEDWINDOW = 4

# Windows 10 1803+ composition attribute: a real blur the DWM composites.
WCA_ACCENT_POLICY = 19
ACCENT_DISABLED = 0
ACCENT_ENABLE_BLURBEHIND = 3
ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
RGN_OR = 2
RGN_DIFF = 4


class _ACCENTPOLICY(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int)]


class _WINCOMPATTRDATA(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(_ACCENTPOLICY)),
                ("SizeOfData", ctypes.c_size_t)]


def is_layered(hwnd: int) -> bool:
    """Layered windows bypass DWM backdrop effects entirely."""
    try:
        return bool(user32.GetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE) & WS_EX_LAYERED)
    except Exception:
        return False


def set_system_backdrop(hwnd: int, kind: int = DWMSBT_TRANSIENTWINDOW) -> bool:
    """Ask DWM for a live backdrop material (Windows 11 22H2+).

    Returns True when the attribute was accepted; that is NOT proof it renders -
    see backsplash.probe_native_backdrop, which checks the pixels.
    """
    if not dwmapi:
        return False
    try:
        value = ctypes.c_int(kind)
        hr = dwmapi.DwmSetWindowAttribute(
            wt.HWND(hwnd), ctypes.c_uint(DWMWA_SYSTEMBACKDROP_TYPE),
            ctypes.byref(value), ctypes.sizeof(value),
        )
        return hr == 0
    except Exception:
        return False


def set_accent_blur(hwnd: int, state: int = ACCENT_ENABLE_ACRYLICBLURBEHIND,
                    tint: int = 0x00000000) -> bool:
    """Windows 10's undocumented live blur. Also works on Windows 11."""
    try:
        policy = _ACCENTPOLICY(state, 2, tint, 0)
        data = _WINCOMPATTRDATA(WCA_ACCENT_POLICY, ctypes.pointer(policy),
                                ctypes.sizeof(policy))
        user32.SetWindowCompositionAttribute(wt.HWND(hwnd), ctypes.byref(data))
        return True
    except Exception:
        return False


def clear_rounded_region(hwnd: int) -> bool:
    """Undo set_rounded_region().

    A window region CLIPS the window. Leaving one behind after the window grows
    cuts off whatever falls outside the old region.
    """
    try:
        return bool(user32.SetWindowRgn(wt.HWND(hwnd), None, True))
    except Exception:
        return False


def clear_backdrop(hwnd: int) -> None:
    """Turn both mechanisms off again."""
    set_system_backdrop(hwnd, DWMSBT_NONE)
    set_accent_blur(hwnd, ACCENT_DISABLED)


def set_rounded_region(hwnd: int, width: int, height: int, radius: int) -> bool:
    """Shape a non-layered window like a rounded rectangle.

    The native backdrop covers the whole window rect, so a window that wants
    rounded corners without a layered (per-pixel alpha) surface has to clip
    itself with a window region instead.
    """
    try:
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1,
                                          radius * 2, radius * 2)
        if not region:
            return False
        # SetWindowRgn takes ownership of the region on success.
        ok = user32.SetWindowRgn(wt.HWND(hwnd), region, True)
        if not ok:
            gdi32.DeleteObject(region)
        return bool(ok)
    except Exception:
        return False


def is_windows_11() -> bool:
    """True on Windows 11 (build >= 22000)."""
    try:
        return sys.getwindowsversion().build >= 22000
    except Exception:
        return False


def set_rounded_corners(hwnd: int, preference: int = DWMWCP_ROUND) -> bool:
    """Ask DWM to round the window corners (Win11). Returns False on Win10."""
    if not dwmapi:
        return False
    try:
        value = ctypes.c_int(preference)
        hr = dwmapi.DwmSetWindowAttribute(
            wt.HWND(hwnd), ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),
            ctypes.byref(value), ctypes.sizeof(value),
        )
        return hr == 0
    except Exception:
        return False


def set_dark_titlebar(hwnd: int, dark: bool = True) -> bool:
    if not dwmapi:
        return False
    try:
        value = ctypes.c_int(1 if dark else 0)
        hr = dwmapi.DwmSetWindowAttribute(
            wt.HWND(hwnd), ctypes.c_uint(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(value), ctypes.sizeof(value),
        )
        return hr == 0
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Process DPI awareness
# --------------------------------------------------------------------------- #
def enable_per_monitor_dpi_awareness() -> None:
    """Best-effort DPI awareness so Win32 coordinates match physical pixels."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Registry backed Windows personalisation
# --------------------------------------------------------------------------- #
def _reg_dword(root, path: str, name: str) -> int | None:
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return int(value)
    except Exception:
        return None


def _reg_str(root, path: str, name: str) -> str | None:
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value) if value else None
    except Exception:
        return None


def is_dark_mode() -> bool:
    """True when Windows apps are configured to use the dark theme."""
    import winreg

    value = _reg_dword(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "AppsUseLightTheme",
    )
    if value is None:
        return False
    return value == 0


SPI_GETCLIENTAREAANIMATION = 0x1042


def client_area_animations_enabled() -> bool:
    """Windows' "show animations in Windows" accessibility setting."""
    try:
        value = ctypes.c_int(1)
        ok = user32.SystemParametersInfoW(
            ctypes.c_uint(SPI_GETCLIENTAREAANIMATION), 0, ctypes.byref(value), 0)
        if not ok:
            return True
        return bool(value.value)
    except Exception:
        return True


SPI_GETANIMATION = 0x0048
SW_MINIMIZE = 6


class _ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("iMinAnimate", ctypes.c_int)]


def native_minimize_animation_enabled() -> bool:
    """Whether Windows itself will animate minimize/maximize.

    This is the system's own "Animate windows when minimizing and maximizing"
    option (SPI_GETANIMATION), not the general animation setting. When it is off,
    ShowWindow(SW_MINIMIZE) makes the window vanish instantly and an app that wants
    the Windows-style shrink has to draw it itself.

    NOTE: SPI_GETANIMATION takes an ANIMATIONINFO struct, whose *first* field is
    cbSize — reading it as a bare UINT reports cbSize, and if the call fails you
    silently get whatever you initialised the buffer with. That mistake is how this
    machine first looked like it had the animation disabled when it does not.
    """
    try:
        info = _ANIMATIONINFO()
        info.cbSize = ctypes.sizeof(info)
        ok = user32.SystemParametersInfoW(
            ctypes.c_uint(SPI_GETANIMATION), ctypes.sizeof(info), ctypes.byref(info), 0)
        if not ok:
            return False
        return bool(info.iMinAnimate)
    except Exception:
        return False


def minimize_window_native(hwnd: int) -> bool:
    """Ask Windows to minimize the window, so DWM plays its own animation."""
    if not hwnd:
        return False
    try:
        return bool(user32.ShowWindow(wt.HWND(hwnd), SW_MINIMIZE))
    except Exception:
        return False


def system_accent_color(dark: bool = False) -> str:
    """The user's accent colour as '#RRGGBB'.

    ``HKCU\\...\\DWM\\AccentColor`` is a DWORD in **ABGR** order, so the red
    component is the low byte (verified against ``AccentPalette``).
    """
    import winreg

    value = _reg_dword(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM", "AccentColor")
    if value is None:
        return "#0078D4"
    r = value & 0xFF
    g = (value >> 8) & 0xFF
    b = (value >> 16) & 0xFF
    # Reject near-greyscale accents; Windows itself falls back to the default blue.
    if abs(r - g) < 12 and abs(g - b) < 12:
        return "#0078D4"
    return f"#{r:02X}{g:02X}{b:02X}"


def wallpaper_path() -> str | None:
    import winreg

    path = _reg_str(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", "WallPaper")
    if path and path.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp")):
        return path
    return None


def wallpaper_style() -> int:
    """WallPaperStyle: 0 centre, 2 stretch, 6 fit, 10 fill, 22 span."""
    import winreg

    value = _reg_str(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", "WallpaperStyle")
    try:
        return int(value) if value is not None else 10
    except ValueError:
        return 10


# --------------------------------------------------------------------------- #
# Windows enumeration (used by the "window" capture mode)
# --------------------------------------------------------------------------- #
GWL_EXSTYLE = -20
GW_HWNDNEXT = 2
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(_RECT)]
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.IsIconic.argtypes = [wt.HWND]
user32.IsIconic.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetDesktopWindow.argtypes = []
user32.GetDesktopWindow.restype = wt.HWND
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.GetWindow.argtypes = [wt.HWND, ctypes.c_uint]
user32.WindowFromPoint.argtypes = [wt.POINT]
user32.WindowFromPoint.restype = wt.HWND
user32.GetAncestor.argtypes = [wt.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wt.HWND
user32.GetWindow.argtypes = [wt.HWND, ctypes.c_uint]
user32.GetWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = wt.BOOL
user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
user32.UnregisterHotKey.restype = wt.BOOL


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    left: int
    top: int
    width: int
    height: int

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.width, self.height)


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    rect = _RECT()
    if dwmapi:
        try:
            hr = dwmapi.DwmGetWindowAttribute(
                wt.HWND(hwnd), ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
                ctypes.byref(rect), ctypes.sizeof(rect),
            )
            if hr == 0 and rect.right > rect.left and rect.bottom > rect.top:
                return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
        except Exception:
            pass
    if not user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def _is_cloaked(hwnd: int) -> bool:
    if not dwmapi:
        return False
    try:
        value = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(
            wt.HWND(hwnd), ctypes.c_uint(DWMWA_CLOAKED), ctypes.byref(value), ctypes.sizeof(value)
        )
        return hr == 0 and value.value != 0
    except Exception:
        return False


def list_windows(min_size: int = 40) -> list[WindowInfo]:
    """Visible, non-tool top level windows, largest first."""
    result: list[WindowInfo] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd) or _is_cloaked(hwnd):
                return True
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if ex_style & (WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE):
                return True
            info = _window_rect(hwnd)
            if not info:
                return True
            left, top, width, height = info
            if width < min_size or height < min_size:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if not title:
                return True
            result.append(WindowInfo(int(hwnd), title, left, top, width, height))
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(_callback, 0)
    except Exception:
        pass
    result.sort(key=lambda w: w.width * w.height, reverse=True)
    return result


def window_pid(hwnd: int) -> int:
    """Process id that owns a top level window."""
    pid = wt.DWORD()
    try:
        user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
    except Exception:
        return 0
    return int(pid.value)


def window_at_point(x: int, y: int, exclude_pid: int | None = None) -> int:
    """Root owner of the topmost *foreign* window under a physical point.

    The capture overlay covers the whole virtual desktop, so a plain
    ``WindowFromPoint`` would always return one of our own windows.  We therefore
    walk down the Z order until a window belonging to another process appears.
    """
    import os

    try:
        hwnd = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
        if not hwnd:
            return 0
        root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
        hwnd = int(root or hwnd)
        if exclude_pid is None:
            exclude_pid = os.getpid()
        guard = 0
        while hwnd and guard < 96:
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(wt.HWND(hwnd), ctypes.byref(pid))
            if pid.value != exclude_pid:
                info = _window_rect(hwnd)
                if info and not _is_cloaked(hwnd) and _is_pickable(hwnd, info, point=(x, y)):
                    return hwnd
            next_hwnd = user32.GetWindow(wt.HWND(hwnd), GW_HWNDNEXT)
            if not next_hwnd:
                break
            root = user32.GetAncestor(next_hwnd, 2)
            hwnd = int(root or next_hwnd)
            guard += 1
        # 兜底：桌面。桌面窗口带 WS_EX_TOOLWINDOW，会被上面的过滤排掉，但没有更合适
        # 的窗口时它正代表"整个屏幕"，比什么都不选（返回 0）好。
        return int(user32.GetDesktopWindow() or 0)
    except Exception:
        return 0


_IGNORED_TITLES = {"msctfime ui", "default ime", "ime", "program manager", "windows 输入体验",
                   "textinputhost", "microsoft text input application"}


def _window_title(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(wt.HWND(hwnd))
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(wt.HWND(hwnd), buf, length + 1)
    return buf.value.strip()


def _is_pickable(hwnd: int, rect: tuple[int, int, int, int], min_size: int = 48,
                 point: tuple[int, int] | None = None) -> bool:
    """Whether a window is a sensible thing to pick with the cursor.

    ``point`` (physical) makes it also require the point to be inside the window.
    Without that the Z-order walk returns whatever happens to be next, which is
    how an invisible QQ window 1000px away got picked for a point near the
    bottom-left corner.
    """
    left, top, width, height = rect
    if width < min_size or height < min_size:
        return False
    if not user32.IsWindowVisible(wt.HWND(hwnd)):
        return False
    if user32.IsIconic(wt.HWND(hwnd)):
        return False
    ex_style = user32.GetWindowLongW(wt.HWND(hwnd), GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    if ex_style & WS_EX_TRANSPARENT:
        return False          # 鼠标穿透的叠层（如 TranslucentTB）不是可选目标
    if point is not None:
        if not (left <= point[0] < left + width and top <= point[1] < top + height):
            return False
    title = _window_title(hwnd).lower()
    if title in _IGNORED_TITLES:
        return False
    return True


def window_info(hwnd: int) -> WindowInfo | None:
    if not hwnd:
        return None
    rect = _window_rect(hwnd)
    if not rect:
        return None
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    left, top, width, height = rect
    return WindowInfo(int(hwnd), buf.value.strip() or "窗口", left, top, width, height)


def cursor_position() -> tuple[int, int]:
    pt = wt.POINT()
    try:
        user32.GetCursorPos(ctypes.byref(pt))
    except Exception:
        return (0, 0)
    return (int(pt.x), int(pt.y))


def force_foreground(hwnd: int) -> bool:
    """Bring our window to the foreground and give it keyboard focus.

    A process that just received a global hotkey is allowed to take the
    foreground, which is what makes Esc work in the capture overlay even when
    another application was active.
    """
    if not hwnd:
        return False
    try:
        user32.ShowWindow(wt.HWND(hwnd), 5)  # SW_SHOW
        user32.BringWindowToTop(wt.HWND(hwnd))
        user32.SetForegroundWindow(wt.HWND(hwnd))
        user32.SetFocus(wt.HWND(hwnd))
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Global hotkeys
# --------------------------------------------------------------------------- #
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """'Win+Shift+R' -> (modifiers, virtual key)."""
    parts = [p.strip().lower() for p in spec.replace("-", "+").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    key: str | None = None
    for part in parts:
        if part in ("win", "windows", "super", "meta"):
            mods |= MOD_WIN
        elif part in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif part in ("shift",):
            mods |= MOD_SHIFT
        elif part in ("alt",):
            mods |= MOD_ALT
        else:
            key = part
    if not key:
        return None
    vk = _virtual_key(key)
    if vk is None:
        return None
    return (mods | MOD_NOREPEAT, vk)


_FUNCTION_KEYS = {f"f{i}": 0x6F + i for i in range(1, 25)}


def _virtual_key(name: str) -> int | None:
    if len(name) == 1:
        ch = name.upper()
        if "A" <= ch <= "Z" or "0" <= ch <= "9":
            return ord(ch)
    if name in _FUNCTION_KEYS:
        return _FUNCTION_KEYS[name]
    specials = {
        "printscreen": 0x2C, "prtsc": 0x2C, "insert": 0x2D, "delete": 0x2E,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "space": 0x20, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B,
        "tab": 0x09, "backspace": 0x08,
    }
    return specials.get(name)


class HotkeyFilter:
    """Registers global hotkeys and dispatches them into Qt.

    Implemented as a native event filter so no extra dependency is needed.
    """

    def __init__(self, dispatcher):
        import logging

        from PySide6.QtCore import QAbstractNativeEventFilter

        self._dispatcher = dispatcher
        self._registered: dict[int, str] = {}
        self._specs: dict[str, str] = {}
        self._next_id = 0xA000
        self._log = logging.getLogger("winsnip.hotkeys")
        owner = self  # the filter must not close over the *filter's* self

        class _Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):  # noqa: N802
                try:
                    msg = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
                    if msg.message == WM_HOTKEY:
                        name = owner._registered.get(int(msg.wParam))
                        if name:
                            owner._dispatcher(name)
                except Exception:
                    owner._log.exception("native event filter failed")
                return (False, 0)

        self._filter = _Filter()

    @property
    def filter(self):
        return self._filter

    def register(self, name: str, spec: str) -> bool:
        parsed = parse_hotkey(spec)
        if not parsed:
            self._log.warning("hotkey %s: cannot parse %r", name, spec)
            return False
        mods, vk = parsed
        self.unregister(name)
        hotkey_id = self._next_id
        self._next_id += 1
        if not user32.RegisterHotKey(None, hotkey_id, mods, vk):
            error = ctypes.get_last_error()
            self._log.warning("hotkey %s: RegisterHotKey(%s) failed (winerror=%s)",
                              name, spec, error)
            return False
        self._registered[hotkey_id] = name
        self._specs[name] = spec
        self._log.info("hotkey %s registered as %s (id=%#x)", name, spec, hotkey_id)
        return True

    def unregister(self, name: str) -> None:
        for hotkey_id, existing in list(self._registered.items()):
            if existing == name:
                try:
                    user32.UnregisterHotKey(None, hotkey_id)
                except Exception:
                    pass
                self._registered.pop(hotkey_id, None)
        self._specs.pop(name, None)

    def unregister_all(self) -> None:
        for name in list(self._registered.values()):
            self.unregister(name)


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wt.HWND), ("message", ctypes.c_uint), ("wParam", ctypes.c_uint64),
        ("lParam", ctypes.c_int64), ("time", ctypes.c_uint), ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]
