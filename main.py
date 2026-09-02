import sys
import logging
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

# Setup minimal logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

import config

def main():
    app = QApplication(sys.argv)
    
    # Ensure High DPI scaling is handled gracefully by PySide6 defaults
    window = MainWindow()
    window.resize(config.WINDOW_SIZE[0], config.WINDOW_SIZE[1])
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
