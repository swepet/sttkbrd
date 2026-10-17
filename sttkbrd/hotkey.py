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
    if ch:
        return ch.lower()
    vk = getattr(key, "vk", None)
    if vk is not None and 32 <= vk < 127:
        return chr(vk).lower()
    return None


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
        self._listener = keyboard.Listener(on_press=self._press, on_release=self._release)

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

    def _press(self, key):
        name = normalize(key)
        if not name:
            return
        with self._lock:
            self._down.add(name)
            fire = bool(self._combo) and not self._active and self._combo <= self._down
            if fire:
                self._active = True
        if fire:
            self._on_press()

    def _release(self, key):
        name = normalize(key)
        if not name:
            return
        with self._lock:
            self._down.discard(name)
            fire = self._active and name in self._combo
            if fire:
                self._active = False
        if fire:
            self._on_release()
