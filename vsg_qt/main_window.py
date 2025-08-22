
from __future__ import annotations
from PySide6 import QtWidgets, QtGui, QtCore
from pathlib import Path
from typing import Optional

from vsg.settings_io import CONFIG, load_settings, save_settings
from vsg_qt.appearance import apply_appearance
from vsg_qt.options_dialog import OptionsDialog
from vsg.logbus import _log, LOG_Q, STATUS_Q, PROGRESS_Q, set_status, set_progress
from vsg.jobs.merge_job import merge_job

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self._app = app
        self.setWindowTitle("Video/Audio Sync & Merge — Qt")
        self.resize(1200, 720)

        central = QtWidgets.QWidget(); self.setCentralWidget(central)
        v = QtWidgets.QVBoxLayout(central)

        # Options row
        row_opts = QtWidgets.QHBoxLayout()
        btn_opts = QtWidgets.QPushButton("Options…")
        btn_opts.clicked.connect(self.open_options)
        row_opts.addWidget(btn_opts)
        row_opts.addStretch(1)
        v.addLayout(row_opts)

        # Inputs
        self.ref_edit, btn_r = self._path_row(v, "Reference")
        self.sec_edit, btn_s = self._path_row(v, "Secondary")
        self.ter_edit, btn_t = self._path_row(v, "Tertiary")

        v.addSpacing(6)

        # Actions row (workflow in Options)
        actions = QtWidgets.QHBoxLayout()
        self.btn_analyze = QtWidgets.QPushButton("Analyze Only")
        self.btn_merge = QtWidgets.QPushButton("Analyze  &  Merge")
        self.progress = QtWidgets.QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        self.status_lbl = QtWidgets.QLabel("Idle")

        self.btn_analyze.clicked.connect(self.analyze_only)
        self.btn_merge.clicked.connect(self.analyze_merge)

        actions.addWidget(self.btn_analyze)
        actions.addWidget(self.btn_merge)
        actions.addWidget(self.progress, 1)
        actions.addWidget(self.status_lbl)
        v.addLayout(actions)

        # Log
        self.log = QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(max(1000, CONFIG.get("log_tail_lines", 2000) or 10000))
        v.addWidget(self.log, 1)

        apply_appearance(self._app, self)

        # F9 opens preferences
        QtGui.QShortcut(QtGui.QKeySequence("F9"), self, activated=self.open_options)

        # Start timers to drain thread-safe queues
        self._log_timer = QtCore.QTimer(self)
        self._log_timer.timeout.connect(self._pump_queues)
        self._log_timer.start(50)

        self._log("Settings initialized/updated with defaults.")
        self._log("Settings applied to UI.")

    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        super().closeEvent(e)

    def _path_row(self, vbox, label: str):
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(label))
        edit = QtWidgets.QLineEdit()
        edit.setPlaceholderText("Choose a file…")
        btn = QtWidgets.QPushButton("…")
        def pick():
            f, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Choose {label} file")
            if f:
                edit.setText(f)
        btn.clicked.connect(pick)
        row.addWidget(edit, 1); row.addWidget(btn)
        vbox.addLayout(row)
        return edit, btn

    # --- logs/status ---
    def _on_log(self, line: str) -> None:
        self.log.appendPlainText(line)
        if CONFIG.get("log_autoscroll", True):
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _on_status(self, text: str) -> None:
        self.status_lbl.setText(text)

    def _on_progress(self, frac: float) -> None:
        try:
            self.progress.setValue(int(max(0.0, min(1.0, float(frac))) * 100.0))
        except Exception:
            pass

    def _log(self, msg: str):
        self._on_log(msg)

    # --- actions
    def open_options(self):
        dlg = OptionsDialog(self._app, self, self)
        dlg.exec()

    def analyze_only(self):
        CONFIG["workflow"] = "Analyze Only"
        save_settings(CONFIG)
        self._run_job()

    def analyze_merge(self):
        CONFIG["workflow"] = "Analyze & Merge"
        save_settings(CONFIG)
        self._run_job()

    def _run_job(self):
        ref = self.ref_edit.text().strip()
        sec = self.sec_edit.text().strip() or None
        ter = self.ter_edit.text().strip() or None
        out_dir = CONFIG.get("output_folder") or "."

        if not ref:
            QtWidgets.QMessageBox.warning(self, "Missing file", "Please choose a Reference file.")
            return
        if not Path(ref).exists():
            QtWidgets.QMessageBox.warning(self, "Not found", f"Reference file not found:\n{ref}")
            return

        self.btn_analyze.setEnabled(False)
        self.btn_merge.setEnabled(False)
        self.progress.setValue(1)
        self.status_lbl.setText("Starting…")
        set_status("Starting…")
        set_progress(0.0)

        # Use a worker thread to keep UI responsive
        set_status("Running analysis…")
        self.worker = _JobWorker(ref, sec, ter, out_dir, self)
        self.worker.finished.connect(self._on_job_done)
        self.worker.start()

    def _on_job_done(self, ok: bool, message: str):
        self.btn_analyze.setEnabled(True)
        self.btn_merge.setEnabled(True)
        if ok:
            set_status("Done")
            set_progress(1.0)
            QtWidgets.QMessageBox.information(self, "Done", message)
        else:
            QtWidgets.QMessageBox.critical(self, "Failed", message)


class _JobWorker(QtCore.QThread):
    finished = QtCore.Signal(bool, str)

    def __init__(self, ref: str, sec: Optional[str], ter: Optional[str], out_dir: str, parent=None):
        super().__init__(parent)
        self.ref, self.sec, self.ter, self.out_dir = ref, sec, ter, out_dir

    def run(self):
        try:
            # videodiff path comes from CONFIG (options); pass Path or empty
            vp = Path(CONFIG.get("videodiff_path") or "")
            res = None
            try:
                res = merge_job(self.ref, self.sec, self.ter, self.out_dir, logger=None, videodiff_path=vp)
            except TypeError:
                try:
                    res = merge_job(self.ref, self.sec, self.ter, self.out_dir, videodiff_path=vp)
                except TypeError:
                    res = merge_job(self.ref, self.sec, self.ter, self.out_dir)
            ok = bool(res and res.get("status"))
            msg = res.get("status") if isinstance(res, dict) else ("OK" if ok else "Unknown result")
            self.finished.emit(ok, msg)
        except Exception as e:
            _log("Job failed:", repr(e))
            self.finished.emit(False, str(e))
