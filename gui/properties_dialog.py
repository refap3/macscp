"""File/directory properties dialog (PyQt6)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QPushButton, QWidget,
)
from PyQt6.QtCore import Qt


class PropertiesDialog(QDialog):
    """Show detailed info for a file or directory entry."""

    def __init__(self, parent: QWidget, entry: dict):
        super().__init__(parent)
        self.setWindowTitle(f"Properties — {entry['name']}")
        self.setFixedWidth(420)
        self.setModal(True)

        self._build_ui(entry)

    def _build_ui(self, e: dict) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Icon
        icon_text = "Directory" if e.get("is_dir") else "File"
        icon_label = QLabel(icon_text)
        icon_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)

        # Properties grid
        grid = QGridLayout()
        grid.setSpacing(6)

        rows = [
            ("Name:", e.get("name", "")),
            ("Path:", e.get("path", "")),
            ("Type:", "Directory" if e.get("is_dir") else "File"),
            ("Size:", _fmt_size(e.get("size", 0)) if not e.get("is_dir") else "—"),
            ("Modified:", _fmt_date(e.get("modified"))),
            ("Permissions:", e.get("permissions") or "—"),
        ]

        for i, (label, value) in enumerate(rows):
            lbl = QLabel(label)
            lbl.setStyleSheet("color: #555; font-weight: bold;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(lbl, i, 0)

            val = QLabel(str(value))
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(val, i, 1)

        layout.addLayout(grid)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)


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
