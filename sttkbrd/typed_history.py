class TypedHistory:
    """What sttkbrd typed, one entry per utterance, so voice 'undo' can erase it step by step.

    Only valid while the same window stays active: if focus moved, the cursor is somewhere else and erasing
    would delete the wrong text, so the history is dropped instead.
    """

    LIMIT = 100

    def __init__(self):
        self._counts = []  # characters typed per utterance, oldest first
        self._window = None

    def record(self, count, window):
        if count <= 0:
            return
        if window != self._window:
            self._counts.clear()
            self._window = window
        self._counts.append(count)
        del self._counts[:-self.LIMIT]

    def undo(self, window):
        """Characters to erase for the latest utterance, or None if there is nothing (valid) to undo."""
        if window != self._window:
            self._counts.clear()
            return None
        return self._counts.pop() if self._counts else None

    def clear(self):
        self._counts.clear()

    def __len__(self):
        return len(self._counts)
