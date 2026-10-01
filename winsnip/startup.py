"""Run-at-logon registration.

Uses the per-user Run key (``HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run``)
which needs no administrator rights and is the same place most tray utilities
register themselves.  The stored value is a full command line, so it works both
for the packaged executable and for running from source.
"""

from __future__ import annotations

import logging
import sys
import winreg
from pathlib import Path
from .i18n import t as _t

__all__ = [
    "VALUE_NAME", "RUN_KEY_PATH", "startup_command", "registered_command",
    "is_enabled", "is_current", "enabled_and_current", "enable", "disable",
    "refresh_if_stale", "describe",
]

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "WinSnipRec"
STARTUP_ARGS = "--tray"

log = logging.getLogger("winsnip.startup")


# --------------------------------------------------------------------------- #
# Command construction
# --------------------------------------------------------------------------- #
def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def startup_command() -> str:
    """The command line that should be registered for this installation."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" {STARTUP_ARGS}'

    script = project_root() / "app.py"
    interpreter = Path(sys.executable)
    # Prefer pythonw.exe so logging in never flashes a console window.
    pythonw = interpreter.with_name("pythonw.exe")
    if pythonw.exists():
        interpreter = pythonw
    return f'"{interpreter.resolve()}" "{script}" {STARTUP_ARGS}'


def _executable_of(command: str) -> str:
    """First token of a command line (quoted or not)."""
    command = command.strip()
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end > 0 else command.strip('"')
    return command.split(" ", 1)[0]


# --------------------------------------------------------------------------- #
# Registry access
# --------------------------------------------------------------------------- #
def registered_command() -> str | None:
    """The currently registered command, or None when autostart is off."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return str(value) if value else None
    except FileNotFoundError:
        return None
    except OSError:
        return None


def is_enabled() -> bool:
    return bool(registered_command())


def is_current() -> bool:
    stored = registered_command()
    if not stored:
        return False
    return stored.strip().lower() == startup_command().strip().lower()


def enabled_and_current() -> bool:
    return is_current()


def _stale() -> bool:
    """Registered, but the executable it points at is gone."""
    stored = registered_command()
    if not stored:
        return False
    try:
        return not Path(_executable_of(stored)).exists()
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
def enable() -> tuple[bool, str]:
    """Register autostart. Returns (ok, message)."""
    command = startup_command()
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    except OSError as exc:
        log.warning("cannot enable autostart: %s", exc)
        return False, _t("写入注册表失败：{0}").format(exc)
    log.info("autostart enabled: %s", command)
    return True, command


def disable() -> tuple[bool, str]:
    """Remove the autostart entry. Returns (ok, message)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                return True, _t("原本就没有开启")
    except FileNotFoundError:
        return True, _t("原本就没有开启")
    except OSError as exc:
        log.warning("cannot disable autostart: %s", exc)
        return False, _t("删除注册表项失败：{0}").format(exc)
    log.info("autostart disabled")
    return True, _t("已关闭")


def refresh_if_stale() -> bool:
    """Repoint a stale entry (e.g. the program was moved) at this copy."""
    if not _stale():
        return False
    ok, message = enable()
    if ok:
        log.info("autostart entry was stale and has been repointed to %s", message)
    return ok


def _short(path: str, limit: int = 52) -> str:
    """Ellipsise the middle of a long path so the settings row stays readable."""
    if len(path) <= limit:
        return path
    head = max(8, limit // 2 - 2)
    tail = max(8, limit - head - 1)
    return f"{path[:head]}…{path[-tail:]}"


def describe() -> str:
    """One line for the settings UI."""
    stored = registered_command()
    if not stored:
        return _t("关闭时登录 Windows 不会自动运行")
    if _stale():
        return _t("已开启，但指向的程序已不存在：{0}").format(
            _short(_executable_of(stored)))
    if not is_current():
        return _t("已开启（指向另一份程序）：{0}").format(
            _short(_executable_of(stored)))
    return _t("已开启：登录后静默运行在通知区域 · {0}").format(
            _short(_executable_of(stored)))
