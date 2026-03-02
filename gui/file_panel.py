"""Dual-purpose file browser panel (local or remote) using PyQt6."""

import json
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QLineEdit, QPushButton, QMenu, QMessageBox, QInputDialog,
    QHeaderView, QAbstractItemView, QDialog, QTextEdit, QScrollBar,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont

from gui._invoke import invoke_in_main

BOOKMARKS_FILE = os.path.expanduser("~/.macscp/bookmarks.json")


# ---------------------------------------------------------------------------
# Local filesystem helpers
# ---------------------------------------------------------------------------

def local_list_dir(path: str) -> list[dict]:
    """Return sorted list of entry dicts for a local directory."""
    try:
        items = list(os.scandir(path))
    except PermissionError:
        raise RuntimeError(f"Permission denied: {path}")
    except FileNotFoundError:
        raise RuntimeError(f"Directory not found: {path}")

    entries = []
    for item in items:
        try:
            s = item.stat(follow_symlinks=False)
            is_dir = stat.S_ISDIR(s.st_mode)
            if not is_dir and stat.S_ISLNK(s.st_mode):
                is_dir = item.is_dir(follow_symlinks=True)
            entries.append({
                "name": item.name,
                "path": item.path,
                "is_dir": is_dir,
                "size": s.st_size if not is_dir else 0,
                "modified": datetime.fromtimestamp(s.st_mtime),
                "permissions": oct(stat.S_IMODE(s.st_mode)),
            })
        except Exception:
            continue

    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    return entries


def _fmt_size(size: int, is_dir: bool) -> str:
    if is_dir:
        return "<DIR>"
    if size < 1024:
        return f"{size} B"
    elif size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB"
    else:
        return f"{size / 1_073_741_824:.1f} GB"


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

