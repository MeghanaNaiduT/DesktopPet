"""Small Windows helpers (all optional: every function degrades to a harmless no-op on other systems)."""
from __future__ import annotations

import io
import math
import os
import struct
import sys
import wave

try:
    import ctypes
    from ctypes import wintypes
except Exception:  # pragma: no cover
    ctypes = None

IS_WINDOWS = sys.platform == "win32"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DesktopPet"
APP_ID = "DesktopPet.App"
_mutex = None


def enable_dpi_awareness() -> None:
    """Crisp text on scaled displays."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_id() -> None:
    """Lets the taskbar show Desktop Pet's own icon instead of Python's."""
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass


def acquire_single_instance() -> bool:
    """True if this is the only copy running (named mutex; local to this PC, no files, no network)."""
    global _mutex
    if not IS_WINDOWS:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        _mutex = kernel32.CreateMutexW(None, False, "Local\\DesktopPet.SingleInstance.PyApp")
        return kernel32.GetLastError() != 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def message_box(title: str, text: str) -> None:
    if IS_WINDOWS:
        try:
            ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
            return
        except Exception:
            pass
    print(f"{title}: {text}")


def work_area(root_width: int, root_height: int):
    """(left, top, right, bottom) of the screen excluding the taskbar."""
    if IS_WINDOWS:
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:
            pass
    return 0, 0, root_width, max(0, root_height - 48)


def pythonw_command(script: str) -> str:
    if getattr(sys, "frozen", False):   # built into DesktopPet.exe with PyInstaller
        return f'"{sys.executable}" --minimized'
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        exe = exe[: -len("python.exe")] + "pythonw.exe"
    return f'"{exe}" "{os.path.abspath(script)}" --minimized'


def set_startup(enabled: bool, script: str):
    """Add/remove the per-user 'start with Windows' entry. Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "Start with Windows is only available on Windows."
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, pythonw_command(script))
            else:
                try:
                    winreg.DeleteValue(key, RUN_NAME)
                except FileNotFoundError:
                    pass
        return True, ""
    except Exception as ex:
        return False, f"Windows did not allow this ({ex.__class__.__name__}). You can start Desktop Pet by hand instead."


# ----------------------------------------------------------------------------- sound (synthesised, no files)

_wav_cache = {}


def _chime_wav(notes) -> bytes:
    rate = 22050
    total = max(s + d for _, s, d in notes) + 0.1
    count = int(total * rate)
    samples = [0.0] * count
    for freq, start, length in notes:
        first = int(start * rate)
        for i in range(first, min(count, first + int(length * rate))):
            t = (i - first) / rate
            env = min(1.0, t / 0.01) * math.exp(-3.5 * t / length)
            samples[i] += (math.sin(2 * math.pi * freq * t) + 0.25 * math.sin(4 * math.pi * freq * t)) * env
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s * 0.3)) * 32767)) for s in samples))
    return buf.getvalue()


def play_chime(kind: str = "reminder") -> None:
    """A soft two-note chime (reminder) or a rising arpeggio (finished). Silent if there is no audio."""
    if not IS_WINDOWS:
        return
    try:
        import winsound
        if kind not in _wav_cache:
            notes = ([(659.25, 0.0, 0.8), (783.99, 0.2, 1.0)] if kind == "reminder"
                     else [(523.25, 0.0, 0.6), (659.25, 0.16, 0.6), (783.99, 0.32, 1.1)])
            _wav_cache[kind] = _chime_wav(notes)
        winsound.PlaySound(_wav_cache[kind], winsound.SND_MEMORY | winsound.SND_ASYNC)
    except Exception:
        pass


def query_notification_state() -> int:
    """QUNS_* state: 2/3/4 = full-screen app, game or presentation; 5 = normal; 6 = Focus Assist. 5 if unknown."""
    if not IS_WINDOWS:
        return 5
    try:
        state = ctypes.c_int(5)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state)) == 0:
            return state.value
    except Exception:
        pass
    return 5


def is_fullscreen() -> bool:
    return query_notification_state() in (2, 3, 4)
