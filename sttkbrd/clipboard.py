import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk


def _on_main(fn):
    """Run fn on the GTK main thread and wait for the result (called from a worker thread)."""
    done, box = threading.Event(), {}

    def run():
        try:
            box["value"] = fn()
        except Exception as ex:  # noqa: BLE001 – re-raised to the caller
            box["error"] = ex
        done.set()
        return False

    GLib.idle_add(run)
    if not done.wait(5):
        raise RuntimeError("The clipboard did not respond")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class Clipboard:
    def swap_in(self, text):
        """Put the text on the clipboard and return its previous text content (or None)."""
        def work():
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            old = cb.wait_for_text()
            cb.set_text(text, -1)
            return old
        return _on_main(work)

    def restore(self, old):
        def work():
            cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            if old is None:
                cb.clear()
            else:
                cb.set_text(old, -1)
        _on_main(work)
