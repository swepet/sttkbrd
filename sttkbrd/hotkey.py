import sys
import threading

from pynput import keyboard

_MODS = {
    "ctrl": {"ctrl", "ctrl_l", "ctrl_r"},
    "shift": {"shift", "shift_l", "shift_r"},
    "alt": {"alt", "alt_l", "alt_r", "alt_gr"},
    "super": {"cmd", "cmd_l", "cmd_r"},
}
_CANON = {n: m for m, names in _MODS.items() for n in names}


def normalize(key):
    """pynput key -> canonical name ('ctrl', 'space', 'a', 'f5')."""
    if isinstance(key, keyboard.Key):
        return _CANON.get(key.name, key.name)
    ch = getattr(key, "char", None)
    if ch and ch.isprintable():
        return ch.lower()
    vk = getattr(key, "vk", None)
    if vk is not None and 32 <= vk < 127:
        return chr(vk).lower()
    return None


_WM_KEYDOWN, _WM_KEYUP, _WM_SYSKEYDOWN, _WM_SYSKEYUP = 0x100, 0x101, 0x104, 0x105
_LLKHF_INJECTED = 0x10


def _vk_names():
    """Windows virtual-key code -> canonical name, for the keys pynput knows by name."""
    names = {}
    for key in keyboard.Key:
        vk = getattr(key.value, "vk", None)
        if vk is not None:
            names.setdefault(vk, _CANON.get(key.name, key.name))
    return names


def parse(combo):
    return {p.strip().lower() for p in combo.split("+") if p.strip()}


class HotkeyListener:
    """Push-to-talk: on_press when the whole combination is held, on_release when any part is released."""

    def __init__(self, combo, on_press, on_release):
        self._combo = parse(combo)
        self._on_press, self._on_release = on_press, on_release
        self._down = set()
        self._active = False
        self._lock = threading.Lock()
        self._swallowed = set()  # Windows: keys whose press was kept from the focused application
        self._vk_names = _vk_names() if sys.platform == "win32" else {}
        extra = {"win32_event_filter": self._filter} if sys.platform == "win32" else {}
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release, **extra)

    @property
    def active(self):
        return self._active

    def set_combo(self, combo):
        with self._lock:
            self._combo = parse(combo)

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()

    def modifiers_down(self):
        with self._lock:
            return bool(self._down & set(_MODS))

    def _filter(self, msg, data):
        """Windows only: the last key of the combination (Space in Ctrl+Shift+Space) is not passed on to the
        focused application, which would otherwise act on it (open menus, insert a space ...). The modifiers
        still go through. A swallowed key never reaches on_press/on_release, so they are driven from here."""
        if msg not in (_WM_KEYDOWN, _WM_KEYUP, _WM_SYSKEYDOWN, _WM_SYSKEYUP) or data.flags & _LLKHF_INJECTED:
            return True
        vk = data.vkCode
        name = self._vk_names.get(vk) or (chr(vk).lower() if 0x30 <= vk <= 0x5A else None)
        if not name:
            return True
        if msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
            with self._lock:
                take = vk in self._swallowed or (name in self._combo and name not in _MODS
                                                 and (self._combo - {name}) <= self._down)
                if take:
                    self._swallowed.add(vk)
            if not take:
                return True
            self._press_name(name)
        else:
            with self._lock:
                take = vk in self._swallowed
                self._swallowed.discard(vk)
            if not take:
                return True
            self._release_name(name)
        self._listener.suppress_event()

    def _press(self, key):
        name = normalize(key)
        if name:
            self._press_name(name)

    def _release(self, key):
        name = normalize(key)
        if name:
            self._release_name(name)

    def _press_name(self, name):
        with self._lock:
            self._down.add(name)
            fire = bool(self._combo) and not self._active and self._combo <= self._down
            if fire:
                self._active = True
        if fire:
            self._on_press()

    def _release_name(self, name):
        with self._lock:
            self._down.discard(name)
            fire = self._active and name in self._combo
            if fire:
                self._active = False
        if fire:
            self._on_release()
