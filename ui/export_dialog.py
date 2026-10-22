import os
import segno
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from PySide6.QtCore import Qt

import config
from core import results
from core.network_info import get_share_info


def qr_pixmap(text: str, size: int = 230) -> QPixmap:
    """Renders a QR code (with quiet zone) as a QPixmap without any imaging dependency."""
    rows = [list(r) for r in segno.make(text, error="m").matrix_iter(scale=1, border=4)]
    n = len(rows)
    cell = max(1, size // n)
    img = QImage(n * cell, n * cell, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(rows):
        for x, v in enumerate(row):
            if v:
                p.drawRect(x * cell, y * cell, cell, cell)
    p.end()
    return QPixmap.fromImage(img)


class ExportDialog(QDialog):
    """Packs the student's work into a ZIP and shows QR codes: join the Pi's Wi-Fi, then open the download page."""
    def __init__(self, main_window):
        super().__init__(main_window)
        self.setWindowTitle("Finish & Export")
        self.setMinimumWidth(620)
        lay = QVBoxLayout(self)

        self.lbl_title = QLabel("Packing your results...")
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        lay.addWidget(self.lbl_title)

        self.qr_row = QHBoxLayout()
        lay.addLayout(self.qr_row)
        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_info)

        btn = QPushButton("Close")
        btn.clicked.connect(self.close)
        lay.addWidget(btn)

        QApplication.processEvents()
        self.build(main_window)

    def _add_qr(self, caption, payload):
        col = QVBoxLayout()
        img = QLabel()
        img.setPixmap(qr_pixmap(payload))
        img.setAlignment(Qt.AlignCenter)
        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignCenter)
        cap.setWordWrap(True)
        col.addWidget(img)
        col.addWidget(cap)
        self.qr_row.addLayout(col)

    def build(self, mw):
        try:
            path = results.build_package(mw)
            results.purge_old()
        except Exception as e:
            self.lbl_title.setText("Export failed")
            self.lbl_info.setText(str(e))
            return
        info = get_share_info()
        self.lbl_title.setText("Your results are ready")
        if info["wifi_qr"]:
            self._add_qr("1. Scan: join the Wi-Fi", info["wifi_qr"])
        self._add_qr("2. Scan: open the download page" if info["wifi_qr"] else "Scan: open the download page",
                     info["url"])
        text = f"File: {os.path.basename(path)}  |  Page: {info['url']}"
        if info["mode"] == "hotspot":
            text += f"\nWi-Fi: {info['ssid']}" + (f"  |  password: {info['password']}" if info["password"] else "")
        elif info["mode"] == "client":
            text += f"\nThe Pi is on Wi-Fi '{info['ssid']}' - connect your phone to the same network."
        text += f"\nFiles are deleted after {config.RESULTS_KEEP_DAYS} days."
        self.lbl_info.setText(text)
