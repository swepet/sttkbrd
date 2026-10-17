import time
import unicodedata

from Xlib import X, XK, display
from Xlib.ext import xtest

from .log import log

CHAR_DELAY = 0.003
PASTE_SETTLE = 0.35  # time the target app gets to read the clipboard before it is restored
_SPECIAL = {"\n": 0xFF0D, "\t": 0xFF09}
_TERMINALS = ("terminal", "xterm", "konsole", "alacritty", "kitty", "tilix", "terminator", "wezterm",
              "urxvt", "rxvt", "foot", "tabby", "guake", "yakuake", "st-256color", "qterminal", "lxterminal")


# dead keys: standalone characters = dead key + space, and combining characters (é = ´ + e)
_DEAD_SPACING = {"~": 0xFE53, "^": 0xFE52, "`": 0xFE50, "´": 0xFE51, "¨": 0xFE57}
_DEAD_COMBINING = {"\u0301": 0xFE51, "\u0300": 0xFE50, "\u0302": 0xFE52, "\u0303": 0xFE53, "\u0308": 0xFE57,
                   "\u030a": 0xFE58}


# Named keys for key commands (same naming style as the hotkey setting)
NAMED_KEYS = {
    "enter": 0xFF0D, "return": 0xFF0D, "tab": 0xFF09, "backspace": 0xFF08, "delete": 0xFFFF, "del": 0xFFFF,
    "esc": 0xFF1B, "escape": 0xFF1B, "space": 0x20, "insert": 0xFF63,
    "up": 0xFF52, "down": 0xFF54, "left": 0xFF51, "right": 0xFF53, "home": 0xFF50, "end": 0xFF57,
    "page_up": 0xFF55, "pageup": 0xFF55, "page_down": 0xFF56, "pagedown": 0xFF56,
}
NAMED_KEYS.update({"f%d" % n: 0xFFBD + n for n in range(1, 13)})
MODIFIER_KEYS = {"ctrl": 0xFFE3, "control": 0xFFE3, "shift": 0xFFE1, "alt": 0xFFE9, "super": 0xFFEB}


def parse_combo(combo):
    """'ctrl+shift+a' -> (['ctrl', 'shift'], 'a'). Raises ValueError with a readable message."""
    parts = [p.strip().lower() for p in (combo or "").split("+") if p.strip()]
    if not parts:
        raise ValueError("Empty key combination")
    *mods, key = parts
    for m in mods:
        if m not in MODIFIER_KEYS:
            raise ValueError("Unknown modifier '%s' (use ctrl, shift, alt or super)" % m)
    if key not in NAMED_KEYS and len(key) != 1:
        raise ValueError("Unknown key '%s'" % key)
    return mods, key


def _keysyms(ch):
    """Possible keysyms for the character: Latin-1, legacy direct keysym (e.g. € = 0x20ac) and the Unicode form."""
    if ch in _SPECIAL:
        return (_SPECIAL[ch],)
    if ord(ch) < 256:
        return (ord(ch),)
    return (ord(ch), 0x1000000 + ord(ch))


def _lookup(ch, table):
    for ks in _keysyms(ch):
        if ks in table:
            return table[ks]
    return None


