# vsg_qt/options_dialog/tabs.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QGroupBox, QVBoxLayout
)

# --- Helper functions (Unchanged) ---
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
        self.widgets['output_folder'].setToolTip("The default directory where final merged files will be saved.")
        self.widgets['temp_root'] = _dir_input()
        self.widgets['temp_root'].setToolTip("The root directory for storing temporary files during processing (e.g., extracted tracks, logs).")
        self.widgets['videodiff_path'] = _file_input()
        self.widgets['videodiff_path'].setToolTip("Optional. The full path to the 'videodiff' executable if it's not in your system's PATH.")
        f.addRow('Output Directory:', self.widgets['output_folder'])
        f.addRow('Temporary Directory:', self.widgets['temp_root'])
        f.addRow('VideoDiff Path (optional):', self.widgets['videodiff_path'])

class AnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # Step 1: Audio Pre-Processing
        prep_group = QGroupBox("Step 1: Audio Pre-Processing")
        prep_layout = QFormLayout(prep_group)
        self.widgets['source_separation_model'] = QComboBox(); self.widgets['source_separation_model'].addItems(['None (Use Original Audio)', 'Demucs (Isolate Dialogue)']); self.widgets['source_separation_model'].setToolTip("Uses an AI model to separate dialogue from music/effects.\n(Requires external dependencies and is experimental).")
        self.widgets['filtering_method'] = QComboBox(); self.widgets['filtering_method'].addItems(['None', 'Low-Pass Filter', 'Dialogue Band-Pass Filter']); self.widgets['filtering_method'].setToolTip("Apply a filter to the audio before analysis to improve the signal-to-noise ratio.\n'Dialogue Band-Pass' is recommended for most content.")
        self.cutoff_container = QWidget()
        cutoff_layout = QFormLayout(self.cutoff_container); cutoff_layout.setContentsMargins(0, 0, 0, 0)
        self.widgets['audio_bandlimit_hz'] = QSpinBox(); self.widgets['audio_bandlimit_hz'].setRange(0, 22000); self.widgets['audio_bandlimit_hz'].setSuffix(" Hz"); self.widgets['audio_bandlimit_hz'].setToolTip("For the Low-Pass Filter, specifies the frequency (in Hz) above which audio data is cut off.")
        cutoff_layout.addRow("Low-Pass Cutoff:", self.widgets['audio_bandlimit_hz'])
        prep_layout.addRow("Source Separation:", self.widgets['source_separation_model'])
        prep_layout.addRow("Audio Filtering:", self.widgets['filtering_method'])
        prep_layout.addRow(self.cutoff_container)
        main_layout.addWidget(prep_group)

        # Step 2: Core Analysis Engine
        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_layout = QFormLayout(core_group)
        self.widgets['correlation_method'] = QComboBox(); self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'VideoDiff']); self.widgets['correlation_method'].setToolTip("The core algorithm used to find the time offset.\nGCC-PHAT is often faster and more robust against noise.")
        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100); self.widgets['scan_chunk_count'].setToolTip("The number of separate audio segments to analyze across the file's duration.")
        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120); self.widgets['scan_chunk_duration'].setToolTip("The length (in seconds) of each individual audio segment to be analyzed.")
        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0); self.widgets['min_match_pct'].setToolTip("The minimum correlation score for an audio chunk to be considered a valid match.")
        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100); self.widgets['min_accepted_chunks'].setToolTip("The minimum number of valid chunks required for the analysis to be considered successful.")
        core_layout.addRow("Correlation Method:", self.widgets['correlation_method'])
        core_layout.addRow("Number of Chunks:", self.widgets['scan_chunk_count'])
        core_layout.addRow("Duration of Chunks (s):", self.widgets['scan_chunk_duration'])
        core_layout.addRow("Minimum Match Confidence (%):", self.widgets['min_match_pct'])
        core_layout.addRow("Minimum Accepted Chunks:", self.widgets['min_accepted_chunks'])
        main_layout.addWidget(core_group)

        # Step 3: Advanced Filtering & Scan Controls
        adv_filter_group = QGroupBox("Step 3: Advanced Filtering & Scan Controls")
        adv_filter_layout = QFormLayout(adv_filter_group)
        self.widgets['scan_start_percentage'] = QDoubleSpinBox(); self.widgets['scan_start_percentage'].setRange(0.0, 99.0); self.widgets['scan_start_percentage'].setSuffix(" %"); self.widgets['scan_start_percentage'].setToolTip("Where to begin the analysis scan, as a percentage of the file's total duration.")
        self.widgets['scan_end_percentage'] = QDoubleSpinBox(); self.widgets['scan_end_percentage'].setRange(1.0, 100.0); self.widgets['scan_end_percentage'].setSuffix(" %"); self.widgets['scan_end_percentage'].setToolTip("Where to end the analysis scan, as a percentage of the file's total duration.")
        self.widgets['filter_bandpass_lowcut_hz'] = QDoubleSpinBox(); self.widgets['filter_bandpass_lowcut_hz'].setRange(20.0, 10000.0); self.widgets['filter_bandpass_lowcut_hz'].setSuffix(" Hz"); self.widgets['filter_bandpass_lowcut_hz'].setToolTip("The lower frequency for the Dialogue Band-Pass filter.")
        self.widgets['filter_bandpass_highcut_hz'] = QDoubleSpinBox(); self.widgets['filter_bandpass_highcut_hz'].setRange(100.0, 22000.0); self.widgets['filter_bandpass_highcut_hz'].setSuffix(" Hz"); self.widgets['filter_bandpass_highcut_hz'].setToolTip("The upper frequency for the Dialogue Band-Pass filter.")
        self.widgets['filter_bandpass_order'] = QSpinBox(); self.widgets['filter_bandpass_order'].setRange(1, 10); self.widgets['filter_bandpass_order'].setToolTip("The steepness of the band-pass filter. Higher values have a sharper cutoff.")
        self.widgets['filter_lowpass_taps'] = QSpinBox(); self.widgets['filter_lowpass_taps'].setRange(11, 501); self.widgets['filter_lowpass_taps'].setToolTip("The number of taps (quality) for the Low-Pass filter. Must be an odd number."); self.widgets['filter_lowpass_taps'].setSingleStep(2)
        adv_filter_layout.addRow("Scan Start Position:", self.widgets['scan_start_percentage'])
        adv_filter_layout.addRow("Scan End Position:", self.widgets['scan_end_percentage'])
        adv_filter_layout.addRow("Band-Pass Low Cutoff:", self.widgets['filter_bandpass_lowcut_hz'])
        adv_filter_layout.addRow("Band-Pass High Cutoff:", self.widgets['filter_bandpass_highcut_hz'])
        adv_filter_layout.addRow("Band-Pass Filter Order:", self.widgets['filter_bandpass_order'])
        adv_filter_layout.addRow("Low-Pass Filter Taps:", self.widgets['filter_lowpass_taps'])
        main_layout.addWidget(adv_filter_group)

        # Step 4: Audio Track Selection
        lang_group = QGroupBox("Step 4: Audio Track Selection")
        lang_layout = QFormLayout(lang_group)
        self.widgets['analysis_lang_source1'] = QLineEdit(); self.widgets['analysis_lang_source1'].setPlaceholderText("e.g., eng (blank = first audio track)"); self.widgets['analysis_lang_source1'].setToolTip("The 3-letter language code (e.g., eng, jpn) for the audio track to use from Source 1.\nLeave blank to use the first available audio track.")
        self.widgets['analysis_lang_others'] = QLineEdit(); self.widgets['analysis_lang_others'].setPlaceholderText("e.g., jpn (blank = first audio track)"); self.widgets['analysis_lang_others'].setToolTip("The 3-letter language code for audio tracks in all other sources.\nLeave blank to use their first available audio track.")
        lang_layout.addRow("Source 1 (Reference) Language:", self.widgets['analysis_lang_source1'])
        lang_layout.addRow("Other Sources Language:", self.widgets['analysis_lang_others'])
        main_layout.addWidget(lang_group)

        # Step 5: Advanced Tweaks & Diagnostics
        adv_group = QGroupBox("Step 5: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)
        self.widgets['use_soxr'] = QCheckBox("Use High-Quality Resampling (SoXR)"); self.widgets['use_soxr'].setToolTip("Use the high-quality SoXR resampler library when decoding audio.\nSlower but more accurate than the default resampler.")
        self.widgets['audio_peak_fit'] = QCheckBox("Enable Sub-Sample Peak Fitting (SCC only)"); self.widgets['audio_peak_fit'].setToolTip("For Standard Correlation (SCC), use parabolic interpolation to find a more precise, sub-sample peak.\nMay improve accuracy slightly.")
        self.widgets['log_audio_drift'] = QCheckBox("Log Audio Drift Metric"); self.widgets['log_audio_drift'].setToolTip("Calculate and log a metric that indicates potential audio drift or speed differences between sources.")
        adv_layout.addWidget(self.widgets['use_soxr'])
        adv_layout.addWidget(self.widgets['audio_peak_fit'])
        adv_layout.addWidget(self.widgets['log_audio_drift'])
        main_layout.addWidget(adv_group)

        # Segmented Correction Group (MOVED TO BOTTOM & ALL WIDGETS ADDED)
        segment_group = QGroupBox("🔧 Segmented Audio Correction (Experimental & Advanced)")
        segment_layout = QFormLayout(segment_group)
        self.widgets['segmented_enabled'] = QCheckBox("Enable segmented audio correction"); self.widgets['segmented_enabled'].setToolTip("When enabled, detects audio with stepping sync issues and creates a corrected version.")
        segment_layout.addRow(self.widgets['segmented_enabled'])
        segment_layout.addRow(QLabel("<b>Main Controls</b>"))
        self.widgets['segmented_qa_threshold'] = QDoubleSpinBox(); self.widgets['segmented_qa_threshold'].setRange(50.0, 99.0); self.widgets['segmented_qa_threshold'].setSuffix("%"); self.widgets['segmented_qa_threshold'].setToolTip("Quality assurance threshold - corrected tracks must correlate above this percentage with the reference.")
        self.widgets['segment_scan_offset_s'] = QDoubleSpinBox(); self.widgets['segment_scan_offset_s'].setRange(0.0, 300.0); self.widgets['segment_scan_offset_s'].setSuffix(" s"); self.widgets['segment_scan_offset_s'].setToolTip("Ignore the first N seconds of the audio during the coarse scan to avoid unstable results from opening logos/music.")
        segment_layout.addRow("QA Correlation Threshold:", self.widgets['segmented_qa_threshold'])
        segment_layout.addRow("Initial Scan Offset:", self.widgets['segment_scan_offset_s'])
        segment_layout.addRow(QLabel("<b>Detection & Triage Tweaks</b>"))
        self.widgets['segment_stepping_drift_threshold_ms'] = QSpinBox(); self.widgets['segment_stepping_drift_threshold_ms'].setRange(50, 1000); self.widgets['segment_stepping_drift_threshold_ms'].setSuffix(" ms"); self.widgets['segment_stepping_drift_threshold_ms'].setToolTip("Minimum time difference between chunks to trigger segmented correction.")
        self.widgets['segment_triage_std_dev_ms'] = QSpinBox(); self.widgets['segment_triage_std_dev_ms'].setRange(10, 200); self.widgets['segment_triage_std_dev_ms'].setSuffix(" ms"); self.widgets['segment_triage_std_dev_ms'].setToolTip("If the standard deviation of delays is below this, correction is skipped.")
        segment_layout.addRow("Stepping Detection Threshold:", self.widgets['segment_stepping_drift_threshold_ms'])
        segment_layout.addRow("Triage Stability Threshold:", self.widgets['segment_triage_std_dev_ms'])
        segment_layout.addRow(QLabel("<b>Coarse Scan Tweaks</b>"))
        self.widgets['segment_coarse_chunk_s'] = QSpinBox(); self.widgets['segment_coarse_chunk_s'].setRange(5, 60); self.widgets['segment_coarse_chunk_s'].setSuffix(" s"); self.widgets['segment_coarse_chunk_s'].setToolTip("Duration of audio chunks for the initial broad scan.")
        self.widgets['segment_coarse_step_s'] = QSpinBox(); self.widgets['segment_coarse_step_s'].setRange(10, 300); self.widgets['segment_coarse_step_s'].setSuffix(" s"); self.widgets['segment_coarse_step_s'].setToolTip("Time to jump forward between each coarse scan chunk.")
        self.widgets['segment_search_locality_s'] = QSpinBox(); self.widgets['segment_search_locality_s'].setRange(2, 30); self.widgets['segment_search_locality_s'].setSuffix(" s"); self.widgets['segment_search_locality_s'].setToolTip("The time window to search for a match in the target audio.")
        segment_layout.addRow("Coarse Scan Chunk Duration:", self.widgets['segment_coarse_chunk_s'])
        segment_layout.addRow("Coarse Scan Step Size:", self.widgets['segment_coarse_step_s'])
        segment_layout.addRow("Search Window Radius:", self.widgets['segment_search_locality_s'])
        segment_layout.addRow(QLabel("<b>Fine Scan & Confidence Tweaks</b>"))
        self.widgets['segment_min_confidence_ratio'] = QDoubleSpinBox(); self.widgets['segment_min_confidence_ratio'].setRange(2.0, 20.0); self.widgets['segment_min_confidence_ratio'].setDecimals(1); self.widgets['segment_min_confidence_ratio'].setToolTip("Minimum ratio of correlation peak to noise floor for a valid match.")
        self.widgets['segment_fine_chunk_s'] = QDoubleSpinBox(); self.widgets['segment_fine_chunk_s'].setRange(0.5, 10.0); self.widgets['segment_fine_chunk_s'].setSuffix(" s"); self.widgets['segment_fine_chunk_s'].setToolTip("Duration of audio chunks for the high-precision boundary search.")
        self.widgets['segment_fine_iterations'] = QSpinBox(); self.widgets['segment_fine_iterations'].setRange(5, 15); self.widgets['segment_fine_iterations'].setToolTip("Number of iterations for the binary search to find a sync boundary.")
        segment_layout.addRow("Min. Correlation Confidence:", self.widgets['segment_min_confidence_ratio'])
        segment_layout.addRow("Fine Scan Chunk Duration:", self.widgets['segment_fine_chunk_s'])
        segment_layout.addRow("Fine Scan Iterations:", self.widgets['segment_fine_iterations'])
        main_layout.addWidget(segment_group)

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
        self.widgets['rename_chapters'] = QCheckBox('Rename to "Chapter NN"'); self.widgets['rename_chapters'].setToolTip("Automatically rename all chapters to a standard format (e.g., 'Chapter 01', 'Chapter 02').")
        self.widgets['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe'); self.widgets['snap_chapters'].setToolTip("Adjust chapter timestamps to align with the nearest video keyframe, which can improve seeking performance.")
        snap_mode = QComboBox(); snap_mode.addItems(['previous', 'nearest']); snap_mode.setToolTip("'previous': Always snaps to the last keyframe before the chapter time.\n'nearest': Snaps to the closest keyframe, either before or after.")
        self.widgets['snap_mode'] = snap_mode
        thr = QSpinBox(); thr.setRange(0, 5000); thr.setToolTip("The maximum time (in milliseconds) a chapter can be from a keyframe to be snapped.\nChapters further away will be left untouched.")
        self.widgets['snap_threshold_ms'] = thr
        self.widgets['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)'); self.widgets['snap_starts_only'].setToolTip("If checked, only chapter start times are snapped. If unchecked, both start and end times are snapped.")
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
        self.widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)'); self.widgets['apply_dialog_norm_gain'].setToolTip("For AC3/E-AC3 audio tracks, remove the DialNorm metadata.\nThis can sometimes prevent players from lowering the volume.")
        self.widgets['disable_track_statistics_tags'] = QCheckBox('Disable track statistics tags (for purist remuxes)'); self.widgets['disable_track_statistics_tags'].setToolTip("Prevent mkvmerge from writing metadata tags about the track's statistics (e.g., BPS, DURATION).")
        form1.addWidget(self.widgets['apply_dialog_norm_gain'])
        form1.addWidget(self.widgets['disable_track_statistics_tags'])
        main_layout.addWidget(general_group)
        post_merge_group = QGroupBox("Post-Merge Finalization")
        form2 = QFormLayout(post_merge_group)
        self.widgets['post_mux_normalize_timestamps'] = QCheckBox("Rebase timestamps to fix thumbnails (requires FFmpeg)"); self.widgets['post_mux_normalize_timestamps'].setToolTip("If a file's video track doesn't start at timestamp zero (due to a global shift),\nthis option will perform a fast, lossless remux with FFmpeg to fix it.\nThis resolves issues with thumbnail generation in most file managers.")
        self.widgets['post_mux_strip_tags'] = QCheckBox("Strip ENCODER tag added by FFmpeg (requires mkvpropedit)"); self.widgets['post_mux_strip_tags'].setToolTip("If the timestamp normalization step is run, FFmpeg will add an 'ENCODER' tag to the file.\nThis option will run a quick update with mkvpropedit to remove that tag for a cleaner file.")
        form2.addWidget(self.widgets['post_mux_normalize_timestamps'])
        form2.addWidget(self.widgets['post_mux_strip_tags'])
        main_layout.addWidget(post_merge_group)
        main_layout.addStretch(1)

class LoggingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['log_compact'] = QCheckBox('Use compact logging'); self.widgets['log_compact'].setToolTip("Reduce the verbosity of command-line tool output in the log.")
        self.widgets['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs'); self.widgets['log_autoscroll'].setToolTip("Automatically scroll the log view to the bottom as new messages arrive.")
        step = QSpinBox(); step.setRange(1, 100); step.setSuffix('%'); step.setToolTip("How often to show 'Progress: X%' messages from mkvmerge in the log.\nA value of 20 means it will log at 20%, 40%, 60%, etc.")
        self.widgets['log_progress_step'] = step
        tail = QSpinBox(); tail.setRange(0, 1000); tail.setSuffix(' lines'); tail.setToolTip("In compact mode, if a command fails, show this many of the last lines of output to help diagnose the error.")
        self.widgets['log_error_tail'] = tail
        self.widgets['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)'); self.widgets['log_show_options_pretty'].setToolTip("Print the full mkvmerge command to the log in a human-readable format before execution.")
        self.widgets['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)'); self.widgets['log_show_options_json'].setToolTip("Print the full mkvmerge command to the log in the raw JSON format that is passed to the tool.")
        f.addRow(self.widgets['log_compact'])
        f.addRow(self.widgets['log_autoscroll'])
        f.addRow('Progress Step:', self.widgets['log_progress_step'])
        f.addRow('Error Tail:', self.widgets['log_error_tail'])
        f.addRow(self.widgets['log_show_options_pretty'])
        f.addRow(self.widgets['log_show_options_json'])
