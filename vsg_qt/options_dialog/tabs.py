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

        # NEW: Segmented Audio Correction section
        segment_group = QGroupBox("🔧 Segmented Audio Correction (Experimental)")
        segment_group.setToolTip("Automatically fixes complex sync issues with multiple step-changes in a single audio track.")
        segment_layout = QFormLayout(segment_group)

        self.widgets['segmented_enabled'] = QCheckBox("Enable segmented audio correction")
        self.widgets['segmented_enabled'].setToolTip(
            "When enabled, detects audio tracks with stepping sync issues and creates perfectly corrected versions.\n"
            "Only applies when multiple distinct delay segments are detected."
        )

        self.widgets['segmented_qa_threshold'] = QDoubleSpinBox()
        self.widgets['segmented_qa_threshold'].setRange(50.0, 99.0)
        self.widgets['segmented_qa_threshold'].setValue(85.0)
        self.widgets['segmented_qa_threshold'].setDecimals(1)
        self.widgets['segmented_qa_threshold'].setSuffix("%")
        self.widgets['segmented_qa_threshold'].setToolTip("Quality assurance threshold - corrected tracks must correlate above this percentage with the reference.")

        segment_layout.addRow(self.widgets['segmented_enabled'])
        segment_layout.addRow("QA Correlation Threshold:", self.widgets['segmented_qa_threshold'])
        main_layout.addWidget(segment_group)

        prep_group = QGroupBox("Step 1: Audio Pre-Processing")
        prep_group.setToolTip("Optionally prepares audio before analysis to improve signal quality.")
        prep_layout = QFormLayout(prep_group)
        self.widgets['source_separation_model'] = QComboBox()
        self.widgets['source_separation_model'].addItems(['None (Use Original Audio)', 'Demucs (Isolate Dialogue)'])
        self.widgets['source_separation_model'].setToolTip("Uses an AI model to separate dialogue from music/effects.")
        self.widgets['filtering_method'] = QComboBox()
        self.widgets['filtering_method'].addItems(['None', 'Low-Pass Filter', 'Dialogue Band-Pass Filter'])
        self.widgets['filtering_method'].setToolTip("'Dialogue Band-Pass' isolates common speech frequencies.")
        self.cutoff_container = QWidget()
        cutoff_layout = QFormLayout(self.cutoff_container); cutoff_layout.setContentsMargins(0, 0, 0, 0)
        self.widgets['audio_bandlimit_hz'] = QSpinBox(); self.widgets['audio_bandlimit_hz'].setRange(0, 22000); self.widgets['audio_bandlimit_hz'].setSuffix(" Hz")
        cutoff_layout.addRow("Low-Pass Cutoff:", self.widgets['audio_bandlimit_hz'])
        prep_layout.addRow("Source Separation:", self.widgets['source_separation_model'])
        prep_layout.addRow("Audio Filtering:", self.widgets['filtering_method'])
        prep_layout.addRow(self.cutoff_container)
        main_layout.addWidget(prep_group)

        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_layout = QFormLayout(core_group)
        self.widgets['correlation_method'] = QComboBox(); self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'VideoDiff'])
        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100)
        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120)
        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0)
        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100)
        core_layout.addRow("Correlation Method:", self.widgets['correlation_method'])
        core_layout.addRow("Number of Chunks:", self.widgets['scan_chunk_count'])
        core_layout.addRow("Duration of Chunks (s):", self.widgets['scan_chunk_duration'])
        core_layout.addRow("Minimum Match Confidence (%):", self.widgets['min_match_pct'])
        core_layout.addRow("Minimum Accepted Chunks:", self.widgets['min_accepted_chunks'])
        main_layout.addWidget(core_group)

        lang_group = QGroupBox("Step 3: Audio Track Selection")
        lang_layout = QFormLayout(lang_group)
        self.widgets['analysis_lang_source1'] = QLineEdit(); self.widgets['analysis_lang_source1'].setPlaceholderText("e.g., eng (blank = first audio track)")
        self.widgets['analysis_lang_others'] = QLineEdit(); self.widgets['analysis_lang_others'].setPlaceholderText("e.g., jpn (blank = first audio track)")
        lang_layout.addRow("Source 1 (Reference) Language:", self.widgets['analysis_lang_source1'])
        lang_layout.addRow("Other Sources Language:", self.widgets['analysis_lang_others'])
        main_layout.addWidget(lang_group)

        adv_group = QGroupBox("Step 4: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)
        self.widgets['use_soxr'] = QCheckBox("Use High-Quality Resampling (SoXR)")
        self.widgets['audio_peak_fit'] = QCheckBox("Enable Sub-Sample Peak Fitting (SCC only)")
        self.widgets['log_audio_drift'] = QCheckBox("Log Audio Drift Metric")
        adv_layout.addWidget(self.widgets['use_soxr'])
        adv_layout.addWidget(self.widgets['audio_peak_fit'])
        adv_layout.addWidget(self.widgets['log_audio_drift'])
        main_layout.addWidget(adv_group)

        main_layout.addStretch(1)
        self.widgets['filtering_method'].currentTextChanged.connect(self._update_filter_options)
        self._update_filter_options(self.widgets['filtering_method'].currentText())

    def _update_filter_options(self, text: str):
        self.cutoff_container.setVisible(text == "Low-Pass Filter")

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
        main_layout = QVBoxLayout(self)

        general_group = QGroupBox("General")
        form1 = QFormLayout(general_group)
        self.widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.widgets['disable_track_statistics_tags'] = QCheckBox('Disable track statistics tags (for purist remuxes)')
        form1.addWidget(self.widgets['apply_dialog_norm_gain'])
        form1.addWidget(self.widgets['disable_track_statistics_tags'])
        main_layout.addWidget(general_group)

        # NEW: Post-Merge Finalization section
        post_merge_group = QGroupBox("Post-Merge Finalization")
        post_merge_group.setToolTip("Optional, lossless steps that run after the main merge to improve compatibility.")
        form2 = QFormLayout(post_merge_group)

        self.widgets['post_mux_normalize_timestamps'] = QCheckBox("Rebase timestamps to fix thumbnails (requires FFmpeg)")
        self.widgets['post_mux_normalize_timestamps'].setToolTip(
            "If a file's video track doesn't start at timestamp zero (due to a global shift),\n"
            "this option will perform a fast, lossless remux to fix it.\n"
            "This resolves issues with thumbnail generation in most file managers."
        )

        self.widgets['post_mux_strip_tags'] = QCheckBox("Strip \"ENCODER\" tag added by FFmpeg (requires mkvpropedit)")
        self.widgets['post_mux_strip_tags'].setToolTip(
            "If the timestamp normalization step is run, FFmpeg will add an 'ENCODER' tag to the file.\n"
            "This option will run a quick update to remove that tag for a cleaner file."
        )

        form2.addWidget(self.widgets['post_mux_normalize_timestamps'])
        form2.addWidget(self.widgets['post_mux_strip_tags'])
        main_layout.addWidget(post_merge_group)

        main_layout.addStretch(1)

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
