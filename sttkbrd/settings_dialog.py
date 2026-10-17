import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from . import autostart, commands, icons, recorder, stt
from .log import log

_GDK_NAMES = {"return": "enter", "escape": "esc", "iso_left_tab": "tab", "prior": "page_up", "next": "page_down"}
_MOD_KEYS = {"control_l", "control_r", "shift_l", "shift_r", "alt_l", "alt_r", "super_l", "super_r",
             "meta_l", "meta_r", "iso_level3_shift"}
HEADER_ICON_SIZE = 64
SPEECH_LEVEL = 0.25  # displayed level (0..1) above which a bar counts as speech, not noise


def _combo_from_event(event):
    name = (Gdk.keyval_name(event.keyval) or "").lower()
    if name in _MOD_KEYS or not name:
        return None
    name = _GDK_NAMES.get(name, name)
    parts = []
    if event.state & Gdk.ModifierType.CONTROL_MASK:
        parts.append("ctrl")
    if event.state & Gdk.ModifierType.SHIFT_MASK:
        parts.append("shift")
    if event.state & Gdk.ModifierType.MOD1_MASK:
        parts.append("alt")
    if event.state & Gdk.ModifierType.SUPER_MASK:
        parts.append("super")
    parts.append(name)
    return "+".join(parts)


class Waveform(Gtk.DrawingArea):
    """Scrolling, mirrored level bars that follow the microphone."""

    def __init__(self, monitor):
        super().__init__()
        self._monitor = monitor
        self.set_size_request(-1, HEADER_ICON_SIZE)
        self.set_hexpand(True)
        self.connect("draw", self._draw)
        self._tick = GLib.timeout_add(33, self._refresh)
        self.connect("destroy", lambda *_: GLib.source_remove(self._tick))

    def _refresh(self):
        self.queue_draw()
        return True

    def _draw(self, widget, cr):
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        ctx = widget.get_style_context()
        color = ctx.get_color(Gtk.StateFlags.NORMAL)
        mid = height / 2.0
        if self._monitor.error:
            cr.set_source_rgba(color.red, color.green, color.blue, 0.7)
            cr.move_to(4, mid + 4)
            cr.show_text("Microphone unavailable: " + self._monitor.error[:60])
            return False
        levels = self._monitor.levels()
        slot = width / float(len(levels))
        bar = max(1.0, slot * 0.6)
        for i, level in enumerate(levels):
            half = max(1.0, level * (mid - 2))
            # newest bars are the most opaque; quiet background noise stays grey, speech turns blue
            alpha = 0.25 + 0.75 * (i + 1) / len(levels)
            if level > SPEECH_LEVEL:
                cr.set_source_rgba(0.15, 0.55, 1.0, alpha)
            else:
                cr.set_source_rgba(color.red, color.green, color.blue, 0.35)
            cr.rectangle(i * slot, mid - half, bar, half * 2)
            cr.fill()
        return False


