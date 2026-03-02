"""File transfer progress dialog (PyQt6)."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QWidget,
)
from PyQt6.QtCore import Qt


class TransferDialog(QDialog):
    """Displays progress for an ongoing file transfer."""

    def __init__(self, parent: QWidget, direction: str = "Upload"):
        super().__init__(parent)
        self.setWindowTitle(f"{direction} in progress…")
        self.setFixedSize(460, 210)
        self.setModal(True)

        self.cancelled = False
        self._direction = direction

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(18, 18, 18, 18)

        self._heading = QLabel("Preparing…")
        self._heading.setStyleSheet("font-weight: bold; font-size: 13px;")
        layout.addWidget(self._heading)

        self._file_lbl = QLabel("")
        self._file_lbl.setStyleSheet("color: #555;")
        layout.addWidget(self._file_lbl)

        layout.addWidget(QLabel("File progress:"))
        self._file_bar = QProgressBar()
        self._file_bar.setRange(0, 100)
        layout.addWidget(self._file_bar)

        layout.addWidget(QLabel("Overall:"))
        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 100)
        layout.addWidget(self._overall_bar)

        self._info_lbl = QLabel("")
        layout.addWidget(self._info_lbl)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self._on_cancel)
        layout.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_cancel(self) -> None:
        self.cancelled = True

    def closeEvent(self, event) -> None:
        self.cancelled = True
        event.accept()

    def update_from_state(self, state: dict) -> None:
        total = state.get("total_files", 1) or 1
        current = state.get("current_num", 0)
        fname = state.get("current_file", "")
        fp = state.get("file_progress", 0)
        ft = state.get("file_total", 0)

        self._heading.setText(f"{self._direction}: file {current + 1} of {total}")
        self._file_lbl.setText(fname)

        if ft > 0:
            self._file_bar.setValue(int((fp / ft) * 100))
        else:
            self._file_bar.setValue(0)

        self._overall_bar.setValue(int((current / total) * 100))

        transferred_str = _fmt(fp) if ft else ""
        total_str = _fmt(ft) if ft else ""
        if transferred_str and total_str:
            self._info_lbl.setText(f"{transferred_str} / {total_str}")


def _fmt(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1_048_576:
        return f"{size / 1024:.1f} KB"
    elif size < 1_073_741_824:
        return f"{size / 1_048_576:.1f} MB"
    else:
        return f"{size / 1_073_741_824:.1f} GB"
