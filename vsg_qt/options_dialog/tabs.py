# vsg_qt/options_dialog/tabs.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QGroupBox, QVBoxLayout
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

        main_layout = QVBoxLayout(self)

        # --- Group 1: Audio Pre-Processing ---
        prep_group = QGroupBox("Step 1: Audio Pre-Processing")
        prep_group.setToolTip("Optionally prepares audio before analysis to improve signal quality.")
        prep_layout = QFormLayout(prep_group)

        self.widgets['source_separation_model'] = QComboBox()
        self.widgets['source_separation_model'].addItems(['None (Use Original Audio)', 'Demucs (Isolate Dialogue)'])
        self.widgets['source_separation_model'].setToolTip("Uses an AI model (Demucs) to separate dialogue from music/effects.\nRecommended for files with very loud background noise that causes poor matches.\nThis is a slow process and requires Demucs to be installed.")

        self.widgets['filtering_method'] = QComboBox()
        self.widgets['filtering_method'].addItems(['None', 'Low-Pass Filter', 'Dialogue Band-Pass Filter'])
        self.widgets['filtering_method'].setToolTip("'Low-Pass' removes high-frequency noise. 'Dialogue Band-Pass' isolates\ncommon speech frequencies, which is highly effective for improving matches.")

        self.cutoff_container = QWidget()
        cutoff_layout = QFormLayout(self.cutoff_container)
        cutoff_layout.setContentsMargins(0, 0, 0, 0)

        self.widgets['audio_bandlimit_hz'] = QSpinBox()
        self.widgets['audio_bandlimit_hz'].setRange(0, 22000)
        self.widgets['audio_bandlimit_hz'].setSuffix(" Hz")
        self.widgets['audio_bandlimit_hz'].setToolTip("The frequency above which sounds will be removed. Set to 0 to disable.")
        cutoff_layout.addRow("Low-Pass Cutoff:", self.widgets['audio_bandlimit_hz'])

        prep_layout.addRow("Source Separation:", self.widgets['source_separation_model'])
        prep_layout.addRow("Audio Filtering:", self.widgets['filtering_method'])
        prep_layout.addRow(self.cutoff_container)

        main_layout.addWidget(prep_group)

        # --- Group 2: Core Analysis Engine ---
        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_group.setToolTip("Configures the main algorithm for detecting the time delay.")
        core_layout = QFormLayout(core_group)

        self.widgets['correlation_method'] = QComboBox()
        self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'VideoDiff'])
        self.widgets['correlation_method'].setToolTip("'Standard' is fast and compares audio waveform shapes.\n'Phase' is more robust against volume and mixing differences.\n'VideoDiff' analyzes video frames instead of audio.")

        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100)
        self.widgets['scan_chunk_count'].setToolTip("How many different segments of the files to analyze.\nMore chunks can improve accuracy on longer files.")

        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120)
        self.widgets['scan_chunk_duration'].setToolTip("The length of each audio segment to compare in seconds.\nLonger durations can be more stable but are slower.")

        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0)
        self.widgets['min_match_pct'].setToolTip("A single chunk's analysis is rejected if its confidence\nscore is below this percentage.")

        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100)
        self.widgets['min_accepted_chunks'].setToolTip("If the total number of accepted chunks is less than this, the entire\nanalysis for the file will fail. Prevents a result based on too few matches.")

        core_layout.addRow("Correlation Method:", self.widgets['correlation_method'])
        core_layout.addRow("Number of Chunks:", self.widgets['scan_chunk_count'])
        core_layout.addRow("Duration of Chunks (s):", self.widgets['scan_chunk_duration'])
        core_layout.addRow("Minimum Match Confidence (%):", self.widgets['min_match_pct'])
        core_layout.addRow("Minimum Accepted Chunks:", self.widgets['min_accepted_chunks'])

        main_layout.addWidget(core_group)

        # --- Group 3: Audio Track Selection ---
        lang_group = QGroupBox("Step 3: Audio Track Selection")
        lang_group.setToolTip("Specify a language code (e.g., 'eng', 'jpn') to ensure analysis uses a specific audio track.")
        lang_layout = QFormLayout(lang_group)

        self.widgets['analysis_lang_source1'] = QLineEdit()
        self.widgets['analysis_lang_source1'].setPlaceholderText("e.g., eng (blank = first audio track)")
        self.widgets['analysis_lang_others'] = QLineEdit()
        self.widgets['analysis_lang_others'].setPlaceholderText("e.g., jpn (blank = first audio track)")

        lang_layout.addRow("Source 1 (Reference) Language:", self.widgets['analysis_lang_source1'])
        lang_layout.addRow("Other Sources Language:", self.widgets['analysis_lang_others'])

        main_layout.addWidget(lang_group)

        # --- Group 4: Advanced Tweaks & Diagnostics ---
        adv_group = QGroupBox("Step 4: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)

        # FIX: Re-added the SoXR resampler option
        self.widgets['use_soxr'] = QCheckBox("Use High-Quality Resampling (SoXR)")
        self.widgets['use_soxr'].setToolTip("Uses a higher-quality algorithm when resampling audio.\nRequires an FFmpeg build that includes SoXR.")

        self.widgets['audio_peak_fit'] = QCheckBox("Enable Sub-Sample Peak Fitting (SCC only)")
        self.widgets['audio_peak_fit'].setToolTip("Uses parabolic interpolation to find the delay with sub-sample\nprecision. Only applies to the 'Standard Correlation (SCC)' method.")

        self.widgets['log_audio_drift'] = QCheckBox("Log Audio Drift Metric")
        self.widgets['log_audio_drift'].setToolTip("Calculates and logs the difference in delay between the start and\nend of the file. Useful for diagnosing framerate mismatches.")

        adv_layout.addWidget(self.widgets['use_soxr']) # FIX: Added to layout
        adv_layout.addWidget(self.widgets['audio_peak_fit'])
        adv_layout.addWidget(self.widgets['log_audio_drift'])

        main_layout.addWidget(adv_group)
        main_layout.addStretch(1)

        self.widgets['filtering_method'].currentTextChanged.connect(self._update_filter_options)
        self._update_filter_options(self.widgets['filtering_method'].currentText())

    def _update_filter_options(self, text: str):
        is_low_pass = (text == "Low-Pass Filter")
        self.cutoff_container.setVisible(is_low_pass)

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
