#!/usr/bin/env python3
"""Minimal click test — verifies Double-Button-1 selection fix."""
import tkinter as tk
from tkinter import ttk

count = {"btn": 0, "tree": 0}

root = tk.Tk()
root.title("Click Test")
root.geometry("400x350")

style = ttk.Style(root)
style.theme_use("aqua")

label = tk.Label(root, text="Click treeview rows as fast as you can.\n"
                            "Every click should increment the counter.",
                 font=("TkDefaultFont", 12), pady=10)
label.pack()

status = tk.StringVar(value="btn: 0  |  tree: 0")
tk.Label(root, textvariable=status, font=("Menlo", 14, "bold"), fg="blue").pack(pady=5)

def on_btn():
    count["btn"] += 1
    status.set(f"btn: {count['btn']}  |  tree: {count['tree']}")

ttk.Button(root, text="Click me", command=on_btn).pack(pady=5)

tree = ttk.Treeview(root, columns=("name",), show="headings", height=8)
tree.heading("name", text="Name")
for i in range(20):
    tree.insert("", "end", values=(f"Row {i}",))
tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

def on_tree_select(event):
    count["tree"] += 1
    status.set(f"btn: {count['btn']}  |  tree: {count['tree']}")

def on_tree_double(event):
    """Fix: Double-Button-1 suppresses the class ButtonPress-1 binding,
    so the selection never updates.  Do it explicitly."""
    row = tree.identify_row(event.y)
    if row:
        tree.selection_set(row)
        tree.focus(row)

tree.bind("<<TreeviewSelect>>", on_tree_select)
tree.bind("<Double-Button-1>", on_tree_double)

root.mainloop()
