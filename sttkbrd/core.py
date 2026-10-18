import threading
import time

from . import commands, config, icons, sounds, stt
from .hotkey import HotkeyListener
from .log import log
from .recorder import Recorder
from .typed_history import TypedHistory
from .vad import AutoListener

ICON_IDLE, ICON_AUTO, ICON_REC, ICON_BUSY, ICON_ERROR = "idle", "auto", "rec", "busy", "error"
MIN_SECONDS = 0.4
MAX_PTT_SECONDS = 120
ALARM_GAP = 8  # seconds: no new alarm sooner than this after the last one


class Core:
    """Dictation logic shared by all platforms. A subclass supplies the tray icon, the Settings window and
    the way to run something on the UI thread:

        _build_tray()                  create the tray icon and its menu (self.icons holds the images)
        _show_state(icon, text)        show the state in the tray icon, tooltip and menu
        _sync_auto_item(active)        tick the Auto mode menu item without triggering _on_auto_toggled
        _make_dialog(cfg, on_change, state, on_close)   create and show Settings (present/set_state/set_auto)
        _post(fn)                      run fn() on the UI thread, from any thread
        quit()                         leave the main loop
    """

    def __init__(self, typer):
        self.cfg = config.load()
        self.recorder = Recorder()
        self.typer = typer
        self._dialog = None
        self._state = ICON_IDLE
        self._pipeline = threading.Lock()  # keeps typed text in speaking order
        self.history = TypedHistory()  # what was typed, for the voice command 'undo'
        # auto mode only: the hotkey toggles listening off/on. Starts paused, so nothing listens until asked.
        self._paused = self.cfg["auto"]
        self._ptt = False  # a push-to-talk recording is in progress
        self._ptt_started = 0.0
        self._busy = 0  # utterances being transcribed or typed
        self._busy_lock = threading.Lock()
        self._error = ""  # last error: the icon stays red until the step that failed works again
        self._error_kind = ""  # which step failed: "stt" (transcription), "type" (typing) or "mic"
        self._last_alarm = 0.0
        self._shown = None  # (icon, text) currently displayed
        self._last_restart = 0.0

        self.icons = icons.build()
        self._build_tray()
        self.hotkey = HotkeyListener(self.cfg["hotkey"], self._on_press, self._on_release)
        self.hotkey.start()
        self.auto = AutoListener(self._on_speech_start, lambda wav, s: self._submit(wav, s, allow_commands=True),
                                lambda: False)
        self._apply_auto()
        log.info("Started. hotkey=%s model=%s microphone=%r language=%r", self.cfg["hotkey"], self.cfg["model"],
                 self.cfg["microphone"], self.cfg["language"])

    def _hold_hint(self):
        return "Hold %s and speak" % self.cfg["hotkey"]

    def _set_state(self, icon, text=None):
        key = self.cfg["hotkey"]
        if self.cfg["auto"] and self._paused:
            base = "Auto mode paused - click the icon or press %s to resume" % key
        elif self.cfg["auto"]:
            base = "Auto mode listening - click the icon or press %s to pause" % key
        else:
            base = self._hold_hint()
        text = text or base
        self._state = icon
        if self._dialog:
            self._dialog.set_state(icon)
        self._show_state(icon, text)

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
        if self._dialog:  # the error text under the waveform lives exactly as long as the error does
            self._dialog.set_error(self._error)
        if force or want != self._shown:
            self._shown = want
            self._set_state(*want)

    def _tick(self):
        if self._ptt and time.monotonic() - self._ptt_started > MAX_PTT_SECONDS:
            # a release event was lost (pointer left the icon, panel restarted ...): stop instead of recording forever
            log.warning("Push-to-talk held for over %d s - stopping it", MAX_PTT_SECONDS)
            self._on_release()
        if self.auto.stalled() and time.monotonic() - self._last_restart > 5:
            log.warning("Auto mode stream stopped delivering audio - restarting it")
            self._last_restart = time.monotonic()
            self._apply_auto()
        self._refresh()
        return True

    def _notify(self):
        """Ask the main thread to refresh the icon (safe to call from any thread)."""
        self._post(self._refresh)

    def _fail(self, message, kind="stt"):
        """Show the error (whole icon red) until a later attempt of the same step succeeds, and sound the alarm."""
        self._error, self._error_kind = message, kind
        if time.monotonic() - self._last_alarm > ALARM_GAP:  # a burst of failures must not beep non-stop
            self._last_alarm = time.monotonic()
            sounds.alarm()
        self._notify()

    def _clear_error(self, kind):
        """A step worked again: forget its error (an error of another step stays)."""
        if self._error and self._error_kind == kind:
            self._error = self._error_kind = ""
            self._notify()

    def _on_speech_start(self):
        self._notify()

    def _idle(self):
        return ICON_AUTO if self.cfg["auto"] and not self._paused else ICON_IDLE

    def _apply_auto(self):
        """Start or stop continuous listening to match the config, and refresh icons and menu."""
        self._sync_auto_item(self.cfg["auto"])
        self.auto.stop()
        if not self.cfg["auto"]:
            self._paused = False
        if self.cfg["auto"] and not self._paused:
            try:
                self.auto.start(self.cfg["microphone"])
            except Exception as ex:
                log.exception("Could not start auto mode")
                self._error, self._error_kind = "Auto mode: microphone error: %s" % ex, "mic"
                self._refresh(force=True)
                return
        if self._error_kind == "mic":
            self._error = self._error_kind = ""
        self._refresh(force=True)

    def _on_auto_toggled(self, active):
        if active == self.cfg["auto"]:
            return
        self.cfg = dict(self.cfg, auto=active)
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

    def open_settings(self):
        log.info("Opening Settings")
        if self._dialog:
            self._dialog.present()
            return
        self._dialog = self._make_dialog(self.cfg, self._on_settings_changed, self._state,
                                         lambda: setattr(self, "_dialog", None))
        self._dialog.set_error(self._error)

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
            self._post(self._toggle_pause)
            return
        log.info("Hotkey pressed - recording")
        try:
            self.recorder.start(self.cfg["microphone"])
            self._ptt = True
            self._ptt_started = time.monotonic()
            self._clear_error("mic")
            self._notify()
        except Exception as ex:
            log.exception("Could not start recording")
            self._fail("Microphone error: %s" % ex, "mic")

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
        self._clear_error("stt")  # the model answered, even if it heard nothing
        log.info("Text: %r", text)
        if not text:
            return
        self._post(lambda: self._dialog and self._dialog.show_text(text))
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
            self._clear_error("type")
        except ValueError as ex:  # a command whose key cannot be pressed
            log.error("Voice command %r failed: %s", text, ex)
            self._fail("Voice command failed: %s" % ex, "type")
        except Exception:
            log.exception("Could not type the text")
            self._fail("Could not type the text - see the log", "type")
