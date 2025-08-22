# -*- coding: utf-8 -*-

"""
The background worker for running analysis/merge jobs without freezing the GUI.
"""

from PySide6.QtCore import QObject, QRunnable, Signal, Slot
from typing import Dict, Any, Optional

from vsg_core.pipeline import JobPipeline

class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    log = Signal(str)
    progress = Signal(float) # 0.0 to 1.0
    status = Signal(str)
    finished = Signal(dict) # Emits the final result dictionary

class JobWorker(QRunnable):
    """
    A QRunnable worker that executes a JobPipeline in a separate thread.
    """
    def __init__(self, config: Dict[str, Any], ref_file: str, sec_file: Optional[str], ter_file: Optional[str], and_merge: bool):
        super().__init__()
        self.config = config
        self.ref_file = ref_file
        self.sec_file = sec_file
        self.ter_file = ter_file
        self.and_merge = and_merge
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """The main entry point for the worker thread."""
        pipeline = JobPipeline(
            config=self.config,
            log_callback=lambda msg: self.signals.log.emit(msg),
            progress_callback=lambda val: self.signals.progress.emit(val)
        )

        try:
            result = pipeline.run_job(self.ref_file, self.sec_file, self.ter_file, self.and_merge)
            self.signals.finished.emit(result)
        except Exception as e:
            error_result = {'status': 'Failed', 'error': str(e)}
            self.signals.log.emit(f'[FATAL WORKER ERROR] {e}')
            self.signals.finished.emit(error_result)