class Typer:
    """Types text through X11 (XTest) with real key presses, over a single connection.

    The keymap is never modified. Characters the active layout can type (including Shift and AltGr) are
    typed as keys. If the text contains something the layout cannot type, the whole text is pasted via
    the clipboard (Ctrl+V, or Ctrl+Shift+V in terminals) and the clipboard is restored afterwards.
    """

    def __init__(self, clipboard):
        self._clip = clipboard
        self._dpy = display.Display()
        info = self._dpy.display.info
        self._lo, self._hi = info.min_keycode, info.max_keycode
        self._shift = self._dpy.keysym_to_keycode(XK.XK_Shift_L)
        self._ctrl = self._dpy.keysym_to_keycode(XK.XK_Control_L)
        self._altgr = self._dpy.keysym_to_keycode(0xFE03)  # ISO_Level3_Shift

    def type(self, text):
        table = self._table()
        plans = {c: self._plan(c, table) for c in set(text)}
        missing = sorted(c for c, plan in plans.items() if plan is None)
        if missing:
            log.info("The layout cannot type %s - pasting via the clipboard", missing)
            self._paste(text)
            return
        for ch in text:
            for entry in plans[ch]:
                self._tap(*entry)
                time.sleep(CHAR_DELAY)

    @staticmethod
    def _plan(ch, table):
        """List of (keycode, level) that types ch, or None if the layout cannot."""
        direct = _lookup(ch, table)
        if direct:
            return [direct]
        space = table.get(0x20)
        if ch in _DEAD_SPACING and _DEAD_SPACING[ch] in table and space:
            return [table[_DEAD_SPACING[ch]], space]
        parts = unicodedata.normalize("NFD", ch)
        if len(parts) == 2 and parts[1] in _DEAD_COMBINING and _DEAD_COMBINING[parts[1]] in table \
                and _lookup(parts[0], table):
            return [table[_DEAD_COMBINING[parts[1]]], _lookup(parts[0], table)]
        return None

    def _table(self):
        """keysym -> (keycode, level) for the active group. Level: 0 plain, 1 Shift, 2 AltGr, 3 Shift+AltGr."""
        group = (self._dpy.screen().root.query_pointer().mask >> 13) & 3
        raw = self._dpy.get_keyboard_mapping(self._lo, self._hi - self._lo + 1)
        cols = (2 * group, 2 * group + 1, 4 + 2 * group, 5 + 2 * group)
        table = {}
        for level in (3, 2, 1, 0):  # lowest level wins
            col = cols[level]
            for i, syms in enumerate(raw):
                if col < len(syms) and syms[col]:
                    table[syms[col]] = (self._lo + i, level)
        return table

    def active_window(self):
        """Id of the window that has focus (EWMH _NET_ACTIVE_WINDOW, else the X input focus), or None."""
        try:
            root = self._dpy.screen().root
            prop = root.get_full_property(self._dpy.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType)
            if prop is not None and len(prop.value) and prop.value[0]:
                return int(prop.value[0])
            win = self._dpy.get_input_focus().focus
            if isinstance(win, int):  # None / PointerRoot
                return None
            while win.query_tree().parent.id != root.id:
                win = win.query_tree().parent
            return win.id
        except Exception:
            log.exception("Could not read the active window")
            return None

    def backspace(self, count):
        """Erase `count` characters before the cursor."""
        code = self._dpy.keysym_to_keycode(NAMED_KEYS["backspace"])
        for _ in range(count):
            self._press([], code)
            time.sleep(CHAR_DELAY)

    def press(self, combo):
        """Press a key combination such as 'enter', 'ctrl+a' or 'shift+tab' (raises ValueError if unusable)."""
        mods, key = parse_combo(combo)
        code, level = None, 0
        if key in NAMED_KEYS:
            code = self._dpy.keysym_to_keycode(NAMED_KEYS[key])
        else:
            entry = _lookup(key, self._table())
            if entry:
                code, level = entry
        if not code:
            raise ValueError("The key '%s' does not exist on the current keyboard layout" % key)
        codes = [self._dpy.keysym_to_keycode(MODIFIER_KEYS[m]) for m in mods]
        if level in (1, 3) and self._shift not in codes:
            codes.append(self._shift)
        if level in (2, 3):
            codes.append(self._altgr)
        self._press(codes, code)

    def _tap(self, code, level):
        mods = []
        if level in (1, 3):
            mods.append(self._shift)
        if level in (2, 3):
            mods.append(self._altgr)
        self._press(mods, code)

    def _press(self, mods, code):
        for m in mods:
            xtest.fake_input(self._dpy, X.KeyPress, m)
        xtest.fake_input(self._dpy, X.KeyPress, code)
        xtest.fake_input(self._dpy, X.KeyRelease, code)
        for m in reversed(mods):
            xtest.fake_input(self._dpy, X.KeyRelease, m)
        self._dpy.sync()

    def _paste(self, text):
        old = self._clip.swap_in(text)
        try:
            v = self._dpy.keysym_to_keycode(XK.XK_v)
            self._press([self._ctrl, self._shift] if self._focus_is_terminal() else [self._ctrl], v)
            time.sleep(PASTE_SETTLE)
        finally:
            self._clip.restore(old)

    def _focus_is_terminal(self):
        try:
            win = self._dpy.get_input_focus().focus
            while win and not isinstance(win, int):
                cls = win.get_wm_class()
                if cls:
                    names = " ".join(cls).lower()
                    return any(t in names for t in _TERMINALS)
                win = win.query_tree().parent
        except Exception:
            log.exception("Could not read the focused window")
        return False
