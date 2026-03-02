"""Thread-safe helper to invoke a callable on the Qt main thread."""

import queue
from PyQt6.QtCore import QTimer


_queue: queue.Queue = queue.Queue()
_timer: QTimer | None = None


def _drain():
    """Process all pending callables (runs on the main thread via QTimer)."""
    while True:
        try:
            fn = _queue.get_nowait()
        except queue.Empty:
            break
        fn()


def init_invoke():
    """Must be called once from the main thread after QApplication is created."""
    global _timer
    _timer = QTimer()
    _timer.timeout.connect(_drain)
    _timer.start(16)  # ~60 Hz polling


def invoke_in_main(fn):
    """Schedule fn() to run on the Qt main/GUI thread. Safe from any thread."""
    _queue.put(fn)
