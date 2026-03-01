"""Connection dialog for entering SSH credentials."""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.session_manager import SavedSession, SessionManager


class ConnectionDialog(tk.Toplevel):
    """Modal dialog that collects SSH connection parameters.

    After the window closes, check ``self.result`` (dict or None).
    """

    def __init__(self, parent: tk.Widget, session_mgr: SessionManager):
        super().__init__(parent)
        self.title("New Connection")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._session_mgr = session_mgr
        self.result: dict | None = None

        self._build_ui()
        self._center(parent)
        self.wait_window()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root_pad = ttk.Frame(self, padding=16)
        root_pad.pack(fill=tk.BOTH, expand=True)

        row = 0

        # Saved sessions (if any)
        sessions = self._session_mgr.sessions
        if sessions:
            ttk.Label(root_pad, text="Saved sessions:").grid(row=row, column=0, sticky="w")
            self._saved_var = tk.StringVar()
            cb = ttk.Combobox(
                root_pad,
                textvariable=self._saved_var,
                values=[str(s) for s in sessions],
                state="readonly",
                width=32,
            )
            cb.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=2)
            cb.bind("<<ComboboxSelected>>", self._load_saved)
            row += 1
            ttk.Separator(root_pad, orient="horizontal").grid(
                row=row, column=0, columnspan=4, sticky="ew", pady=6
            )
            row += 1

        # Host / Port
        ttk.Label(root_pad, text="Host:").grid(row=row, column=0, sticky="w", pady=3)
        self._host = tk.StringVar()
        ttk.Entry(root_pad, textvariable=self._host, width=26).grid(
            row=row, column=1, sticky="ew", padx=(6, 4), pady=3
        )
        ttk.Label(root_pad, text="Port:").grid(row=row, column=2, sticky="w", pady=3)
        self._port = tk.StringVar(value="22")
        ttk.Entry(root_pad, textvariable=self._port, width=6).grid(
            row=row, column=3, sticky="w", pady=3
        )
        row += 1

        # Username
        ttk.Label(root_pad, text="Username:").grid(row=row, column=0, sticky="w", pady=3)
        self._user = tk.StringVar()
        ttk.Entry(root_pad, textvariable=self._user, width=34).grid(
            row=row, column=1, columnspan=3, sticky="ew", padx=(6, 0), pady=3
        )
        row += 1

        # Auth type
        ttk.Label(root_pad, text="Auth:").grid(row=row, column=0, sticky="w", pady=3)
        self._auth = tk.StringVar(value="password")
        af = ttk.Frame(root_pad)
        af.grid(row=row, column=1, columnspan=3, sticky="w", padx=(6, 0), pady=3)
        ttk.Radiobutton(af, text="Password", variable=self._auth, value="password",
                        command=self._toggle_auth).pack(side=tk.LEFT)
        ttk.Radiobutton(af, text="Key file", variable=self._auth, value="key",
                        command=self._toggle_auth).pack(side=tk.LEFT, padx=12)
        row += 1

        # --- Password frame ---
        self._pw_frame = ttk.Frame(root_pad)
        self._pw_frame.grid(row=row, column=0, columnspan=4, sticky="ew")
        ttk.Label(self._pw_frame, text="Password:").grid(row=0, column=0, sticky="w", pady=3)
        self._pw = tk.StringVar()
        ttk.Entry(self._pw_frame, textvariable=self._pw, show="*", width=34).grid(
            row=0, column=1, sticky="ew", padx=(6, 0), pady=3
        )
        self._pw_frame.columnconfigure(1, weight=1)

        # --- Key frame ---
        self._key_frame = ttk.Frame(root_pad)
        self._key_frame.grid(row=row, column=0, columnspan=4, sticky="ew")
        ttk.Label(self._key_frame, text="Key file:").grid(row=0, column=0, sticky="w", pady=3)
        self._key = tk.StringVar()
        ttk.Entry(self._key_frame, textvariable=self._key, width=26).grid(
            row=0, column=1, sticky="ew", padx=(6, 4), pady=3
        )
        ttk.Button(self._key_frame, text="Browse…", command=self._browse_key).grid(
            row=0, column=2, pady=3
        )
        ttk.Label(self._key_frame, text="Passphrase:").grid(row=1, column=0, sticky="w", pady=3)
        self._pp = tk.StringVar()
        ttk.Entry(self._key_frame, textvariable=self._pp, show="*", width=26).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=3
        )
        self._key_frame.columnconfigure(1, weight=1)
        self._key_frame.grid_remove()  # hidden by default

        row += 1

        # Buttons
        bf = ttk.Frame(root_pad)
        bf.grid(row=row, column=0, columnspan=4, pady=(14, 0))
        ttk.Button(bf, text="Connect", command=self._connect).pack(side=tk.LEFT, padx=6)
        ttk.Button(bf, text="Save Session", command=self._save_session).pack(side=tk.LEFT, padx=6)
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=6)

        root_pad.columnconfigure(1, weight=1)

        self.bind("<Return>", lambda _: self._connect())
        self.bind("<Escape>", lambda _: self.destroy())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _toggle_auth(self) -> None:
        if self._auth.get() == "password":
            self._key_frame.grid_remove()
            self._pw_frame.grid()
        else:
            self._pw_frame.grid_remove()
            self._key_frame.grid()

    def _browse_key(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Private Key File",
            initialdir=os.path.expanduser("~/.ssh"),
            parent=self,
        )
        if path:
            self._key.set(path)

    def _load_saved(self, _event=None) -> None:
        sessions = self._session_mgr.sessions
        idx = [str(s) for s in sessions].index(self._saved_var.get())
        s = sessions[idx]
        self._host.set(s.host)
        self._port.set(str(s.port))
        self._user.set(s.username)
        self._auth.set(s.auth_type)
        self._key.set(s.key_file or "")
        self._toggle_auth()

    def _save_session(self) -> None:
        host = self._host.get().strip()
        if not host:
            messagebox.showerror("Error", "Host is required.", parent=self)
            return
        s = SavedSession(
            name=f"{self._user.get().strip()}@{host}",
            host=host,
            port=self._port_int(),
            username=self._user.get().strip(),
            auth_type=self._auth.get(),
            key_file=self._key.get().strip(),
        )
        self._session_mgr.add_or_update(s)
        messagebox.showinfo("Saved", f"Session '{s.name}' saved.", parent=self)

    def _port_int(self) -> int:
        try:
            return int(self._port.get())
        except ValueError:
            return 22

    def _connect(self) -> None:
        host = self._host.get().strip()
        if not host:
            messagebox.showerror("Error", "Host is required.", parent=self)
            return
        self.result = {
            "host": host,
            "port": self._port_int(),
            "username": self._user.get().strip(),
            "auth_type": self._auth.get(),
            "password": self._pw.get() if self._auth.get() == "password" else None,
            "key_file": self._key.get().strip() or None,
            "key_passphrase": self._pp.get() or None,
        }
        self.destroy()

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")
