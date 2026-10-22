import os
import sys
import logging
import tempfile
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import config

def acquire_single_instance_lock():
    """
    System-wide single instance guard: an exclusive flock on a lock file. The OS releases it automatically
    when the process dies (even on kill -9), so a crash never leaves a stale lock. Returns the open file,
    which must stay referenced for the lifetime of the process, or None if another instance is running.
    """
    try:
        import fcntl
    except ImportError:  # Windows: no flock, skip the guard
        return True
    lock_file = open(os.path.join(tempfile.gettempdir(), "lab_triangulacja.lock"), "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    lock_file.write(str(os.getpid()))
    lock_file.flush()
    return lock_file


def main():
    lock = acquire_single_instance_lock()
    if lock is None:
        print("Triangulate App is already running - not starting a second instance.", file=sys.stderr)
        sys.exit(0)
    app = QApplication(sys.argv)
    
    # Ensure High DPI scaling is handled gracefully by PySide6 defaults
    window = MainWindow()
    window.resize(config.WINDOW_SIZE[0], config.WINDOW_SIZE[1])
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
