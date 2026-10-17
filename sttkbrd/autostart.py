import os

from .log import log

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # where this copy of sttkbrd lives
LAUNCHER = os.path.join(APP_DIR, "sttkbrd.sh")
ICON = os.path.join(APP_DIR, "art", "icon.png")
_UNSAFE = set('"`$\\\n')  # would need desktop-entry escaping; refuse instead of writing a broken Exec line


class AutostartError(Exception):
    pass


def desktop_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", "sttkbrd.desktop")


def _exec_line():
    if not (os.path.isfile(LAUNCHER) and os.access(LAUNCHER, os.X_OK)):
        raise AutostartError("Launcher not found or not executable: %s" % LAUNCHER)
    if _UNSAFE & set(LAUNCHER):
        raise AutostartError("Unsupported character in the install path: %s" % LAUNCHER)
    return '"%s"' % LAUNCHER if " " in LAUNCHER else LAUNCHER


def _read(path):
    values = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.rstrip("\n").partition("=")
                    values[key.strip()] = value.strip()
    except OSError:
        return None
    return values


def _content(exec_line):
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=sttkbrd",
        "Comment=Speech to keyboard",
        "Exec=" + exec_line,
        "Path=" + APP_DIR,
        "Icon=" + (ICON if os.path.isfile(ICON) else "audio-input-microphone"),
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
        "X-GNOME-Autostart-Delay=3",  # give the panel time to create the tray before the icon is added
    ]
    return "\n".join(lines) + "\n"


def is_enabled():
    values = _read(desktop_path())
    if values is None:
        return False
    return values.get("Hidden", "false").lower() != "true" \
        and values.get("X-GNOME-Autostart-enabled", "true").lower() != "false"


def enable():
    """Write the autostart entry pointing at this copy of the app. Raises AutostartError."""
    exec_line = _exec_line()  # validates that the launcher really exists before anything is created
    path = desktop_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_content(exec_line))
    except OSError as ex:
        raise AutostartError("Could not write %s: %s" % (path, ex))
    log.info("Autostart enabled: %s -> %s", path, exec_line)


def disable():
    try:
        os.remove(desktop_path())
        log.info("Autostart disabled")
    except FileNotFoundError:
        pass
    except OSError as ex:
        raise AutostartError("Could not remove %s: %s" % (desktop_path(), ex))


def refresh_if_stale():
    """If autostart is on but points somewhere else (the project was moved), rewrite it to this location."""
    values = _read(desktop_path())
    if values is None or not is_enabled():
        return
    try:
        expected = _exec_line()
    except AutostartError as ex:
        log.warning("Autostart entry cannot be verified: %s", ex)
        return
    if values.get("Exec") != expected or values.get("Path") != APP_DIR:
        log.info("Autostart entry pointed at %r - updating to %r", values.get("Exec"), expected)
        enable()
