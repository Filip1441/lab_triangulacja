import time
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
from PySide6.QtCore import Qt

from core import admin_auth

MAX_ATTEMPTS = 3
LOCKOUT_SEC = 30
_failures = 0
_locked_until = 0.0


class AdminLoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Admin")
        self.setMinimumWidth(340)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        title = QLabel("Admin access")
        title.setObjectName("dialogTitle")
        lay.addWidget(title)

        self.lbl_msg = QLabel("Enter the admin password.")
        self.lbl_msg.setWordWrap(True)
        lay.addWidget(self.lbl_msg)

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.returnPressed.connect(self.try_login)
        lay.addWidget(self.edit)

        row = QHBoxLayout()
        self.btn_ok = QPushButton("Unlock")
        self.btn_ok.clicked.connect(self.try_login)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setObjectName("secondary")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(self.btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

        if not admin_auth.is_configured():
            self.lbl_msg.setText("Admin password is not set.\nOn the Pi run: deploy/set-admin-password.sh")
            self.edit.setEnabled(False)
            self.btn_ok.setEnabled(False)

    def try_login(self):
        global _failures, _locked_until
        now = time.time()
        if now < _locked_until:
            self.lbl_msg.setText(f"Too many attempts. Wait {int(_locked_until - now) + 1} s.")
            return
        if admin_auth.verify(self.edit.text()):
            _failures = 0
            self.accept()
            return
        _failures += 1
        self.edit.clear()
        if _failures >= MAX_ATTEMPTS:
            _failures = 0
            _locked_until = time.time() + LOCKOUT_SEC
            self.lbl_msg.setText(f"Too many attempts. Locked for {LOCKOUT_SEC} s.")
        else:
            self.lbl_msg.setText("Wrong password.")


def request_admin_access(parent) -> bool:
    return AdminLoginDialog(parent).exec() == QDialog.Accepted
