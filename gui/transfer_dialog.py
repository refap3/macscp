"""File transfer progress dialog."""

import tkinter as tk
from tkinter import ttk


class TransferDialog(tk.Toplevel):
    """Displays progress for an ongoing file transfer.

    The dialog reads from a shared ``state`` dict updated by the worker thread.
    Call ``poll()`` from the main thread via ``root.after`` to refresh the UI.
    """

    def __init__(self, parent: tk.Widget, direction: str = "Upload"):
        super().__init__(parent)
        self.title(f"{direction} in progress…")
        self.geometry("460x210")
        self.resizable(False, False)
        self.transient(parent)

        self.cancelled = False
        self._direction = direction

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._center(parent)

    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)

        self._heading = ttk.Label(f, text="Preparing…", font=("TkDefaultFont", 11, "bold"))
        self._heading.pack(anchor="w")

        self._file_lbl = ttk.Label(f, text="", foreground="#555555")
        self._file_lbl.pack(anchor="w", pady=(3, 8))

        ttk.Label(f, text="File progress:").pack(anchor="w")
        self._file_bar = ttk.Progressbar(f, mode="determinate", length=420)
        self._file_bar.pack(fill=tk.X, pady=(2, 8))

        ttk.Label(f, text="Overall:").pack(anchor="w")
        self._overall_bar = ttk.Progressbar(f, mode="determinate", length=420)
        self._overall_bar.pack(fill=tk.X, pady=(2, 10))

        row = ttk.Frame(f)
        row.pack(fill=tk.X)
        self._info_lbl = ttk.Label(row, text="")
        self._info_lbl.pack(side=tk.LEFT)

        ttk.Button(f, text="Cancel", command=self._on_cancel).pack(pady=(6, 0))

    def _on_cancel(self) -> None:
        self.cancelled = True

    def update_from_state(self, state: dict) -> None:
        """Refresh all widgets from the shared state dict."""
        total = state.get("total_files", 1) or 1
        current = state.get("current_num", 0)
        fname = state.get("current_file", "")
        fp = state.get("file_progress", 0)
        ft = state.get("file_total", 0)

        self._heading.config(
            text=f"{self._direction}: file {current + 1} of {total}"
        )
        self._file_lbl.config(text=fname)

        if ft > 0:
            self._file_bar["value"] = (fp / ft) * 100
        else:
            self._file_bar["value"] = 0

        self._overall_bar["value"] = (current / total) * 100

        transferred_str = _fmt(fp) if ft else ""
        total_str = _fmt(ft) if ft else ""
        if transferred_str and total_str:
            self._info_lbl.config(text=f"{transferred_str} / {total_str}")

        self.update_idletasks()

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")


def _fmt(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB"
    else:
        return f"{size / 1_073_741_824:.1f} GB"
