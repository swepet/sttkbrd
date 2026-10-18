import os
import subprocess
import sys
import winreg

from PIL import Image

from . import icons, paths
from .log import log

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FROZEN = bool(getattr(sys, "frozen", False))  # built into a single exe with PyInstaller
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "sttkbrd"
MENU_LINK = os.path.join(os.environ.get("APPDATA") or "", "Microsoft", "Windows", "Start Menu", "Programs",
                         "sttkbrd.lnk")
_MENU_TARGET = os.path.join(paths.cache_dir(), "menu-target.txt")  # what the shortcut was last written for


class AutostartError(Exception):
    pass


def _launch():
    """(program, arguments, working directory) that starts this copy of the app without a console window."""
    if FROZEN:
        return sys.executable, "", os.path.dirname(sys.executable)
    script = os.path.join(APP_DIR, "sttkbrd.pyw")
    if not os.path.isfile(script):
        raise AutostartError("Launcher not found: %s" % script)
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return (pythonw if os.path.isfile(pythonw) else sys.executable), '"%s"' % script, APP_DIR


def _command():
    program, args, _ = _launch()
    return ('"%s" %s' % (program, args)).strip()


def _run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_NAME)[0]
    except OSError:
        return None


def is_enabled():
    return _run_value() is not None


def enable():
    command = _command()
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, command)
    except OSError as ex:
        raise AutostartError("Could not write the Run key: %s" % ex)
    log.info("Autostart enabled: %s", command)


def disable():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, RUN_NAME)
        log.info("Autostart disabled")
    except FileNotFoundError:
        pass
    except OSError as ex:
        raise AutostartError("Could not remove the Run key value: %s" % ex)


def refresh_if_stale():
    """If autostart is on but points somewhere else (the exe or project was moved), rewrite it."""
    current = _run_value()
    if current is None:
        return
    try:
        expected = _command()
    except AutostartError as ex:
        log.warning("Autostart entry cannot be verified: %s", ex)
        return
    if current != expected:
        log.info("Autostart entry pointed at %r - updating to %r", current, expected)
        enable()


# --- Start menu shortcut (start the app without a terminal) ------------------------------------------------
def menu_entry_enabled():
    return os.path.isfile(MENU_LINK)


def _icon_file():
    """A .ico for the shortcut, built from the app icon (shortcuts cannot use a PNG)."""
    path = os.path.join(paths.cache_dir(), "sttkbrd.ico")
    if not os.path.exists(path) or os.path.getmtime(path) < os.path.getmtime(icons.SOURCE):
        os.makedirs(paths.cache_dir(), exist_ok=True)
        img = icons._transparent_corners(Image.open(icons.SOURCE).resize((256, 256), Image.LANCZOS))
        img.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    return path


def install_menu_entry():
    """Write the Start menu shortcut for this copy of the app. Returns its path."""
    program, args, workdir = _launch()
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:STT_LINK);"
        "$s.TargetPath = $env:STT_PROGRAM; $s.Arguments = $env:STT_ARGS; $s.WorkingDirectory = $env:STT_DIR;"
        "$s.IconLocation = $env:STT_ICON; $s.Description = 'Speech to keyboard'; $s.Save()"
    )
    try:
        icon = _icon_file()
        os.makedirs(os.path.dirname(MENU_LINK), exist_ok=True)
        env = dict(os.environ, STT_LINK=MENU_LINK, STT_PROGRAM=program, STT_ARGS=args, STT_DIR=workdir,
                   STT_ICON=icon)
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env,
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as ex:
        raise AutostartError("Could not create %s: %s" % (MENU_LINK, ex))
    if result.returncode != 0:
        raise AutostartError("Could not create %s: %s" % (MENU_LINK, result.stderr.strip()[:200]))
    with open(_MENU_TARGET, "w", encoding="utf-8") as f:
        f.write(_command())
    log.info("Menu entry installed: %s", MENU_LINK)
    return MENU_LINK


def remove_menu_entry():
    try:
        os.remove(MENU_LINK)
        log.info("Menu entry removed")
    except FileNotFoundError:
        pass
    except OSError as ex:
        raise AutostartError("Could not remove %s: %s" % (MENU_LINK, ex))


def refresh_menu_if_stale():
    """If the exe or project was moved, point an existing Start menu shortcut at the new location."""
    if not menu_entry_enabled():
        return
    try:
        expected = _command()
        with open(_MENU_TARGET, encoding="utf-8") as f:
            current = f.read()
    except (AutostartError, OSError):
        current, expected = None, None
    if current != expected or expected is None:
        try:
            install_menu_entry()
        except AutostartError as ex:
            log.warning("Menu entry cannot be updated: %s", ex)
