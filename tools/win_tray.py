from __future__ import annotations

import ctypes
import sys
import threading
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32


WM_USER = 0x0400
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002
WM_TRAY_CALLBACK = WM_USER + 0x100
TRAY_MSG_SHOW = 1001
TRAY_MSG_EXIT = 1002
TASKBAR_CREATED_NAME = "TaskbarCreated"

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
HWND_MESSAGE = -3

MF_STRING = 0x00000000
TPM_RIGHTBUTTON = 0x00000002
TPM_RETURNCMD = 0x00000100


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uTimeoutOrVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


def _configure_win32() -> None:
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    user32.GetMessageW.argtypes = [
        ctypes.POINTER(MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = ctypes.c_int

    user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t

    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostMessageW.restype = wintypes.BOOL

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE,
        wintypes.LPCWSTR,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.LoadImageW.restype = wintypes.HANDLE

    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL

    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT

    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    user32.CreatePopupMenu.restype = wintypes.HMENU

    user32.AppendMenuW.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_size_t,
        wintypes.LPCWSTR,
    ]
    user32.AppendMenuW.restype = wintypes.BOOL

    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = wintypes.UINT

    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    shell32.Shell_NotifyIconW.argtypes = [
        wintypes.DWORD,
        ctypes.POINTER(NOTIFYICONDATAW),
    ]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.HICON),
        ctypes.POINTER(wintypes.HICON),
        wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = wintypes.UINT


_configure_win32()


class WinTrayIcon:
    def __init__(
        self,
        icon_path: Path,
        *,
        on_show: Callable[[], None] | None = None,
        on_exit: Callable[[], None] | None = None,
        tk_root=None,
        tooltip: str = "AAA",
    ) -> None:
        self.icon_path = Path(icon_path)
        self.on_show = on_show
        self.on_exit = on_exit
        self.tk_root = tk_root
        self.tooltip = tooltip[:127]
        self._thread: threading.Thread | None = None
        self._hwnd: int | None = None
        self._hicon: int | None = None
        self._wndproc_ref = None
        self._taskbar_created: int | None = None
        self._running = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="aaa-tray", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        hwnd = self._hwnd
        if hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None

    def set_tooltip(self, text: str) -> None:
        self.tooltip = text[:127]
        if self._running and self._hwnd and self._hicon:
            self._notify(NIM_MODIFY, NIF_TIP)

    def _run(self) -> None:
        self._taskbar_created = ctypes.windll.user32.RegisterWindowMessageW(
            TASKBAR_CREATED_NAME
        )
        self._hwnd = self._create_window()
        self._hicon = self._load_icon()
        if not self._hicon:
            self._hicon = self._load_icon_from_exe()
        self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self._running = True

        msg = MSG()
        get_message = ctypes.windll.user32.GetMessageW
        translate = ctypes.windll.user32.TranslateMessage
        dispatch = ctypes.windll.user32.DispatchMessageW
        while self._running:
            result = get_message(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            translate(ctypes.byref(msg))
            dispatch(ctypes.byref(msg))

        self._notify(NIM_DELETE, 0)
        self._destroy_icon()
        if self._hwnd:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
        self._hwnd = None
        self._running = False

    def _create_window(self) -> int:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = "AAATrayWindowClass"

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self._taskbar_created:
                self._notify(NIM_ADD, NIF_MESSAGE | NIF_ICON | NIF_TIP)
                return 0
            if msg == WM_TRAY_CALLBACK:
                if lparam == WM_LBUTTONDBLCLK:
                    self._dispatch(self.on_show)
                elif lparam == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc_ref = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )(wnd_proc)

        wnd_class = WNDCLASSW()
        wnd_class.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        wnd_class.hInstance = hinstance
        wnd_class.lpszClassName = class_name
        if not user32.RegisterClassW(ctypes.byref(wnd_class)):
            error = ctypes.get_last_error()
            if error != 1410:  # class already exists
                raise OSError(f"RegisterClassW failed: {error}")

        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            "AAA Tray",
            0,
            0,
            0,
            0,
            0,
            wintypes.HWND(HWND_MESSAGE),
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
        return hwnd

    def _load_icon(self) -> int:
        if not self.icon_path.exists():
            return 0
        handle = ctypes.windll.user32.LoadImageW(
            None,
            str(self.icon_path),
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        return int(handle or 0)

    def _load_icon_from_exe(self) -> int:
        if not getattr(sys, "frozen", False):
            return 0
        try:
            small = wintypes.HICON()
            big = wintypes.HICON()
            count = shell32.ExtractIconExW(
                str(sys.executable), 0, ctypes.byref(big), ctypes.byref(small), 1
            )
            if count < 1:
                return 0
            if big.value:
                return int(big.value)
            return int(small.value or 0)
        except Exception:
            return 0

    def _notify(self, action: int, flags: int) -> None:
        data = NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        data.hWnd = self._hwnd
        data.uID = 1
        data.uFlags = flags
        data.uCallbackMessage = WM_TRAY_CALLBACK
        data.hIcon = self._hicon or 0
        data.szTip = self.tooltip
        ctypes.windll.shell32.Shell_NotifyIconW(action, ctypes.byref(data))

    def _show_menu(self) -> None:
        user32 = ctypes.windll.user32
        hwnd = self._hwnd
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        user32.AppendMenuW(menu, MF_STRING, TRAY_MSG_SHOW, "显示主窗口")
        user32.AppendMenuW(menu, MF_STRING, TRAY_MSG_EXIT, "退出程序")
        point = POINT()
        user32.GetCursorPos(ctypes.byref(point))
        user32.SetForegroundWindow(hwnd)
        command = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, point.x, point.y, 0, hwnd, None
        )
        user32.DestroyMenu(menu)
        if command == TRAY_MSG_SHOW:
            self._dispatch(self.on_show)
        elif command == TRAY_MSG_EXIT:
            self._dispatch(self.on_exit)

    def _dispatch(self, callback: Callable[[], None] | None) -> None:
        if callback is None:
            return
        if self.tk_root is not None:
            self.tk_root.after(0, callback)
        else:
            callback()

    def _destroy_icon(self) -> None:
        if self._hicon:
            ctypes.windll.user32.DestroyIcon(self._hicon)
            self._hicon = None
