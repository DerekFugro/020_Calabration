"""db_dialog.py - where the van's ARAN database is, and how to log in (src/camera_db.py).

Blank server = <VAN>-SERVER, then this PC.  Blank database = the van name.
Login is always this PC's Windows sign-in: no SQL login, no password.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
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
        self.result = QLabel(""); self.result.setWordWrap(True)
        test = QPushButton("Test")
        f = QFormLayout()
        f.addRow("Server:", self.server); f.addRow("Database:", self.database)
        f.addRow("Login:", QLabel("Windows sign-in of this PC"))
        note = QLabel("Read only: the app only reads the camera list (VideoDeviceConfig). "
                      "It logs in as the Windows user running the app, so no password is needed or stored.")
        note.setWordWrap(True); note.setStyleSheet("color: rgb(150,150,150); font-size: 8pt;")
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        lay = QVBoxLayout(self); lay.addLayout(f); lay.addWidget(test); lay.addWidget(self.result); lay.addWidget(note); lay.addWidget(bb)
        test.clicked.connect(self._test); bb.accepted.connect(self._save); bb.rejected.connect(self.reject)

    def _settings(self) -> dict:
        return {"server": self.server.text().strip(), "database": self.database.text().strip()}

    def _test(self):
        s = self._settings()
        res = camera_db.lookup(self._van, s)
        self.result.setText(("OK: " + res.where + " - " + ", ".join(f"{c.camera} {c.serial}" for c in res.cameras.values()))
                            if not res.error else "Not OK: " + res.error)

    def _save(self):
        camera_db.save_settings(self._settings())
        self.accept()
