#!/usr/bin/env python3
"""MacSCP — A WinSCP-style SFTP client for macOS, written in Python."""

import sys
import os

# Ensure the project root is on the path regardless of how this is launched.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk
from gui.app import MacSCPApp


def main() -> None:
    root = tk.Tk()

    # Use clam theme — aqua's native NSTableView hover rendering is too expensive
    # (redraws at 60 fps on every mouse-move, causing the UI to feel sluggish).
    style = ttk.Style(root)
    style.theme_use("clam")
    # Tune treeview appearance for readability
    style.configure("Treeview",
                    rowheight=22,
                    font=("TkDefaultFont", 12),
                    background="#FFFFFF",
                    fieldbackground="#FFFFFF",
                    foreground="#111111")
    style.configure("Treeview.Heading",
                    font=("TkDefaultFont", 11, "bold"),
                    relief="flat",
                    padding=(4, 4))
    style.map("Treeview",
              background=[("selected", "#3574E2")],
              foreground=[("selected", "#FFFFFF")])
    # Hover effect is already gone with clam; disable focus outline on rows too
    style.layout("Treeview.Item", [
        ("Treeview.padding", {"sticky": "nswe", "children": [
            ("Treeview.image",  {"side": "left", "sticky": ""}),
            ("Treeview.focus",  {"side": "left", "sticky": "", "children": [
                ("Treeview.text", {"side": "left", "sticky": ""}),
            ]}),
        ]}),
    ])

    # macOS-specific: use native menu bar
    root.createcommand("tk::mac::Quit", root.destroy)

    # Set application icon if available
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(icon_path):
        img = tk.PhotoImage(file=icon_path)
        root.iconphoto(True, img)

    app = MacSCPApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
