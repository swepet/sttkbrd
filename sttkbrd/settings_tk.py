import threading
import time
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import ImageTk

from . import __version__, autostart, commands, icons, languages, recorder, stt
from .log import log

_TK_NAMES = {"return": "enter", "escape": "esc", "prior": "page_up", "next": "page_down", "iso_left_tab": "tab"}
_MOD_KEYS = {"control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "win_l", "win_r", "super_l",
             "super_r", "caps_lock", "num_lock", "scroll_lock"}
HEADER_ICON_SIZE = 64
WAVE_HEIGHT = 32  # the waveform and the text under it together are about as tall as the icon
WAVE_FPS = 30  # bars the waveform advances per second (the microphone delivers 30 blocks a second)
SPEECH_LEVEL = 0.25  # displayed level (0..1) above which a bar counts as speech, not noise


FADE_EDGE = 0.12  # fraction of the width at each side over which the waveform and the text fade


def _fade(x, width):
    """1 in the middle, falling to 0 at the left and right edge."""
    edge = max(width * FADE_EDGE, 1.0)
    return max(0.0, min(1.0, x / edge, (width - x) / edge))


def _mix(fg, bg, f):
    """Hex colour f of the way from the background colour bg to fg (both 0-255 triples)."""
    return "#%02x%02x%02x" % tuple(int(b + (c - b) * f) for c, b in zip(fg, bg))


