import ctypes
from pathlib import Path

import tools.win_tray as win_tray


def test_tray_menu_constants_are_distinct():
    assert win_tray.TRAY_MSG_SHOW == 1001
    assert win_tray.TRAY_MSG_EXIT == 1002
    assert win_tray.TRAY_MSG_SHOW != win_tray.TRAY_MSG_EXIT


def test_tray_tooltip_is_truncated_to_system_limit():
    tray = win_tray.WinTrayIcon(Path("red_bull.ico"), tooltip="A" * 300)

    assert len(tray.tooltip) == 127
    assert tray.tooltip == "A" * 127


def test_tray_icon_uses_single_notification_id():
    assert win_tray.WM_TRAY_CALLBACK == win_tray.WM_USER + 0x100


def test_win32_window_handles_use_pointer_sized_types():
    from ctypes import wintypes

    assert win_tray.user32.CreateWindowExW.restype == wintypes.HWND
    assert win_tray.user32.RegisterWindowMessageW.restype == wintypes.UINT
    assert win_tray.shell32.Shell_NotifyIconW.argtypes[-1] == ctypes.POINTER(
        win_tray.NOTIFYICONDATAW
    )
