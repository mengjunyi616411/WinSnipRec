"""Global hotkey registration shared by the whole application."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QApplication

from .. import winapi

_filter: winapi.HotkeyFilter | None = None
_handlers: dict[str, Callable[[], None]] = {}
_failures: dict[str, str] = {}


def _ensure_filter() -> winapi.HotkeyFilter:
    global _filter
    if _filter is None:
        app = QApplication.instance()
        _filter = winapi.HotkeyFilter(_dispatch)
        if app is not None:
            app.installNativeEventFilter(_filter.filter)
    return _filter


def _dispatch(name: str) -> None:
    handler = _handlers.get(name)
    if handler is not None:
        try:
            handler()
        except Exception:
            pass


def register(name: str, spec: str, handler: Callable[[], None]) -> bool:
    """Register ``spec`` (e.g. 'Win+Shift+R'). Returns False when Windows already
    owns the combination, which is common because the real Snipping Tool binds
    Win+Shift+S and Win+Shift+R on Windows 11."""
    hotkey_filter = _ensure_filter()
    hotkey_filter.unregister(name)
    ok = hotkey_filter.register(name, spec)
    if ok:
        _handlers[name] = handler
        _failures.pop(name, None)
    else:
        _failures[name] = spec
    return ok


def unregister(name: str) -> None:
    if _filter is not None:
        _filter.unregister(name)
    _handlers.pop(name, None)


def registered(name: str) -> bool:
    return name in _handlers


def failures() -> dict[str, str]:
    return dict(_failures)


def unregister_all() -> None:
    if _filter is not None:
        _filter.unregister_all()
    _handlers.clear()