def _background(widget):
    return tuple(v // 257 for v in widget.winfo_rgb(widget.cget("bg")))


def _combo_from_event(event):
    name = (event.keysym or "").lower()
    if not name or name in _MOD_KEYS:
        return None
    name = _TK_NAMES.get(name, name)
    parts = []
    if event.state & 0x4:
        parts.append("ctrl")
    if event.state & 0x1:
        parts.append("shift")
    if event.state & 0x20000:  # Alt on Windows
        parts.append("alt")
    parts.append(name)
    return "+".join(parts)


class Waveform(tk.Canvas):
    """Scrolling, mirrored level bars that follow the microphone."""

    def __init__(self, parent, monitor):
        super().__init__(parent, height=WAVE_HEIGHT, highlightthickness=0)
        self._monitor = monitor
        self._after = self.after(33, self._draw)

    def destroy(self):
        self.after_cancel(self._after)
        super().destroy()

    def _draw(self):
        self.delete("all")
        width, height = max(self.winfo_width(), 1), max(self.winfo_height(), 1)
        mid = height / 2.0
        if self._monitor.error:
            self.create_text(4, mid, anchor="w", fill="#888888",
                             text="Microphone unavailable: " + self._monitor.error[:60])
        else:
            levels = self._monitor.levels()
            slot = width / float(len(levels))
            bar = max(1.0, slot * 0.6)
            bg = _background(self)
            for i, level in enumerate(levels):
                f = _fade(i * slot + bar / 2, width)
                if f <= 0.02:
                    continue
                half = max(1.0, level * (mid - 2))
                color = _mix((42, 140, 255) if level > SPEECH_LEVEL else (160, 160, 160), bg, f)
                self.create_rectangle(i * slot, mid - half, i * slot + bar, mid + half, fill=color, outline="")
        self._after = self.after(33, self._draw)


class TextTicker(tk.Canvas):
    """Transcribed text enters at the right edge and scrolls left at the speed of the waveform above it
    (the waveform moves one bar, width / bars pixels, every 1 / WAVE_FPS second). It fades in and out at the
    edges, character by character."""

    HEIGHT = 20

    def __init__(self, parent, bars=96):
        super().__init__(parent, height=self.HEIGHT, highlightthickness=0)
        self._bars = bars
        self._font = tkfont.Font(family="Segoe UI", size=10)
        self._items = []  # [text, x of its left end, x offset of each character, width]
        self._error = ""
        self._last = time.monotonic()
        self._after = self.after(33, self._step)

    def destroy(self):
        self.after_cancel(self._after)
        super().destroy()

    def add(self, text):
        width = max(self.winfo_width(), 1)
        offsets = [self._font.measure(text[:i]) for i in range(len(text))]
        # never overlap the previous text: start after its end
        start = width
        if self._items:
            last = self._items[-1]
            start = max(width, last[1] + last[3] + 24)
        self._items.append([text, start, offsets, self._font.measure(text)])

    def set_error(self, text):
        """Permanent red message in place of the scrolling text; empty clears it. Taller if it needs two lines."""
        if text == self._error:
            return
        self._error = text
        wrapped = text and self._font.measure(text) > max(self.winfo_width(), 1) - 8
        self.configure(height=2 * self.HEIGHT - 4 if wrapped else self.HEIGHT)

    def _step(self):
        now = time.monotonic()
        width = max(self.winfo_width(), 1)
        speed = width / float(self._bars) * WAVE_FPS  # pixels per second
        dx = speed * (now - self._last)
        self._last = now
        self._items = [i for i in self._items if i[1] + i[3] >= 0]
        self.delete("all")
        bg = _background(self)
        for item in self._items:
            item[1] -= dx
            text, x, offsets, _ = item
            for ch, off in zip(text, offsets if not self._error else ()):
                if ch.isspace() or not -20 < x + off < width:
                    continue
                f = _fade(x + off + 4, width)
                if f > 0.03:
                    self.create_text(x + off, 1, anchor="nw", text=ch, font=self._font,
                                     fill=_mix((42, 140, 255), bg, f))
        if self._error:
            self.create_text(4, 1, anchor="nw", text=self._error, font=self._font, fill="#e03030",
                             width=max(width - 8, 1))
        self._after = self.after(33, self._step)


class SettingsDialog:
    """Settings window (tkinter). Every change is saved and applied at once, there is no Save button."""

    def __init__(self, root, cfg, on_change, state, on_close):
        self._cfg = dict(cfg)
        self._on_change = on_change
        self._on_close = on_close
        self._commit_timer = None
        self._quiet = True  # no saving while the widgets are being built
        self._hotkey = cfg["hotkey"]
        self._rows = []  # voice command rows: (frame, phrase var, type var, value var)

        self.win = win = tk.Toplevel(root)
        win.title("sttkbrd v%s - Settings" % __version__)
        win.minsize(520, 0)
        self._icon_paths = icons.build()
        self._images = {}
        try:
            win.iconphoto(False, self._image("idle", 32))
        except Exception:
            log.exception("Could not set the window icon")
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)

        self._monitor = recorder.MicMonitor()
        header = ttk.Frame(body)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        self._header_icon = ttk.Label(header)
        self._header_icon.grid(row=0, column=0, padx=(0, 12))
        self.set_state(state)
        wave_box = ttk.Frame(header)  # one cell, so the text sits directly under the waveform
        wave_box.grid(row=0, column=1, sticky="ew")
        self._wave = Waveform(wave_box, self._monitor)
        self._wave.pack(fill="x")
        self._ticker = TextTicker(wave_box)
        self._ticker.pack(fill="x")

        grid = ttk.Frame(body)
        grid.grid(row=1, column=0, sticky="ew")
        grid.columnconfigure(1, weight=1)
        self._status = tk.StringVar()

        def row(i, label, widget):
            ttk.Label(grid, text=label).grid(row=i, column=0, sticky="e", padx=(0, 10), pady=4)
            widget.grid(row=i, column=1, sticky="ew", pady=4)

        self._provider = ttk.Combobox(grid, values=["OpenRouter"], state="readonly")
        self._provider.set("OpenRouter")
        row(0, "Provider", self._provider)

        self._url = tk.StringVar(value=cfg["base_url"])
        row(1, "Base URL", ttk.Entry(grid, textvariable=self._url))

        self._key = tk.StringVar(value=cfg["api_key"])
        row(2, "API key", ttk.Entry(grid, textvariable=self._key, show="•"))

        self._model = tk.StringVar(value=cfg["model"])
        box = ttk.Frame(grid)
        box.columnconfigure(0, weight=1)
        self._model_box = ttk.Combobox(box, textvariable=self._model, values=stt.FALLBACK_MODELS)
        self._model_box.grid(row=0, column=0, sticky="ew")
        row(3, "Model", box)

        self._hotkey_btn = ttk.Button(grid, text=self._hotkey, command=self._capture_hotkey)
        row(4, "Hotkey", self._hotkey_btn)

        mics = []
        try:
            mics = recorder.list_microphones()
        except Exception:
            log.exception("Could not list microphones")
        self._mic = ttk.Combobox(grid, values=["(default)"] + mics, state="readonly")
        self._mic.set(cfg["microphone"] if cfg["microphone"] in mics else "(default)")
        row(5, "Microphone", self._mic)

        saved = languages.normalize(cfg["language"])
        self._lang = ttk.Combobox(grid, values=languages.labels(saved), state="readonly")
        self._lang.set(languages.label(saved) if saved else languages.AUTO)
        self._lang.bind("<<ComboboxSelected>>", lambda *_: self._commit())
        row(6, "Main language", self._lang)
        ttk.Label(grid, text="the language you mostly speak - other languages still work; automatic detection can guess wrong on short sentences",
                  foreground="gray").grid(row=7, column=1, sticky="w")

        self._space = tk.BooleanVar(value=cfg["trailing_space"])
        self._auto = tk.BooleanVar(value=cfg["auto"])
        self._menu = tk.BooleanVar(value=autostart.menu_entry_enabled())
        self._autostart = tk.BooleanVar(value=autostart.is_enabled())
        for i, (var, text) in enumerate([
                (self._space, "Add a space after the text"),
                (self._menu, "Show in the Start menu"),
                (self._autostart, "Start automatically when Windows starts"),
                (self._auto, "Auto mode: listen continuously (hotkey pauses / resumes)")]):
            ttk.Checkbutton(grid, text=text, variable=var).grid(row=8 + i, column=1, sticky="w", pady=2)

        self._cmd_frame = ttk.LabelFrame(body, text="Voice commands", padding=8)
        self._build_commands(self._cmd_frame, cfg)
        ttk.Label(body, textvariable=self._status).grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Button(body, text="Close", command=self.close).grid(row=4, column=0, sticky="e", pady=(8, 0))
        self._sync_commands_visibility()

        self._models_timer = None
        self._models_for = None  # (key, url) the model list was last requested for
        if cfg["api_key"]:
            self._load_models()

        # Text fields are debounced so typing does not save on every keypress; the pending save is flushed on close.
        for var in (self._url, self._key, self._model):
            var.trace_add("write", self._schedule_commit)
        for var in (self._url, self._key):
            var.trace_add("write", self._schedule_models)
        self._model_box.bind("<<ComboboxSelected>>", lambda *_: self._commit())
        self._mic.bind("<<ComboboxSelected>>", lambda *_: (self._monitor.start(self._selected_mic()), self._commit()))
        self._space.trace_add("write", lambda *_: self._commit())
        self._auto.trace_add("write", lambda *_: (self._sync_commands_visibility(), self._commit()))
        self._autostart.trace_add("write", lambda *_: self._on_autostart())
        self._menu.trace_add("write", lambda *_: self._on_menu())
        win.protocol("WM_DELETE_WINDOW", self.close)

        self._monitor.start(self._selected_mic())
        self._quiet = False

    # --- helpers --------------------------------------------------------------------------------------------
    def _image(self, state, size):
        key = (state, size)
        if key not in self._images:
            from PIL import Image
            self._images[key] = ImageTk.PhotoImage(Image.open(self._icon_paths[state]).resize((size, size),
                                                                                              Image.LANCZOS))
        return self._images[key]

    def present(self):
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def set_state(self, state):
        """Show the same state badge as the tray icon (red = listening, orange = working, yellow = error)."""
        try:
            self._header_icon.configure(image=self._image(state, HEADER_ICON_SIZE))
        except Exception:
            log.exception("Could not load the header icon for state %s", state)

    def show_text(self, text):
        """A transcription arrived: let it scroll by under the waveform."""
        self._ticker.add(text)

    def set_error(self, text):
        """Show what went wrong in red under the waveform for as long as the error lasts."""
        self._ticker.set_error(text)

    def set_auto(self, value):
        """Reflect an auto-mode change made elsewhere (tray menu) without saving it again."""
        self._quiet = True
        self._auto.set(value)
        self._quiet = False
        self._sync_commands_visibility()

    def close(self):
        if self._models_timer:
            self.win.after_cancel(self._models_timer)
            self._models_timer = None
        if self._commit_timer:
            self._commit()
        self._monitor.stop()
        self.win.destroy()
        self._on_close()

    def _selected_mic(self):
        mic = self._mic.get()
        return "" if mic in ("", "(default)") else mic

    # --- voice commands -------------------------------------------------------------------------------------
    def _build_commands(self, frame, cfg):
        self._cmd_enabled = tk.BooleanVar(value=cfg["commands_enabled"])
        self._cmd_enabled.trace_add("write", lambda *_: self._commit())
        ttk.Checkbutton(frame, text="Run a command when the whole sentence is just its phrase",
                        variable=self._cmd_enabled).pack(anchor="w")
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(6, 0))
        for col, (text, weight) in enumerate([("Phrase(s)", 3), ("Type", 1), ("Key or text", 3)]):
            ttk.Label(header, text=text).grid(row=0, column=col, sticky="w")
            header.columnconfigure(col, weight=weight, uniform="cmd")
        # The list scrolls, so many commands never make the window taller than the screen.
        holder = ttk.Frame(frame)
        holder.pack(fill="x")
        canvas = tk.Canvas(holder, height=110, highlightthickness=0)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="x", expand=True)
        self._cmd_list = ttk.Frame(canvas)
        inner = canvas.create_window((0, 0), window=self._cmd_list, anchor="nw")
        self._cmd_list.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(inner, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        self._cmd_list.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))
        for c in cfg["commands"]:
            self._add_row(c["phrase"], c["type"], c["value"])
        ttk.Button(frame, text="Add", command=lambda: self._add_row("", "key", "")).pack(anchor="w", pady=(6, 0))
        ttk.Label(frame, text="Several phrases: separate with commas (enter, retur).  Types: key, text, undo.",
                  foreground="gray").pack(anchor="w", pady=(4, 0))

    def _add_row(self, phrase, kind, value):
        frame = ttk.Frame(self._cmd_list)
        frame.pack(fill="x", pady=1)
        for col, weight in enumerate((3, 1, 3)):
            frame.columnconfigure(col, weight=weight, uniform="cmd")
        p, k, v = tk.StringVar(value=phrase), tk.StringVar(value=kind), tk.StringVar(value=value)
        ttk.Entry(frame, textvariable=p).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        kind_box = ttk.Combobox(frame, textvariable=k, values=commands.TYPES, state="readonly", width=6)
        kind_box.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        value_entry = ttk.Entry(frame, textvariable=v)
        value_entry.grid(row=0, column=2, sticky="ew", padx=(0, 4))
        entry = (frame, p, k, v)
        ttk.Button(frame, text="✕", width=3, command=lambda: self._remove_row(entry)).grid(row=0, column=3)

        def kind_changed(*_):
            if not commands.needs_value(k.get()):
                v.set("")
            value_entry.configure(state="normal" if commands.needs_value(k.get()) else "disabled")
            self._check_row(entry)

        k.trace_add("write", kind_changed)
        for var in (p, v):
            var.trace_add("write", lambda *_: (self._check_row(entry), self._schedule_commit()))
        value_entry.configure(state="normal" if commands.needs_value(kind) else "disabled")
        self._rows.append(entry)

    def _remove_row(self, entry):
        self._rows.remove(entry)
        entry[0].destroy()
        self._commit()

    def _check_row(self, entry):
        _, p, k, v = entry
        error = commands.value_error(k.get(), v.get()) if commands.needs_value(k.get()) and v.get() else None
        self._status.set("Not saved: " + error if error else "")
        self._schedule_commit()

    def _command_list(self):
        """Complete rows only; half-filled or invalid ones are kept in the list but not saved."""
        result = []
        for _, p, k, v in self._rows:
            phrase, kind, value = p.get().strip(), k.get(), v.get().strip()
            if phrase and kind in commands.TYPES and (value or not commands.needs_value(kind)) \
                    and not commands.value_error(kind, value):
                result.append({"phrase": phrase, "type": kind, "value": value})
        return result

    def _sync_commands_visibility(self):
        """The voice command settings belong to auto mode: show them only while it is on."""
        if self._auto.get():
            self._cmd_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        else:
            self._cmd_frame.grid_remove()
            self.win.geometry("")  # let the window shrink back

    # --- saving ---------------------------------------------------------------------------------------------
    def _on_autostart(self):
        """Autostart is the registry entry, not a config value, so it is applied right here."""
        if self._quiet:
            return
        want = self._autostart.get()
        try:
            autostart.enable() if want else autostart.disable()
            self._status.set("Autostart %s." % ("enabled" if want else "disabled"))
        except autostart.AutostartError as ex:
            log.error("Autostart: %s", ex)
            self._status.set(str(ex))
            self._reset(self._autostart, autostart.is_enabled())

    def _on_menu(self):
        """Like autostart, the Start menu shortcut is a file, so it is written or removed right here."""
        if self._quiet:
            return
        want = self._menu.get()
        try:
            autostart.install_menu_entry() if want else autostart.remove_menu_entry()
            self._status.set("Start menu entry %s." % ("added" if want else "removed"))
        except autostart.AutostartError as ex:
            log.error("Menu entry: %s", ex)
            self._status.set(str(ex))
            self._reset(self._menu, autostart.menu_entry_enabled())

    def _reset(self, var, value):
        """Put a checkbox back to what is really on disk."""
        self._quiet = True
        var.set(value)
        self._quiet = False

    def _schedule_commit(self, *_):
        if self._quiet:
            return
        if self._commit_timer:
            self.win.after_cancel(self._commit_timer)
        self._commit_timer = self.win.after(600, self._commit)

    def _commit(self):
        if self._commit_timer:
            self.win.after_cancel(self._commit_timer)
            self._commit_timer = None
        if self._quiet:
            return
        cfg = dict(self._cfg)
        cfg.update(
            provider=self._provider.get() or "OpenRouter",
            base_url=self._url.get().strip(),
            api_key=self._key.get().strip(),
            model=self._model.get().strip().split("  (")[0] or stt.DEFAULT_MODEL,
            hotkey=self._hotkey,
            language=languages.code(self._lang.get()),
            microphone=self._selected_mic(),
            trailing_space=self._space.get(),
            auto=self._auto.get(),
            commands_enabled=self._cmd_enabled.get(),
            commands=self._command_list(),
        )
        if cfg != self._cfg:
            self._cfg = cfg
            self._on_change(dict(cfg))

    # --- models and hotkey ----------------------------------------------------------------------------------
    def _schedule_models(self, *_):
        """Reload the model list a moment after the key or URL stops changing."""
        if self._quiet:
            return
        if self._models_timer:
            self.win.after_cancel(self._models_timer)
        self._models_timer = self.win.after(800, self._load_models)

    def _load_models(self):
        self._models_timer = None
        key, url = self._key.get().strip(), self._url.get()
        if not key:
            return
        self._models_for = (key, url)
        self._status.set("Loading models…")

        def work():
            try:
                models = stt.load_models(key, url)
                if self._models_for == (key, url):  # the key or URL changed meanwhile: a newer request is on its way
                    self.win.after(0, self._set_models, models)
            except stt.SttError as ex:
                log.error("Loading models: %s", ex)
                if self._models_for == (key, url):
                    self.win.after(0, self._status.set, str(ex))
            except RuntimeError:  # the window was closed meanwhile
                pass

        threading.Thread(target=work, daemon=True).start()

    def _set_models(self, models):
        was_quiet, self._quiet = self._quiet, True  # refilling the list must not save anything
        self._model_box.configure(values=["%s  (%s)" % (mid, price) if price else mid for mid, price in models])
        self._quiet = was_quiet
        self._status.set("%d models loaded." % len(models))

    def _capture_hotkey(self):
        dlg = tk.Toplevel(self.win)
        dlg.title("Hotkey")
        dlg.transient(self.win)
        ttk.Label(dlg, text="Press the key combination you want (e.g. Ctrl+Shift+Space)", padding=20).pack()
        ttk.Button(dlg, text="Cancel", command=dlg.destroy).pack(pady=(0, 12))

        def on_key(event):
            combo = _combo_from_event(event)
            if combo:
                self._hotkey = combo
                self._hotkey_btn.configure(text=combo)
                dlg.destroy()
                self._commit()
            return "break"

        dlg.bind("<KeyPress>", on_key)
        dlg.grab_set()
        dlg.focus_force()
