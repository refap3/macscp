"""File/directory properties dialog."""

import tkinter as tk
from tkinter import ttk


class PropertiesDialog(tk.Toplevel):
    """Show detailed info for a file or directory entry."""

    def __init__(self, parent: tk.Widget, entry: dict):
        super().__init__(parent)
        self.title(f"Properties — {entry['name']}")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._build_ui(entry)
        self._center(parent)
        self.wait_window()

    def _build_ui(self, e: dict) -> None:
        f = ttk.Frame(self, padding=20)
        f.pack(fill=tk.BOTH, expand=True)

        icon = "📁" if e.get("is_dir") else "📄"
        ttk.Label(f, text=icon, font=("TkDefaultFont", 32)).grid(
            row=0, column=0, columnspan=2, pady=(0, 8)
        )

        rows = [
            ("Name:",        e.get("name", "")),
            ("Path:",        e.get("path", "")),
            ("Type:",        "Directory" if e.get("is_dir") else "File"),
            ("Size:",        _fmt_size(e.get("size", 0)) if not e.get("is_dir") else "—"),
            ("Modified:",    _fmt_date(e.get("modified"))),
            ("Permissions:", e.get("permissions") or "—"),
        ]

        for i, (label, value) in enumerate(rows, start=1):
            ttk.Label(f, text=label, foreground="#555", anchor="e").grid(
                row=i, column=0, sticky="e", padx=(0, 8), pady=3
            )
            # Selectable value label via Text widget
            t = tk.Text(f, height=1, width=48, relief="flat",
                        background=f.cget("background"), font=("TkDefaultFont", 12))
            t.insert("1.0", value)
            t.config(state="disabled")
            t.grid(row=i, column=1, sticky="w", pady=3)

        ttk.Button(f, text="Close", command=self.destroy).grid(
            row=len(rows) + 1, column=0, columnspan=2, pady=(12, 0)
        )

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1_048_576:
        return f"{size / 1024:.1f} KB ({size:,} bytes)"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB ({size:,} bytes)"
    else:
        return f"{size / 1_073_741_824:.1f} GB ({size:,} bytes)"


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%Y-%m-%d  %H:%M:%S")
    except Exception:
        return str(dt)
