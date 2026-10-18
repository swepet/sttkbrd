import fcntl
import os
import signal
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import GLib, Gtk, XApp

from . import autostart, typer
from .core import Core, ICON_IDLE
from .log import log, setup as setup_log
from .settings_dialog import SettingsDialog


class App(Core):
    def __init__(self):
        self._syncing_auto = False
        super().__init__(typer.create())
        GLib.timeout_add(300, self._tick)  # keeps the icon honest even if an event was missed

    def _build_tray(self):
        self.icon = XApp.StatusIcon()
        self.icon.set_name("sttkbrd")
        self.icon.set_icon_name(self.icons[ICON_IDLE])
        # Left button on the tray icon does what the hotkey does: toggles listening in auto mode, push-to-talk
        # (hold) otherwise. Settings are reached from the right-click menu. "activate" is ignored on purpose.
        self.icon.connect("button-press-event", self._on_icon_press)
        self.icon.connect("button-release-event", self._on_icon_release)
        self.icon.set_secondary_menu(self._build_menu())

    def _hold_hint(self):
        return "Hold %s (or the left mouse button on the icon) and speak" % self.cfg["hotkey"]

    def _show_state(self, icon, text):
        self.icon.set_icon_name(self.icons[icon])
        self.icon.set_tooltip_text("sttkbrd – " + text)
        self._status_item.set_label(text)

    def _sync_auto_item(self, active):
        self._syncing_auto = True
        self._auto_item.set_active(active)
        self._syncing_auto = False

    def _post(self, fn):
        GLib.idle_add(lambda: (fn(), False)[1])

    def _make_dialog(self, cfg, on_change, state, on_close):
        dialog = SettingsDialog(cfg, on_change, state)
        dialog.connect("destroy", lambda *a: on_close())
        return dialog

    def quit(self):
        Gtk.main_quit()

    def _on_icon_press(self, _icon, _x, _y, button, _time, _position):
        if button == 1:  # left button only; right button opens the menu by itself
            self._on_press()

    def _on_icon_release(self, _icon, _x, _y, button, _time, _position):
        if button == 1:
            self._on_release()

    def _build_menu(self):
        menu = Gtk.Menu()
        self._status_item = Gtk.MenuItem(label="")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)
        menu.append(Gtk.SeparatorMenuItem())
        self._auto_item = Gtk.CheckMenuItem(label="Auto mode (listen continuously)")
        self._auto_item.set_active(self.cfg["auto"])
        self._auto_item.connect("toggled", lambda item: self._syncing_auto or self._on_auto_toggled(item.get_active()))
        menu.append(self._auto_item)
        settings = Gtk.MenuItem(label="Settings…")
        settings.connect("activate", lambda *a: self.open_settings())
        menu.append(settings)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *a: self.quit())
        menu.append(quit_item)
        menu.show_all()
        return menu


def _single_instance():
    """Take the instance lock. If another instance runs, ask it to show its Settings window and exit.

    The running instance writes its pid into the lock file. An older instance that does not (empty file) is left
    alone: it has no signal handler, so signalling it would just kill it.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(runtime, "sttkbrd.lock")
    lock = open(path, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.seek(0)
        pid = lock.read().strip()
        log.info("sttkbrd is already running (pid %s) - asking it to show Settings", pid or "unknown")
        if pid.isdigit():
            try:
                os.kill(int(pid), signal.SIGUSR1)
            except OSError:
                log.exception("Could not signal the running instance")
        sys.exit(0)
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    return lock


def main():
    setup_log()
    lock = _single_instance()  # noqa: F841 (must live as long as the process)
    autostart.refresh_if_stale()
    autostart.refresh_menu_if_stale()
    app = App()
    # a second launch (e.g. clicking the menu entry again) opens Settings here; SIGTERM/SIGINT quit cleanly
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, lambda: app.open_settings() or True)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: Gtk.main_quit() or False)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: Gtk.main_quit() or False)
    if not app.cfg["api_key"]:
        GLib.idle_add(app.open_settings)
    Gtk.main()
    app.auto.stop()
    app.hotkey.stop()