class SettingsDialog(Gtk.Dialog):
    def __init__(self, cfg, on_change, state="idle"):
        super().__init__(title="sttkbrd - Settings")
        self._cfg = dict(cfg)
        self._on_change = on_change
        self._commit_timer = None
        self._quiet = True  # no saving while the widgets are being built
        self._hotkey = cfg["hotkey"]
        self.set_default_size(480, -1)
        self.set_border_width(12)
        try:
            self.set_icon_from_file(icons.build()["idle"])
        except Exception:
            log.exception("Could not set the window icon")

        content = self.get_content_area()
        content.set_spacing(12)

        # Header: icon on the left, live microphone waveform to the right of it.
        self._monitor = recorder.MicMonitor()
        header = Gtk.Box(spacing=12)
        self._icon_paths = icons.build()
        self._header_icon = Gtk.Image.new_from_icon_name("audio-input-microphone", Gtk.IconSize.DIALOG)
        header.pack_start(self._header_icon, False, False, 0)
        self.set_state(state)
        header.pack_start(Waveform(self._monitor), True, True, 0)
        content.pack_start(header, False, False, 0)

        grid = Gtk.Grid(column_spacing=10, row_spacing=8)
        content.pack_start(grid, True, True, 0)

        def row(i, label, widget):
            lab = Gtk.Label(label=label, xalign=1)
            widget.set_hexpand(True)
            grid.attach(lab, 0, i, 1, 1)
            grid.attach(widget, 1, i, 1, 1)

        self._provider = Gtk.ComboBoxText()
        self._provider.append_text("OpenRouter")
        self._provider.set_active(0)
        row(0, "Provider", self._provider)

        self._url = Gtk.Entry(text=cfg["base_url"])
        row(1, "Base URL", self._url)

        self._key = Gtk.Entry(text=cfg["api_key"], visibility=False)
        row(2, "API key", self._key)

        self._store = Gtk.ListStore(str, str)
        for m in stt.FALLBACK_MODELS:
            self._store.append([m, m])
        self._model = Gtk.ComboBox.new_with_model_and_entry(self._store)
        self._model.set_entry_text_column(0)
        self._model.clear()  # drop the default renderer GTK adds for the entry text column
        renderer = Gtk.CellRendererText()
        self._model.pack_start(renderer, True)
        self._model.add_attribute(renderer, "text", 1)
        self._model.get_child().set_text(cfg["model"])
        refresh = Gtk.Button(label="Load")
        refresh.connect("clicked", self._load_models)
        box = Gtk.Box(spacing=6)
        box.pack_start(self._model, True, True, 0)
        box.pack_start(refresh, False, False, 0)
        row(3, "Model", box)

        self._hotkey_btn = Gtk.Button(label=self._hotkey)
        self._hotkey_btn.connect("clicked", self._capture_hotkey)
        row(4, "Hotkey", self._hotkey_btn)

        self._mic = Gtk.ComboBoxText()
        self._mic.append_text("(default)")
        mics = []
        try:
            mics = recorder.list_microphones()
        except Exception:
            log.exception("Could not list microphones")
        for m in mics:
            self._mic.append_text(m)
        self._mic.set_active(mics.index(cfg["microphone"]) + 1 if cfg["microphone"] in mics else 0)
        self._mic.connect("changed", lambda *_: self._monitor.start(self._selected_mic()))
        row(5, "Microphone", self._mic)

        self._lang = Gtk.Entry(text=cfg["language"], placeholder_text="one code, e.g. sv or en - empty = automatic")
        row(6, "Language", self._lang)

        self._space = Gtk.CheckButton(label="Add a space after the text")
        self._space.set_active(cfg["trailing_space"])
        grid.attach(self._space, 1, 7, 1, 1)

        self._auto = Gtk.CheckButton(label="Auto mode: listen continuously (hotkey pauses / resumes)")
        self._auto.set_active(cfg["auto"])
        grid.attach(self._auto, 1, 10, 1, 1)

        self._menu = Gtk.CheckButton(label="Show in the application menu")
        self._menu.set_active(autostart.menu_entry_enabled())
        grid.attach(self._menu, 1, 8, 1, 1)

        self._autostart = Gtk.CheckButton(label="Start automatically when the desktop starts")
        self._autostart.set_active(autostart.is_enabled())
        grid.attach(self._autostart, 1, 9, 1, 1)

        self._status = Gtk.Label(xalign=0)
        grid.attach(self._status, 0, 12, 2, 1)

        self._build_commands(grid, cfg)

        if cfg["api_key"]:
            self._load_models(None)

        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda *_: self.destroy())

        # Every change is saved and applied immediately. Text fields are debounced so typing does not
        # save on every keypress; the pending save is flushed when the window closes.
        for entry in (self._url, self._key, self._lang, self._model.get_child()):
            entry.connect("changed", self._schedule_commit)
        for widget in (self._provider, self._model, self._mic):
            widget.connect("changed", lambda *_: self._commit())
        for check in (self._space, self._auto, self._cmd_enabled):
            check.connect("toggled", lambda *_: self._commit())
        self._autostart.connect("toggled", self._on_autostart)
        self._menu.connect("toggled", self._on_menu)
        self._auto.connect("toggled", lambda *_: self._sync_commands_visibility())
        self.connect("destroy", self._on_destroy)

        self.show_all()
        self._monitor.start(self._selected_mic())
        self._quiet = False

    def set_state(self, state):
        """Show the same state badge as the tray icon (red = listening, orange = working, yellow = error)."""
        try:
            path = self._icon_paths[state]
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, HEADER_ICON_SIZE, HEADER_ICON_SIZE)
            self._header_icon.set_from_pixbuf(pixbuf)
        except Exception:
            log.exception("Could not load the header icon for state %s", state)

    # --- voice commands ---------------------------------------------------------------------------------
    def _build_commands(self, grid, cfg):
        """Editable list: when a whole utterance equals a phrase (auto mode), the action runs instead of typing.

        Sits right under the Auto mode checkbox and is only shown while auto mode is on."""
        frame = Gtk.Frame(label="Voice commands")
        self._cmd_frame = frame
        frame.set_margin_start(24)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        frame.add(box)

        self._cmd_enabled = Gtk.CheckButton(label="Run a command when the whole sentence is just its phrase")
        self._cmd_enabled.set_active(cfg["commands_enabled"])
        box.pack_start(self._cmd_enabled, False, False, 0)

        self._cmds = Gtk.ListStore(str, str, str)  # phrase, type, value
        for c in cfg["commands"]:
            self._cmds.append([c["phrase"], c["type"], c["value"]])
        tree = Gtk.TreeView(model=self._cmds)
        self._cmd_tree = tree

        def text_column(title, index, expand):
            renderer = Gtk.CellRendererText(editable=True)
            renderer.connect("edited", self._on_cmd_edited, index)
            col = Gtk.TreeViewColumn(title, renderer, text=index)
            col.set_expand(expand)
            col.set_resizable(True)
            tree.append_column(col)

        text_column("Phrase(s)", 0, True)
        type_model = Gtk.ListStore(str)
        for kind in commands.TYPES:
            type_model.append([kind])
        kind_renderer = Gtk.CellRendererCombo(model=type_model, text_column=0, editable=True, has_entry=False)
        kind_renderer.connect("edited", self._on_cmd_edited, 1)
        tree.append_column(Gtk.TreeViewColumn("Type", kind_renderer, text=1))
        text_column("Key or text", 2, True)

        scroll = Gtk.ScrolledWindow(min_content_height=120, shadow_type=Gtk.ShadowType.IN)
        scroll.add(tree)
        box.pack_start(scroll, True, True, 0)

        buttons = Gtk.Box(spacing=6)
        add = Gtk.Button(label="Add")
        add.connect("clicked", self._on_cmd_add)
        remove = Gtk.Button(label="Remove")
        remove.connect("clicked", self._on_cmd_remove)
        buttons.pack_start(add, False, False, 0)
        buttons.pack_start(remove, False, False, 0)
        box.pack_start(buttons, False, False, 0)
        hint = Gtk.Label(label="Several phrases: separate with commas (enter, retur).  Types: key, text, undo.",
                         xalign=0, wrap=True)
        hint.get_style_context().add_class("dim-label")
        box.pack_start(hint, False, False, 0)
        frame.show_all()  # children first: no_show_all below would otherwise leave them hidden for good
        frame.set_no_show_all(True)  # shown only while auto mode is on
        frame.set_visible(cfg["auto"])
        grid.attach(frame, 0, 11, 2, 1)

    def _sync_commands_visibility(self):
        """The voice command settings belong to auto mode: show them only while it is on."""
        want = self._auto.get_active()
        if self._cmd_frame.get_visible() == want:
            return
        self._cmd_frame.set_visible(want)
        if not want:  # let the window shrink back instead of leaving an empty gap
            GLib.idle_add(lambda: self.resize(self.get_size()[0], 1) or False)

    def _on_cmd_edited(self, _renderer, path, new_text, column):
        row = self._cmds[path]
        new_text = new_text.strip()
        if column == 1:
            row[1] = new_text
            if not commands.needs_value(new_text):
                row[2] = ""
            self._check_command_row(row)
        elif column == 2:
            if not commands.needs_value(row[1]):  # undo takes no value
                return
            error = commands.value_error(row[1], new_text)
            if error:  # reject: keep the old value so a broken command is never saved
                self._status.set_text("Not saved: " + error)
                return
            row[2] = new_text
            self._status.set_text("")
        else:
            row[0] = new_text
        self._commit()

    def _check_command_row(self, row):
        """After the type changed, make sure the existing value still makes sense for it."""
        error = commands.value_error(row[1], row[2]) if commands.needs_value(row[1]) else None
        self._status.set_text("Check the value: " + error if error else "")

    def _on_cmd_add(self, _btn):
        it = self._cmds.append(["", "key", ""])
        path = self._cmds.get_path(it)
        self._cmd_tree.set_cursor(path, self._cmd_tree.get_column(0), True)

    def _on_cmd_remove(self, _btn):
        model, it = self._cmd_tree.get_selection().get_selected()
        if it:
            model.remove(it)
            self._commit()

    def _command_list(self):
        """Complete rows only; half-filled or invalid ones are kept in the list but not saved."""
        result = []
        for phrase, kind, value in self._cmds:
            if phrase and kind in commands.TYPES and (value or not commands.needs_value(kind)) \
                    and not commands.value_error(kind, value):
                result.append({"phrase": phrase, "type": kind, "value": value})
        return result

    def _on_autostart(self, check):
        """Autostart is the presence of a desktop file, not a config value, so it is applied right here."""
        if self._quiet:
            return
        try:
            autostart.enable() if check.get_active() else autostart.disable()
            self._status.set_text("Autostart %s." % ("enabled" if check.get_active() else "disabled"))
        except autostart.AutostartError as ex:
            log.error("Autostart: %s", ex)
            self._status.set_text(str(ex))
            self._quiet = True  # put the checkbox back to what is really on disk
            check.set_active(autostart.is_enabled())
            self._quiet = False

    def _on_menu(self, check):
        """Like autostart, the application menu entry is a desktop file, so it is written or removed right here."""
        if self._quiet:
            return
        try:
            if check.get_active():
                autostart.install_menu_entry()
            else:
                autostart.remove_menu_entry()
            self._status.set_text("Menu entry %s." % ("added" if check.get_active() else "removed"))
        except autostart.AutostartError as ex:
            log.error("Menu entry: %s", ex)
            self._status.set_text(str(ex))
            self._quiet = True  # put the checkbox back to what is really on disk
            check.set_active(autostart.menu_entry_enabled())
            self._quiet = False

    def set_auto(self, value):
        """Reflect an auto-mode change made elsewhere (tray menu) without saving it again."""
        self._quiet = True
        self._auto.set_active(value)
        self._quiet = False
        self._sync_commands_visibility()

    def _on_destroy(self, *_):
        if self._commit_timer:
            self._commit()
        self._monitor.stop()

    def _schedule_commit(self, *_):
        if self._quiet:
            return
        if self._commit_timer:
            GLib.source_remove(self._commit_timer)
        self._commit_timer = GLib.timeout_add(600, self._commit)

    def _commit(self):
        if self._commit_timer:
            GLib.source_remove(self._commit_timer)
            self._commit_timer = None
        if self._quiet:
            return False
        cfg = dict(self._cfg)
        cfg.update(
            provider=self._provider.get_active_text() or "OpenRouter",
            base_url=self._url.get_text().strip(),
            api_key=self._key.get_text().strip(),
            model=self._model.get_child().get_text().strip() or stt.DEFAULT_MODEL,
            hotkey=self._hotkey,
            language=self._lang.get_text().strip(),
            microphone=self._selected_mic(),
            trailing_space=self._space.get_active(),
            auto=self._auto.get_active(),
            commands_enabled=self._cmd_enabled.get_active(),
            commands=self._command_list(),
        )
        if cfg != self._cfg:
            self._cfg = cfg
            self._on_change(dict(cfg))
        return False

    def _selected_mic(self):
        mic = self._mic.get_active_text()
        return "" if mic in (None, "(default)") else mic

    def _load_models(self, _btn):
        key, url = self._key.get_text().strip(), self._url.get_text()
        self._status.set_text("Loading models…")

        def work():
            try:
                models = stt.load_models(key, url)
                GLib.idle_add(self._set_models, models)
            except stt.SttError as ex:
                log.error("Loading models: %s", ex)
                GLib.idle_add(self._status.set_text, str(ex))

        threading.Thread(target=work, daemon=True).start()

    def _set_models(self, models):
        current = self._model.get_child().get_text()
        was_quiet, self._quiet = self._quiet, True  # refilling the list must not save a half-empty model field
        self._store.clear()
        for mid, price in models:
            self._store.append([mid, "%s  (%s)" % (mid, price) if price else mid])
        self._model.get_child().set_text(current or models[0][0])
        self._quiet = was_quiet
        self._status.set_text("%d models loaded." % len(models))

    def _capture_hotkey(self, _btn):
        dlg = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                                buttons=Gtk.ButtonsType.CANCEL,
                                text="Press the key combination you want (e.g. Ctrl+Shift+Space)")

        def on_key(_w, event):
            combo = _combo_from_event(event)
            if combo:
                self._hotkey = combo
                self._hotkey_btn.set_label(combo)
                dlg.response(Gtk.ResponseType.OK)
                GLib.idle_add(self._commit)
            return True

        dlg.connect("key-press-event", on_key)
        dlg.run()
        dlg.destroy()