def _load_bookmarks() -> list[dict]:
    if not os.path.exists(BOOKMARKS_FILE):
        return []
    try:
        with open(BOOKMARKS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save_bookmarks(bm: list[dict]) -> None:
    os.makedirs(os.path.dirname(BOOKMARKS_FILE), exist_ok=True)
    try:
        with open(BOOKMARKS_FILE, "w") as f:
            json.dump(bm, f, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# FilePanel
# ---------------------------------------------------------------------------

class FilePanel(QWidget):
    """File-browser panel that works for both local and remote filesystems."""

    # Signal emitted when navigation finishes (for status updates)
    status_changed = pyqtSignal(str)

    def __init__(self, is_remote: bool = False, parent=None):
        super().__init__(parent)
        self.is_remote = is_remote
        self._ssh = None
        self._current_path = ""
        self._entries: list[dict] = []
        self._filtered: list[dict] = []
        self._show_hidden = False
        self._filter_text = ""
        self._sort_col = 0
        self._sort_rev = False
        self._history: list[str] = []
        self._hist_idx = -1
        self._navigating = False

        self._build_ui()

        if not is_remote:
            self._navigate_to(str(Path.home()))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_ssh_client(self, client) -> None:
        self._ssh = client

    def navigate_to_home(self) -> None:
        if self.is_remote and self._ssh:
            self._set_status("Loading…")

            def fetch():
                home = self._ssh.get_home_dir()
                invoke_in_main(lambda: self._navigate_to(home))

            threading.Thread(target=fetch, daemon=True).start()
        elif not self.is_remote:
            self._navigate_to(str(Path.home()))

    def get_current_path(self) -> str:
        return self._current_path

    def get_selected_entries(self) -> list[dict]:
        result = []
        for item in self._tree.selectedItems():
            idx = self._tree.indexOfTopLevelItem(item)
            if 0 <= idx < len(self._filtered):
                result.append(self._filtered[idx])
        return result

    def refresh(self) -> None:
        if self._current_path:
            self._navigate_to(self._current_path, add_history=False)

    def show_disconnected(self) -> None:
        self._tree.clear()
        self._entries.clear()
        self._filtered.clear()
        self._set_status("Not connected")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        label = QLabel("Remote" if self.is_remote else "Local")
        label.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(label)
        header.addStretch()

        self._bookmark_btn = QPushButton("Bookmarks")
        self._bookmark_btn.clicked.connect(self._show_bookmarks_menu)
        header.addWidget(self._bookmark_btn)
        layout.addLayout(header)

        # Navigation bar
        nav = QHBoxLayout()

        self._back_btn = QPushButton("<")
        self._back_btn.setFixedWidth(30)
        self._back_btn.setEnabled(False)
        self._back_btn.clicked.connect(self._go_back)
        nav.addWidget(self._back_btn)

        self._up_btn = QPushButton("^")
        self._up_btn.setFixedWidth(30)
        self._up_btn.clicked.connect(self._go_up)
        nav.addWidget(self._up_btn)

        self._home_btn = QPushButton("~")
        self._home_btn.setFixedWidth(30)
        self._home_btn.clicked.connect(self.navigate_to_home)
        nav.addWidget(self._home_btn)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        nav.addWidget(self._refresh_btn)

        self._path_edit = QLineEdit()
        self._path_edit.returnPressed.connect(self._on_path_enter)
        nav.addWidget(self._path_edit)

        layout.addLayout(nav)

        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Type to filter…")
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        filter_bar.addWidget(self._filter_edit)

        self._hidden_btn = QPushButton("Show Hidden")
        self._hidden_btn.setCheckable(True)
        self._hidden_btn.toggled.connect(self._on_hidden_toggle)
        filter_bar.addWidget(self._hidden_btn)
        layout.addLayout(filter_bar)

        # Tree widget
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Name", "Size", "Modified", "Permissions"])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSortingEnabled(False)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemDoubleClicked.connect(self._on_double_click)

        # Column widths
        hdr = self._tree.header()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.sectionClicked.connect(self._on_header_click)

        layout.addWidget(self._tree)

        # Status bar
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(self._status_label)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate_to(self, path: str, add_history: bool = True) -> None:
        if self._navigating:
            return
        self._navigating = True
        self._set_status(f"Loading {path}…")

        def fetch():
            try:
                if self.is_remote:
                    if not self._ssh or not self._ssh.connected:
                        raise RuntimeError("Not connected")
                    entries = self._ssh.list_directory(path)
                else:
                    entries = local_list_dir(path)
                invoke_in_main(lambda: self._finish_navigate(path, entries, add_history))
            except Exception as exc:
                msg = str(exc)
                invoke_in_main(lambda: self._navigate_error(msg))

        threading.Thread(target=fetch, daemon=True).start()

    def _finish_navigate(self, path: str, entries: list[dict], add_history: bool) -> None:
        self._navigating = False
        self._current_path = path
        self._entries = entries
        self._path_edit.setText(path)

        if add_history:
            if self._hist_idx < len(self._history) - 1:
                self._history = self._history[:self._hist_idx + 1]
            self._history.append(path)
            self._hist_idx = len(self._history) - 1

        self._back_btn.setEnabled(self._hist_idx > 0)
        self._apply_filter()

    def _navigate_error(self, error: str) -> None:
        self._navigating = False
        self._set_status("Error")
        QMessageBox.critical(self, "Error", error)

    def _go_back(self) -> None:
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._navigate_to(self._history[self._hist_idx], add_history=False)

    def _go_up(self) -> None:
        if not self._current_path:
            return
        if self.is_remote:
            parts = self._current_path.rstrip("/").rsplit("/", 1)
            parent = parts[0] if len(parts) > 1 and parts[0] else "/"
        else:
            parent = str(Path(self._current_path).parent)
        if parent != self._current_path:
            self._navigate_to(parent)

    def _on_path_enter(self) -> None:
        path = self._path_edit.text().strip()
        if path:
            self._navigate_to(path)

    # ------------------------------------------------------------------
    # Filter & display
    # ------------------------------------------------------------------

    def _on_filter_changed(self, text: str) -> None:
        self._filter_text = text.lower()
        self._apply_filter()

    def _on_hidden_toggle(self, checked: bool) -> None:
        self._show_hidden = checked
        self._apply_filter()

    def _apply_filter(self) -> None:
        entries = self._entries
        if not self._show_hidden:
            entries = [e for e in entries if not e["name"].startswith(".")]
        if self._filter_text:
            entries = [e for e in entries if self._filter_text in e["name"].lower()]
        self._filtered = entries
        self._populate_tree()

    def _populate_tree(self) -> None:
        self._tree.clear()
        dir_color = QColor("#1565C0")
        hidden_color = QColor("#888888")
        hidden_dir_color = QColor("#7B9FCC")

        for entry in self._filtered:
            name = entry["name"]
            size_str = _fmt_size(entry.get("size", 0), entry["is_dir"])
            mod = entry.get("modified")
            mod_str = mod.strftime("%Y-%m-%d %H:%M") if mod else ""
            perms = entry.get("permissions", "")

            item = QTreeWidgetItem([name, size_str, mod_str, perms])

            is_hidden = name.startswith(".")
            if is_hidden and entry["is_dir"]:
                item.setForeground(0, hidden_dir_color)
            elif is_hidden:
                item.setForeground(0, hidden_color)
            elif entry["is_dir"]:
                item.setForeground(0, dir_color)

            # Right-align size column
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self._tree.addTopLevelItem(item)

        n = len(self._filtered)
        total = len(self._entries)
        hidden_count = total - len([e for e in self._entries if not e["name"].startswith(".")])
        if self._filter_text:
            self._set_status(f"{n} match{'es' if n != 1 else ''} / {total} items")
        elif not self._show_hidden and hidden_count:
            self._set_status(f"{n} items ({hidden_count} hidden)")
        else:
            self._set_status(f"{n} item{'s' if n != 1 else ''}")

    def _on_header_click(self, col: int) -> None:
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = False

        key_fns = {
            0: lambda x: (not x["is_dir"], x["name"].lower()),
            1: lambda x: (not x["is_dir"], x.get("size", 0)),
            2: lambda x: (not x["is_dir"], x.get("modified") or datetime.min),
            3: lambda x: (not x["is_dir"], x.get("permissions", "")),
        }
        key = key_fns.get(col, key_fns[0])
        self._entries.sort(key=key, reverse=self._sort_rev)
        self._apply_filter()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_double_click(self, item: QTreeWidgetItem, column: int) -> None:
        idx = self._tree.indexOfTopLevelItem(item)
        if 0 <= idx < len(self._filtered):
            entry = self._filtered[idx]
            if entry["is_dir"]:
                self._navigate_to(entry["path"])

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, pos) -> None:
        selected = self.get_selected_entries()
        menu = QMenu(self)

        if len(selected) == 1:
            entry = selected[0]
            if entry["is_dir"]:
                menu.addAction("Open", lambda: self._navigate_to(entry["path"]))
            else:
                menu.addAction("Edit in VSCode", lambda: self._edit_vscode(entry))
                menu.addAction("View contents", lambda: self._view_file(entry))
            menu.addAction("Properties", lambda: self._show_properties(entry))
            menu.addSeparator()

        if selected:
            menu.addAction("Copy Path", self._copy_path)
            menu.addAction("Delete", self._delete_selected)
            menu.addAction("Rename…", self._rename_selected)
            menu.addSeparator()

        menu.addAction("Select All", self._select_all)
        menu.addSeparator()
        menu.addAction("New Folder…", self._new_folder)
        menu.addAction("New File…", self._new_file)
        menu.addSeparator()
        menu.addAction("Add Bookmark", self._add_bookmark)
        menu.addSeparator()
        menu.addAction("Open Terminal", self._open_terminal)
        menu.addSeparator()
        menu.addAction("Refresh", self.refresh)

        menu.exec(self._tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _delete_selected(self) -> None:
        selected = self.get_selected_entries()
        if not selected:
            return
        names = [e["name"] for e in selected]
        msg = f"Delete '{names[0]}'?" if len(names) == 1 else f"Delete {len(names)} items?"
        reply = QMessageBox.question(self, "Confirm Delete", msg)
        if reply != QMessageBox.StandardButton.Yes:
            return

        if self.is_remote:
            def do_delete():
                errors = []
                for e in selected:
                    try:
                        if e["is_dir"]:
                            self._ssh.remove_dir(e["path"])
                        else:
                            self._ssh.remove_file(e["path"])
                    except Exception as exc:
                        errors.append(f"{e['name']}: {exc}")
                if errors:
                    raise Exception("\n".join(errors))

            self._run_threaded(do_delete, lambda _: self.refresh(), "Deleting…")
        else:
            errors = []
            for e in selected:
                try:
                    if e["is_dir"]:
                        shutil.rmtree(e["path"])
                    else:
                        os.remove(e["path"])
                except Exception as exc:
                    errors.append(f"{e['name']}: {exc}")
            if errors:
                QMessageBox.critical(self, "Error", "\n".join(errors))
            self.refresh()

    def _rename_selected(self) -> None:
        selected = self.get_selected_entries()
        if len(selected) != 1:
            QMessageBox.information(self, "Rename", "Select exactly one item to rename.")
            return
        entry = selected[0]
        new_name, ok = QInputDialog.getText(self, "Rename", f"New name for '{entry['name']}':",
                                            text=entry["name"])
        if not ok or not new_name or new_name == entry["name"]:
            return

        if self.is_remote:
            new_path = self._current_path.rstrip("/") + "/" + new_name
            self._run_threaded(
                lambda: self._ssh.rename(entry["path"], new_path),
                lambda _: self.refresh(),
                f"Renaming {entry['name']}…"
            )
        else:
            new_path = os.path.join(self._current_path, new_name)
            try:
                os.rename(entry["path"], new_path)
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))
            self.refresh()

    def _new_folder(self) -> None:
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if not ok or not name:
            return
        if self.is_remote:
            path = self._current_path.rstrip("/") + "/" + name
            self._run_threaded(
                lambda: self._ssh.mkdir(path),
                lambda _: self.refresh(),
                "Creating folder…"
            )
        else:
            path = os.path.join(self._current_path, name)
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))
            self.refresh()

    def _new_file(self) -> None:
        name, ok = QInputDialog.getText(self, "New File", "File name:")
        if not ok or not name:
            return
        if self.is_remote:
            path = self._current_path.rstrip("/") + "/" + name
            self._run_threaded(
                lambda: self._ssh.create_file(path),
                lambda _: self.refresh(),
                "Creating file…"
            )
        else:
            path = os.path.join(self._current_path, name)
            try:
                open(path, "w").close()
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))
            self.refresh()

    def _select_all(self) -> None:
        self._tree.selectAll()

    def _copy_path(self) -> None:
        selected = self.get_selected_entries()
        if selected:
            from PyQt6.QtWidgets import QApplication
            paths = "\n".join(e["path"] for e in selected)
            QApplication.clipboard().setText(paths)

    # ------------------------------------------------------------------
    # Properties dialog
    # ------------------------------------------------------------------

    def _show_properties(self, entry: dict) -> None:
        from gui.properties_dialog import PropertiesDialog
        PropertiesDialog(self, entry).exec()

    # ------------------------------------------------------------------
    # Edit in VSCode
    # ------------------------------------------------------------------

    def _edit_vscode(self, entry: dict) -> None:
        if self.is_remote:
            self._edit_remote_vscode(entry)
        else:
            subprocess.Popen(["code", entry["path"]])

    def _edit_remote_vscode(self, entry: dict) -> None:
        tmp_dir = tempfile.mkdtemp(prefix="macscp_")
        local_path = os.path.join(tmp_dir, entry["name"])
        ssh_ref = self._ssh
        remote_path = entry["path"]

        def download_and_open():
            self._ssh.download(remote_path, local_path)

        def after_download(_):
            subprocess.Popen(["code", local_path])

            def _watch():
                last_mtime = os.path.getmtime(local_path)
                deadline = time.time() + 7200
                while time.time() < deadline:
                    time.sleep(1.5)
                    try:
                        mtime = os.path.getmtime(local_path)
                        if mtime > last_mtime:
                            last_mtime = mtime
                            if ssh_ref.connected:
                                ssh_ref.upload(local_path, remote_path)
                    except Exception:
                        break

            threading.Thread(target=_watch, daemon=True).start()

        self._run_threaded(download_and_open, after_download,
                           f"Downloading {entry['name']} for editing…")

    def _view_file(self, entry: dict) -> None:
        if self.is_remote:
            def fetch():
                return self._ssh.read_file(entry["path"]).decode("utf-8", errors="replace")
            self._run_threaded(fetch, lambda text: self._open_viewer(entry, text),
                               f"Loading {entry['name']}…")
        else:
            try:
                with open(entry["path"], "r", errors="replace") as f:
                    text = f.read()
            except Exception as exc:
                QMessageBox.critical(self, "Error", str(exc))
                return
            self._open_viewer(entry, text)

    def _open_viewer(self, entry: dict, text: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(entry["name"])
        dlg.resize(760, 540)
        layout = QVBoxLayout(dlg)

        path_label = QLabel(entry["path"])
        path_label.setStyleSheet("color: #555;")
        layout.addWidget(path_label)

        text_edit = QTextEdit()
        text_edit.setPlainText(text)
        text_edit.setReadOnly(True)
        text_edit.setFont(QFont("Menlo", 12))
        layout.addWidget(text_edit)

        dlg.show()

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def _show_bookmarks_menu(self) -> None:
        menu = QMenu(self)
        bm = _load_bookmarks()
        if bm:
            for b in bm:
                path = b["path"]
                menu.addAction(f"{b.get('label', path)}  —  {path}",
                               lambda p=path: self._navigate_to(p))
            menu.addSeparator()
            menu.addAction("Manage bookmarks…", self._manage_bookmarks)
        else:
            action = menu.addAction("(no bookmarks)")
            action.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Add current path", self._add_bookmark)
        menu.exec(self._bookmark_btn.mapToGlobal(self._bookmark_btn.rect().bottomLeft()))

    def _add_bookmark(self) -> None:
        if not self._current_path:
            return
        label, ok = QInputDialog.getText(
            self, "Add Bookmark", "Bookmark label:",
            text=self._current_path.rstrip("/").split("/")[-1] or self._current_path)
        if not ok or not label:
            return
        bm = _load_bookmarks()
        if not any(b["path"] == self._current_path for b in bm):
            bm.append({"label": label, "path": self._current_path})
            _save_bookmarks(bm)

    def _manage_bookmarks(self) -> None:
        from PyQt6.QtWidgets import QListWidget
        dlg = QDialog(self)
        dlg.setWindowTitle("Manage Bookmarks")
        dlg.resize(480, 300)
        layout = QVBoxLayout(dlg)

        bm = _load_bookmarks()
        listw = QListWidget()
        for b in bm:
            listw.addItem(f"{b.get('label', '')}  —  {b['path']}")
        layout.addWidget(listw)

        btn_layout = QHBoxLayout()
        del_btn = QPushButton("Delete selected")

        def delete_sel():
            row = listw.currentRow()
            if row >= 0:
                bm.pop(row)
                _save_bookmarks(bm)
                listw.takeItem(row)

        del_btn.clicked.connect(delete_sel)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        dlg.exec()

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    def _open_terminal(self) -> None:
        if self.is_remote:
            if self._ssh and self._ssh.connected:
                self._ssh.open_terminal()
        else:
            import sys
            path = self._current_path or str(Path.home())
            if sys.platform == "darwin":
                safe = path.replace("\\", "\\\\").replace('"', '\\"')
                script = (
                    'tell application "Terminal" to activate\n'
                    f'tell application "Terminal" to do script "cd \\"{safe}\\""'
                )
                subprocess.Popen(["osascript", "-e", script])
            elif sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", f"cd /d {path}"])
            else:
                # Linux / other — try common terminal emulators
                for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                    if shutil.which(term):
                        if term == "gnome-terminal":
                            subprocess.Popen([term, "--working-directory", path])
                        else:
                            subprocess.Popen([term], cwd=path)
                        break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        self._status_label.setText(msg)
        self.status_changed.emit(msg)

    def _run_threaded(self, fn, on_done=None, status="Working…") -> None:
        """Run fn in a background thread; call on_done(result) on the main thread."""
        self._set_status(status)

        def worker():
            try:
                result = fn()
                if on_done:
                    invoke_in_main(lambda: on_done(result))
            except Exception as exc:
                msg = str(exc)
                invoke_in_main(lambda: QMessageBox.critical(self, "Error", msg))
            invoke_in_main(lambda: self._set_status(""))

        threading.Thread(target=worker, daemon=True).start()
