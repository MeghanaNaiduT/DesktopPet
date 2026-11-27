"""System-tray icon using only the Win32 API through ctypes (no extra packages, no network).
It runs in its own thread with its own hidden window and message loop, and talks to the UI through a queue."""
from __future__ import annotations

import queue
import sys
import threading

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                    ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                    ("dwInfoFlags", wintypes.DWORD), ("guidItem", ctypes.c_ubyte * 16), ("hBalloonIcon", wintypes.HICON)]

WM_USER, WM_NULL, WM_CLOSE, WM_DESTROY = 0x400, 0, 0x10, 0x2
WM_LBUTTONUP, WM_RBUTTONUP = 0x202, 0x205
WM_TRAY = WM_USER + 20
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0, 0x800, 8
TPM_RIGHTBUTTON, TPM_BOTTOMALIGN, TPM_RETURNCMD = 2, 0x20, 0x100
ID_OPEN, ID_PAUSE, ID_QUIT = 1, 3, 9
NAMES = {ID_OPEN: "open", ID_PAUSE: "pause", ID_QUIT: "quit"}


class Tray:
    """Events (strings 'open', 'pause', 'quit') arrive on `events`; poll it from the UI thread."""

    def __init__(self, icon_path: str, tooltip: str = "Desktop Pet"):
        self.events: "queue.Queue[str]" = queue.Queue()
        self.state = {"paused": False}
        self.ok = False
        self._icon_path = icon_path
        self._tip = tooltip
        self._hwnd = None
        self._ready = threading.Event()
        self._thread = None

    def start(self) -> bool:
        if not IS_WINDOWS:
            return False
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)
        return self.ok

    def stop(self) -> None:
        if IS_WINDOWS and self._hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            except Exception:
                pass

    # ------------------------------------------------------------------ thread
    def _run(self) -> None:
        try:
            u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
            u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            u32.DefWindowProcW.restype = LRESULT
            u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                            wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
            u32.CreateWindowExW.restype = wintypes.HWND
            u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            u32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u32.LoadImageW.restype = wintypes.HANDLE
            u32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            u32.CreatePopupMenu.restype = wintypes.HMENU
            u32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
            u32.DestroyMenu.argtypes = [wintypes.HMENU]
            u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            u32.SetForegroundWindow.argtypes = [wintypes.HWND]
            u32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            u32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            u32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            k32.GetModuleHandleW.restype = wintypes.HINSTANCE

            self._wndproc = WNDPROC(self._proc)                      # keep a reference alive
            hinst = k32.GetModuleHandleW(None)
            cls = WNDCLASSW()
            cls.lpfnWndProc = self._wndproc
            cls.hInstance = hinst
            cls.lpszClassName = "DesktopPetTrayWindow"
            u32.RegisterClassW(ctypes.byref(cls))
            self._hwnd = u32.CreateWindowExW(0, cls.lpszClassName, "Desktop Pet", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self._hwnd:
                raise OSError("could not create the tray window")
            self._taskbar_created = u32.RegisterWindowMessageW("TaskbarCreated")
            size = u32.GetSystemMetrics(49)                          # SM_CXSMICON
            self._icon = u32.LoadImageW(None, self._icon_path, 1, size, size, 0x10)   # IMAGE_ICON, LR_LOADFROMFILE
            self._add_icon()
            self.ok = True
            self._ready.set()

            msg = wintypes.MSG()
            while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                u32.TranslateMessage(ctypes.byref(msg))
                u32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self.ok = False
            self._ready.set()

    def _data(self) -> "NOTIFYICONDATAW":
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon
        nid.szTip = self._tip
        return nid

    def _add_icon(self) -> None:
        ctypes.windll.shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self._data()))

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    self.events.put("open")
                elif event == WM_RBUTTONUP:
                    self._show_menu(hwnd)
                return 0
            if msg == getattr(self, "_taskbar_created", -1):         # Explorer restarted: put the icon back
                self._add_icon()
                return 0
            if msg == WM_DESTROY:
                ctypes.windll.shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._data()))
                ctypes.windll.user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self, hwnd) -> None:
        u32 = ctypes.windll.user32
        menu = u32.CreatePopupMenu()
        u32.AppendMenuW(menu, MF_STRING, ID_OPEN, "Open Desktop Pet")
        u32.AppendMenuW(menu, MF_STRING, ID_PAUSE, "Resume reminders" if self.state.get("paused") else "Pause reminders")
        u32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u32.AppendMenuW(menu, MF_STRING, ID_QUIT, "Quit")
        point = wintypes.POINT()
        u32.GetCursorPos(ctypes.byref(point))
        u32.SetForegroundWindow(hwnd)                                # required so the menu closes when clicking away
        command = u32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN | TPM_RETURNCMD, point.x, point.y, 0, hwnd, None)
        u32.PostMessageW(hwnd, WM_NULL, 0, 0)
        u32.DestroyMenu(menu)
        if command in NAMES:
            self.events.put(NAMES[command])
