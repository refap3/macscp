"""Main application window for MacSCP (PyQt6)."""

import os
import subprocess
import threading
import time

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QMenuBar, QToolBar, QStatusBar, QLabel, QComboBox, QMessageBox,
    QTextEdit, QPushButton, QInputDialog, QFrame, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QFont, QColor, QShortcut, QKeySequence

from gui._invoke import invoke_in_main

from core.session_manager import SavedSession, SessionManager
from core.ssh_client import SSHClient
from gui.connection_dialog import ConnectionDialog
from gui.file_panel import FilePanel
from gui.overwrite_dialog import OverwriteDialog
from gui.transfer_dialog import TransferDialog


# ---------------------------------------------------------------------------
# Session tab
# ---------------------------------------------------------------------------

class SessionTab(QWidget):
    """One tab = one SSH connection + dual file panels."""

    def __init__(self, session_mgr: SessionManager, log_fn=None, parent=None):
        super().__init__(parent)
        self._session_mgr = session_mgr
        self._ssh: SSHClient | None = None
        self._log = log_fn or (lambda *_: None)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self._local = FilePanel(is_remote=False)
        self._remote = FilePanel(is_remote=True)
        splitter.addWidget(self._local)
        splitter.addWidget(self._remote)
        splitter.setSizes([500, 500])
        layout.addWidget(splitter)

    @property
    def ssh(self) -> SSHClient | None:
        return self._ssh

    @property
    def local_panel(self) -> FilePanel:
        return self._local

    @property
    def remote_panel(self) -> FilePanel:
        return self._remote

    def set_ssh(self, client: SSHClient) -> None:
        self._ssh = client
        self._remote.set_ssh_client(client)
        self._remote.navigate_to_home()
        client.start_keepalive(30)

    def disconnect(self) -> None:
        if self._ssh:
            try:
                self._ssh.disconnect()
            except Exception:
                pass
            self._ssh = None
        self._remote.set_ssh_client(None)
        self._remote.show_disconnected()

    def upload(self, preselected=None) -> None:
        _do_transfer(self.window(), self._ssh, self._local, self._remote,
                     "upload", preselected=preselected, log_fn=self._log)

    def download(self, preselected=None) -> None:
        _do_transfer(self.window(), self._ssh, self._local, self._remote,
                     "download", preselected=preselected, log_fn=self._log)

    def refresh(self) -> None:
        self._local.refresh()
        self._remote.refresh()


# ---------------------------------------------------------------------------
# File transfer
# ---------------------------------------------------------------------------

