# Key names shared by voice commands and the typers. Values are X11 keysyms (the Windows typer maps by name).
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
