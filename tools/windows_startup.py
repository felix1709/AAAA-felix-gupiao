"""Windows current-user startup registration helpers.

This module only manages the ``HKEY_CURRENT_USER`` Run key, which works for
both normal and administrator Windows accounts without requiring elevation.
On non-Windows platforms every function is a no-op or returns ``False``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # pragma: no cover - non-Windows platforms
    winreg = None  # type: ignore[assignment]


STARTUP_VALUE_NAME = "AAAStockBriefingManager"
RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_windows() -> bool:
    """Return True when the application is running on Windows."""
    return os.name == "nt"


def _manager_script_path() -> Path:
    return Path(__file__).resolve().with_name("tradingagents_service_manager.py")


def startup_command() -> str:
    """Build the command line used by the Windows startup entry.

    Packaged builds launch ``AAA.exe --autostart``. Source checkouts launch the
    manager script with ``--autostart`` so the feature can still be exercised
    during development.
    """
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --autostart'
    return f'"{sys.executable}" "{_manager_script_path()}" --autostart'


def is_enabled_for_current_user() -> bool:
    """Return True when the current user has our startup Run value."""
    if not is_windows() or winreg is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_READ,
        ) as key:
            value, _kind = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return bool(value)


def set_enabled(enabled: bool) -> None:
    """Add or remove the current-user Windows startup entry."""
    if not is_windows() or winreg is None:
        return

    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            winreg.SetValueEx(
                key,
                STARTUP_VALUE_NAME,
                0,
                winreg.REG_SZ,
                startup_command(),
            )
        return

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            RUN_KEY_PATH,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, STARTUP_VALUE_NAME)
    except FileNotFoundError:
        return
