"""Connection dialog for entering SSH credentials (PyQt6)."""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QRadioButton, QButtonGroup, QFileDialog,
    QMessageBox, QWidget, QFrame,
)
from PyQt6.QtCore import Qt

from core.session_manager import SavedSession, SessionManager


class ConnectionDialog(QDialog):
    """Modal dialog that collects SSH connection parameters.

    After exec(), check self.result (dict or None).
    """

    def __init__(self, parent: QWidget, session_mgr: SessionManager):
        super().__init__(parent)
        self.setWindowTitle("New Connection")
        self.setFixedSize(460, 340)
        self.setModal(True)

        self._session_mgr = session_mgr
        self.result: dict | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setSpacing(6)
        row = 0

        # Saved sessions
        sessions = self._session_mgr.sessions
        if sessions:
            grid.addWidget(QLabel("Saved sessions:"), row, 0)
            self._saved_cb = QComboBox()
            self._saved_cb.addItem("(select…)")
            for s in sessions:
                self._saved_cb.addItem(str(s))
            self._saved_cb.currentIndexChanged.connect(self._load_saved)
            grid.addWidget(self._saved_cb, row, 1, 1, 3)
            row += 1

            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            grid.addWidget(sep, row, 0, 1, 4)
            row += 1

        # Host / Port
        grid.addWidget(QLabel("Host:"), row, 0)
        self._host_edit = QLineEdit()
        grid.addWidget(self._host_edit, row, 1, 1, 2)
        grid.addWidget(QLabel("Port:"), row, 3)
        self._port_edit = QLineEdit("22")
        self._port_edit.setFixedWidth(60)
        grid.addWidget(self._port_edit, row, 4)
        row += 1

        # Username
        grid.addWidget(QLabel("Username:"), row, 0)
        self._user_edit = QLineEdit()
        grid.addWidget(self._user_edit, row, 1, 1, 4)
        row += 1

        # Auth type
        grid.addWidget(QLabel("Auth:"), row, 0)
        auth_layout = QHBoxLayout()
        self._auth_pw_radio = QRadioButton("Password")
        self._auth_key_radio = QRadioButton("Key file")
        self._auth_pw_radio.setChecked(True)
        auth_group = QButtonGroup(self)
        auth_group.addButton(self._auth_pw_radio)
        auth_group.addButton(self._auth_key_radio)
        auth_layout.addWidget(self._auth_pw_radio)
        auth_layout.addWidget(self._auth_key_radio)
        auth_layout.addStretch()
        grid.addLayout(auth_layout, row, 1, 1, 4)
        row += 1

        # Password field
        self._pw_label = QLabel("Password:")
        self._pw_edit = QLineEdit()
        self._pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self._pw_label, row, 0)
        grid.addWidget(self._pw_edit, row, 1, 1, 4)
        row += 1

        # Key file fields (hidden by default)
        self._key_label = QLabel("Key file:")
        self._key_edit = QLineEdit()
        self._key_browse = QPushButton("Browse…")
        self._key_browse.clicked.connect(self._browse_key)
        grid.addWidget(self._key_label, row, 0)
        grid.addWidget(self._key_edit, row, 1, 1, 3)
        grid.addWidget(self._key_browse, row, 4)
        row += 1

        self._pp_label = QLabel("Passphrase:")
        self._pp_edit = QLineEdit()
        self._pp_edit.setEchoMode(QLineEdit.EchoMode.Password)
        grid.addWidget(self._pp_label, row, 0)
        grid.addWidget(self._pp_edit, row, 1, 1, 4)
        row += 1

        layout.addLayout(grid)

        # Hide key fields by default
        self._key_label.hide()
        self._key_edit.hide()
        self._key_browse.hide()
        self._pp_label.hide()
        self._pp_edit.hide()

        self._auth_pw_radio.toggled.connect(self._toggle_auth)
        self._auth_key_radio.toggled.connect(self._toggle_auth)

        # Buttons
        btn_layout = QHBoxLayout()
        connect_btn = QPushButton("Connect")
        connect_btn.setDefault(True)
        connect_btn.clicked.connect(self._connect)
        btn_layout.addWidget(connect_btn)

        save_btn = QPushButton("Save Session")
        save_btn.clicked.connect(self._save_session)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addStretch()
        layout.addLayout(btn_layout)

    def _toggle_auth(self) -> None:
        is_key = self._auth_key_radio.isChecked()
        self._pw_label.setVisible(not is_key)
        self._pw_edit.setVisible(not is_key)
        self._key_label.setVisible(is_key)
        self._key_edit.setVisible(is_key)
        self._key_browse.setVisible(is_key)
        self._pp_label.setVisible(is_key)
        self._pp_edit.setVisible(is_key)

    def _browse_key(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Private Key File",
            os.path.expanduser("~/.ssh"))
        if path:
            self._key_edit.setText(path)

    def _load_saved(self, index: int) -> None:
        if index <= 0:
            return
        sessions = self._session_mgr.sessions
        s = sessions[index - 1]
        self._host_edit.setText(s.host)
        self._port_edit.setText(str(s.port))
        self._user_edit.setText(s.username)
        if s.auth_type == "key":
            self._auth_key_radio.setChecked(True)
            self._key_edit.setText(s.key_file or "")
        else:
            self._auth_pw_radio.setChecked(True)

    def _save_session(self) -> None:
        host = self._host_edit.text().strip()
        if not host:
            QMessageBox.critical(self, "Error", "Host is required.")
            return
        s = SavedSession(
            name=f"{self._user_edit.text().strip()}@{host}",
            host=host,
            port=self._port_int(),
            username=self._user_edit.text().strip(),
            auth_type="key" if self._auth_key_radio.isChecked() else "password",
            key_file=self._key_edit.text().strip(),
        )
        self._session_mgr.add_or_update(s)
        QMessageBox.information(self, "Saved", f"Session '{s.name}' saved.")

    def _port_int(self) -> int:
        try:
            return int(self._port_edit.text())
        except ValueError:
            return 22

    def _connect(self) -> None:
        host = self._host_edit.text().strip()
        if not host:
            QMessageBox.critical(self, "Error", "Host is required.")
            return
        auth_type = "key" if self._auth_key_radio.isChecked() else "password"
        self.result = {
            "host": host,
            "port": self._port_int(),
            "username": self._user_edit.text().strip(),
            "auth_type": auth_type,
            "password": self._pw_edit.text() if auth_type == "password" else None,
            "key_file": self._key_edit.text().strip() or None,
            "key_passphrase": self._pp_edit.text() or None,
        }
        self.accept()
