import os
import segno
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QApplication
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


class ExportPage(QWidget):
    """
    Stage 4 tab. Opening it packs the student's work into a ZIP automatically (no click needed) and shows
    QR codes: join the Pi's Wi-Fi, then open the download page.
    """
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)

        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("font-size: 20px; font-weight: bold;")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_title)

        self.qr_row = QHBoxLayout()
        self.qr_row.setSpacing(40)
        lay.addLayout(self.qr_row)
        lay.addStretch(1)

        self.lbl_info = QLabel("")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.lbl_info.setWordWrap(True)
        self.lbl_info.setStyleSheet("font-size: 14px;")
        self.lbl_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.lbl_info)

        self.btn_repack = QPushButton("Pack again (include latest work)")
        self.btn_repack.clicked.connect(self.refresh)
        lay.addWidget(self.btn_repack)

    def _clear_qr(self):
        while self.qr_row.count():
            item = self.qr_row.takeAt(0)
            lay = item.layout()
            if lay:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w:
                        w.deleteLater()

    def _add_qr(self, caption, payload):
        col = QVBoxLayout()
        img = QLabel()
        img.setPixmap(qr_pixmap(payload, 360))
        img.setAlignment(Qt.AlignCenter)
        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignCenter)
        cap.setWordWrap(True)
        cap.setStyleSheet("font-size: 16px;")
        col.addWidget(img)
        col.addWidget(cap)
        self.qr_row.addLayout(col)

    def refresh(self):
        self._clear_qr()
        self.lbl_title.setText("Packing your results...")
        self.lbl_info.setText("")
        QApplication.processEvents()
        try:
            path = results.build_package(self.main_window)
            results.purge_old()
        except Exception as e:
            self.lbl_title.setText("Export failed")
            self.lbl_info.setText(str(e))
            return
        info = get_share_info()
        self.lbl_title.setText("Your results are saved and ready to download")
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
