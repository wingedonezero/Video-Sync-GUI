# vsg_qt/options_dialog/tabs.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel
)

def _dir_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le); h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_dir(le))
    return w

def _file_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le); h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_file(le))
    return w

def _browse_for_dir(line_edit: QLineEdit):
    path = QFileDialog.getExistingDirectory(None, "Select Directory", line_edit.text())
    if path: line_edit.setText(path)

def _browse_for_file(line_edit: QLineEdit):
    path, _ = QFileDialog.getOpenFileName(None, "Select File", line_edit.text())
    if path: line_edit.setText(path)

class StorageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['output_folder'] = _dir_input()
        self.widgets['temp_root'] = _dir_input()
        self.widgets['videodiff_path'] = _file_input()
        f.addRow('Output Directory:', self.widgets['output_folder'])
        f.addRow('Temporary Directory:', self.widgets['temp_root'])
        f.addRow('VideoDiff Path (optional):', self.widgets['videodiff_path'])

class AnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)

        mode = QComboBox(); mode.addItems(['Audio Correlation', 'VideoDiff'])
        self.widgets['analysis_mode'] = mode

        scc = QSpinBox(); scc.setRange(1, 100)
        scd = QSpinBox(); scd.setRange(1, 120)
        mmp = QDoubleSpinBox(); mmp.setRange(0.1, 100.0); mmp.setDecimals(1); mmp.setSingleStep(1.0)
        self.widgets['scan_chunk_count'] = scc
        self.widgets['scan_chunk_duration'] = scd
        self.widgets['min_match_pct'] = mmp

        vmin = QDoubleSpinBox(); vmin.setRange(0.0, 500.0); vmin.setDecimals(2)
        vmax = QDoubleSpinBox(); vmax.setRange(0.0, 500.0); vmax.setDecimals(2)
        self.widgets['videodiff_error_min'] = vmin
        self.widgets['videodiff_error_max'] = vmax

        # --- UPDATED: Generalized Language hints ---
        self.widgets['analysis_lang_source1'] = QLineEdit(); self.widgets['analysis_lang_source1'].setPlaceholderText('e.g., eng (blank = first available)')
        self.widgets['analysis_lang_others'] = QLineEdit(); self.widgets['analysis_lang_others'].setPlaceholderText('e.g., jpn (blank = first available)')
        # -----------------------------------------

        self.widgets['audio_decode_native'] = QCheckBox("Decode at native sample rate (may be less stable)")
        self.widgets['audio_peak_fit'] = QCheckBox("Enable sub-sample peak fitting (higher precision)")
        bl_hz = QSpinBox(); bl_hz.setRange(0, 22000); bl_hz.setSuffix(" Hz"); bl_hz.setToolTip("0 = Off")
        self.widgets['audio_bandlimit_hz'] = bl_hz

        f.addRow('Analysis Mode:', self.widgets['analysis_mode'])
        f.addRow(QLabel('<b>Audio Correlation Settings</b>'))
        f.addRow('Scan Chunks:', self.widgets['scan_chunk_count'])
        f.addRow('Chunk Duration (s):', self.widgets['scan_chunk_duration'])
        f.addRow('Minimum Match %:', self.widgets['min_match_pct'])
        f.addRow(QLabel('<b>Advanced Correlation Settings (Experimental)</b>'))
        f.addRow(self.widgets['audio_decode_native'])
        f.addRow(self.widgets['audio_peak_fit'])
        f.addRow("Apply low-pass filter below:", self.widgets['audio_bandlimit_hz'])
        f.addRow(QLabel('<b>VideoDiff Settings</b>'))
        f.addRow('Min Allowed Error:', self.widgets['videodiff_error_min'])
        f.addRow('Max Allowed Error:', self.widgets['videodiff_error_max'])
        f.addRow(QLabel('<b>Analysis Audio Track Selection</b>'))
        f.addRow('Source 1 (Reference) Language:', self.widgets['analysis_lang_source1'])
        f.addRow('Other Sources Language:', self.widgets['analysis_lang_others'])

class ChaptersTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['rename_chapters'] = QCheckBox('Rename to "Chapter NN"')
        self.widgets['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe')
        snap_mode = QComboBox(); snap_mode.addItems(['previous', 'nearest'])
        self.widgets['snap_mode'] = snap_mode
        thr = QSpinBox(); thr.setRange(0, 5000)
        self.widgets['snap_threshold_ms'] = thr
        self.widgets['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)')
        f.addWidget(self.widgets['rename_chapters'])
        f.addWidget(self.widgets['snap_chapters'])
        f.addRow('Snap Mode:', self.widgets['snap_mode'])
        f.addRow('Snap Threshold (ms):', self.widgets['snap_threshold_ms'])
        f.addWidget(self.widgets['snap_starts_only'])

class MergeBehaviorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.widgets['disable_track_statistics_tags'] = QCheckBox('Disable track statistics tags (for purist remuxes)')
        f.addRow(self.widgets['apply_dialog_norm_gain'])
        f.addRow(self.widgets['disable_track_statistics_tags'])

class LoggingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['log_compact'] = QCheckBox('Use compact logging')
        self.widgets['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs')
        step = QSpinBox(); step.setRange(1, 100); step.setSuffix('%')
        self.widgets['log_progress_step'] = step
        tail = QSpinBox(); tail.setRange(0, 1000); tail.setSuffix(' lines')
        self.widgets['log_error_tail'] = tail
        self.widgets['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)')
        self.widgets['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)')
        f.addRow(self.widgets['log_compact'])
        f.addRow(self.widgets['log_autoscroll'])
        f.addRow('Progress Step:', self.widgets['log_progress_step'])
        f.addRow('Error Tail:', self.widgets['log_error_tail'])
        f.addRow(self.widgets['log_show_options_pretty'])
        f.addRow(self.widgets['log_show_options_json'])
