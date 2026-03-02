"""Dialog shown when a transfer destination file already exists (PyQt6)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout,
    QFrame, QWidget,
)
from PyQt6.QtCore import Qt


class OverwriteDialog(QDialog):
    """Ask user how to handle an existing destination file.

    result is one of: 'overwrite', 'overwrite_all', 'skip', 'skip_all', 'cancel'
    """

    def __init__(self, parent: QWidget, filename: str,
                 src_info: dict | None = None, dst_info: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("File already exists")
        self.setFixedSize(520, 220)
        self.setModal(True)

        self.result: str = "cancel"
        self._build_ui(filename, src_info, dst_info)

    def _build_ui(self, filename: str, src_info, dst_info) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)

        # Warning header
        header = QHBoxLayout()
        icon = QLabel("Warning")
        icon.setStyleSheet("font-size: 24px; font-weight: bold; color: #FF9800;")
        header.addWidget(icon)

        msg_layout = QVBoxLayout()
        msg_layout.addWidget(QLabel("A file with this name already exists:"))
        name_label = QLabel(filename)
        name_label.setStyleSheet("font-weight: bold;")
        msg_layout.addWidget(name_label)
        header.addLayout(msg_layout)
        header.addStretch()
        layout.addLayout(header)

        # File info
        if src_info or dst_info:
            info_grid = QGridLayout()
            row = 0
            for label_text, info in [("Source:", src_info), ("Destination:", dst_info)]:
                if info:
                    size_str = _fmt_size(info.get("size", 0))
                    mod_str = ""
                    if info.get("modified"):
                        try:
                            mod_str = f" ({info['modified'].strftime('%Y-%m-%d %H:%M')})"
                        except Exception:
                            pass
                    lbl = QLabel(label_text)
                    lbl.setStyleSheet("color: #666;")
                    info_grid.addWidget(lbl, row, 0)
                    info_grid.addWidget(QLabel(f"{size_str}{mod_str}"), row, 1)
                    row += 1
            layout.addLayout(info_grid)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        for text, value in [
            ("Overwrite", "overwrite"),
            ("Overwrite All", "overwrite_all"),
            ("Skip", "skip"),
            ("Skip All", "skip_all"),
            ("Cancel", "cancel"),
        ]:
            btn = QPushButton(text)
            btn.clicked.connect(lambda checked, v=value: self._pick(v))
            btn_layout.addWidget(btn)

        layout.addLayout(btn_layout)

    def _pick(self, value: str) -> None:
        self.result = value
        self.accept()


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB"
    else:
        return f"{size / 1_073_741_824:.1f} GB"
