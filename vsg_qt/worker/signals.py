from PySide6.QtCore import QObject, Signal


class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    log = Signal(str)            # Emitted with log lines
    progress = Signal(float)     # 0.0 to 1.0
    status = Signal(str)         # Short status string
    finished_job = Signal(dict)  # Result for a single job
    finished_all = Signal(list)  # List of all results at batch end
