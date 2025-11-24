# vsg_qt/options_dialog/tabs.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QGroupBox, QVBoxLayout
)

# --- Helper functions ---
def _dir_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0,0,0,0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le)
    h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_dir(le))
    return w

def _file_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0,0,0,0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le)
    h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_file(le))
    return w

def _browse_for_dir(line_edit: QLineEdit):
    path = QFileDialog.getExistingDirectory(None, "Select Directory", line_edit.text())
    if path: line_edit.setText(path)

def _browse_for_file(line_edit: QLineEdit, nameFilter: str = "All Files (*)"):
    path, _ = QFileDialog.getOpenFileName(None, "Select File", line_edit.text(), nameFilter)
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
        self.widgets['subtile_ocr_path'] = _file_input()
        self.widgets['subtile_ocr_path'].setToolTip("Optional. The full path to the 'subtile-ocr' executable if it's not in your system's PATH.")
        self.widgets['subtile_ocr_char_blacklist'] = QLineEdit()
        self.widgets['subtile_ocr_char_blacklist'].setToolTip("Optional. A string of characters to blacklist during the OCR process (e.g., '|/_~').")
        f.addRow('Output Directory:', self.widgets['output_folder'])
        f.addRow('Temporary Directory:', self.widgets['temp_root'])
        f.addRow('VideoDiff Path (optional):', self.widgets['videodiff_path'])
        f.addRow('Subtitle OCR Path (optional):', self.widgets['subtile_ocr_path'])
        f.addRow('OCR Character Blacklist (optional):', self.widgets['subtile_ocr_char_blacklist'])

class SubtitleCleanupTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets['ocr_cleanup_enabled'] = QCheckBox("Enable post-OCR cleanup")
        self.widgets['ocr_cleanup_enabled'].setToolTip("Automatically fix common OCR errors in subtitles after processing.")

        self.widgets['ocr_cleanup_custom_wordlist_path'] = _file_input()
        self.widgets['ocr_cleanup_custom_wordlist_path'].setToolTip("Optional. A path to a custom wordlist (.txt file, one word per line) to prevent OCR corrections on specific names or terms.")

        self.widgets['ocr_cleanup_normalize_ellipsis'] = QCheckBox("Normalize ellipsis (...)")
        self.widgets['ocr_cleanup_normalize_ellipsis'].setToolTip("Replace the Unicode ellipsis character '…' with three periods '...'.")

        f.addRow(self.widgets['ocr_cleanup_enabled'])
        f.addRow("Custom Wordlist:", self.widgets['ocr_cleanup_custom_wordlist_path'])
        f.addRow(self.widgets['ocr_cleanup_normalize_ellipsis'])

class TimingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        self.widgets['timing_fix_enabled'] = QCheckBox("Enable subtitle timing corrections")
        self.widgets['timing_fix_enabled'].setToolTip("Apply automated timing fixes after OCR and text cleanup.")
        main_layout.addWidget(self.widgets['timing_fix_enabled'])

        # --- Overlaps Group ---
        overlap_group = QGroupBox("Fix Overlapping Display Times")
        overlap_layout = QFormLayout(overlap_group)
        self.widgets['timing_fix_overlaps'] = QCheckBox("Enable")
        self.widgets['timing_overlap_min_gap_ms'] = QSpinBox()
        self.widgets['timing_overlap_min_gap_ms'].setRange(0, 1000)
        self.widgets['timing_overlap_min_gap_ms'].setSuffix(" ms")
        self.widgets['timing_overlap_min_gap_ms'].setToolTip("The minimum gap to enforce between two subtitles.")
        overlap_layout.addRow(self.widgets['timing_fix_overlaps'])
        overlap_layout.addRow("Minimum Gap:", self.widgets['timing_overlap_min_gap_ms'])
        main_layout.addWidget(overlap_group)

        # --- Short Durations Group ---
        short_group = QGroupBox("Fix Short Display Times")
        short_layout = QFormLayout(short_group)
        self.widgets['timing_fix_short_durations'] = QCheckBox("Enable")
        self.widgets['timing_min_duration_ms'] = QSpinBox()
        self.widgets['timing_min_duration_ms'].setRange(100, 5000)
        self.widgets['timing_min_duration_ms'].setSuffix(" ms")
        self.widgets['timing_min_duration_ms'].setToolTip("Subtitles shorter than this duration will be extended.")
        short_layout.addRow(self.widgets['timing_fix_short_durations'])
        short_layout.addRow("Minimum Duration:", self.widgets['timing_min_duration_ms'])
        main_layout.addWidget(short_group)

        # --- Long Durations Group ---
        long_group = QGroupBox("Fix Long Display Times (based on Reading Speed)")
        long_layout = QFormLayout(long_group)
        self.widgets['timing_fix_long_durations'] = QCheckBox("Enable")
        self.widgets['timing_max_cps'] = QDoubleSpinBox()
        self.widgets['timing_max_cps'].setRange(5.0, 100.0)
        self.widgets['timing_max_cps'].setSuffix(" CPS")
        self.widgets['timing_max_cps'].setToolTip("Maximum characters per second. Subtitles that stay on screen too long for their text length will be shortened.")
        long_layout.addRow(self.widgets['timing_fix_long_durations'])
        long_layout.addRow("Max Characters Per Second:", self.widgets['timing_max_cps'])
        main_layout.addWidget(long_group)

        main_layout.addStretch(1)

class AnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

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

        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_layout = QFormLayout(core_group)
        self.widgets['correlation_method'] = QComboBox(); self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'VideoDiff']); self.widgets['correlation_method'].setToolTip("The core algorithm used to find the time offset.\nGCC-PHAT is often faster and more robust against noise.")
        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100); self.widgets['scan_chunk_count'].setToolTip("The number of separate audio segments to analyze across the file's duration.")
        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120); self.widgets['scan_chunk_duration'].setToolTip("The length (in seconds) of each individual audio segment to be analyzed.")
        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0); self.widgets['min_match_pct'].setToolTip("The minimum correlation score for an audio chunk to be considered a valid match.")
        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100); self.widgets['min_accepted_chunks'].setToolTip("The minimum number of valid chunks required for the analysis to be considered successful.")
        self.widgets['delay_selection_mode'] = QComboBox(); self.widgets['delay_selection_mode'].addItems(['Mode (Most Common)', 'First Stable', 'Average']); self.widgets['delay_selection_mode'].setToolTip("How to choose the final delay from multiple chunk measurements:\n\n• Mode (Most Common) - Picks the delay that appears most frequently (Default)\n  Best for: Files with stable sync throughout most of the duration\n\n• First Stable - Uses the delay from the first stable segment\n  Best for: Files where sync changes mid-file (stepping issues)\n  Configure stability criteria below\n\n• Average - Calculates the mean of all delay measurements\n  Best for: Files with small variations around a central value")
        self.widgets['first_stable_min_chunks'] = QSpinBox(); self.widgets['first_stable_min_chunks'].setRange(1, 100); self.widgets['first_stable_min_chunks'].setToolTip("Minimum number of consecutive chunks with the same delay required\nfor a segment to be considered 'stable'.\n\nHigher values = more strict (avoids false positives at file start)\nLower values = more lenient (may catch brief stable periods)\n\nRecommended: 3-5 chunks")
        self.widgets['first_stable_skip_unstable'] = QCheckBox(); self.widgets['first_stable_skip_unstable'].setToolTip("When enabled, skips segments that don't meet the minimum chunk count\nand looks for the next stable segment.\n\nUseful for avoiding offset beginnings (e.g., 2 chunks at wrong delay\nbefore the rest of the file stabilizes).\n\nWhen disabled, always uses the very first segment regardless of size.")
        core_layout.addRow("Correlation Method:", self.widgets['correlation_method'])
        core_layout.addRow("Number of Chunks:", self.widgets['scan_chunk_count'])
        core_layout.addRow("Duration of Chunks (s):", self.widgets['scan_chunk_duration'])
        core_layout.addRow("Minimum Match Confidence (%):", self.widgets['min_match_pct'])
        core_layout.addRow("Minimum Accepted Chunks:", self.widgets['min_accepted_chunks'])
        core_layout.addRow("Delay Selection Method:", self.widgets['delay_selection_mode'])
        core_layout.addRow("  ↳ Min Chunks for Stability:", self.widgets['first_stable_min_chunks'])
        core_layout.addRow("  ↳ Skip Unstable Segments:", self.widgets['first_stable_skip_unstable'])
        main_layout.addWidget(core_group)

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

        lang_group = QGroupBox("Step 4: Audio Track Selection")
        lang_layout = QFormLayout(lang_group)
        self.widgets['analysis_lang_source1'] = QLineEdit(); self.widgets['analysis_lang_source1'].setPlaceholderText("e.g., eng (blank = first audio track)"); self.widgets['analysis_lang_source1'].setToolTip("The 3-letter language code (e.g., eng, jpn) for the audio track to use from Source 1.\nLeave blank to use the first available audio track.")
        self.widgets['analysis_lang_others'] = QLineEdit(); self.widgets['analysis_lang_others'].setPlaceholderText("e.g., jpn (blank = first audio track)"); self.widgets['analysis_lang_others'].setToolTip("The 3-letter language code for audio tracks in all other sources.\nLeave blank to use their first available audio track.")
        lang_layout.addRow("Source 1 (Reference) Language:", self.widgets['analysis_lang_source1'])
        lang_layout.addRow("Other Sources Language:", self.widgets['analysis_lang_others'])
        main_layout.addWidget(lang_group)

        adv_group = QGroupBox("Step 5: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)
        self.widgets['use_soxr'] = QCheckBox("Use High-Quality Resampling (SoXR)"); self.widgets['use_soxr'].setToolTip("Use the high-quality SoXR resampler library when decoding audio.\nSlower but more accurate than the default resampler.")
        self.widgets['audio_peak_fit'] = QCheckBox("Enable Sub-Sample Peak Fitting (SCC only)"); self.widgets['audio_peak_fit'].setToolTip("For Standard Correlation (SCC), use parabolic interpolation to find a more precise, sub-sample peak.\nMay improve accuracy slightly.")
        self.widgets['log_audio_drift'] = QCheckBox("Log Audio Drift Metric"); self.widgets['log_audio_drift'].setToolTip("Calculate and log a metric that indicates potential audio drift or speed differences between sources.")
        adv_layout.addWidget(self.widgets['use_soxr'])
        adv_layout.addWidget(self.widgets['audio_peak_fit'])
        adv_layout.addWidget(self.widgets['log_audio_drift'])
        main_layout.addWidget(adv_group)

        segment_group = QGroupBox("🔧 Segmented Audio Correction (Experimental & Advanced)")
        segment_layout = QFormLayout(segment_group)
        self.widgets['segmented_enabled'] = QCheckBox("Enable segmented audio correction"); self.widgets['segmented_enabled'].setToolTip("When enabled, detects audio with stepping sync issues and creates a corrected version.")
        segment_layout.addRow(self.widgets['segmented_enabled'])

        # --- Section 1: Quality Assurance Settings ---
        segment_layout.addRow(QLabel("<b>Section 1: Quality Assurance Settings</b>"))
        self.widgets['segmented_qa_threshold'] = QDoubleSpinBox(); self.widgets['segmented_qa_threshold'].setRange(50.0, 99.0); self.widgets['segmented_qa_threshold'].setSuffix("%"); self.widgets['segmented_qa_threshold'].setToolTip("Quality assurance threshold - corrected tracks must correlate above this percentage with the reference.")
        self.widgets['segment_qa_chunk_count'] = QSpinBox(); self.widgets['segment_qa_chunk_count'].setRange(10, 100); self.widgets['segment_qa_chunk_count'].setToolTip("The number of chunks to scan during the final quality assurance check.")
        self.widgets['segment_qa_min_accepted_chunks'] = QSpinBox(); self.widgets['segment_qa_min_accepted_chunks'].setRange(5, 100); self.widgets['segment_qa_min_accepted_chunks'].setToolTip("The minimum number of QA chunks that must pass for the correction to be successful.")
        segment_layout.addRow("QA Correlation Threshold:", self.widgets['segmented_qa_threshold'])
        segment_layout.addRow("QA Scan Chunks:", self.widgets['segment_qa_chunk_count'])
        segment_layout.addRow("QA Min. Accepted Chunks:", self.widgets['segment_qa_min_accepted_chunks'])

        # --- Section 2: Stepping & Drift Detection ---
        segment_layout.addRow(QLabel("<b>Section 2: Stepping & Drift Detection</b>"))

        # Stepping Correction Mode
        self.widgets['stepping_correction_mode'] = QComboBox()
        self.widgets['stepping_correction_mode'].addItems(['full', 'filtered', 'strict', 'disabled'])
        self.widgets['stepping_correction_mode'].setToolTip(
            "CORRECTION STRATEGY: Controls how detected timing clusters are used\n\n"
            "• full (Current Default): All-or-nothing mode\n"
            "  - Uses ALL detected clusters for correction\n"
            "  - Rejects entire stepping correction if ANY cluster fails validation\n"
            "  - Use when: All clusters are reliable (no small/brief clusters)\n\n"
            "• filtered (Recommended for Problem Files): Smart filtering mode\n"
            "  - Automatically filters out unreliable clusters (too small, brief, low match)\n"
            "  - Uses ONLY stable clusters for correction\n"
            "  - Handles filtered regions per 'Filtered Fallback' setting below\n"
            "  - Use when: You have small/unreliable clusters causing issues\n\n"
            "• strict: Extra strict all-or-nothing mode\n"
            "  - Like 'full' but with stricter validation thresholds\n"
            "  - Use when: High-quality sources, want maximum confidence\n\n"
            "• disabled: Skip stepping correction entirely\n"
            "  - Use when: No stepping present or you want to disable this feature"
        )

        # Quality Mode
        self.widgets['stepping_quality_mode'] = QComboBox()
        self.widgets['stepping_quality_mode'].addItems(['strict', 'normal', 'lenient', 'custom'])
        self.widgets['stepping_quality_mode'].setToolTip(
            "QUALITY VALIDATION THRESHOLDS: Controls what makes a cluster 'valid'\n\n"
            "A cluster must pass ALL these checks to be considered valid:\n"
            "1. Minimum chunks (how many correlation chunks in the cluster)\n"
            "2. Minimum percentage (% of total chunks the cluster represents)\n"
            "3. Minimum duration (time span in seconds)\n"
            "4. Minimum match quality (average correlation match %)\n\n"
            "• strict: Very conservative (prevents false positives)\n"
            "  - 3+ chunks, 10%+ of total, 30+ seconds, 90%+ match quality\n"
            "  - Use when: High-quality Blu-ray sources\n\n"
            "• normal (Default): Balanced validation\n"
            "  - 3+ chunks, 5%+ of total, 20+ seconds, 85%+ match quality\n"
            "  - Use when: Most DVD/BD sources, general use\n\n"
            "• lenient: Permissive (catches edge cases)\n"
            "  - 2+ chunks, 3%+ of total, 10+ seconds, 75%+ match quality\n"
            "  - Use when: Brief stepping at file boundaries, low-quality sources\n\n"
            "• custom: Manually configure each threshold below\n"
            "  - Use when: You know exactly what thresholds you need"
        )

        # Filtered Fallback Mode
        self.widgets['stepping_filtered_fallback'] = QComboBox()
        self.widgets['stepping_filtered_fallback'].addItems(['nearest', 'interpolate', 'uniform', 'skip', 'reject'])
        self.widgets['stepping_filtered_fallback'].setToolTip(
            "FILTERED REGION HANDLING: What to do with time regions from invalid clusters\n"
            "(Only applies when Correction Mode = 'filtered')\n\n"
            "• nearest (Recommended): Use closest valid cluster's delay\n"
            "  - Filtered regions get the delay from the nearest stable cluster\n"
            "  - Creates a clean corrected track with stable timing\n"
            "  - QA check: Normal (expects stable delays)\n"
            "  - Use when: You want reliable correction without bad clusters\n\n"
            "• interpolate: Smooth transition between valid clusters\n"
            "  - Gradually transitions delay values between surrounding clusters\n"
            "  - Experimental, may not work well with large delay differences\n"
            "  - QA check: Normal\n\n"
            "• uniform: Use overall median delay for filtered regions\n"
            "  - Filtered regions use the median delay of all accepted chunks\n"
            "  - Conservative approach\n"
            "  - QA check: Normal\n\n"
            "• skip: Keep original (possibly wrong) timing in filtered regions\n"
            "  - Filtered regions are NOT corrected - they keep original delays\n"
            "  - Results in mixed delays in the corrected track\n"
            "  - QA check: Relaxed (allows high std deviation)\n"
            "  - ⚠️ WARNING: May result in audible timing jumps!\n"
            "  - Use when: You only want to fix specific regions, not all\n\n"
            "• reject: All-or-nothing (reject if any cluster filtered)\n"
            "  - If ANY cluster is filtered, reject entire stepping correction\n"
            "  - Equivalent to 'full' correction mode\n"
            "  - Use when: You want filtering validation but all-or-nothing behavior"
        )

        segment_layout.addRow("Correction Mode:", self.widgets['stepping_correction_mode'])
        segment_layout.addRow("Quality Mode:", self.widgets['stepping_quality_mode'])
        segment_layout.addRow("Filtered Fallback:", self.widgets['stepping_filtered_fallback'])

        # Add separator
        separator = QLabel()
        separator.setFixedHeight(10)
        segment_layout.addRow(separator)

        # Advanced thresholds (shown when quality_mode == 'custom')
        segment_layout.addRow(QLabel("<b>Custom Quality Thresholds (for 'custom' mode)</b>"))

        self.widgets['stepping_min_chunks_per_cluster'] = QSpinBox()
        self.widgets['stepping_min_chunks_per_cluster'].setRange(1, 20)
        self.widgets['stepping_min_chunks_per_cluster'].setToolTip("Minimum chunks required per cluster")

        self.widgets['stepping_min_cluster_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_min_cluster_percentage'].setRange(0.0, 50.0)
        self.widgets['stepping_min_cluster_percentage'].setSuffix(" %")
        self.widgets['stepping_min_cluster_percentage'].setDecimals(1)
        self.widgets['stepping_min_cluster_percentage'].setToolTip("Minimum percentage of total chunks a cluster must represent")

        self.widgets['stepping_min_cluster_duration_s'] = QDoubleSpinBox()
        self.widgets['stepping_min_cluster_duration_s'].setRange(0.0, 120.0)
        self.widgets['stepping_min_cluster_duration_s'].setSuffix(" s")
        self.widgets['stepping_min_cluster_duration_s'].setDecimals(1)
        self.widgets['stepping_min_cluster_duration_s'].setToolTip("Minimum duration in seconds for a cluster")

        self.widgets['stepping_min_match_quality_pct'] = QDoubleSpinBox()
        self.widgets['stepping_min_match_quality_pct'].setRange(50.0, 100.0)
        self.widgets['stepping_min_match_quality_pct'].setSuffix(" %")
        self.widgets['stepping_min_match_quality_pct'].setDecimals(1)
        self.widgets['stepping_min_match_quality_pct'].setToolTip("Minimum average match quality percentage")

        self.widgets['stepping_min_total_clusters'] = QSpinBox()
        self.widgets['stepping_min_total_clusters'].setRange(1, 10)
        self.widgets['stepping_min_total_clusters'].setToolTip("Minimum number of total clusters required")

        segment_layout.addRow("Min Chunks/Cluster:", self.widgets['stepping_min_chunks_per_cluster'])
        segment_layout.addRow("Min Cluster %:", self.widgets['stepping_min_cluster_percentage'])
        segment_layout.addRow("Min Cluster Duration:", self.widgets['stepping_min_cluster_duration_s'])
        segment_layout.addRow("Min Match Quality:", self.widgets['stepping_min_match_quality_pct'])
        segment_layout.addRow("Min Total Clusters:", self.widgets['stepping_min_total_clusters'])

        # Add separator
        separator2 = QLabel()
        separator2.setFixedHeight(10)
        segment_layout.addRow(separator2)

        segment_layout.addRow(QLabel("<b>Legacy Settings</b>"))
        self.widgets['detection_dbscan_epsilon_ms'] = QDoubleSpinBox(); self.widgets['detection_dbscan_epsilon_ms'].setRange(5.0, 100.0); self.widgets['detection_dbscan_epsilon_ms'].setSuffix(" ms"); self.widgets['detection_dbscan_epsilon_ms'].setToolTip("Stability Tolerance: The maximum time difference for delays to be considered part of the same sync group.")
        self.widgets['detection_dbscan_min_samples'] = QSpinBox(); self.widgets['detection_dbscan_min_samples'].setRange(2, 10); self.widgets['detection_dbscan_min_samples'].setToolTip("Cluster Size: The minimum number of similar chunks needed to form a stable sync group.")
        self.widgets['stepping_min_cluster_size'] = QSpinBox()
        self.widgets['stepping_min_cluster_size'].setRange(1, 10)
        self.widgets['stepping_min_cluster_size'].setToolTip(
            "Minimum number of chunks required per timing cluster to qualify as real stepping.\n"
            "Default: 3 (safe). Lower to 2 or 1 for edge cases like end credits with brief timing changes.\n"
            "Higher values reduce false positives but may miss legitimate stepping at file boundaries."
        )
        self.widgets['segment_triage_std_dev_ms'] = QSpinBox(); self.widgets['segment_triage_std_dev_ms'].setRange(10, 200); self.widgets['segment_triage_std_dev_ms'].setSuffix(" ms"); self.widgets['segment_triage_std_dev_ms'].setToolTip("If the standard deviation of delays is below this, correction is skipped.")
        self.widgets['drift_detection_r2_threshold'] = QDoubleSpinBox(); self.widgets['drift_detection_r2_threshold'].setRange(0.5, 1.0); self.widgets['drift_detection_r2_threshold'].setDecimals(2); self.widgets['drift_detection_r2_threshold'].setToolTip("For lossy codecs, how closely the drift must fit a straight line (R-squared value).")
        self.widgets['drift_detection_r2_threshold_lossless'] = QDoubleSpinBox(); self.widgets['drift_detection_r2_threshold_lossless'].setRange(0.5, 1.0); self.widgets['drift_detection_r2_threshold_lossless'].setDecimals(2); self.widgets['drift_detection_r2_threshold_lossless'].setToolTip("For lossless codecs, how closely the drift must fit a straight line (R-squared value).")
        self.widgets['drift_detection_slope_threshold_lossy'] = QDoubleSpinBox(); self.widgets['drift_detection_slope_threshold_lossy'].setRange(0.1, 5.0); self.widgets['drift_detection_slope_threshold_lossy'].setSuffix(" ms/s"); self.widgets['drift_detection_slope_threshold_lossy'].setToolTip("For lossy codecs, the minimum drift rate required to trigger a correction.")
        self.widgets['drift_detection_slope_threshold_lossless'] = QDoubleSpinBox(); self.widgets['drift_detection_slope_threshold_lossless'].setRange(0.1, 5.0); self.widgets['drift_detection_slope_threshold_lossless'].setSuffix(" ms/s"); self.widgets['drift_detection_slope_threshold_lossless'].setToolTip("For lossless codecs, the minimum drift rate required to trigger a correction.")
        self.widgets['stepping_diagnostics_verbose'] = QCheckBox("Enable detailed cluster diagnostics")
        self.widgets['stepping_diagnostics_verbose'].setToolTip(
            "When enabled, logs detailed cluster composition, transition patterns, and likely causes.\n"
            "Helps understand what's causing stepping: reel changes, commercials, scene edits, etc.\n"
            "Recommended: Keep enabled for debugging stepping issues."
        )
        segment_layout.addRow("DBSCAN Epsilon (Stability):", self.widgets['detection_dbscan_epsilon_ms'])
        segment_layout.addRow("DBSCAN Min Samples (Size):", self.widgets['detection_dbscan_min_samples'])
        segment_layout.addRow("Min. Cluster Size:", self.widgets['stepping_min_cluster_size'])
        segment_layout.addRow("Triage Stability Threshold:", self.widgets['segment_triage_std_dev_ms'])
        segment_layout.addRow("Lossy R² Threshold:", self.widgets['drift_detection_r2_threshold'])
        segment_layout.addRow("Lossless R² Threshold:", self.widgets['drift_detection_r2_threshold_lossless'])
        segment_layout.addRow("Lossy Slope Threshold:", self.widgets['drift_detection_slope_threshold_lossy'])
        segment_layout.addRow("Lossless Slope Threshold:", self.widgets['drift_detection_slope_threshold_lossless'])
        segment_layout.addRow(self.widgets['stepping_diagnostics_verbose'])

        # --- Section 3: Scan Configuration ---
        segment_layout.addRow(QLabel("<b>Section 3: Scan Configuration</b>"))
        self.widgets['stepping_scan_start_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_scan_start_percentage'].setRange(0.0, 99.0)
        self.widgets['stepping_scan_start_percentage'].setSuffix(" %")
        self.widgets['stepping_scan_start_percentage'].setDecimals(1)
        self.widgets['stepping_scan_start_percentage'].setToolTip(
            "Where to begin stepping correction coarse scan (independent from main analysis scan).\n"
            "Usually same as main analysis start (5%), but can be adjusted separately.\n"
            "Default: 5.0%"
        )
        self.widgets['stepping_scan_end_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_scan_end_percentage'].setRange(1.0, 100.0)
        self.widgets['stepping_scan_end_percentage'].setSuffix(" %")
        self.widgets['stepping_scan_end_percentage'].setDecimals(1)
        self.widgets['stepping_scan_end_percentage'].setToolTip(
            "Where to end stepping correction coarse scan (independent from main analysis scan).\n"
            "Set higher than main analysis (e.g., 99%) to catch stepping at file end.\n"
            "Default: 99.0%"
        )
        self.widgets['segment_coarse_chunk_s'] = QSpinBox(); self.widgets['segment_coarse_chunk_s'].setRange(5, 60); self.widgets['segment_coarse_chunk_s'].setSuffix(" s"); self.widgets['segment_coarse_chunk_s'].setToolTip("Duration of audio chunks for the initial broad scan.")
        self.widgets['segment_coarse_step_s'] = QSpinBox(); self.widgets['segment_coarse_step_s'].setRange(10, 300); self.widgets['segment_coarse_step_s'].setSuffix(" s"); self.widgets['segment_coarse_step_s'].setToolTip("Time to jump forward between each coarse scan chunk.")
        self.widgets['segment_search_locality_s'] = QSpinBox(); self.widgets['segment_search_locality_s'].setRange(2, 30); self.widgets['segment_search_locality_s'].setSuffix(" s"); self.widgets['segment_search_locality_s'].setToolTip("The time window to search for a match in the target audio.")
        self.widgets['segment_min_confidence_ratio'] = QDoubleSpinBox(); self.widgets['segment_min_confidence_ratio'].setRange(2.0, 20.0); self.widgets['segment_min_confidence_ratio'].setDecimals(1); self.widgets['segment_min_confidence_ratio'].setToolTip("Minimum ratio of correlation peak to noise floor for a valid match.")
        self.widgets['segment_fine_chunk_s'] = QDoubleSpinBox(); self.widgets['segment_fine_chunk_s'].setRange(0.5, 10.0); self.widgets['segment_fine_chunk_s'].setSuffix(" s"); self.widgets['segment_fine_chunk_s'].setToolTip("Duration of audio chunks for the high-precision boundary search.")
        self.widgets['segment_fine_iterations'] = QSpinBox(); self.widgets['segment_fine_iterations'].setRange(5, 15); self.widgets['segment_fine_iterations'].setToolTip("Number of iterations for the binary search to find a sync boundary.")
        segment_layout.addRow("Stepping Scan Start:", self.widgets['stepping_scan_start_percentage'])
        segment_layout.addRow("Stepping Scan End:", self.widgets['stepping_scan_end_percentage'])
        segment_layout.addRow("Coarse Scan Chunk Duration:", self.widgets['segment_coarse_chunk_s'])
        segment_layout.addRow("Coarse Scan Step Size:", self.widgets['segment_coarse_step_s'])
        segment_layout.addRow("Search Window Radius:", self.widgets['segment_search_locality_s'])
        segment_layout.addRow("Min. Correlation Confidence:", self.widgets['segment_min_confidence_ratio'])
        segment_layout.addRow("Fine Scan Chunk Duration:", self.widgets['segment_fine_chunk_s'])
        segment_layout.addRow("Fine Scan Iterations:", self.widgets['segment_fine_iterations'])

        # --- Section 4: Internal Drift Correction ---
        segment_layout.addRow(QLabel("<b>Section 4: Internal Drift Correction</b>"))
        self.widgets['segment_drift_r2_threshold'] = QDoubleSpinBox(); self.widgets['segment_drift_r2_threshold'].setRange(0.5, 1.0); self.widgets['segment_drift_r2_threshold'].setDecimals(2); self.widgets['segment_drift_r2_threshold'].setToolTip("Inside a segment, how closely the drift must fit a straight line to be corrected.")
        self.widgets['segment_drift_slope_threshold'] = QDoubleSpinBox(); self.widgets['segment_drift_slope_threshold'].setRange(0.1, 5.0); self.widgets['segment_drift_slope_threshold'].setSuffix(" ms/s"); self.widgets['segment_drift_slope_threshold'].setToolTip("Inside a segment, the minimum drift rate required to trigger a correction.")
        self.widgets['segment_drift_outlier_sensitivity'] = QDoubleSpinBox(); self.widgets['segment_drift_outlier_sensitivity'].setRange(1.0, 3.0); self.widgets['segment_drift_outlier_sensitivity'].setDecimals(1); self.widgets['segment_drift_outlier_sensitivity'].setToolTip("How aggressively to reject inconsistent measurements before calculating drift. Lower is stricter.")
        self.widgets['segment_drift_scan_buffer_pct'] = QDoubleSpinBox(); self.widgets['segment_drift_scan_buffer_pct'].setRange(0.0, 10.0); self.widgets['segment_drift_scan_buffer_pct'].setSuffix(" %"); self.widgets['segment_drift_scan_buffer_pct'].setToolTip("Percentage of the start and end of a segment to ignore during drift scan.")
        segment_layout.addRow("Segment R² Threshold:", self.widgets['segment_drift_r2_threshold'])
        segment_layout.addRow("Segment Slope Threshold:", self.widgets['segment_drift_slope_threshold'])
        segment_layout.addRow("Segment Outlier Sensitivity:", self.widgets['segment_drift_outlier_sensitivity'])
        segment_layout.addRow("Segment Scan Buffer:", self.widgets['segment_drift_scan_buffer_pct'])

        # --- Section 5: Audio Processing & Gap Filling ---
        segment_layout.addRow(QLabel("<b>Section 5: Audio Processing & Gap Filling</b>"))
        self.widgets['segment_resample_engine'] = QComboBox()
        self.widgets['segment_resample_engine'].addItems(['aresample', 'atempo', 'rubberband'])
        self.widgets['segment_resample_engine'].setToolTip(
            "The audio resampling engine for drift correction.\n"
            "- aresample: High quality, no pitch correction. (Recommended Default)\n"
            "- atempo: Fast, standard quality, no pitch correction.\n"
            "- rubberband: Slower, highest quality, preserves audio pitch."
        )
        segment_layout.addRow("Resample Engine:", self.widgets['segment_resample_engine'])

        self.rb_group = QGroupBox("Rubberband Settings")
        rb_layout = QFormLayout(self.rb_group)
        self.widgets['segment_rb_pitch_correct'] = QCheckBox("Enable Pitch Correction")
        self.widgets['segment_rb_pitch_correct'].setToolTip("When enabled, preserves the original audio pitch (slower).\nWhen disabled, acts as a high-quality resampler where pitch changes with speed (faster).")
        self.widgets['segment_rb_transients'] = QComboBox()
        self.widgets['segment_rb_transients'].addItems(['crisp', 'mixed', 'smooth'])
        self.widgets['segment_rb_transients'].setToolTip("How to handle transients (sharp sounds like consonants).\n'crisp' is usually best for dialogue.")
        self.widgets['segment_rb_smoother'] = QCheckBox("Enable Phase Smoothing (Higher Quality)")
        self.widgets['segment_rb_smoother'].setToolTip("Improves quality by smoothing phase shifts between processing windows.\nDisabling this can be slightly faster.")
        self.widgets['segment_rb_pitchq'] = QCheckBox("Enable High-Quality Pitch Algorithm")
        self.widgets['segment_rb_pitchq'].setToolTip("Uses a higher-quality, more CPU-intensive algorithm for pitch processing.")
        rb_layout.addRow(self.widgets['segment_rb_pitch_correct'])
        rb_layout.addRow("Transient Handling:", self.widgets['segment_rb_transients'])
        rb_layout.addRow(self.widgets['segment_rb_smoother'])
        rb_layout.addRow(self.widgets['segment_rb_pitchq'])
        segment_layout.addRow(self.rb_group)

        self.widgets['stepping_fill_mode'] = QComboBox()
        self.widgets['stepping_fill_mode'].addItems(['silence', 'auto', 'content'])
        self.widgets['stepping_fill_mode'].setToolTip(
            "How to fill gaps when delay increases:\n"
            "• silence: Always insert pure silence (RECOMMENDED - safe and professional)\n"
            "• auto: Intelligently decides between content and silence based on correlation analysis (experimental)\n"
            "• content: Always extract content from reference audio (experimental, may cause audio artifacts)"
        )
        self.widgets['stepping_content_correlation_threshold'] = QDoubleSpinBox()
        self.widgets['stepping_content_correlation_threshold'].setRange(0.1, 1.0)
        self.widgets['stepping_content_correlation_threshold'].setDecimals(2)
        self.widgets['stepping_content_correlation_threshold'].setSingleStep(0.05)
        self.widgets['stepping_content_correlation_threshold'].setToolTip(
            "In 'auto' mode, correlation threshold for determining if content should be extracted.\n"
            "Lower = more aggressive content extraction. Higher = more conservative (prefers silence).\n"
            "Default: 0.5. Try 0.3-0.4 if you know reference has missing content."
        )
        self.widgets['stepping_content_search_window_s'] = QDoubleSpinBox()
        self.widgets['stepping_content_search_window_s'].setRange(1.0, 30.0)
        self.widgets['stepping_content_search_window_s'].setSuffix(" s")
        self.widgets['stepping_content_search_window_s'].setDecimals(1)
        self.widgets['stepping_content_search_window_s'].setToolTip(
            "Time window (in seconds) to search for matching content around stepping boundaries.\n"
            "Larger windows = more thorough search but slower processing.\n"
            "Default: 5.0 seconds is usually sufficient."
        )
        segment_layout.addRow("Gap Fill Mode:", self.widgets['stepping_fill_mode'])
        segment_layout.addRow("Content Correlation Threshold:", self.widgets['stepping_content_correlation_threshold'])
        segment_layout.addRow("Content Search Window:", self.widgets['stepping_content_search_window_s'])

        # --- Section 6: Subtitle Adjustment ---
        segment_layout.addRow(QLabel("<b>Section 6: Subtitle Adjustment</b>"))
        self.widgets['stepping_adjust_subtitles'] = QCheckBox("Adjust subtitle timestamps for stepped sources")
        self.widgets['stepping_adjust_subtitles'].setToolTip(
            "When enabled, subtitle timestamps from stepped sources are automatically adjusted to match\n"
            "the audio corrections (insertions/removals). This keeps subtitles in sync with the corrected audio.\n\n"
            "Recommended: Keep enabled unless troubleshooting subtitle timing issues.\n"
            "Only applies when stepping correction is enabled and detected for a source."
        )
        segment_layout.addRow(self.widgets['stepping_adjust_subtitles'])

        self.widgets['stepping_adjust_subtitles_no_audio'] = QCheckBox("Apply stepping to subtitles when no audio is merged")
        self.widgets['stepping_adjust_subtitles_no_audio'].setToolTip(
            "When enabled, applies stepping correction to subtitles even when no audio tracks from that source\n"
            "are being merged. Uses correlation results to generate a simplified timing adjustment map.\n\n"
            "This is useful for subtitle-only merges where the source has stepped delays but you're not merging audio.\n\n"
            "How it works:\n"
            "  - Detects stepped delays from audio correlation analysis\n"
            "  - Generates timing regions from correlation chunks (e.g., 0-156s: +18ms, 156-843s: -9925ms)\n"
            "  - Applies appropriate delay to each subtitle based on its timestamp\n\n"
            "Note: Less precise than full audio stepping correction, but usually sufficient for subtitles.\n"
            "Recommended: Enable if you're merging subtitles from sources with variable sync offsets.\n"
            "Only applies when stepping is detected during correlation analysis."
        )
        segment_layout.addRow(self.widgets['stepping_adjust_subtitles_no_audio'])

        self.widgets['stepping_boundary_mode'] = QComboBox()
        self.widgets['stepping_boundary_mode'].addItems(['start', 'majority', 'midpoint'])
        self.widgets['stepping_boundary_mode'].setToolTip(
            "How to handle subtitles that span across stepping boundaries:\n\n"
            "• Start Time (default):\n"
            "  Uses the subtitle's start timestamp to determine which delay region it belongs to.\n"
            "  Fast and simple. Works well for short subtitles (2-3 seconds).\n\n"
            "• Majority Duration:\n"
            "  Calculates which delay region the subtitle spends the most time in.\n"
            "  More accurate for long subtitles or song lyrics that span boundaries.\n"
            "  Example: A 10-second subtitle spanning a boundary at 5 seconds gets the delay\n"
            "  of whichever region it occupies for more than 5 seconds.\n\n"
            "• Midpoint:\n"
            "  Uses the middle timestamp of the subtitle: (start + end) / 2.\n"
            "  Simple compromise between start-only and duration-based.\n"
            "  Better than start-only for moderately long subtitles.\n\n"
            "Note: This only affects subtitle timing adjustment, not audio stepping correction.\n"
            "Recommended: Use 'start' for typical dialogue, 'majority' for songs/karaoke."
        )
        segment_layout.addRow("Boundary Spanning Mode:", self.widgets['stepping_boundary_mode'])

        main_layout.addWidget(segment_group)

        main_layout.addStretch(1)
        self.widgets['filtering_method'].currentTextChanged.connect(self._update_filter_options)
        self.widgets['segment_resample_engine'].currentTextChanged.connect(self._update_rb_group_visibility)
        self._update_rb_group_visibility(self.widgets['segment_resample_engine'].currentText())
        self._update_filter_options(self.widgets['filtering_method'].currentText())

    def _update_filter_options(self, text: str):
        self.cutoff_container.setVisible(text == "Low-Pass Filter")

    def _update_rb_group_visibility(self, text: str):
        self.rb_group.setVisible(text == 'rubberband')

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
        self.widgets['disable_header_compression'] = QCheckBox('Disable header removal compression for all tracks')
        self.widgets['disable_header_compression'].setToolTip("Prevents mkvmerge from using header removal compression.\nThis is enabled by default as it can sometimes cause issues.")
        form1.addWidget(self.widgets['apply_dialog_norm_gain'])
        form1.addWidget(self.widgets['disable_track_statistics_tags'])
        form1.addWidget(self.widgets['disable_header_compression'])
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