def _do_transfer(parent, ssh, local, remote, direction,
                 preselected=None, log_fn=None):
    if not ssh or not ssh.connected:
        QMessageBox.warning(parent, "Not connected",
                            "Please connect to a remote host first.")
        return

    if direction == "upload":
        selected = preselected or local.get_selected_entries()
        dest_dir = remote.get_current_path()
        if not selected:
            QMessageBox.information(parent, "Upload",
                                    "Select local files/folders to upload.")
            return
        if not dest_dir:
            QMessageBox.information(parent, "Upload",
                                    "Navigate to a remote destination first.")
            return
    else:
        selected = preselected or remote.get_selected_entries()
        dest_dir = local.get_current_path()
        if not selected:
            QMessageBox.information(parent, "Download",
                                    "Select remote files/folders to download.")
            return
        if not dest_dir:
            QMessageBox.information(parent, "Download",
                                    "Navigate to a local destination first.")
            return

    dialog = TransferDialog(parent, direction.capitalize())
    dialog.show()

    state = {
        "current_file": "",
        "current_num": 0,
        "total_files": len(selected),
        "file_progress": 0,
        "file_total": 0,
        "done": False,
        "error": None,
        "ow_event": threading.Event(),
        "ow_result": [None],
        "overwrite_all": False,
        "skip_all": False,
    }

    def ask_overwrite(filename, src_info, dst_info):
        if state["overwrite_all"]:
            return "overwrite"
        if state["skip_all"]:
            return "skip"
        state["ow_event"].clear()
        state["ow_result"][0] = None

        def show_dlg():
            dlg = OverwriteDialog(parent, filename, src_info, dst_info)
            dlg.exec()
            result = dlg.result
            if result == "overwrite_all":
                state["overwrite_all"] = True
                result = "overwrite"
            elif result == "skip_all":
                state["skip_all"] = True
                result = "skip"
            state["ow_result"][0] = result
            state["ow_event"].set()

        invoke_in_main(show_dlg)
        state["ow_event"].wait()
        return state["ow_result"][0] or "cancel"

    def check_overwrite(entry, dest_path):
        if entry["is_dir"]:
            return "overwrite"
        if direction == "upload":
            exists = ssh.file_exists(dest_path)
            src_info = entry
            dst_info = None
        else:
            exists = os.path.exists(dest_path)
            src_info = entry
            dst_info = {"size": os.path.getsize(dest_path)} if exists else None
        if not exists:
            return "overwrite"
        return ask_overwrite(entry["name"], src_info, dst_info)

    def progress(done, total):
        if dialog.cancelled:
            raise InterruptedError("Cancelled by user")
        state["file_progress"] = done
        state["file_total"] = total

    results = []

    def worker():
        for i, entry in enumerate(selected):
            if dialog.cancelled:
                break
            state["current_num"] = i
            state["current_file"] = entry["name"]
            state["file_progress"] = 0
            state["file_total"] = entry.get("size", 0)

            if direction == "upload":
                dest = dest_dir.rstrip("/") + "/" + entry["name"]
            else:
                dest = os.path.join(dest_dir, entry["name"])

            action = check_overwrite(entry, dest)
            if action == "cancel":
                break
            if action == "skip":
                results.append(f"Skipped: {entry['name']}")
                continue

            try:
                if direction == "upload":
                    ssh.upload_tree(entry["path"], dest_dir, state, progress)
                else:
                    ssh.download_tree(entry["path"], dest_dir, entry["is_dir"],
                                      state, progress)
                arrow = ">>>" if direction == "upload" else "<<<"
                results.append(f"{arrow} {entry['name']}  ->  {dest_dir}")
            except InterruptedError:
                break
            except Exception as exc:
                state["error"] = str(exc)
                results.append(f"ERROR {entry['name']}: {exc}")
                break

        state["done"] = True

    threading.Thread(target=worker, daemon=True).start()

    timer = QTimer(parent)

    def poll():
        if not dialog.isVisible():
            timer.stop()
            return
        dialog.update_from_state(state)
        if dialog.cancelled or state["done"]:
            timer.stop()
            dialog.close()
            if state.get("error"):
                QMessageBox.critical(parent, "Transfer error", state["error"])
            if log_fn and results:
                for r in results:
                    log_fn(r)
            if direction == "upload":
                remote.refresh()
            else:
                local.refresh()

    timer.timeout.connect(poll)
    timer.start(250)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class MacSCPApp(QMainWindow):
    """Top-level MacSCP window with menu, toolbar, tabbed sessions, and log."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MacSCP")
        self.resize(1320, 820)
        self.setMinimumSize(900, 560)

        self._session_mgr = SessionManager()
        self._tabs: list[SessionTab] = []

        self._build_menu()
        self._build_toolbar()
        self._build_central()
        self._build_log_panel()
        self._build_statusbar()

        self._add_tab("Unconnected")

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()

        fm = bar.addMenu("File")
        self._add_action(fm, "New Connection…", self._new_connection, "Ctrl+N")
        self._add_action(fm, "New Tab", self._new_tab, "Ctrl+T")
        self._add_action(fm, "Close Tab", self._close_tab, "Ctrl+W")
        fm.addSeparator()
        self._add_action(fm, "Disconnect", self._disconnect)
        fm.addSeparator()
        self._add_action(fm, "Quit", self.close, "Ctrl+Q")

        vm = bar.addMenu("View")
        self._add_action(vm, "Refresh", self._refresh, "Ctrl+R")
        vm.addSeparator()
        self._add_action(vm, "Toggle Log Panel", self._toggle_log)

        tm = bar.addMenu("Transfer")
        self._add_action(tm, "Upload", self._upload, "Ctrl+U")
        self._add_action(tm, "Download", self._download, "Ctrl+D")

        rm = bar.addMenu("Remote")
        self._add_action(rm, "Open SSH Terminal", self._open_remote_term)
        self._add_action(rm, "Go to Home Directory", self._remote_home)
        self._add_action(rm, "Execute Command…", self._exec_command)

        lm = bar.addMenu("Local")
        self._add_action(lm, "Open Terminal", self._open_local_term)
        self._add_action(lm, "Go to Home Directory", self._local_home)

    def _add_action(self, menu, text, callback, shortcut=None):
        action = menu.addAction(text)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addAction("Connect", self._new_connection)
        self._disc_action = tb.addAction("Disconnect", self._disconnect)
        self._disc_action.setEnabled(False)
        tb.addSeparator()

        # Session combobox
        tb.addWidget(QLabel(" Session: "))
        self._session_cb = QComboBox()
        self._session_cb.setMinimumWidth(180)
        self._session_cb.activated.connect(self._quick_connect)
        tb.addWidget(self._session_cb)
        self._refresh_session_combobox()
        tb.addSeparator()

        tb.addAction("+ Tab", self._new_tab)
        tb.addSeparator()
        tb.addAction("Refresh", self._refresh)
        tb.addSeparator()
        tb.addAction("Upload >>>", self._upload)
        tb.addAction("<<< Download", self._download)
        tb.addSeparator()
        tb.addAction("SSH Terminal", self._open_remote_term)
        tb.addAction("Exec Cmd…", self._exec_command)
        tb.addSeparator()
        tb.addAction("Log", self._toggle_log)

        # Spacer + connection status
        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy(),
                             spacer.sizePolicy().verticalPolicy())
        from PyQt6.QtWidgets import QSizePolicy
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)

        self._conn_dot = QLabel("  ")
        self._conn_dot.setFixedSize(14, 14)
        self._set_dot("#BBBBBB")
        tb.addWidget(self._conn_dot)

        self._conn_label = QLabel("Not connected")
        self._conn_label.setStyleSheet("color: #444; margin-left: 4px;")
        tb.addWidget(self._conn_label)

    def _set_dot(self, color: str) -> None:
        self._conn_dot.setStyleSheet(
            f"background-color: {color}; border-radius: 7px; margin: 2px;")

    def _refresh_session_combobox(self) -> None:
        self._session_cb.clear()
        sessions = self._session_mgr.sessions
        if sessions:
            self._session_cb.addItem("(select session…)")
            for s in sessions:
                self._session_cb.addItem(str(s))
            self._session_cb.setEnabled(True)
        else:
            self._session_cb.addItem("(no saved sessions)")
            self._session_cb.setEnabled(False)

    def _quick_connect(self, index: int) -> None:
        if index <= 0:
            return
        sessions = self._session_mgr.sessions
        s = sessions[index - 1]
        pw = None
        if s.auth_type == "password":
            from PyQt6.QtWidgets import QLineEdit
            pw, ok = QInputDialog.getText(self, "Password",
                                          f"Password for {s}:",
                                          QLineEdit.EchoMode.Password)
            if not ok:
                return
        self._connect({
            "host": s.host,
            "port": s.port,
            "username": s.username,
            "auth_type": s.auth_type,
            "password": pw,
            "key_file": s.key_file or None,
            "key_passphrase": None,
        })

    # ------------------------------------------------------------------
    # Central widget (tabs)
    # ------------------------------------------------------------------

    def _build_central(self) -> None:
        self._central = QWidget()
        self._central_layout = QVBoxLayout(self._central)
        self._central_layout.setContentsMargins(4, 4, 4, 0)

        self._tab_widget = QTabWidget()
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._central_layout.addWidget(self._tab_widget)

        self.setCentralWidget(self._central)

    def _add_tab(self, title: str) -> SessionTab:
        tab = SessionTab(self._session_mgr, log_fn=self._log)
        self._tabs.append(tab)
        self._tab_widget.addTab(tab, f"  {title}  ")
        self._tab_widget.setCurrentWidget(tab)
        return tab

    def _current_tab(self) -> SessionTab | None:
        idx = self._tab_widget.currentIndex()
        if 0 <= idx < len(self._tabs):
            return self._tabs[idx]
        return None

    def _on_tab_changed(self, idx: int) -> None:
        tab = self._current_tab()
        if tab and tab.ssh:
            self._conn_label.setText(f"Connected: {tab.ssh.label}")
            self._disc_action.setEnabled(True)
            self._set_dot("#4CAF50")
        else:
            self._conn_label.setText("Not connected")
            self._disc_action.setEnabled(False)
            self._set_dot("#BBBBBB")

    # ------------------------------------------------------------------
    # Log panel
    # ------------------------------------------------------------------

    def _build_log_panel(self) -> None:
        self._log_frame = QFrame()
        self._log_frame.setFrameShape(QFrame.Shape.StyledPanel)
        log_layout = QVBoxLayout(self._log_frame)
        log_layout.setContentsMargins(4, 4, 4, 4)

        header = QHBoxLayout()
        header.addWidget(QLabel("<b>Transfer Log</b>"))
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear_log)
        header.addWidget(clear_btn)
        header.addStretch()
        hide_btn = QPushButton("Hide")
        hide_btn.clicked.connect(self._toggle_log)
        header.addWidget(hide_btn)
        log_layout.addLayout(header)

        self._log_text = QTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setFont(QFont("Menlo", 10))
        self._log_text.setMaximumHeight(150)
        log_layout.addWidget(self._log_text)

        self._log_visible = False
        self._log_frame.hide()
        self._central_layout.addWidget(self._log_frame)

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        self._log_frame.setVisible(self._log_visible)

    def _log(self, message: str) -> None:
        def _append():
            ts = time.strftime("%H:%M:%S")
            self._log_text.append(f"[{ts}]  {message}")
            if not self._log_visible:
                self._toggle_log()

        invoke_in_main(_append)

    def _clear_log(self) -> None:
        self._log_text.clear()

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_statusbar(self) -> None:
        self._statusbar = self.statusBar()
        self._statusbar.showMessage("Ready")

    def _set_status(self, msg: str) -> None:
        self._statusbar.showMessage(msg)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _new_connection(self) -> None:
        dlg = ConnectionDialog(self, self._session_mgr)
        if dlg.exec():
            self._connect(dlg.result)

    def _connect(self, params: dict) -> None:
        host = params["host"]
        self._set_status(f"Connecting to {host}…")
        self._set_dot("#FF9800")

        tab = self._current_tab()
        if tab and tab.ssh:
            tab = self._add_tab(host)
        elif tab is None:
            tab = self._add_tab(host)

        def worker():
            client = SSHClient()
            try:
                client.connect(
                    host=params["host"],
                    port=params["port"],
                    username=params["username"],
                    password=params.get("password"),
                    key_file=params.get("key_file"),
                    key_passphrase=params.get("key_passphrase"),
                )
                invoke_in_main(lambda: self._on_connected(tab, client, params))
            except Exception as exc:
                msg = str(exc)
                invoke_in_main(lambda: self._on_connect_failed(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connected(self, tab: SessionTab, client: SSHClient, params: dict) -> None:
        tab.set_ssh(client)
        label = f"{params['username']}@{params['host']}"
        idx = self._tabs.index(tab)
        self._tab_widget.setTabText(idx, f"  {label}  ")
        self._conn_label.setText(f"Connected: {client.label}")
        self._set_dot("#4CAF50")
        self._disc_action.setEnabled(True)
        self.setWindowTitle(f"MacSCP — {label}")
        self._set_status(f"Connected to {params['host']}")
        self._log(f"Connected to {client.label}")

        s = SavedSession(
            name=label,
            host=params["host"],
            port=params["port"],
            username=params["username"],
            auth_type=params.get("auth_type", "password"),
            key_file=params.get("key_file") or "",
        )
        self._session_mgr.add_or_update(s)
        self._refresh_session_combobox()

    def _on_connect_failed(self, error: str) -> None:
        self._set_dot("#F44336")
        QMessageBox.critical(self, "Connection failed", error)
        self._set_status("Connection failed.")
        self._set_dot("#BBBBBB")

    def _disconnect(self) -> None:
        tab = self._current_tab()
        if tab:
            label = tab.ssh.label if tab.ssh else ""
            tab.disconnect()
            if label:
                self._log(f"Disconnected from {label}")
        self._conn_label.setText("Not connected")
        self._set_dot("#BBBBBB")
        self._disc_action.setEnabled(False)
        self.setWindowTitle("MacSCP")
        self._set_status("Disconnected.")

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _new_tab(self) -> None:
        self._add_tab("Unconnected")
        self._conn_label.setText("Not connected")
        self._set_dot("#BBBBBB")
        self._disc_action.setEnabled(False)

    def _close_tab(self) -> None:
        tab = self._current_tab()
        if not tab:
            return
        if tab.ssh:
            reply = QMessageBox.question(self, "Close tab",
                                         "Disconnect and close this tab?")
            if reply != QMessageBox.StandardButton.Yes:
                return
            tab.disconnect()
        idx = self._tabs.index(tab)
        self._tabs.pop(idx)
        self._tab_widget.removeTab(idx)
        if not self._tabs:
            self._add_tab("Unconnected")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.refresh()

    def _upload(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.upload()

    def _download(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.download()

    def _open_remote_term(self) -> None:
        tab = self._current_tab()
        if tab and tab.ssh and tab.ssh.connected:
            tab.ssh.open_terminal()
        else:
            QMessageBox.information(self, "Not connected",
                                    "Connect to a remote host first.")

    def _open_local_term(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.local_panel._open_terminal()

    def _remote_home(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.remote_panel.navigate_to_home()

    def _local_home(self) -> None:
        tab = self._current_tab()
        if tab:
            tab.local_panel.navigate_to_home()

    def _exec_command(self) -> None:
        tab = self._current_tab()
        if not tab or not tab.ssh or not tab.ssh.connected:
            QMessageBox.information(self, "Not connected",
                                    "Connect to a remote host first.")
            return

        cmd, ok = QInputDialog.getText(self, "Execute Command",
                                       "Command to run on remote host:")
        if not ok or not cmd:
            return

        self._set_status(f"Running: {cmd}")

        def worker():
            try:
                stdout, stderr = tab.ssh.exec_command(cmd)
                output = stdout or stderr or "(no output)"
            except Exception as exc:
                output = f"Error: {exc}"
            invoke_in_main(lambda: self._show_output(cmd, output))
            invoke_in_main(lambda: self._set_status("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_output(self, cmd: str, output: str) -> None:
        from PyQt6.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Output: {cmd[:60]}")
        dlg.resize(700, 420)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(f"$ {cmd}"))
        txt = QTextEdit()
        txt.setPlainText(output)
        txt.setReadOnly(True)
        txt.setFont(QFont("Menlo", 11))
        layout.addWidget(txt)
        dlg.show()

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        for tab in self._tabs:
            try:
                tab.disconnect()
            except Exception:
                pass
        event.accept()
