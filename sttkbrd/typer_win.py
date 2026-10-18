import ctypes
import time
from ctypes import wintypes

from .keys import MODIFIER_KEYS, NAMED_KEYS, parse_combo

CHAR_DELAY = 0.002

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_VK_MODS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "super": 0x5B}
_VK_NAMED = {
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "insert": 0x2D,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
    "page_up": 0x21, "pageup": 0x21, "page_down": 0x22, "pagedown": 0x22,
}
_VK_NAMED.update({"f%d" % n: 0x6F + n for n in range(1, 13)})
_EXTENDED = {0x2E, 0x2D, 0x26, 0x28, 0x25, 0x27, 0x24, 0x23, 0x21, 0x22, 0x5B}
assert set(_VK_NAMED) == set(NAMED_KEYS) and set(_VK_MODS) == set(MODIFIER_KEYS)

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):  # only here so the union has the size Windows expects
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
_user32.VkKeyScanW.restype = ctypes.c_short
_user32.GetForegroundWindow.restype = wintypes.HWND


def _key(vk=0, scan=0, flags=0):
    i = _INPUT(type=INPUT_KEYBOARD)
    i.ki = _KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags)
    return i


def _send(*events):
    arr = (_INPUT * len(events))(*events)
    if _user32.SendInput(len(events), arr, ctypes.sizeof(_INPUT)) != len(events):
        raise OSError("SendInput was blocked (is the target window running as administrator?)")


def _vk_events(vk, up=False):
    flags = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    return _key(vk=vk, flags=flags)


class Typer:
    """Types text on Windows with SendInput. Characters go in as Unicode key events, so every character
    the target accepts can be typed regardless of the keyboard layout, and the clipboard is never touched."""

    def type(self, text):
        for ch in text.replace("\r\n", "\n"):
            if ch == "\n":
                self._tap_vk(_VK_NAMED["enter"])
            elif ch == "\t":
                self._tap_vk(_VK_NAMED["tab"])
            else:
                data = ch.encode("utf-16-le")  # characters outside the BMP are two surrogate units
                for i in range(0, len(data), 2):
                    unit = int.from_bytes(data[i:i + 2], "little")
                    _send(_key(scan=unit, flags=KEYEVENTF_UNICODE),
                          _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            time.sleep(CHAR_DELAY)

    def active_window(self):
        """Handle of the window that has focus, or None."""
        return _user32.GetForegroundWindow() or None

    def backspace(self, count):
        """Erase `count` characters before the cursor."""
        for _ in range(count):
            self._tap_vk(_VK_NAMED["backspace"])
            time.sleep(CHAR_DELAY)

    def press(self, combo):
        """Press a key combination such as 'enter', 'ctrl+a' or 'shift+tab' (raises ValueError if unusable)."""
        mods, key = parse_combo(combo)
        vks = [_VK_MODS[m] for m in mods]
        if key in _VK_NAMED:
            vk = _VK_NAMED[key]
        else:
            scan = _user32.VkKeyScanW(key)
            if scan == -1:
                raise ValueError("The key '%s' does not exist on the current keyboard layout" % key)
            vk = scan & 0xFF
            for bit, mod in ((1, 0x10), (2, 0x11), (4, 0x12)):  # Shift, Ctrl, Alt that the layout needs for it
                if scan >> 8 & bit and mod not in vks:
                    vks.append(mod)
        events = [_vk_events(m) for m in vks] + [_vk_events(vk), _vk_events(vk, up=True)] \
            + [_vk_events(m, up=True) for m in reversed(vks)]
        _send(*events)

    def _tap_vk(self, vk):
        _send(_vk_events(vk), _vk_events(vk, up=True))
