import json
import os
import tempfile
import threading

STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")


class SettingsStore:
    """
    Remembers user settings across restarts (PID gains, B, sweep, ...) in settings.json next to the app
    (station-specific, not tracked by git). set() only marks the store dirty; flush() writes atomically,
    so dragging a slider does not hammer the SD card.
    """
    def __init__(self, path=STORE_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._data = {}
        self._dirty = False
        self.enabled = True  # set False while restoring, so restored values are not re-saved as user changes
        try:
            with open(self.path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        except (OSError, ValueError):
            pass

    def get(self, key, default=None):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key, value):
        if not self.enabled:
            return
        with self._lock:
            if self._data.get(key) != value:
                self._data[key] = value
                self._dirty = True

    def flush(self):
        with self._lock:
            if not self._dirty:
                return
            data = dict(self._data)
            self._dirty = False
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def reset(self):
        with self._lock:
            self._data = {}
            self._dirty = False
        try:
            os.remove(self.path)
        except OSError:
            pass
