#!/usr/bin/env python3
"""MacSCP — A WinSCP-style SFTP client for macOS, written in Python."""

import sys
import os

# Ensure the project root is on the path regardless of how this is launched.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gui._invoke import init_invoke
from gui.app import MacSCPApp


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("MacSCP")
    init_invoke()  # enable thread-safe callbacks to main thread

    # Set application icon if available
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MacSCPApp()
    window.show()
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
