import re

from . import keys

# Voice commands: when a whole utterance equals one of a command's phrases, the action runs instead of the
# text being typed. A command's phrase field may hold several phrases separated by commas: "enter, retur".
#   key  - press a key or key combination (value: "enter", "ctrl+a", ...)
#   text - type a fixed text (value; "\n" is a line break)
#   undo - erase what sttkbrd typed most recently, one utterance per use (value unused)
TYPES = ("key", "text", "undo")

DEFAULTS = [
    {"phrase": "enter, retur, ny rad, new line", "type": "key", "value": "enter"},
    {"phrase": "tab", "type": "key", "value": "tab"},
    {"phrase": "backspace", "type": "key", "value": "backspace"},
    {"phrase": "escape", "type": "key", "value": "esc"},
    {"phrase": "undo, ångra", "type": "undo", "value": ""},
]

# Earlier default lists. A saved list that is still exactly one of these was never customised and is upgraded.
OLD_DEFAULTS = [
    [
        {"phrase": "enter", "type": "key", "value": "enter"},
        {"phrase": "ny rad", "type": "key", "value": "enter"},
        {"phrase": "new line", "type": "key", "value": "enter"},
        {"phrase": "tab", "type": "key", "value": "tab"},
        {"phrase": "backspace", "type": "key", "value": "backspace"},
        {"phrase": "escape", "type": "key", "value": "esc"},
    ],
]


def normalize(text):
    """'Ny rad.' -> 'ny rad'. Speech-to-text adds capitals and punctuation that must not matter."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", (text or "").casefold()).split())


def phrases(command):
    """The normalized phrases of a command: 'enter, Retur' -> ['enter', 'retur']. Split before normalizing."""
    return [p for p in (normalize(part) for part in (command.get("phrase") or "").split(",")) if p]


def match(text, commands):
    heard = normalize(text)
    if not heard:
        return None
    for command in commands:
        if heard in phrases(command):
            return command
    return None


def needs_value(kind):
    return kind != "undo"


def value_error(kind, value):
    """Readable problem with an action, or None if it is usable."""
    if kind == "key":
        try:
            keys.parse_combo(value)
        except ValueError as ex:
            return str(ex)
    elif kind == "text" and not value:
        return "The text is empty"
    return None


def unescape(value):
    """Let a text action contain a line break written as \\n."""
    return value.replace("\\n", "\n")


def upgrade(saved):
    """Replace a never-customised older default list with the current defaults."""
    plain = [{"phrase": c.get("phrase"), "type": c.get("type"), "value": c.get("value")} for c in saved]
    return [dict(c) for c in DEFAULTS] if plain in OLD_DEFAULTS else saved
