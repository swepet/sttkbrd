import fcntl
import os
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("XApp", "1.0")
from gi.repository import GLib, Gtk, XApp

from . import autostart, commands, config, icons, sounds, stt
from .clipboard import Clipboard
from .hotkey import HotkeyListener
from .log import log, setup as setup_log
from .recorder import Recorder
from .settings_dialog import SettingsDialog
from .typed_history import TypedHistory
from .typer import Typer
from .vad import AutoListener

ICON_IDLE, ICON_AUTO, ICON_REC, ICON_BUSY, ICON_ERROR = "idle", "auto", "rec", "busy", "error"
MIN_SECONDS = 0.4


class App:
    def __init__(self):
        self.cfg = config.load()
        self.recorder = Recorder()
        self.typer = Typer(Clipboard())
        self._dialog = None
        self._state = ICON_IDLE
        self._pipeline = threading.Lock()  # keeps typed text in speaking order
        self.history = TypedHistory()  # what was typed, for the voice command 'undo'
        self._syncing_auto = False
        # auto mode only: the hotkey toggles listening off/on. Starts paused, so nothing listens until asked.
        self._paused = self.cfg["auto"]
        self._ptt = False  # a push-to-talk recording is in progress
        self._busy = 0  # utterances being transcribed or typed
        self._busy_lock = threading.Lock()
        self._error = ""  # last error, shown until the next activity starts
        self._shown = None  # (icon, text) currently displayed
        self._last_restart = 0.0

        self.icons = icons.build()
        self.icon = XApp.StatusIcon()
        self.icon.set_name("sttkbrd")
        self.icon.set_icon_name(self.icons[ICON_IDLE])
        self.icon.connect("activate", lambda *a: self.open_settings())
        self.icon.set_secondary_menu(self._build_menu())
        self.hotkey = HotkeyListener(self.cfg["hotkey"], self._on_press, self._on_release)
        self.hotkey.start()
        self.auto = AutoListener(self._on_speech_start, lambda wav, s: self._submit(wav, s, allow_commands=True),
                                lambda: False)
        self._apply_auto()
        GLib.timeout_add(300, self._tick)  # keeps the icon honest even if an event was missed
        log.info("Started. hotkey=%s model=%s microphone=%r language=%r", self.cfg["hotkey"], self.cfg["model"],
                 self.cfg["microphone"], self.cfg["language"])

    def _build_menu(self):
        menu = Gtk.Menu()
        self._status_item = Gtk.MenuItem(label="")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)
        menu.append(Gtk.SeparatorMenuItem())
        self._auto_item = Gtk.CheckMenuItem(label="Auto mode (listen continuously)")
        self._auto_item.set_active(self.cfg["auto"])
        self._auto_item.connect("toggled", self._on_auto_toggled)
        menu.append(self._auto_item)
        settings = Gtk.MenuItem(label="Settings…")
        settings.connect("activate", lambda *a: self.open_settings())
        menu.append(settings)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *a: Gtk.main_quit())
        menu.append(quit_item)
        menu.show_all()
        return menu

    def _set_state(self, icon, text=None):
        if self.cfg["auto"] and self._paused:
            base = "Auto mode paused - press %s to resume" % self.cfg["hotkey"]
        elif self.cfg["auto"]:
            base = "Auto mode listening - press %s to pause" % self.cfg["hotkey"]
        else:
            base = "Hold %s and speak" % self.cfg["hotkey"]
        text = text or base
        self._state = icon
        if self._dialog:
            self._dialog.set_state(icon)
        self.icon.set_icon_name(self.icons[icon])
        self.icon.set_tooltip_text("sttkbrd – " + text)
        self._status_item.set_label(text)
        return False

    # The icon is never set by individual events. It is always derived from what is really going on, so a
    # late or lost event (e.g. speech detected just as listening is paused) cannot leave it stuck on red.
    def _compute(self):
        if self.recorder.recording or self.auto.speaking:
            return ICON_REC, "Listening…"
        if self._busy:
            return ICON_BUSY, "Transcribing…"
        if self._error:
            return ICON_ERROR, self._error
        return self._idle(), None

    def _refresh(self, force=False):
        want = self._compute()
        if force or want != self._shown:
            self._shown = want
            self._set_state(*want)

    def _tick(self):
        if self.auto.stalled() and time.monotonic() - self._last_restart > 5:
            log.warning("Auto mode stream stopped delivering audio - restarting it")
            self._last_restart = time.monotonic()
            self._apply_auto()
        self._refresh()
        return True

    def _notify(self):
        """Ask the main thread to refresh the icon (safe to call from any thread)."""
        GLib.idle_add(self._refresh_once)

    def _refresh_once(self):
        self._refresh()
        return False

    def _fail(self, message):
        self._error = message
        self._notify()

    def _on_speech_start(self):
        self._error = ""
        self._notify()

    def _idle(self):
        return ICON_AUTO if self.cfg["auto"] and not self._paused else ICON_IDLE

    def _apply_auto(self):
        """Start or stop continuous listening to match the config, and refresh icons and menu."""
        self._syncing_auto = True
        self._auto_item.set_active(self.cfg["auto"])
        self._syncing_auto = False
        self.auto.stop()
        if not self.cfg["auto"]:
            self._paused = False
        if self.cfg["auto"] and not self._paused:
            try:
                self.auto.start(self.cfg["microphone"])
            except Exception as ex:
                log.exception("Could not start auto mode")
                self._error = "Auto mode: microphone error: %s" % ex
                self._refresh(force=True)
                return
        self._error = ""
        self._refresh(force=True)

    def _on_auto_toggled(self, item):
        if self._syncing_auto or item.get_active() == self.cfg["auto"]:
            return
        self.cfg = dict(self.cfg, auto=item.get_active())
        config.save(self.cfg)
        log.info("Auto mode %s", "on" if self.cfg["auto"] else "off")
        if self._dialog:
            self._dialog.set_auto(self.cfg["auto"])
        self._apply_auto()

    def _toggle_pause(self):
        self._paused = not self._paused
        log.info("Auto mode %s", "paused" if self._paused else "resumed")
        self._apply_auto()
        (sounds.listening_off if self._paused else sounds.listening_on)()
        return False

    def open_settings(self):
        if self._dialog:
            self._dialog.present()
            return
        self._dialog = SettingsDialog(self.cfg, self._on_settings_changed, self._state)
        self._dialog.connect("destroy", lambda *a: setattr(self, "_dialog", None))

    def _on_settings_changed(self, cfg):
        """Called by the settings window on every change: save, and apply only what changed."""
        old, self.cfg = self.cfg, cfg
        config.save(cfg)
        log.info("Settings saved. hotkey=%s model=%s auto=%s", cfg["hotkey"], cfg["model"], cfg["auto"])
        self.hotkey.set_combo(cfg["hotkey"])
        if cfg["auto"] != old["auto"] or cfg["microphone"] != old["microphone"]:
            self._apply_auto()
        else:
            self._refresh(force=True)

    # --- push-to-talk (runs on the pynput thread) ---
    def _on_press(self):
        if self.cfg["auto"]:
            GLib.idle_add(self._toggle_pause)
            return
        log.info("Hotkey pressed - recording")
        try:
            self.recorder.start(self.cfg["microphone"])
            self._ptt = True
            self._error = ""
            self._notify()
        except Exception as ex:
            log.exception("Could not start recording")
            self._fail("Microphone error: %s" % ex)

    def _on_release(self):
        if not self._ptt:
            return
        self._ptt = False
        wav, seconds = self.recorder.stop()
        log.info("Hotkey released - %.2f s recorded", seconds)
        self._submit(wav, seconds)

    def _submit(self, wav, seconds, allow_commands=False):
        """Common path for hotkey recordings and auto-mode utterances (only the latter may be voice commands)."""
        if seconds < MIN_SECONDS:
            self._notify()
            return
        with self._busy_lock:
            self._busy += 1
            self._error = ""
        self._notify()
        threading.Thread(target=self._transcribe_and_type, args=(wav, allow_commands), daemon=True).start()

    def _type_recorded(self, chunk):
        """Type text and remember it (and in which window) so 'undo' can erase it again."""
        window = self.typer.active_window()
        self.typer.type(chunk)
        self.history.record(len(chunk), window)

    def _run_command(self, command, heard):
        kind, value = command["type"], command["value"]
        log.info("Voice command %r (%s) -> %s %r", heard, command["phrase"], kind, value)
        if kind == "undo":
            count = self.history.undo(self.typer.active_window())
            if count is None:
                log.info("Nothing to undo (nothing typed yet, or the window changed)")
            else:
                log.info("Undo: erasing %d characters", count)
                self.typer.backspace(count)
        elif kind == "text":
            self._type_recorded(commands.unescape(value))
        else:
            window = self.typer.active_window()
            self.typer.press(value)
            if value.strip().lower() in ("enter", "return", "tab", "space"):
                self.history.record(1, window)  # inserts one character, so it can be undone too
            else:
                self.history.clear()  # the effect on the text is unknown, so earlier steps can no longer be trusted

    def _transcribe_and_type(self, wav, allow_commands=False):
        try:
            with self._pipeline:
                self._transcribe_and_type_locked(wav, allow_commands)
        except Exception:
            log.exception("Unexpected error while dictating")
            self._fail("Unexpected error - see the log")
        finally:
            with self._busy_lock:
                self._busy -= 1
            self._notify()

    def _transcribe_and_type_locked(self, wav, allow_commands=False):
        cfg = self.cfg
        try:
            text = stt.transcribe(cfg["api_key"], cfg["model"], cfg["base_url"], wav, cfg["language"])
        except stt.SttError as ex:
            log.error("Transcription failed: %s", ex)
            self._fail(str(ex)[:200])
            return
        except Exception:
            log.exception("Unexpected error during transcription")
            self._fail("Unexpected error - see the log")
            return
        log.info("Text: %r", text)
        if not text:
            return
        command = commands.match(text, cfg["commands"]) if allow_commands and cfg["commands_enabled"] else None
        # wait until Ctrl/Shift/Alt are released so they do not mix into the typed text
        deadline = time.time() + 3
        while self.hotkey.modifiers_down() and time.time() < deadline:
            time.sleep(0.02)
        try:
            if command:
                self._run_command(command, text)
            else:
                self._type_recorded(text + (" " if cfg["trailing_space"] else ""))
        except ValueError as ex:  # a command whose key cannot be pressed
            log.error("Voice command %r failed: %s", text, ex)
            self._fail("Voice command failed: %s" % ex)
        except Exception:
            log.exception("Could not type the text")
            self._fail("Could not type the text - see the log")


def _single_instance():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    lock = open(os.path.join(runtime, "sttkbrd.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.error("sttkbrd is already running.")
        sys.exit(1)
    return lock


def main():
    setup_log()
    lock = _single_instance()  # noqa: F841 (must live as long as the process)
    autostart.refresh_if_stale()
    app = App()
    if not app.cfg["api_key"]:
        GLib.idle_add(app.open_settings)
    Gtk.main()
    app.auto.stop()
    app.hotkey.stop()
