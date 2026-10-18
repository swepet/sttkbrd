import ctypes
import queue
import socket
import sys
import threading
import tkinter as tk

import pystray
from PIL import Image

from . import autostart, typer
from .core import Core, ICON_IDLE
from .log import log, setup as setup_log
from .settings_tk import SettingsDialog

PORT = 47653  # on localhost: whoever holds it is the running instance, and others ask it to show Settings


class App(Core):
    def __init__(self):
        self._calls = queue.SimpleQueue()
        self.root = tk.Tk()
        self.root.withdraw()
        super().__init__(typer.create())
        self.root.after(50, self._pump)
        self.root.after(300, self._timer)

    def _build_tray(self):
        self._images = {state: Image.open(path) if not path.startswith("audio-") else Image.new("RGBA", (64, 64))
                        for state, path in self.icons.items()}
        self._status_text = ""
        self._auto_checked = self.cfg["auto"]
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: self._status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Auto mode (listen continuously)", self._menu_auto, checked=lambda item: self._auto_checked),
            pystray.MenuItem("Settings…", lambda: self._post(self.open_settings)),
            pystray.MenuItem("Quit", lambda: self._post(self.quit)),
            # left click: pystray reports clicks, not press and release, so push-to-talk by mouse is not possible
            pystray.MenuItem("click", self._menu_click, default=True, visible=False),
        )
        self.icon = pystray.Icon("sttkbrd", self._images[ICON_IDLE], "sttkbrd", menu)
        self.icon.run_detached()

    def _hold_hint(self):
        return "Hold %s and speak (click the icon for Settings)" % self.cfg["hotkey"]

    def _show_state(self, icon, text):
        self._status_text = text
        self.icon.icon = self._images[icon]
        self.icon.title = ("sttkbrd – " + text)[:127]  # the Windows tooltip limit
        self.icon.update_menu()

    def _sync_auto_item(self, active):
        self._auto_checked = active

    def _menu_auto(self, icon, item):
        active = not self._auto_checked
        self._post(lambda: self._on_auto_toggled(active))

    def _menu_click(self):
        self._post(self._toggle_pause if self.cfg["auto"] else self.open_settings)

    def _post(self, fn):
        self._calls.put(fn)

    def _make_dialog(self, cfg, on_change, state, on_close):
        return SettingsDialog(self.root, cfg, on_change, state, on_close)

    def quit(self):
        self.root.quit()

    def _pump(self):
        """Run what other threads posted (tray menu, hotkey, workers) on the Tk thread."""
        try:
            while True:
                try:
                    fn = self._calls.get_nowait()
                except queue.Empty:
                    break
                try:
                    fn()
                except Exception:
                    log.exception("Error in a UI callback")
        finally:
            self.root.after(50, self._pump)

    def _timer(self):
        self._tick()
        self.root.after(300, self._timer)


def _single_instance(show_settings):
    """Hold a localhost port as the instance lock. If it is taken, ask the running instance to show Settings."""
    server = socket.socket()
    try:
        server.bind(("127.0.0.1", PORT))
    except OSError:
        log.info("sttkbrd is already running - asking it to show Settings")
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=3) as c:
                c.sendall(b"settings\n")
        except OSError:
            log.exception("Could not reach the running instance")
        sys.exit(0)
    server.listen(4)

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                conn.settimeout(1)
                try:
                    if conn.recv(16).startswith(b"settings"):
                        show_settings()
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True, name="instance").start()
    return server


def main():
    setup_log()
    try:  # sharp text on high-DPI screens instead of a blurry upscaled window
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    holder = {}
    server = _single_instance(lambda: holder["app"]._post(holder["app"].open_settings) if "app" in holder else None)  # noqa: F841
    autostart.refresh_if_stale()
    autostart.refresh_menu_if_stale()
    app = holder["app"] = App()
    if not app.cfg["api_key"]:
        app._post(app.open_settings)
    try:
        app.root.mainloop()
    finally:
        app.auto.stop()
        app.hotkey.stop()
        app.icon.stop()
