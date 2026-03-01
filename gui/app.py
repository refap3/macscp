"""Main application window for MacSCP."""

import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from core.session_manager import SavedSession, SessionManager
from core.ssh_client import SSHClient
from gui.connection_dialog import ConnectionDialog
from gui.file_panel import FilePanel
from gui.overwrite_dialog import OverwriteDialog
from gui.transfer_dialog import TransferDialog


# ---------------------------------------------------------------------------
# Session tab
# ---------------------------------------------------------------------------

class SessionTab(ttk.Frame):
    """One tab = one SSH connection + dual file panels."""

    def __init__(self, parent, session_mgr: SessionManager, root: tk.Tk,
                 log_fn=None):
        super().__init__(parent)
        self._session_mgr = session_mgr
        self._root = root
        self._ssh: SSHClient | None = None
        self._log = log_fn or (lambda *_: None)

        self._build_ui()

    def _build_ui(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self._local  = FilePanel(paned, is_remote=False)
        self._remote = FilePanel(paned, is_remote=True)
        paned.add(self._local,  weight=1)
        paned.add(self._remote, weight=1)

    # ---- public ----

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
        _do_transfer(
            self._root, self._ssh, self._local, self._remote, "upload",
            preselected=preselected, log_fn=self._log,
        )

    def download(self, preselected=None) -> None:
        _do_transfer(
            self._root, self._ssh, self._local, self._remote, "download",
            preselected=preselected, log_fn=self._log,
        )

    def refresh(self) -> None:
        self._local.refresh()
        self._remote.refresh()


# ---------------------------------------------------------------------------
# File transfer (background thread + progress + overwrite dialog)
# ---------------------------------------------------------------------------

def _do_transfer(
    root: tk.Tk,
    ssh: SSHClient,
    local: FilePanel,
    remote: FilePanel,
    direction: str,
    preselected: list[dict] | None = None,
    log_fn=None,
) -> None:
    """Orchestrate a file transfer with progress, overwrite handling, and logging."""

    if not ssh or not ssh.connected:
        messagebox.showwarning("Not connected", "Please connect to a remote host first.")
        return

    if direction == "upload":
        selected = preselected or local.get_selected_entries()
        dest_dir = remote.get_current_path()
        if not selected:
            messagebox.showinfo("Upload", "Select local files/folders to upload.")
            return
        if not dest_dir:
            messagebox.showinfo("Upload", "Navigate to a remote destination first.")
            return
    else:
        selected = preselected or remote.get_selected_entries()
        dest_dir = local.get_current_path()
        if not selected:
            messagebox.showinfo("Download", "Select remote files/folders to download.")
            return
        if not dest_dir:
            messagebox.showinfo("Download", "Navigate to a local destination first.")
            return

    dialog = TransferDialog(root, direction.capitalize())

    state: dict = {
        "current_file":  "",
        "current_num":   0,
        "total_files":   len(selected),
        "file_progress": 0,
        "file_total":    0,
        "done":          False,
        "error":         None,
        # Overwrite state
        "ow_event":      threading.Event(),
        "ow_result":     [None],
        "overwrite_all": False,
        "skip_all":      False,
    }

    def ask_overwrite(filename: str, src_info: dict | None, dst_info: dict | None) -> str:
        """Show overwrite dialog from main thread; block worker thread until answered."""
        if state["overwrite_all"]:
            return "overwrite"
        if state["skip_all"]:
            return "skip"
        state["ow_event"].clear()
        state["ow_result"][0] = None

        def show_dlg():
            dlg = OverwriteDialog(root, filename, src_info, dst_info)
            result = dlg.result
            if result == "overwrite_all":
                state["overwrite_all"] = True
                result = "overwrite"
            elif result == "skip_all":
                state["skip_all"] = True
                result = "skip"
            state["ow_result"][0] = result
            state["ow_event"].set()

        root.after(0, show_dlg)
        state["ow_event"].wait()
        return state["ow_result"][0] or "cancel"

    def check_overwrite(entry: dict, dest_path: str) -> str:
        """Return 'overwrite', 'skip', or 'cancel'."""
        if entry["is_dir"]:
            return "overwrite"  # directories always merge
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
        state["file_total"]    = total

    results: list[str] = []

    def worker():
        for i, entry in enumerate(selected):
            if dialog.cancelled:
                break
            state["current_num"]   = i
            state["current_file"]  = entry["name"]
            state["file_progress"] = 0
            state["file_total"]    = entry.get("size", 0)

            # Determine destination path (top-level only; subtrees handled by *_tree)
            if direction == "upload":
                dest = dest_dir.rstrip("/") + "/" + entry["name"]
            else:
                dest = os.path.join(dest_dir, entry["name"])

            action = check_overwrite(entry, dest)
            if action == "cancel":
                break
            if action == "skip":
                results.append(f"⊘ Skipped: {entry['name']}")
                continue

            try:
                if direction == "upload":
                    ssh.upload_tree(entry["path"], dest_dir, state, progress)
                else:
                    ssh.download_tree(entry["path"], dest_dir, entry["is_dir"], state, progress)
                results.append(
                    f"{'⬆' if direction == 'upload' else '⬇'} {entry['name']}  →  {dest_dir}"
                )
            except InterruptedError:
                break
            except Exception as exc:
                state["error"] = str(exc)
                results.append(f"✗ {entry['name']}: {exc}")
                break

        state["done"] = True

    threading.Thread(target=worker, daemon=True).start()

    def poll():
        if not dialog.winfo_exists():
            return
        dialog.update_from_state(state)
        if dialog.cancelled or state["done"]:
            try:
                dialog.destroy()
            except Exception:
                pass
            if state.get("error"):
                messagebox.showerror("Transfer error", state["error"])
            # Log results
            if log_fn and results:
                for r in results:
                    log_fn(r)
            if direction == "upload":
                remote.refresh()
            else:
                local.refresh()
            return
        root.after(150, poll)

    root.after(150, poll)


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class MacSCPApp:
    """Top-level MacSCP window with menu, toolbar, tabbed sessions, and log."""

    def __init__(self, root: tk.Tk):
        self._root = root
        self._root.title("MacSCP")
        self._root.geometry("1320x820")
        self._root.minsize(900, 560)

        self._session_mgr = SessionManager()
        self._tabs: list[SessionTab] = []

        self._build_menu()
        self._build_toolbar()
        self._build_notebook()
        self._build_log_panel()
        self._build_statusbar()

        self._add_tab("Unconnected")

        # DnD: detect drop between panels on mouse release anywhere on root
        self._root.bind("<ButtonRelease-1>", self._on_root_mouse_up, "+")

        self._root.protocol("WM_DELETE_WINDOW", self._on_quit)

    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = tk.Menu(self._root)

        fm = tk.Menu(bar, tearoff=0)
        fm.add_command(label="New Connection…", command=self._new_connection, accelerator="⌘N")
        fm.add_command(label="New Tab",          command=self._new_tab,        accelerator="⌘T")
        fm.add_command(label="Close Tab",        command=self._close_tab,      accelerator="⌘W")
        fm.add_separator()
        fm.add_command(label="Disconnect",       command=self._disconnect)
        fm.add_separator()
        fm.add_command(label="Quit MacSCP",      command=self._on_quit,        accelerator="⌘Q")
        bar.add_cascade(label="File", menu=fm)

        vm = tk.Menu(bar, tearoff=0)
        vm.add_command(label="Refresh",          command=self._refresh,        accelerator="⌘R")
        vm.add_separator()
        vm.add_command(label="Show Log Panel",   command=self._toggle_log)
        bar.add_cascade(label="View", menu=vm)

        tm = tk.Menu(bar, tearoff=0)
        tm.add_command(label="Upload →",         command=self._upload,         accelerator="⌘U")
        tm.add_command(label="← Download",       command=self._download,       accelerator="⌘D")
        bar.add_cascade(label="Transfer", menu=tm)

        rm = tk.Menu(bar, tearoff=0)
        rm.add_command(label="Open SSH Terminal",      command=self._open_remote_term)
        rm.add_command(label="Go to Home Directory",   command=self._remote_home)
        rm.add_command(label="Execute Command…",       command=self._exec_command)
        bar.add_cascade(label="Remote", menu=rm)

        lm = tk.Menu(bar, tearoff=0)
        lm.add_command(label="Open Terminal",          command=self._open_local_term)
        lm.add_command(label="Go to Home Directory",   command=self._local_home)
        bar.add_cascade(label="Local", menu=lm)

        self._root.config(menu=bar)

        self._root.bind("<Command-n>", lambda _: self._new_connection())
        self._root.bind("<Command-t>", lambda _: self._new_tab())
        self._root.bind("<Command-w>", lambda _: self._close_tab())
        self._root.bind("<Command-r>", lambda _: self._refresh())
        self._root.bind("<Command-u>", lambda _: self._upload())
        self._root.bind("<Command-d>", lambda _: self._download())
        self._root.bind("<Command-q>", lambda _: self._on_quit())

    # ------------------------------------------------------------------
    # Toolbar
    # ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        tb = ttk.Frame(self._root, relief="ridge")
        tb.pack(fill=tk.X)

        def sep():
            ttk.Separator(tb, orient="vertical").pack(side=tk.LEFT, fill=tk.Y, pady=3, padx=3)

        def btn(text, cmd, **kw):
            b = ttk.Button(tb, text=text, command=cmd, **kw)
            b.pack(side=tk.LEFT, padx=3, pady=4)
            return b

        btn("⚡ Connect", self._new_connection)
        self._disc_btn = btn("✕ Disconnect", self._disconnect, state="disabled")
        sep()

        # Quick-connect: saved sessions combobox
        ttk.Label(tb, text="Session:").pack(side=tk.LEFT, padx=(2, 2))
        self._session_var = tk.StringVar()
        self._session_cb = ttk.Combobox(tb, textvariable=self._session_var,
                                         state="readonly", width=22)
        self._session_cb.pack(side=tk.LEFT, pady=4)
        self._session_cb.bind("<<ComboboxSelected>>", self._quick_connect)
        self._refresh_session_combobox()

        sep()
        btn("＋ Tab",         self._new_tab)
        sep()
        btn("⟳ Refresh",      self._refresh)
        sep()
        btn("⬆ Upload →",    self._upload)
        btn("← Download ⬇",  self._download)
        sep()
        btn("⬛ SSH Terminal", self._open_remote_term)
        btn("📋 Exec Cmd…",    self._exec_command)
        sep()
        btn("📋 Log",          self._toggle_log)

        # Connection status dot + label (right side)
        right = ttk.Frame(tb)
        right.pack(side=tk.RIGHT, padx=8)

        self._dot_canvas = tk.Canvas(right, width=14, height=14,
                                      highlightthickness=0, bd=0)
        self._dot_canvas.pack(side=tk.LEFT, padx=(0, 4))
        self._dot_oval = self._dot_canvas.create_oval(2, 2, 12, 12, fill="#BBBBBB", outline="")

        self._conn_var = tk.StringVar(value="Not connected")
        ttk.Label(right, textvariable=self._conn_var, foreground="#444").pack(side=tk.LEFT)

    def _set_dot(self, color: str) -> None:
        self._dot_canvas.itemconfig(self._dot_oval, fill=color)

    def _refresh_session_combobox(self) -> None:
        sessions = self._session_mgr.sessions
        self._session_cb["values"] = [str(s) for s in sessions]
        if sessions:
            self._session_cb.config(state="readonly")
        else:
            self._session_cb.config(state="disabled")

    def _quick_connect(self, _event=None) -> None:
        sessions = self._session_mgr.sessions
        names = [str(s) for s in sessions]
        sel = self._session_var.get()
        if sel not in names:
            return
        s = sessions[names.index(sel)]
        # Prompt for password/passphrase if needed
        pw = None
        if s.auth_type == "password":
            from tkinter.simpledialog import askstring
            pw = askstring("Password", f"Password for {s}:", show="*", parent=self._root)
            if pw is None:
                return
        self._connect({
            "host":           s.host,
            "port":           s.port,
            "username":       s.username,
            "auth_type":      s.auth_type,
            "password":       pw,
            "key_file":       s.key_file or None,
            "key_passphrase": None,
        })

    # ------------------------------------------------------------------
    # Notebook (tabs)
    # ------------------------------------------------------------------

    def _build_notebook(self) -> None:
        self._nb = ttk.Notebook(self._root)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))
        self._nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _add_tab(self, title: str) -> SessionTab:
        tab = SessionTab(self._nb, self._session_mgr, self._root, log_fn=self._log)
        self._tabs.append(tab)
        self._nb.add(tab, text=f"  {title}  ")
        self._nb.select(tab)
        return tab

    def _current_tab(self) -> SessionTab | None:
        if not self._tabs:
            return None
        try:
            idx = self._nb.index("current")
        except Exception:
            return None
        if idx < 0 or idx >= len(self._tabs):
            return None
        return self._tabs[idx]

    def _on_tab_changed(self, _event=None) -> None:
        tab = self._current_tab()
        if tab and tab.ssh:
            self._conn_var.set(f"Connected: {tab.ssh.label}")
            self._disc_btn.config(state="normal")
            self._set_dot("#4CAF50")  # green
        else:
            self._conn_var.set("Not connected")
            self._disc_btn.config(state="disabled")
            self._set_dot("#BBBBBB")  # grey

    # ------------------------------------------------------------------
    # Log panel
    # ------------------------------------------------------------------

    def _build_log_panel(self) -> None:
        self._log_frame = ttk.Frame(self._root)
        # Not packed initially; toggled by user

        hdr = ttk.Frame(self._log_frame)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text="Transfer Log", font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT, padx=6)
        ttk.Button(hdr, text="Clear", command=self._clear_log).pack(side=tk.LEFT, padx=4)
        ttk.Button(hdr, text="✕ Hide", command=self._toggle_log).pack(side=tk.RIGHT, padx=4)

        self._log_text = tk.Text(
            self._log_frame, height=7, wrap="none",
            font=("Menlo", 10), state="disabled", relief="flat",
        )
        sb = ttk.Scrollbar(self._log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        self._log_visible = False

    def _toggle_log(self) -> None:
        if self._log_visible:
            self._log_frame.pack_forget()
            self._log_visible = False
        else:
            self._log_frame.pack(fill=tk.X, side=tk.BOTTOM, before=self._status_frame)
            self._log_visible = True

    def _log(self, message: str) -> None:
        """Append a timestamped message to the log panel (safe to call from any thread)."""
        def _append():
            ts = time.strftime("%H:%M:%S")
            self._log_text.config(state="normal")
            self._log_text.insert("end", f"[{ts}]  {message}\n")
            self._log_text.see("end")
            self._log_text.config(state="disabled")
            if not self._log_visible:
                self._toggle_log()
        self._root.after(0, _append)

    def _clear_log(self) -> None:
        self._log_text.config(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.config(state="disabled")

    # ------------------------------------------------------------------
    # Status bar
    # ------------------------------------------------------------------

    def _build_statusbar(self) -> None:
        self._status_frame = ttk.Frame(self._root, relief="sunken")
        self._status_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self._status = tk.StringVar(value="Ready")
        ttk.Label(self._status_frame, textvariable=self._status, anchor="w").pack(
            fill=tk.X, padx=6, pady=2
        )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _new_connection(self) -> None:
        dlg = ConnectionDialog(self._root, self._session_mgr)
        if dlg.result:
            self._connect(dlg.result)

    def _connect(self, params: dict) -> None:
        host = params["host"]
        self._set_status(f"Connecting to {host}…")
        self._set_dot("#FF9800")  # orange = connecting

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
                self._root.after(0, lambda: self._on_connected(tab, client, params))
            except Exception as exc:
                self._root.after(0, lambda e=str(exc): self._on_connect_failed(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_connected(self, tab: SessionTab, client: SSHClient, params: dict) -> None:
        tab.set_ssh(client)
        label = f"{params['username']}@{params['host']}"
        idx = self._tabs.index(tab)
        self._nb.tab(idx, text=f"  {label}  ")
        self._conn_var.set(f"Connected: {client.label}")
        self._set_dot("#4CAF50")  # green
        self._disc_btn.config(state="normal")
        self._root.title(f"MacSCP — {label}")
        self._set_status(f"Connected to {params['host']}")
        self._log(f"✔ Connected to {client.label}")

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
        self._set_dot("#F44336")  # red
        messagebox.showerror("Connection failed", error, parent=self._root)
        self._set_status("Connection failed.")
        self._set_dot("#BBBBBB")

    def _disconnect(self) -> None:
        tab = self._current_tab()
        if tab:
            label = tab.ssh.label if tab.ssh else ""
            tab.disconnect()
            if label:
                self._log(f"✘ Disconnected from {label}")
        self._conn_var.set("Not connected")
        self._set_dot("#BBBBBB")
        self._disc_btn.config(state="disabled")
        self._root.title("MacSCP")
        self._set_status("Disconnected.")

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _new_tab(self) -> None:
        self._add_tab("Unconnected")
        self._conn_var.set("Not connected")
        self._set_dot("#BBBBBB")
        self._disc_btn.config(state="disabled")

    def _close_tab(self) -> None:
        tab = self._current_tab()
        if not tab:
            return
        if tab.ssh:
            if not messagebox.askyesno("Close tab", "Disconnect and close this tab?", parent=self._root):
                return
            tab.disconnect()
        idx = self._tabs.index(tab)
        self._tabs.pop(idx)
        self._nb.forget(idx)
        if not self._tabs:
            self._add_tab("Unconnected")

    # ------------------------------------------------------------------
    # Drag and drop (between panels)
    # ------------------------------------------------------------------

    def _on_root_mouse_up(self, event) -> None:
        """Handle drag release — detect cross-panel drops and trigger transfer."""
        if not FilePanel._dnd_active:
            return
        source = FilePanel._dnd_source
        entries = list(FilePanel._dnd_entries)

        # Reset DnD state
        FilePanel._dnd_active = False
        FilePanel._dnd_source = None
        FilePanel._dnd_entries = []

        if not entries or source is None:
            return

        tab = self._current_tab()
        if not tab:
            return

        x, y = self._root.winfo_pointerxy()

        def _over(panel: FilePanel) -> bool:
            rx = panel.winfo_rootx()
            ry = panel.winfo_rooty()
            return rx <= x <= rx + panel.winfo_width() and ry <= y <= ry + panel.winfo_height()

        if source is tab.local_panel and _over(tab.remote_panel):
            if tab.ssh and tab.ssh.connected:
                tab.upload(preselected=entries)
            else:
                messagebox.showinfo("Not connected", "Connect to a remote host first.")
        elif source is tab.remote_panel and _over(tab.local_panel):
            tab.download(preselected=entries)

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
            messagebox.showinfo("Not connected", "Connect to a remote host first.")

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
        """Execute a shell command on the remote host and show output."""
        tab = self._current_tab()
        if not tab or not tab.ssh or not tab.ssh.connected:
            messagebox.showinfo("Not connected", "Connect to a remote host first.")
            return

        from tkinter.simpledialog import askstring
        cmd = askstring("Execute Command", "Command to run on remote host:", parent=self._root)
        if not cmd:
            return

        self._set_status(f"Running: {cmd}")

        def worker():
            try:
                stdout, stderr = tab.ssh.exec_command(cmd)
                output = stdout or stderr or "(no output)"
            except Exception as exc:
                output = f"Error: {exc}"
            self._root.after(0, lambda: self._show_output(cmd, output))
            self._root.after(0, lambda: self._set_status("Ready"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_output(self, cmd: str, output: str) -> None:
        win = tk.Toplevel(self._root)
        win.title(f"Output: {cmd[:60]}")
        win.geometry("700x420")
        ttk.Label(win, text=f"$ {cmd}", foreground="#555", font=("Menlo", 10)).pack(
            anchor="w", padx=8, pady=(6, 0)
        )
        txt = tk.Text(win, font=("Menlo", 11), wrap="none")
        txt.insert("1.0", output)
        txt.config(state="disabled")
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=txt.yview)
        hsb = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _set_status(self, msg: str) -> None:
        self._status.set(msg)

    def _on_quit(self) -> None:
        for tab in self._tabs:
            try:
                tab.disconnect()
            except Exception:
                pass
        self._root.destroy()
