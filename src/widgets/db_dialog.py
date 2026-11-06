"""db_dialog.py - where the van's ARAN database is, and how to log in (src/camera_db.py).

Blank server = <VAN>-SERVER, then this PC.  Blank database = the van name.
A SQL password is stored with Windows' protection for this user on this PC only.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from src import camera_db


class DbDialog(QDialog):
    def __init__(self, van: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Van database")
        self._van = (van or "").strip().upper()
        s = camera_db.load_settings()
        self.server = QLineEdit(s.get("server", "")); self.server.setPlaceholderText(f"blank = {self._van or '<VAN>'}-SERVER, then this PC")
        self.database = QLineEdit(s.get("database", "")); self.database.setPlaceholderText(f"blank = {self._van or 'the van name'}")
        self.auth = QComboBox(); self.auth.addItems(["Windows sign-in", "SQL login"])
        self.auth.setCurrentIndex(1 if s.get("auth") == "sql" else 0)
        self.user = QLineEdit(s.get("user", ""))
        self.password = QLineEdit(); self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("stored on this PC only" if camera_db.stored_password() else "")
        self.result = QLabel(""); self.result.setWordWrap(True)
        test = QPushButton("Test")
        f = QFormLayout()
        f.addRow("Server:", self.server); f.addRow("Database:", self.database); f.addRow("Login:", self.auth)
        f.addRow("User:", self.user); f.addRow("Password:", self.password)
        note = QLabel("Read only: the app only reads the camera list (VideoDeviceConfig). "
                      "A password is kept with Windows' protection, for this user on this PC only.")
        note.setWordWrap(True); note.setStyleSheet("color: rgb(150,150,150); font-size: 8pt;")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        lay = QVBoxLayout(self); lay.addLayout(f); lay.addWidget(test); lay.addWidget(self.result); lay.addWidget(note); lay.addWidget(bb)
        test.clicked.connect(self._test); bb.accepted.connect(self._save); bb.rejected.connect(self.reject)
        self.auth.currentIndexChanged.connect(self._sql_fields); self._sql_fields()

    def _sql_fields(self):
        sql = self.auth.currentIndex() == 1
        self.user.setEnabled(sql); self.password.setEnabled(sql)

    def _settings(self) -> dict:
        return {"server": self.server.text().strip(), "database": self.database.text().strip(),
                "auth": "sql" if self.auth.currentIndex() == 1 else "windows", "user": self.user.text().strip()}

    def _store_pw(self):
        if self.auth.currentIndex() == 1 and self.password.text():
            camera_db.store_password(self.password.text())

    def _test(self):
        self._store_pw()
        s = self._settings()
        res = camera_db.lookup(self._van, s)
        self.result.setText(("OK: " + res.where + " - " + ", ".join(f"{c.camera} {c.serial}" for c in res.cameras.values()))
                            if not res.error else "Not OK: " + res.error)

    def _save(self):
        self._store_pw()
        camera_db.save_settings(self._settings())
        self.accept()
