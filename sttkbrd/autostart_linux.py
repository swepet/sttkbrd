import os
import shutil
import subprocess

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


def menu_path():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "applications", "sttkbrd.desktop")


def _content(exec_line, autostart=True):
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=sttkbrd",
        "Comment=Speech to keyboard",
        "Exec=" + exec_line,
        "TryExec=" + LAUNCHER,  # desktops hide the entry if the program has been moved or deleted
        "Path=" + APP_DIR,
        "Icon=" + (ICON if os.path.isfile(ICON) else "audio-input-microphone"),
        "Terminal=false",
    ]
    if autostart:
        lines += [
            "X-GNOME-Autostart-enabled=true",
            "X-GNOME-Autostart-Delay=3",  # give the panel time to create the tray before the icon is added
        ]
    else:
        lines += ["Categories=Utility;Accessibility;", "Keywords=speech;dictation;voice;microphone;", "StartupNotify=false"]
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


# --- application menu entry (start the app without a terminal) -------------------------------------------------
# A plain freedesktop.org desktop entry in $XDG_DATA_HOME/applications: read by GNOME, KDE, Xfce, MATE, Cinnamon,
# LXQt and the others, so nothing here is specific to one desktop environment.
def _update_desktop_database(directory):
    """Best effort: some desktops cache the menu. Harmless if the tool is missing or fails."""
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, directory], capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass


def menu_entry_enabled():
    values = _read(menu_path())
    return values is not None and values.get("Hidden", "false").lower() != "true" \
        and values.get("NoDisplay", "false").lower() != "true"


def install_menu_entry():
    """Write ~/.local/share/applications/sttkbrd.desktop for this copy of the app. Returns its path."""
    exec_line = _exec_line()  # same checks as autostart: the launcher must exist at this exact path
    path = menu_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_content(exec_line, autostart=False))
    except OSError as ex:
        raise AutostartError("Could not write %s: %s" % (path, ex))
    _update_desktop_database(os.path.dirname(path))
    log.info("Menu entry installed: %s -> %s", path, exec_line)
    return path


def remove_menu_entry():
    try:
        os.remove(menu_path())
        _update_desktop_database(os.path.dirname(menu_path()))
        log.info("Menu entry removed")
    except FileNotFoundError:
        pass
    except OSError as ex:
        raise AutostartError("Could not remove %s: %s" % (menu_path(), ex))


def refresh_menu_if_stale():
    """Like refresh_if_stale(): if the project was moved, point an existing menu entry at the new location."""
    values = _read(menu_path())
    if values is None:
        return
    try:
        expected = _exec_line()
    except AutostartError as ex:
        log.warning("Menu entry cannot be verified: %s", ex)
        return
    if values.get("Exec") != expected or values.get("Path") != APP_DIR:
        log.info("Menu entry pointed at %r - updating to %r", values.get("Exec"), expected)
        install_menu_entry()
