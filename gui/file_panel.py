"""Dual-purpose file browser panel (local or remote)."""

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
from tkinter import filedialog, messagebox, simpledialog
import tkinter as tk
from tkinter import ttk

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
            # Use the DirEntry cached lstat (follow_symlinks=False) so we never
            # block on iCloud / network-volume metadata fetches per file.
            s = item.stat(follow_symlinks=False)
            is_dir = stat.S_ISDIR(s.st_mode)
            # For symlinks to dirs, is_dir via mode is False; check the link target.
            if not is_dir and stat.S_ISLNK(s.st_mode):
                is_dir = item.is_dir(follow_symlinks=True)
            entries.append({
                "name":        item.name,
                "path":        item.path,
                "is_dir":      is_dir,
                "size":        s.st_size if not is_dir else 0,
                "modified":    datetime.fromtimestamp(s.st_mtime),
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

class FilePanel(ttk.Frame):
    """File-browser panel that works for both local and remote filesystems."""

    # ---- Class-level drag-and-drop state (shared across all instances) ----
    _dnd_active: bool = False
    _dnd_source: "FilePanel | None" = None
    _dnd_entries: list[dict] = []
    _dnd_start_xy: tuple[int, int] | None = None
    _dnd_last_motion_t: float = 0.0   # throttle: skip motion events < 16 ms apart

    def __init__(self, parent, is_remote: bool = False, ssh_client=None):
        super().__init__(parent)
        self.is_remote = is_remote
        self._ssh = ssh_client

        self._current_path = ""
        self._history: list[str] = []
        self._hist_idx = -1
        self._entries: list[dict] = []        # all entries in current dir
        self._filtered: list[dict] = []       # after apply_filter
        self._item_map: dict[str, dict] = {}  # tree iid -> entry

        self._show_hidden = False
        self._filter_text = ""
        self._navigating = False      # guard against concurrent remote fetches
        self._filter_after_id = None  # debounce timer for filter entry

        self._sort_col = "name"
        self._sort_rev = False
        self._hidden_count = 0        # cached so _populate_tree doesn't recount

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
            # get_home_dir() is an SSH call — run off the main thread
            self._status.set("Loading…")
            def fetch():
                home = self._ssh.get_home_dir()
                self.after(0, lambda: self._navigate_to(home))
            threading.Thread(target=fetch, daemon=True).start()
        elif not self.is_remote:
            self._navigate_to(str(Path.home()))

    def get_current_path(self) -> str:
        return self._current_path

    def get_selected_entries(self) -> list[dict]:
        return [self._item_map[iid] for iid in self._tree.selection() if iid in self._item_map]

    def refresh(self) -> None:
        if self._current_path:
            self._navigate_to(self._current_path, add_history=False)

    def _run_ssh(self, fn, on_done=None, status="Working…") -> None:
        """Run fn() in a background thread; call on_done() on the main thread when finished."""
        self._status.set(status)
        def worker():
            err = None
            result = None
            try:
                result = fn()
            except Exception as exc:
                err = str(exc)
            def finish():
                if err:
                    messagebox.showerror("Error", err, parent=self)
                    self._status.set("Error")
                elif on_done:
                    on_done(result)
            self.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def show_disconnected(self) -> None:
        self._tree.delete(*self._tree.get_children())
        self._item_map.clear()
        self._status.set("Not connected")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # Header row
        hf = ttk.Frame(self)
        hf.pack(fill=tk.X, padx=4, pady=(4, 0))

        label = "Remote" if self.is_remote else "Local"
        ttk.Label(hf, text=label, font=("TkDefaultFont", 11, "bold")).pack(side=tk.LEFT)

        # Bookmarks button
        self._bm_btn = ttk.Menubutton(hf, text="★ Bookmarks", direction="below")
        self._bm_btn.pack(side=tk.RIGHT)
        self._bm_menu = tk.Menu(self._bm_btn, tearoff=0)
        self._bm_btn["menu"] = self._bm_menu
        self._rebuild_bm_menu()

        # Path bar
        pf = ttk.Frame(self)
        pf.pack(fill=tk.X, padx=4, pady=2)

        self._btn_back = ttk.Button(pf, text="◀", width=3, command=self._go_back, state="disabled")
        self._btn_back.pack(side=tk.LEFT)
        ttk.Button(pf, text="▲", width=3, command=self._go_up).pack(side=tk.LEFT, padx=2)
        ttk.Button(pf, text="⌂", width=3, command=self.navigate_to_home).pack(side=tk.LEFT)
        ttk.Button(pf, text="⟳", width=3, command=self.refresh).pack(side=tk.LEFT, padx=2)

        self._path_var = tk.StringVar()
        pe = ttk.Entry(pf, textvariable=self._path_var)
        pe.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        pe.bind("<Return>", self._on_path_enter)

        # Controls bar: filter + hidden toggle
        cf = ttk.Frame(self)
        cf.pack(fill=tk.X, padx=4, pady=(0, 2))

        ttk.Label(cf, text="Filter:").pack(side=tk.LEFT)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add("write", lambda *_: self._on_filter_change())
        filter_entry = ttk.Entry(cf, textvariable=self._filter_var, width=18)
        filter_entry.pack(side=tk.LEFT, padx=(4, 8))

        self._hidden_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            cf, text="Show hidden", variable=self._hidden_var,
            command=self._on_hidden_toggle
        ).pack(side=tk.LEFT)

        # Treeview
        tf = ttk.Frame(self)
        tf.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(tf, orient=tk.HORIZONTAL)

        self._tree = ttk.Treeview(
            tf,
            columns=("name", "size", "modified", "perms"),
            show="headings",
            selectmode="extended",
            yscrollcommand=vsb.set,
            xscrollcommand=hsb.set,
        )

        self._tree.heading("name",     text="Name ↕",      command=lambda: self._sort("name"))
        self._tree.heading("size",     text="Size",         command=lambda: self._sort("size"))
        self._tree.heading("modified", text="Modified",     command=lambda: self._sort("modified"))
        self._tree.heading("perms",    text="Permissions",  command=lambda: self._sort("perms"))

        self._tree.column("name",     width=240, minwidth=120)
        self._tree.column("size",     width=80,  minwidth=60, anchor="e")
        self._tree.column("modified", width=130, minwidth=100)
        self._tree.column("perms",    width=80,  minwidth=60)

        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)

        # Tag styling — plain files get no tag (fastest path through Tk renderer)
        self._tree.tag_configure("dir",        foreground="#1565C0")
        self._tree.tag_configure("hidden",     foreground="#888888")
        self._tree.tag_configure("hidden_dir", foreground="#7B9FCC")

        # Events
        self._tree.bind("<Double-Button-1>",  self._on_double_click)
        self._tree.bind("<Return>",           self._on_double_click)
        self._tree.bind("<Button-2>",         self._show_context_menu)
        self._tree.bind("<Button-3>",         self._show_context_menu)
        self._tree.bind("<<TreeviewSelect>>", self._on_select)
        self._tree.bind("<Delete>",           lambda _: self._delete_selected())
        self._tree.bind("<BackSpace>",        lambda _: self._go_up())
        self._tree.bind("<F5>",               lambda _: self.refresh())
        self._tree.bind("<F2>",               lambda _: self._rename_selected())
        self._tree.bind("<Command-a>",        lambda _: self._select_all())
        self._tree.bind("<Command-c>",        lambda _: self._copy_path())

        # Drag-and-drop
        self._tree.bind("<ButtonPress-1>",   self._dnd_press)
        self._tree.bind("<B1-Motion>",       self._dnd_motion)
        self._tree.bind("<ButtonRelease-1>", self._dnd_release)

        # Status bar
        self._status = tk.StringVar(value="")
        ttk.Label(self, textvariable=self._status, anchor="w").pack(
            fill=tk.X, padx=4, pady=(0, 2)
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate_to(self, path: str, add_history: bool = True) -> None:
        if self.is_remote:
            if not self._ssh or not self._ssh.connected:
                self.show_disconnected()
                return
            # Remote: I/O in background thread; guard against concurrent fetches.
            if self._navigating:
                return
            self._navigating = True
            self._status.set(f"Loading {path} …")

            def fetch():
                try:
                    entries = self._ssh.list_directory(path)
                    if self.winfo_exists():
                        self.after(0, lambda: self._finish_navigate(path, entries, add_history))
                except Exception as exc:
                    if self.winfo_exists():
                        self.after(0, lambda e=str(exc): self._navigate_error(e))

            threading.Thread(target=fetch, daemon=True).start()
        else:
            # Local: synchronous — lstat-only so iCloud/network volumes don't block.
            try:
                entries = local_list_dir(path)
                self._finish_navigate(path, entries, add_history)
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self)

    def _finish_navigate(self, path: str, entries: list[dict], add_history: bool) -> None:
        self._navigating = False
        if add_history:
            if self._hist_idx < len(self._history) - 1:
                self._history = self._history[: self._hist_idx + 1]
            self._history.append(path)
            self._hist_idx = len(self._history) - 1
        self._current_path = path
        self._entries = entries
        self._path_var.set(path)
        self._btn_back.config(state="normal" if self._hist_idx > 0 else "disabled")
        self._apply_filter()

    def _navigate_error(self, error: str) -> None:
        self._navigating = False
        self._status.set("Error")
        messagebox.showerror("Error", error, parent=self)

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

    def _on_path_enter(self, _event=None) -> None:
        path = self._path_var.get().strip()
        if path:
            self._navigate_to(path)

    # ------------------------------------------------------------------
    # Filter & hidden files
    # ------------------------------------------------------------------

    def _on_filter_change(self) -> None:
        # Debounce: wait 80 ms after the last keystroke before rebuilding the list.
        if self._filter_after_id is not None:
            self.after_cancel(self._filter_after_id)
        self._filter_after_id = self.after(80, self._apply_filter_committed)

    def _apply_filter_committed(self) -> None:
        self._filter_after_id = None
        self._filter_text = self._filter_var.get().lower()
        self._apply_filter()

    def _on_hidden_toggle(self) -> None:
        self._show_hidden = self._hidden_var.get()
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter entries and rebuild the treeview."""
        entries = self._entries

        # Count hidden items once here (before hidden filter) and cache it.
        self._hidden_count = sum(1 for e in entries if e["name"].startswith("."))

        if not self._show_hidden:
            entries = [e for e in entries if not e["name"].startswith(".")]

        if self._filter_text:
            entries = [e for e in entries if self._filter_text in e["name"].lower()]

        self._filtered = entries
        self._populate_tree()

    # ------------------------------------------------------------------
    # Tree population & sorting
    # ------------------------------------------------------------------

    def _populate_tree(self) -> None:
        # Suppress <<TreeviewSelect>> while we clear+rebuild so _on_select
        # doesn't fire mid-delete and issue extra Tcl round-trips.
        self._tree.unbind("<<TreeviewSelect>>")
        try:
            children = self._tree.get_children()
            if children:
                self._tree.delete(*children)
            self._item_map.clear()

            for i, entry in enumerate(self._filtered):
                iid = f"row_{i}"
                self._item_map[iid] = entry
                is_hidden = entry["name"].startswith(".")
                mod = (entry["modified"].strftime("%Y-%m-%d %H:%M")
                       if entry.get("modified") else "")

                if is_hidden:
                    tags = ("hidden_dir",) if entry["is_dir"] else ("hidden",)
                elif entry["is_dir"]:
                    tags = ("dir",)
                else:
                    tags = ()          # plain file — no tag needed

                self._tree.insert(
                    "", "end", iid=iid,
                    values=(
                        entry["name"],
                        _fmt_size(entry["size"], entry["is_dir"]),
                        mod,
                        entry.get("permissions", ""),
                    ),
                    tags=tags,
                )
        finally:
            self._tree.bind("<<TreeviewSelect>>", self._on_select)

        n_total = len(self._entries)
        n_shown = len(self._filtered)
        hc = self._hidden_count  # pre-computed in _apply_filter

        if self._filter_text:
            self._status.set(f"{n_shown} match{'es' if n_shown != 1 else ''} / {n_total} items")
        elif not self._show_hidden and hc:
            self._status.set(f"{n_shown} items ({hc} hidden)")
        else:
            self._status.set(f"{n_total} item{'s' if n_total != 1 else ''}")

    def _sort(self, col: str) -> None:
        rev = (not self._sort_rev) if self._sort_col == col else False
        self._sort_col = col
        self._sort_rev = rev

        # Update heading arrow
        arrows = {"name": "Name ↕", "size": "Size ↕", "modified": "Modified ↕", "perms": "Permissions ↕"}
        for c, base in [("name", "Name"), ("size", "Size"), ("modified", "Modified"), ("perms", "Permissions")]:
            marker = (" ▲" if not rev else " ▼") if c == col else " ↕"
            self._tree.heading(c, text=base + marker)

        key_fns = {
            "name":     lambda x: (not x["is_dir"], x["name"].lower()),
            "size":     lambda x: (not x["is_dir"], x["size"]),
            "modified": lambda x: (not x["is_dir"], x.get("modified") or datetime.min),
            "perms":    lambda x: (not x["is_dir"], x.get("permissions", "")),
        }
        self._entries.sort(key=key_fns.get(col, key_fns["name"]), reverse=rev)
        self._apply_filter()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_double_click(self, event=None) -> None:
        # Ignore if this was a drag
        if FilePanel._dnd_active:
            return
        sel = self._tree.selection()
        if not sel:
            return
        entry = self._item_map.get(sel[0])
        if entry and entry["is_dir"]:
            self._navigate_to(entry["path"])

    def _on_select(self, _event=None) -> None:
        n_sel = len(self._tree.selection())
        total = len(self._filtered)
        if n_sel:
            self._status.set(f"{n_sel} selected / {total} items")
        else:
            n_total = len(self._entries)
            self._status.set(f"{total} item{'s' if total != 1 else ''}"
                             + (f" ({n_total - total} hidden)" if total < n_total else ""))

    def _select_all(self) -> None:
        children = self._tree.get_children()
        if children:
            self._tree.selection_set(children)

    def _copy_path(self) -> None:
        selected = self.get_selected_entries()
        if selected:
            paths = "\n".join(e["path"] for e in selected)
        else:
            paths = self._current_path
        self.clipboard_clear()
        self.clipboard_append(paths)

    # ------------------------------------------------------------------
    # Drag and drop
    # ------------------------------------------------------------------

    def _dnd_press(self, event) -> None:
        FilePanel._dnd_start_xy = (event.x_root, event.y_root)
        FilePanel._dnd_active = False

    def _dnd_motion(self, event) -> None:
        if FilePanel._dnd_start_xy is None:
            return

        # Throttle: process at most ~60 fps to avoid flooding the event queue
        now = time.monotonic()
        if now - FilePanel._dnd_last_motion_t < 0.016:
            return
        FilePanel._dnd_last_motion_t = now

        dx = abs(event.x_root - FilePanel._dnd_start_xy[0])
        dy = abs(event.y_root - FilePanel._dnd_start_xy[1])
        if dx < 8 and dy < 8:
            return

        if not FilePanel._dnd_active:
            selected = self.get_selected_entries()
            if not selected:
                return
            FilePanel._dnd_active = True
            FilePanel._dnd_source = self
            FilePanel._dnd_entries = list(selected)
            # Disable selection changes during drag so <<TreeviewSelect>> doesn't
            # fire on every pixel (which causes the treeview to redraw constantly).
            self._tree.config(cursor="hand2", selectmode="none")
            n = len(selected)
            label = selected[0]["name"] if n == 1 else f"{n} items"
            self._status.set(f"Dragging: {label}  —  drop on the other panel to transfer")

    def _dnd_release(self, event) -> None:
        FilePanel._dnd_start_xy = None
        if not FilePanel._dnd_active:
            return
        self._tree.config(cursor="", selectmode="extended")
        FilePanel._dnd_active = False
        # MacSCPApp root binding handles the actual drop

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, event) -> None:
        row = self._tree.identify_row(event.y)
        if row and row not in self._tree.selection():
            self._tree.selection_set(row)

        selected = self.get_selected_entries()
        menu = tk.Menu(self, tearoff=0)

        if len(selected) == 1:
            e = selected[0]
            if e["is_dir"]:
                menu.add_command(label="Open", command=lambda: self._navigate_to(e["path"]))
            else:
                menu.add_command(label="Edit in VSCode",  command=lambda: self._edit_vscode(e))
                menu.add_command(label="View contents",   command=lambda: self._view_file(e))
            menu.add_command(label="Properties",          command=lambda: self._show_properties(e))
            menu.add_separator()

        if selected:
            menu.add_command(label="Copy Path",  command=self._copy_path)
            menu.add_command(label="Delete",     command=self._delete_selected)
            menu.add_command(label="Rename… F2", command=self._rename_selected)
            menu.add_separator()

        menu.add_command(label="Select All  ⌘A",  command=self._select_all)
        menu.add_separator()
        menu.add_command(label="New Folder…",     command=self._new_folder)
        menu.add_command(label="New File…",       command=self._new_file)
        menu.add_separator()
        menu.add_command(label="Add Bookmark ★",  command=self._add_bookmark)
        menu.add_separator()
        menu.add_command(label="Open Terminal Here", command=self._open_terminal)
        menu.add_separator()
        menu.add_command(label="Refresh  F5",     command=self.refresh)

        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def _delete_selected(self) -> None:
        selected = self.get_selected_entries()
        if not selected:
            return
        names = [e["name"] for e in selected]
        msg = f"Delete '{names[0]}'?" if len(names) == 1 else f"Delete {len(names)} items?"
        if not messagebox.askyesno("Confirm Delete", msg, parent=self):
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
            self._run_ssh(do_delete, on_done=lambda _: self.refresh(),
                          status=f"Deleting {len(selected)} item(s)…")
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
                messagebox.showerror("Delete errors", "\n".join(errors), parent=self)
            self.refresh()

    def _rename_selected(self) -> None:
        selected = self.get_selected_entries()
        if len(selected) != 1:
            messagebox.showinfo("Rename", "Select exactly one item to rename.", parent=self)
            return
        e = selected[0]
        new_name = simpledialog.askstring(
            "Rename", f"New name for '{e['name']}':", initialvalue=e["name"], parent=self
        )
        if not new_name or new_name == e["name"]:
            return

        new_path = (
            self._current_path.rstrip("/") + "/" + new_name
            if self.is_remote
            else os.path.join(self._current_path, new_name)
        )
        if self.is_remote:
            self._run_ssh(
                lambda: self._ssh.rename(e["path"], new_path),
                on_done=lambda _: self.refresh(),
                status=f"Renaming {e['name']}…",
            )
        else:
            try:
                os.rename(e["path"], new_path)
            except Exception as exc:
                messagebox.showerror("Rename error", str(exc), parent=self)
            self.refresh()

    def _new_folder(self) -> None:
        name = simpledialog.askstring("New Folder", "Folder name:", parent=self)
        if not name:
            return
        path = (
            self._current_path.rstrip("/") + "/" + name
            if self.is_remote
            else os.path.join(self._current_path, name)
        )
        if self.is_remote:
            self._run_ssh(lambda: self._ssh.mkdir(path),
                          on_done=lambda _: self.refresh(), status="Creating folder…")
        else:
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self)
            self.refresh()

    def _new_file(self) -> None:
        name = simpledialog.askstring("New File", "File name:", parent=self)
        if not name:
            return
        path = (
            self._current_path.rstrip("/") + "/" + name
            if self.is_remote
            else os.path.join(self._current_path, name)
        )
        if self.is_remote:
            self._run_ssh(lambda: self._ssh.create_file(path),
                          on_done=lambda _: self.refresh(), status="Creating file…")
        else:
            try:
                open(path, "w").close()
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self)
            self.refresh()

    def _show_properties(self, entry: dict) -> None:
        from gui.properties_dialog import PropertiesDialog
        PropertiesDialog(self, entry)

    # ------------------------------------------------------------------
    # Bookmarks
    # ------------------------------------------------------------------

    def _add_bookmark(self) -> None:
        if not self._current_path:
            return
        label = simpledialog.askstring(
            "Add Bookmark",
            "Bookmark label:",
            initialvalue=self._current_path.rstrip("/").split("/")[-1] or self._current_path,
            parent=self,
        )
        if not label:
            return
        bm = _load_bookmarks()
        # Avoid duplicates
        if not any(b["path"] == self._current_path for b in bm):
            bm.append({"label": label, "path": self._current_path})
            _save_bookmarks(bm)
        self._rebuild_bm_menu()

    def _rebuild_bm_menu(self) -> None:
        self._bm_menu.delete(0, "end")
        bm = _load_bookmarks()
        if bm:
            for b in bm:
                path = b["path"]
                self._bm_menu.add_command(
                    label=f"  {b['label']}  —  {path}",
                    command=lambda p=path: self._navigate_to(p),
                )
            self._bm_menu.add_separator()
            self._bm_menu.add_command(
                label="Manage bookmarks…", command=self._manage_bookmarks
            )
        else:
            self._bm_menu.add_command(
                label="(no bookmarks yet — right-click to add)",
                state="disabled",
            )
        self._bm_menu.add_command(
            label="Add current path ★", command=self._add_bookmark
        )

    def _manage_bookmarks(self) -> None:
        bm = _load_bookmarks()
        if not bm:
            messagebox.showinfo("Bookmarks", "No bookmarks saved yet.", parent=self)
            return

        win = tk.Toplevel(self)
        win.title("Manage Bookmarks")
        win.geometry("480x300")
        win.transient(self)
        win.grab_set()

        lb = tk.Listbox(win, font=("TkDefaultFont", 11))
        lb.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        for b in bm:
            lb.insert("end", f"{b['label']}  →  {b['path']}")

        def delete_selected():
            sel = lb.curselection()
            if not sel:
                return
            idx = sel[0]
            bm.pop(idx)
            _save_bookmarks(bm)
            lb.delete(idx)
            self._rebuild_bm_menu()

        bf = ttk.Frame(win)
        bf.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(bf, text="Delete selected", command=delete_selected).pack(side=tk.LEFT)
        ttk.Button(bf, text="Close", command=win.destroy).pack(side=tk.RIGHT)

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

        self._run_ssh(download_and_open, on_done=after_download,
                      status=f"Downloading {entry['name']} for editing…")

    def _view_file(self, entry: dict) -> None:
        if self.is_remote:
            def fetch():
                return self._ssh.read_file(entry["path"]).decode("utf-8", errors="replace")
            self._run_ssh(fetch,
                          on_done=lambda text: self._open_viewer(entry, text),
                          status=f"Loading {entry['name']}…")
        else:
            try:
                with open(entry["path"], "r", errors="replace") as f:
                    text = f.read()
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self)
                return
            self._open_viewer(entry, text)

    def _open_viewer(self, entry: dict, text: str) -> None:
        win = tk.Toplevel(self)
        win.title(entry["name"])
        win.geometry("760x540")

        # Toolbar
        tf = ttk.Frame(win)
        tf.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(tf, text=entry["path"], foreground="#555").pack(side=tk.LEFT)

        txt = tk.Text(win, wrap="none", font=("Menlo", 12), undo=False)
        txt.insert("1.0", text)
        txt.config(state="disabled")
        vsb = ttk.Scrollbar(win, orient=tk.VERTICAL, command=txt.yview)
        hsb = ttk.Scrollbar(win, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------
    # Terminal
    # ------------------------------------------------------------------

    def _open_terminal(self) -> None:
        if self.is_remote:
            if self._ssh and self._ssh.connected:
                self._ssh.open_terminal()
        else:
            path = self._current_path or str(Path.home())
            safe = path.replace("\\", "\\\\").replace('"', '\\"')
            script = (
                'tell application "Terminal" to activate\n'
                f'tell application "Terminal" to do script "cd \\"{safe}\\""'
            )
            subprocess.Popen(["osascript", "-e", script])
