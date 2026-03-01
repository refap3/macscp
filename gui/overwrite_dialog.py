"""Dialog shown when a transfer destination file already exists."""

import tkinter as tk
from tkinter import ttk
from datetime import datetime


class OverwriteDialog(tk.Toplevel):
    """Ask user how to handle an existing destination file.

    ``result`` is one of: 'overwrite', 'overwrite_all', 'skip', 'skip_all', 'cancel'
    """

    def __init__(
        self,
        parent: tk.Widget,
        filename: str,
        src_info: dict | None = None,
        dst_info: dict | None = None,
    ):
        super().__init__(parent)
        self.title("File already exists")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.result: str = "cancel"

        self._build_ui(filename, src_info, dst_info)
        self._center(parent)
        self.wait_window()

    # ------------------------------------------------------------------

    def _build_ui(self, filename: str, src_info, dst_info) -> None:
        f = ttk.Frame(self, padding=18)
        f.pack(fill=tk.BOTH, expand=True)

        # Icon + message
        ttk.Label(f, text="⚠️", font=("TkDefaultFont", 28)).grid(
            row=0, column=0, rowspan=3, padx=(0, 12), sticky="n"
        )
        ttk.Label(f, text="A file with this name already exists:", font=("TkDefaultFont", 11)).grid(
            row=0, column=1, sticky="w"
        )
        ttk.Label(f, text=filename, font=("TkDefaultFont", 11, "bold")).grid(
            row=1, column=1, sticky="w"
        )

        # Source / destination info
        if src_info or dst_info:
            info_frame = ttk.Frame(f, relief="sunken", padding=8)
            info_frame.grid(row=2, column=1, sticky="ew", pady=(8, 0))
            row = 0
            for label, info in [("Source:", src_info), ("Destination:", dst_info)]:
                if info:
                    size_str = _fmt_size(info.get("size", 0))
                    mod_str = ""
                    if info.get("modified"):
                        try:
                            mod_str = info["modified"].strftime(" (%Y-%m-%d %H:%M)")
                        except Exception:
                            pass
                    ttk.Label(info_frame, text=label, foreground="#666").grid(
                        row=row, column=0, sticky="w"
                    )
                    ttk.Label(info_frame, text=f"{size_str}{mod_str}").grid(
                        row=row, column=1, sticky="w", padx=(6, 0)
                    )
                    row += 1

        # Buttons
        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, pady=(16, 0))

        btn_defs = [
            ("Overwrite",     "overwrite"),
            ("Overwrite All", "overwrite_all"),
            ("Skip",          "skip"),
            ("Skip All",      "skip_all"),
            ("Cancel",        "cancel"),
        ]
        for text, value in btn_defs:
            v = value
            ttk.Button(bf, text=text, width=12, command=lambda v=v: self._pick(v)).pack(
                side=tk.LEFT, padx=4
            )

        self.bind("<Escape>", lambda _: self._pick("cancel"))

    def _pick(self, value: str) -> None:
        self.result = value
        self.destroy()

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
        return f"{size / 1024:.1f} KB"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB"
    else:
        return f"{size / 1_073_741_824:.1f} GB"
