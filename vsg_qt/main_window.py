# vsg_qt/main_window.py
from __future__ import annotations
from pathlib import Path
from importlib import import_module

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QPushButton, QLabel, QComboBox, QProgressBar,
    QFileDialog, QMessageBox
)

from vsg_qt.settings_io import Settings
from vsg_qt.widgets.options_dialog import OptionsDialog
from vsg.logbus import add_sink, remove_sink, _log
from vsg.settings import load_settings, CONFIG
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job

class MainWindow(QMainWindow):
    def __init__(self, project_root: Path) -> None:
        super().__init__()
        self.setWindowTitle("Video/Audio Sync & Merge — Qt")
        self.resize(1400, 900)
        self.project_root = project_root
        self.settings = Settings(project_root)

        central = QWidget(self); self.setCentralWidget(central)
        vbox = QVBoxLayout(central); vbox.setContentsMargins(12, 12, 12, 12); vbox.setSpacing(int(self.settings.get("row_spacing_px", 8)))

        hdr = QHBoxLayout(); vbox.addLayout(hdr)
        self.btn_options = QPushButton("Options…"); self.btn_options.clicked.connect(self.open_options)
        hdr.addWidget(self.btn_options); hdr.addStretch(1)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        self.inp_ref = QLineEdit(); self._add_browse_row(form, "Reference", self.inp_ref)
        self.inp_sec = QLineEdit(); self._add_browse_row(form, "Secondary", self.inp_sec)
        self.inp_ter = QLineEdit(); self._add_browse_row(form, "Tertiary", self.inp_ter)
        vbox.addLayout(form)

        vbox.addWidget(self._hline())
        row = QHBoxLayout()
        row.addWidget(QLabel("Workflow"))
        self.cmb_workflow = QComboBox(); self.cmb_workflow.addItems(["Analyze Only", "Analyze & Merge"])
        self.cmb_workflow.setCurrentText(self.settings.get("workflow", "Analyze & Merge"))
        self.cmb_workflow.currentTextChanged.connect(lambda v: self._set("workflow", v))
        row.addWidget(self.cmb_workflow)
        row.addSpacing(16)
        row.addWidget(QLabel("Mode"))
        self.cmb_mode = QComboBox(); self.cmb_mode.addItems(["Audio Correlation", "VideoDiff"])
        self.cmb_mode.setCurrentText(self.settings.get("analysis_mode", "Audio Correlation"))
        self.cmb_mode.currentTextChanged.connect(lambda v: self._set("analysis_mode", v))
        row.addWidget(self.cmb_mode); row.addStretch(1); vbox.addLayout(row)

        vbox.addWidget(self._hline()); vbox.addWidget(QLabel("Actions"))
        act = QHBoxLayout()
        self.btn_analyze_only = QPushButton("Analyze Only"); self.btn_analyze_only.clicked.connect(self.run_analyze_only); act.addWidget(self.btn_analyze_only)
        self.btn_analyze_merge = QPushButton("Analyze & Merge"); self.btn_analyze_merge.clicked.connect(self.run_analyze_and_merge); act.addWidget(self.btn_analyze_merge)
        act.addSpacing(16); self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0); act.addWidget(self.progress, 1)
        vbox.addLayout(act)

        vbox.addWidget(self._hline()); vbox.addWidget(QLabel("Log"))
        self.txt_log = QTextEdit(); self.txt_log.setReadOnly(True); self.txt_log.setMinimumHeight(260); vbox.addWidget(self.txt_log, 1)

        self.apply_appearance()
        add_sink(self._on_log)

    def closeEvent(self, event):
        remove_sink(self._on_log)
        return super().closeEvent(event)

    def _hline(self):
        w = QWidget(); w.setFixedHeight(1); w.setStyleSheet("background:#999;"); return w

    def _set(self, key: str, value): self.settings.set(key, value)
    def _log(self, msg: str): self.txt_log.append(msg)

    def _on_log(self, line: str):
        # append from backend logbus
        self.txt_log.append(line)

    def _add_browse_row(self, form: QFormLayout, label: str, edit: QLineEdit):
        row = QHBoxLayout(); w = QWidget(); w.setLayout(row); row.addWidget(edit, 1)
        btn = QPushButton("…"); btn.clicked.connect(lambda: self._browse_file(edit)); row.addWidget(btn, 0)
        form.addRow(label, w)

    def _browse_file(self, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", edit.text() or "", "Media (*.mkv *.mp4 *.m4a *.flac *.aac *.wav);;All files (*)")
        if path: edit.setText(path)

    def open_options(self):
        dlg = OptionsDialog(self, self.settings)
        if dlg.exec():
            self.settings.save()
            self.apply_appearance()

    def apply_appearance(self):
        fam = self.settings.get("font_family", "")
        size = int(self.settings.get("font_point_size", 10))
        self.setFont(QFont(fam, pointSize=size) if fam else QFont("", pointSize=size))
        row_gap = int(self.settings.get("row_spacing_px", 8))
        self.centralWidget().layout().setSpacing(row_gap)
        h = int(self.settings.get("input_height_px", 32))
        for w in (self.inp_ref, self.inp_sec, self.inp_ter):
            w.setMinimumHeight(h); w.setMaximumHeight(h)

    def _ensure_settings(self):
        # Persist current UI selections to settings + load into vsg.settings.CONFIG
        self.settings.set("workflow", self.cmb_workflow.currentText())
        self.settings.set("analysis_mode", self.cmb_mode.currentText())
        self.settings.save()
        load_settings()  # refresh vsg.settings.CONFIG

    @Slot()
    def run_analyze_only(self):
        self._ensure_settings()
        ref, sec, ter = self.inp_ref.text().strip(), self.inp_sec.text().strip(), self.inp_ter.text().strip()
        if not ref:
            QMessageBox.warning(self, "Missing", "Reference path is required.")
            return
        _log("=== Job start (Analyze Only) ===")
        try:
            for (r, s, t) in discover_jobs(ref, sec or None, ter or None):
                _log("Job:", r, s, t)
                # Use merge_job with workflow==Analyze Only — backend should honor skip-mux.
                merge_job(r, s, t, self.settings.get("output_folder",""), logger="qt", videodiff_path=Path(self.settings.get("videodiff_path","") or "."))
            _log("=== Job complete ===")
        except Exception as e:
            _log("[FAILED]", repr(e))
            _log("=== Job complete (failed) ===")

    @Slot()
    def run_analyze_and_merge(self):
        self._ensure_settings()
        ref, sec, ter = self.inp_ref.text().strip(), self.inp_sec.text().strip(), self.inp_ter.text().strip()
        if not ref:
            QMessageBox.warning(self, "Missing", "Reference path is required.")
            return
        _log("=== Job start (Analyze & Merge) ===")
        try:
            for (r, s, t) in discover_jobs(ref, sec or None, ter or None):
                _log("Job:", r, s, t)
                merge_job(r, s, t, self.settings.get("output_folder",""), logger="qt", videodiff_path=Path(self.settings.get("videodiff_path","") or "."))
            _log("=== Job complete ===")
        except Exception as e:
            _log("[FAILED]", repr(e))
            _log("=== Job complete (failed) ===")
