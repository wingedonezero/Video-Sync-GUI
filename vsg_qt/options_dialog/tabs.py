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
        self.widgets['source_separation_model'] = QComboBox(); self.widgets['source_separation_model'].addItems(['None (Use Original Audio)', 'Demucs - Music/Effects (Strip Vocals)', 'Demucs - Vocals Only']); self.widgets['source_separation_model'].setToolTip("Uses Demucs AI to separate audio stems before correlation.\n\n• None - Use original audio (default)\n• Music/Effects (Strip Vocals) - For cross-language sync (JP↔EN)\n  Removes vocals, correlates on music/effects which match across dubs\n• Vocals Only - Isolate dialogue for speech-based correlation\n\nRequires: torch, torchaudio, demucs\nSupports: CUDA, ROCm (AMD), CPU fallback\nNote: Runs in subprocess for guaranteed memory cleanup.")
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
        self.widgets['correlation_method'] = QComboBox(); self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'Onset Detection', 'GCC-SCOT', 'DTW (Dynamic Time Warping)', 'Spectrogram Correlation', 'VideoDiff']); self.widgets['correlation_method'].setToolTip("The core algorithm used to find the time offset.\n\n• SCC - Standard cross-correlation. Precise for identical audio sources.\n• GCC-PHAT - Phase correlation. More robust to noise and different mixes.\n• Onset Detection - Matches audio transients (hits, speech onsets). Best for\n  different releases/mixes where waveforms differ but events align.\n• GCC-SCOT - Smoothed Coherence Transform. Better when one signal is noisier.\n• DTW - Dynamic Time Warping on MFCC features. Handles tempo variations.\n• Spectrogram - Correlates mel spectrograms. Captures frequency+time structure.\n• VideoDiff - External tool for video-based sync.")
        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100); self.widgets['scan_chunk_count'].setToolTip("The number of separate audio segments to analyze across the file's duration.")
        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120); self.widgets['scan_chunk_duration'].setToolTip("The length (in seconds) of each individual audio segment to be analyzed.")
        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0); self.widgets['min_match_pct'].setToolTip("The minimum correlation score for an audio chunk to be considered a valid match.")
        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100); self.widgets['min_accepted_chunks'].setToolTip("The minimum number of valid chunks required for the analysis to be considered successful.")
        self.widgets['delay_selection_mode'] = QComboBox(); self.widgets['delay_selection_mode'].addItems(['Mode (Most Common)', 'First Stable', 'Average']); self.widgets['delay_selection_mode'].setToolTip("How to choose the final delay from multiple chunk measurements:\n\n• Mode (Most Common) - Picks the delay that appears most frequently (Default)\n  Best for: Files with stable sync throughout most of the duration\n\n• First Stable - Uses the delay from the first stable segment\n  Best for: Files where sync changes mid-file due to authoring issues\n  (Note: For stepping correction, use the Segmented Audio settings instead)\n\n• Average - Calculates the mean of all delay measurements\n  Best for: Files with small variations around a central value")
        self.widgets['first_stable_min_chunks'] = QSpinBox(); self.widgets['first_stable_min_chunks'].setRange(1, 100); self.widgets['first_stable_min_chunks'].setToolTip("[First Stable mode only]\n\nMinimum number of consecutive chunks with the same delay required\nfor a segment to be considered 'stable'.\n\nHigher values = more strict (avoids false positives at file start)\nLower values = more lenient (may catch brief stable periods)\n\nRecommended: 3-5 chunks")
        self.widgets['first_stable_skip_unstable'] = QCheckBox(); self.widgets['first_stable_skip_unstable'].setToolTip("[First Stable mode only]\n\nWhen enabled, skips segments that don't meet the minimum chunk count\nand looks for the next stable segment.\n\nUseful for avoiding offset beginnings (e.g., 2 chunks at wrong delay\nbefore the rest of the file stabilizes).\n\nWhen disabled, always uses the very first segment regardless of size.")
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

        timing_mode_group = QGroupBox("Step 5: Timing Sync Mode")
        timing_mode_layout = QFormLayout(timing_mode_group)
        self.widgets['sync_mode'] = QComboBox()
        self.widgets['sync_mode'].addItems(['positive_only', 'allow_negative'])
        self.widgets['sync_mode'].setToolTip(
            "Controls how timing delays are applied:\n\n"
            "• positive_only (Default): Shifts all tracks to eliminate negative delays.\n"
            "  Source 1 remains the reference timeline. Best for standard merges.\n"
            "  Exception: When only subtitles (no audio) from other sources are merged,\n"
            "  negative delays are automatically allowed.\n\n"
            "• allow_negative: Allows negative delays for secondary sources.\n"
            "  Source 1 remains the reference (delay = 0). Useful when merging early\n"
            "  releases (e.g., JPN Blu-ray + web audio) that will be remuxed later\n"
            "  with a US Blu-ray in positive_only mode to add lossless audio."
        )
        timing_mode_layout.addRow("Sync Mode:", self.widgets['sync_mode'])
        main_layout.addWidget(timing_mode_group)

        adv_group = QGroupBox("Step 6: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)
        self.widgets['use_soxr'] = QCheckBox("Use High-Quality Resampling (SoXR)"); self.widgets['use_soxr'].setToolTip("Use the high-quality SoXR resampler library when decoding audio.\nSlower but more accurate than the default resampler.")
        self.widgets['audio_peak_fit'] = QCheckBox("Enable Sub-Sample Peak Fitting (SCC only)"); self.widgets['audio_peak_fit'].setToolTip("For Standard Correlation (SCC), use parabolic interpolation to find a more precise, sub-sample peak.\nMay improve accuracy slightly.")
        self.widgets['log_audio_drift'] = QCheckBox("Log Audio Drift Metric"); self.widgets['log_audio_drift'].setToolTip("Calculate and log a metric that indicates potential audio drift or speed differences between sources.")
        adv_layout.addWidget(self.widgets['use_soxr'])
        adv_layout.addWidget(self.widgets['audio_peak_fit'])
        adv_layout.addWidget(self.widgets['log_audio_drift'])
        main_layout.addWidget(adv_group)

        self.widgets['filtering_method'].currentTextChanged.connect(self._update_filter_options)
        self.widgets['delay_selection_mode'].currentTextChanged.connect(self._update_first_stable_options)
        self._update_filter_options(self.widgets['filtering_method'].currentText())
        self._update_first_stable_options(self.widgets['delay_selection_mode'].currentText())

    def _update_filter_options(self, text: str):
        self.cutoff_container.setVisible(text == "Low-Pass Filter")

    def _update_first_stable_options(self, text: str):
        is_first_stable = (text == "First Stable")
        self.widgets['first_stable_min_chunks'].setEnabled(is_first_stable)
        self.widgets['first_stable_skip_unstable'].setEnabled(is_first_stable)

class SteppingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        segment_group = QGroupBox("🔧 Stepping Correction (Audio with Mid-File Timing Changes)")
        segment_layout = QFormLayout(segment_group)

        # Enable toggle
        self.widgets['segmented_enabled'] = QCheckBox("Enable stepping correction")
        self.widgets['segmented_enabled'].setToolTip(
            "Detects and corrects audio with stepped timing changes (e.g., reel changes, commercial breaks).\n"
            "Only applies when Analysis detects stepping via correlation chunk clustering."
        )
        segment_layout.addRow(self.widgets['segmented_enabled'])

        # ===== SECTION 1: DETECTION SETTINGS =====
        # Controls how timing clusters are detected from correlation data
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Detection Settings ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls how timing changes are detected from correlation data</i>"))

        self.widgets['detection_dbscan_epsilon_ms'] = QDoubleSpinBox()
        self.widgets['detection_dbscan_epsilon_ms'].setRange(5.0, 100.0)
        self.widgets['detection_dbscan_epsilon_ms'].setSuffix(" ms")
        self.widgets['detection_dbscan_epsilon_ms'].setToolTip(
            "DBSCAN clustering tolerance - maximum delay difference for chunks to be grouped together.\n"
            "Smaller = stricter grouping (more distinct clusters)\n"
            "Larger = looser grouping (fewer, larger clusters)\n"
            "Default: 20ms"
        )

        self.widgets['detection_dbscan_min_samples'] = QSpinBox()
        self.widgets['detection_dbscan_min_samples'].setRange(2, 10)
        self.widgets['detection_dbscan_min_samples'].setToolTip(
            "DBSCAN minimum samples - minimum chunks needed to form a core cluster.\n"
            "Higher = requires more evidence before creating a cluster\n"
            "Lower = more sensitive to brief timing changes\n"
            "Default: 3"
        )

        self.widgets['segment_triage_std_dev_ms'] = QSpinBox()
        self.widgets['segment_triage_std_dev_ms'].setRange(10, 200)
        self.widgets['segment_triage_std_dev_ms'].setSuffix(" ms")
        self.widgets['segment_triage_std_dev_ms'].setToolTip(
            "Early triage threshold - skips stepping correction if delay variation is below this.\n"
            "Prevents unnecessary processing on files with stable, uniform delays.\n"
            "Default: 50ms"
        )

        # Drift detection thresholds
        self.widgets['drift_detection_r2_threshold'] = QDoubleSpinBox()
        self.widgets['drift_detection_r2_threshold'].setRange(0.5, 1.0)
        self.widgets['drift_detection_r2_threshold'].setDecimals(2)
        self.widgets['drift_detection_r2_threshold'].setToolTip(
            "R² threshold for lossy codecs - how linear the drift must be to treat as drift vs stepping.\n"
            "Higher = stricter (requires very linear drift pattern)\n"
            "Default: 0.95"
        )

        self.widgets['drift_detection_r2_threshold_lossless'] = QDoubleSpinBox()
        self.widgets['drift_detection_r2_threshold_lossless'].setRange(0.5, 1.0)
        self.widgets['drift_detection_r2_threshold_lossless'].setDecimals(2)
        self.widgets['drift_detection_r2_threshold_lossless'].setToolTip(
            "R² threshold for lossless codecs - how linear the drift must be to treat as drift vs stepping.\n"
            "Default: 0.98"
        )

        self.widgets['drift_detection_slope_threshold_lossy'] = QDoubleSpinBox()
        self.widgets['drift_detection_slope_threshold_lossy'].setRange(0.1, 5.0)
        self.widgets['drift_detection_slope_threshold_lossy'].setSuffix(" ms/s")
        self.widgets['drift_detection_slope_threshold_lossy'].setToolTip(
            "Minimum drift rate for lossy codecs to trigger drift correction instead of stepping.\n"
            "Default: 0.5 ms/s"
        )

        self.widgets['drift_detection_slope_threshold_lossless'] = QDoubleSpinBox()
        self.widgets['drift_detection_slope_threshold_lossless'].setRange(0.1, 5.0)
        self.widgets['drift_detection_slope_threshold_lossless'].setSuffix(" ms/s")
        self.widgets['drift_detection_slope_threshold_lossless'].setToolTip(
            "Minimum drift rate for lossless codecs to trigger drift correction instead of stepping.\n"
            "Default: 0.3 ms/s"
        )

        segment_layout.addRow("DBSCAN Epsilon:", self.widgets['detection_dbscan_epsilon_ms'])
        segment_layout.addRow("DBSCAN Min Samples:", self.widgets['detection_dbscan_min_samples'])
        segment_layout.addRow("Triage Threshold:", self.widgets['segment_triage_std_dev_ms'])
        segment_layout.addRow("Lossy R² Threshold:", self.widgets['drift_detection_r2_threshold'])
        segment_layout.addRow("Lossless R² Threshold:", self.widgets['drift_detection_r2_threshold_lossless'])
        segment_layout.addRow("Lossy Slope Threshold:", self.widgets['drift_detection_slope_threshold_lossy'])
        segment_layout.addRow("Lossless Slope Threshold:", self.widgets['drift_detection_slope_threshold_lossless'])

        # ===== SECTION 2: QUALITY VALIDATION =====
        # Controls which detected clusters are considered valid for correction
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Quality Validation ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls which detected timing clusters are considered valid</i>"))

        self.widgets['stepping_correction_mode'] = QComboBox()
        self.widgets['stepping_correction_mode'].addItems(['full', 'filtered', 'strict', 'disabled'])
        self.widgets['stepping_correction_mode'].setToolTip(
            "CORRECTION STRATEGY: How to handle detected timing clusters\n\n"
            "• full (Default): All-or-nothing\n"
            "  - Uses ALL clusters, rejects entire correction if ANY fail validation\n"
            "  - Use when: All clusters are reliable\n\n"
            "• filtered (Recommended): Smart filtering\n"
            "  - Filters out unreliable clusters, uses only stable ones\n"
            "  - See 'Filtered Fallback' for how filtered regions are handled\n"
            "  - Use when: Small/brief clusters causing issues\n\n"
            "• strict: Extra strict all-or-nothing\n"
            "  - Like 'full' but stricter thresholds\n\n"
            "• disabled: Skip stepping correction"
        )

        self.widgets['stepping_quality_mode'] = QComboBox()
        self.widgets['stepping_quality_mode'].addItems(['strict', 'normal', 'lenient', 'custom'])
        self.widgets['stepping_quality_mode'].setToolTip(
            "QUALITY THRESHOLDS: What makes a cluster 'valid'\n\n"
            "Clusters must pass ALL checks:\n"
            "  1. Minimum chunks (correlation chunk count)\n"
            "  2. Minimum percentage (% of total chunks)\n"
            "  3. Minimum duration (time span in seconds)\n"
            "  4. Minimum match quality (average correlation %)\n\n"
            "• strict: 3+ chunks, 10%+, 30+ sec, 90%+ match (Blu-ray)\n"
            "• normal: 3+ chunks, 5%+, 20+ sec, 85%+ match (Default)\n"
            "• lenient: 2+ chunks, 3%+, 10+ sec, 75%+ match (Edge cases)\n"
            "• custom: Configure thresholds manually below"
        )

        self.widgets['stepping_filtered_fallback'] = QComboBox()
        self.widgets['stepping_filtered_fallback'].addItems(['nearest', 'interpolate', 'uniform', 'skip', 'reject'])
        self.widgets['stepping_filtered_fallback'].setToolTip(
            "FILTERED REGION HANDLING: What to do with invalid cluster regions\n"
            "(Only applies when Correction Mode = 'filtered')\n\n"
            "• nearest: Use closest valid cluster's delay (Recommended)\n"
            "• interpolate: Smooth transition between valid clusters\n"
            "• uniform: Use median delay of all accepted chunks\n"
            "• skip: Keep original (possibly wrong) timing ⚠️ May cause timing jumps\n"
            "• reject: Reject entire correction if any cluster filtered"
        )

        segment_layout.addRow("Correction Mode:", self.widgets['stepping_correction_mode'])
        segment_layout.addRow("Quality Mode:", self.widgets['stepping_quality_mode'])
        segment_layout.addRow("Filtered Fallback:", self.widgets['stepping_filtered_fallback'])

        # Custom quality thresholds (for 'custom' mode)
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<i>Custom Quality Thresholds (for 'custom' mode):</i>"))

        self.widgets['stepping_min_chunks_per_cluster'] = QSpinBox()
        self.widgets['stepping_min_chunks_per_cluster'].setRange(1, 20)
        self.widgets['stepping_min_chunks_per_cluster'].setToolTip("Minimum correlation chunks required per cluster")

        self.widgets['stepping_min_cluster_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_min_cluster_percentage'].setRange(0.0, 50.0)
        self.widgets['stepping_min_cluster_percentage'].setSuffix(" %")
        self.widgets['stepping_min_cluster_percentage'].setDecimals(1)
        self.widgets['stepping_min_cluster_percentage'].setToolTip("Minimum % of total chunks a cluster must represent")

        self.widgets['stepping_min_cluster_duration_s'] = QDoubleSpinBox()
        self.widgets['stepping_min_cluster_duration_s'].setRange(0.0, 120.0)
        self.widgets['stepping_min_cluster_duration_s'].setSuffix(" s")
        self.widgets['stepping_min_cluster_duration_s'].setDecimals(1)
        self.widgets['stepping_min_cluster_duration_s'].setToolTip("Minimum duration in seconds for a cluster")

        self.widgets['stepping_min_match_quality_pct'] = QDoubleSpinBox()
        self.widgets['stepping_min_match_quality_pct'].setRange(50.0, 100.0)
        self.widgets['stepping_min_match_quality_pct'].setSuffix(" %")
        self.widgets['stepping_min_match_quality_pct'].setDecimals(1)
        self.widgets['stepping_min_match_quality_pct'].setToolTip("Minimum average correlation match quality %")

        self.widgets['stepping_min_total_clusters'] = QSpinBox()
        self.widgets['stepping_min_total_clusters'].setRange(1, 10)
        self.widgets['stepping_min_total_clusters'].setToolTip("Minimum total number of clusters required")

        segment_layout.addRow("  Min Chunks/Cluster:", self.widgets['stepping_min_chunks_per_cluster'])
        segment_layout.addRow("  Min Cluster %:", self.widgets['stepping_min_cluster_percentage'])
        segment_layout.addRow("  Min Cluster Duration:", self.widgets['stepping_min_cluster_duration_s'])
        segment_layout.addRow("  Min Match Quality:", self.widgets['stepping_min_match_quality_pct'])
        segment_layout.addRow("  Min Total Clusters:", self.widgets['stepping_min_total_clusters'])

        # ===== SECTION 3: DELAY SELECTION =====
        # Controls how base delay is determined for stepping detection
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Delay Selection ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls base delay determination for stepping detection</i>"))

        self.widgets['stepping_first_stable_min_chunks'] = QSpinBox()
        self.widgets['stepping_first_stable_min_chunks'].setRange(1, 100)
        self.widgets['stepping_first_stable_min_chunks'].setToolTip(
            "Minimum consecutive chunks for a segment to be 'stable' when determining base delay.\n"
            "Higher = stricter (avoids false positives at file start)\n"
            "Lower = more lenient (may catch brief stable periods)\n"
            "Note: Separate from 'First Stable' mode in Analysis tab.\n"
            "Default: 3"
        )

        self.widgets['stepping_first_stable_skip_unstable'] = QCheckBox()
        self.widgets['stepping_first_stable_skip_unstable'].setToolTip(
            "When enabled, skips segments below minimum chunk count and looks for next stable segment.\n"
            "Useful for avoiding offset beginnings (e.g., 2 wrong chunks before file stabilizes).\n"
            "When disabled, always uses first segment regardless of size.\n"
            "Default: Enabled"
        )

        segment_layout.addRow("First Stable Min Chunks:", self.widgets['stepping_first_stable_min_chunks'])
        segment_layout.addRow("First Stable Skip Unstable:", self.widgets['stepping_first_stable_skip_unstable'])

        # ===== SECTION 4: SCAN CONFIGURATION =====
        # Controls stepping detection scan parameters (coarse, fine, QA)
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Scan Configuration ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls stepping detection scan parameters</i>"))

        # Scan position
        self.widgets['stepping_scan_start_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_scan_start_percentage'].setRange(0.0, 99.0)
        self.widgets['stepping_scan_start_percentage'].setSuffix(" %")
        self.widgets['stepping_scan_start_percentage'].setDecimals(1)
        self.widgets['stepping_scan_start_percentage'].setToolTip(
            "Where to begin stepping detection coarse scan (independent from main analysis scan).\n"
            "Default: 5.0%"
        )

        self.widgets['stepping_scan_end_percentage'] = QDoubleSpinBox()
        self.widgets['stepping_scan_end_percentage'].setRange(1.0, 100.0)
        self.widgets['stepping_scan_end_percentage'].setSuffix(" %")
        self.widgets['stepping_scan_end_percentage'].setDecimals(1)
        self.widgets['stepping_scan_end_percentage'].setToolTip(
            "Where to end stepping detection coarse scan.\n"
            "Set higher (e.g., 99%) to catch stepping at file end.\n"
            "Default: 99.0%"
        )

        # Coarse scan
        self.widgets['segment_coarse_chunk_s'] = QSpinBox()
        self.widgets['segment_coarse_chunk_s'].setRange(5, 60)
        self.widgets['segment_coarse_chunk_s'].setSuffix(" s")
        self.widgets['segment_coarse_chunk_s'].setToolTip("Duration of audio chunks for initial broad scan.")

        self.widgets['segment_coarse_step_s'] = QSpinBox()
        self.widgets['segment_coarse_step_s'].setRange(10, 300)
        self.widgets['segment_coarse_step_s'].setSuffix(" s")
        self.widgets['segment_coarse_step_s'].setToolTip("Time to jump forward between each coarse scan chunk.")

        self.widgets['segment_search_locality_s'] = QSpinBox()
        self.widgets['segment_search_locality_s'].setRange(2, 30)
        self.widgets['segment_search_locality_s'].setSuffix(" s")
        self.widgets['segment_search_locality_s'].setToolTip("Time window to search for a match in the target audio.")

        self.widgets['segment_min_confidence_ratio'] = QDoubleSpinBox()
        self.widgets['segment_min_confidence_ratio'].setRange(2.0, 20.0)
        self.widgets['segment_min_confidence_ratio'].setDecimals(1)
        self.widgets['segment_min_confidence_ratio'].setToolTip("Minimum ratio of correlation peak to noise floor for valid match.")

        # Fine scan
        self.widgets['segment_fine_chunk_s'] = QDoubleSpinBox()
        self.widgets['segment_fine_chunk_s'].setRange(0.5, 10.0)
        self.widgets['segment_fine_chunk_s'].setSuffix(" s")
        self.widgets['segment_fine_chunk_s'].setToolTip("Duration of audio chunks for high-precision boundary search.")

        self.widgets['segment_fine_iterations'] = QSpinBox()
        self.widgets['segment_fine_iterations'].setRange(5, 15)
        self.widgets['segment_fine_iterations'].setToolTip("Number of binary search iterations to find sync boundary.")

        # QA scan
        self.widgets['segmented_qa_threshold'] = QDoubleSpinBox()
        self.widgets['segmented_qa_threshold'].setRange(50.0, 99.0)
        self.widgets['segmented_qa_threshold'].setSuffix("%")
        self.widgets['segmented_qa_threshold'].setToolTip("QA threshold - corrected tracks must correlate above this % with reference.")

        self.widgets['segment_qa_chunk_count'] = QSpinBox()
        self.widgets['segment_qa_chunk_count'].setRange(10, 100)
        self.widgets['segment_qa_chunk_count'].setToolTip("Number of chunks to scan during final QA check.")

        self.widgets['segment_qa_min_accepted_chunks'] = QSpinBox()
        self.widgets['segment_qa_min_accepted_chunks'].setRange(5, 100)
        self.widgets['segment_qa_min_accepted_chunks'].setToolTip("Minimum QA chunks that must pass for correction to be successful.")

        segment_layout.addRow("Scan Start Position:", self.widgets['stepping_scan_start_percentage'])
        segment_layout.addRow("Scan End Position:", self.widgets['stepping_scan_end_percentage'])
        segment_layout.addRow(QLabel("<i>Coarse Scan:</i>"))
        segment_layout.addRow("  Chunk Duration:", self.widgets['segment_coarse_chunk_s'])
        segment_layout.addRow("  Step Size:", self.widgets['segment_coarse_step_s'])
        segment_layout.addRow("  Search Window:", self.widgets['segment_search_locality_s'])
        segment_layout.addRow("  Min Confidence Ratio:", self.widgets['segment_min_confidence_ratio'])
        segment_layout.addRow(QLabel("<i>Fine Scan:</i>"))
        segment_layout.addRow("  Chunk Duration:", self.widgets['segment_fine_chunk_s'])
        segment_layout.addRow("  Iterations:", self.widgets['segment_fine_iterations'])

        # Advanced Silence Detection Methods
        segment_layout.addRow(QLabel("<b>Advanced Silence Detection:</b>"))

        self.widgets['stepping_silence_detection_method'] = QComboBox()
        self.widgets['stepping_silence_detection_method'].addItems(['smart_fusion', 'ffmpeg_silencedetect', 'rms_basic'])
        self.widgets['stepping_silence_detection_method'].setToolTip(
            "Silence detection algorithm:\n"
            "• smart_fusion (RECOMMENDED): Combines FFmpeg silencedetect + VAD + transient detection\n"
            "  Uses multiple signals to find optimal cut points that avoid speech and music\n"
            "  Provides the most accurate and content-aware boundary placement\n\n"
            "• ffmpeg_silencedetect: Frame-accurate FFmpeg silence detector\n"
            "  Fast and precise, but doesn't avoid speech or musical beats\n\n"
            "• rms_basic: Traditional RMS energy-based detection\n"
            "  Legacy method, least accurate but fastest\n\n"
            "Default: smart_fusion"
        )

        self.widgets['stepping_vad_enabled'] = QCheckBox("Enable speech protection (VAD)")
        self.widgets['stepping_vad_enabled'].setToolTip(
            "Uses Voice Activity Detection to identify and avoid cutting dialogue.\n"
            "Prevents boundaries from being placed in the middle of speech.\n"
            "Requires: pip install webrtcvad-wheels\n"
            "Recommended: Keep enabled for dialogue-heavy content\n"
            "Default: Enabled"
        )

        self.widgets['stepping_vad_aggressiveness'] = QSpinBox()
        self.widgets['stepping_vad_aggressiveness'].setRange(0, 3)
        self.widgets['stepping_vad_aggressiveness'].setToolTip(
            "VAD aggressiveness level (0-3):\n"
            "0 = Least aggressive (keeps more audio as speech, safest)\n"
            "1 = Moderate (balanced)\n"
            "2 = Aggressive (recommended, good speech detection)\n"
            "3 = Very aggressive (may miss some speech)\n"
            "Default: 2"
        )

        self.widgets['stepping_transient_detection_enabled'] = QCheckBox("Enable transient detection (avoid musical beats)")
        self.widgets['stepping_transient_detection_enabled'].setToolTip(
            "Detects sudden amplitude increases (transients) like drum hits, beats, and impacts.\n"
            "Avoids placing boundaries on musical beats for smoother cuts.\n"
            "Recommended: Keep enabled for music-heavy content\n"
            "Default: Enabled"
        )

        self.widgets['stepping_transient_threshold'] = QDoubleSpinBox()
        self.widgets['stepping_transient_threshold'].setRange(3.0, 15.0)
        self.widgets['stepping_transient_threshold'].setSuffix(" dB")
        self.widgets['stepping_transient_threshold'].setDecimals(1)
        self.widgets['stepping_transient_threshold'].setToolTip(
            "dB threshold for detecting transients (sudden amplitude increases).\n"
            "Lower = more sensitive (detects softer beats)\n"
            "Higher = less sensitive (only loud impacts)\n"
            "Default: 8.0 dB"
        )

        segment_layout.addRow("Detection Method:", self.widgets['stepping_silence_detection_method'])
        segment_layout.addRow(self.widgets['stepping_vad_enabled'])
        segment_layout.addRow("    VAD Aggressiveness:", self.widgets['stepping_vad_aggressiveness'])
        segment_layout.addRow(self.widgets['stepping_transient_detection_enabled'])
        segment_layout.addRow("    Transient Threshold:", self.widgets['stepping_transient_threshold'])

        # Silence-aware boundary snapping
        segment_layout.addRow(QLabel("<b>Silence-Aware Boundary Snapping:</b>"))

        self.widgets['stepping_snap_to_silence'] = QCheckBox("Enable boundary snapping to silence zones")
        self.widgets['stepping_snap_to_silence'].setToolTip(
            "Intelligently adjusts boundary placement to silence zones instead of mid-speech.\n"
            "When enabled, searches for silence regions near detected boundaries and snaps to them.\n"
            "Significantly improves audio quality by avoiding cuts in the middle of dialogue/music.\n"
            "Recommended: Keep enabled unless debugging.\n"
            "Default: Enabled"
        )

        self.widgets['stepping_silence_search_window_s'] = QDoubleSpinBox()
        self.widgets['stepping_silence_search_window_s'].setRange(0.5, 15.0)
        self.widgets['stepping_silence_search_window_s'].setSuffix(" s")
        self.widgets['stepping_silence_search_window_s'].setDecimals(1)
        self.widgets['stepping_silence_search_window_s'].setToolTip(
            "Search window in seconds (±N seconds from detected boundary).\n"
            "Larger = more flexibility in finding silence, but may move boundary further\n"
            "Smaller = keeps boundary closer to original detection\n"
            "Default: 5.0s (increased from 3.0s for better accuracy)"
        )

        self.widgets['stepping_silence_threshold_db'] = QDoubleSpinBox()
        self.widgets['stepping_silence_threshold_db'].setRange(-60.0, -20.0)
        self.widgets['stepping_silence_threshold_db'].setSuffix(" dB")
        self.widgets['stepping_silence_threshold_db'].setDecimals(1)
        self.widgets['stepping_silence_threshold_db'].setToolTip(
            "Audio level threshold in dB to consider as 'silence'.\n"
            "More negative = stricter (quieter required)\n"
            "Less negative = more lenient (includes quieter dialogue)\n"
            "Typical values: -50 dB (very quiet), -40 dB (quiet), -30 dB (soft)\n"
            "Default: -40.0 dB"
        )

        self.widgets['stepping_silence_min_duration_ms'] = QDoubleSpinBox()
        self.widgets['stepping_silence_min_duration_ms'].setRange(50.0, 1000.0)
        self.widgets['stepping_silence_min_duration_ms'].setSuffix(" ms")
        self.widgets['stepping_silence_min_duration_ms'].setDecimals(0)
        self.widgets['stepping_silence_min_duration_ms'].setToolTip(
            "Minimum silence duration to be considered for boundary snapping.\n"
            "Prevents snapping to very brief quiet moments (like pauses between words).\n"
            "Larger = requires longer silence zones (more conservative)\n"
            "Smaller = can use brief pauses (more aggressive)\n"
            "Default: 100 ms"
        )

        segment_layout.addRow(self.widgets['stepping_snap_to_silence'])
        segment_layout.addRow("    Search Window:", self.widgets['stepping_silence_search_window_s'])
        segment_layout.addRow("    Silence Threshold:", self.widgets['stepping_silence_threshold_db'])
        segment_layout.addRow("    Min Silence Duration:", self.widgets['stepping_silence_min_duration_ms'])

        # Video-aware boundary snapping
        segment_layout.addRow(QLabel("<i>Video-Aware Boundary Snapping:</i>"))

        self.widgets['stepping_snap_to_video_frames'] = QCheckBox("Enable boundary snapping to video frames/scenes")
        self.widgets['stepping_snap_to_video_frames'].setToolTip(
            "Aligns boundaries to video structure (scenes, keyframes, or frames).\n"
            "When enabled, searches for video edit points near detected boundaries.\n"
            "Ensures perfect audio-video sync at boundary points.\n"
            "Particularly useful for stepped audio caused by:\n"
            "  • Commercial breaks\n"
            "  • Scene changes\n"
            "  • Film reel changes\n"
            "  • Chapter markers\n"
            "Recommended: Enable for video content with visible scene changes.\n"
            "Default: Disabled"
        )

        self.widgets['stepping_video_snap_mode'] = QComboBox()
        self.widgets['stepping_video_snap_mode'].addItems(['scenes', 'keyframes', 'any_frame'])
        self.widgets['stepping_video_snap_mode'].setToolTip(
            "Video snap detection mode:\n"
            "• scenes: Snap to scene changes (recommended for most content)\n"
            "          Detects visual transitions like cuts, fades, and chapter breaks\n"
            "• keyframes: Snap to I-frames (fast, good for encoded video)\n"
            "             I-frames are complete frames, not deltas\n"
            "• any_frame: Snap to nearest frame (most precise, slowest)\n"
            "             Frame-perfect alignment\n"
            "Default: scenes"
        )

        self.widgets['stepping_video_snap_max_offset_s'] = QDoubleSpinBox()
        self.widgets['stepping_video_snap_max_offset_s'].setRange(0.1, 10.0)
        self.widgets['stepping_video_snap_max_offset_s'].setSuffix(" s")
        self.widgets['stepping_video_snap_max_offset_s'].setDecimals(1)
        self.widgets['stepping_video_snap_max_offset_s'].setToolTip(
            "Maximum distance to snap boundary to video position.\n"
            "If nearest video position is further than this, boundary stays at audio-based position.\n"
            "Larger = more flexible, but may move boundary further from audio detection\n"
            "Smaller = keeps boundary closer to audio detection\n"
            "Typical: 1-3 seconds\n"
            "Default: 2.0s"
        )

        self.widgets['stepping_video_scene_threshold'] = QDoubleSpinBox()
        self.widgets['stepping_video_scene_threshold'].setRange(0.1, 1.0)
        self.widgets['stepping_video_scene_threshold'].setSingleStep(0.05)
        self.widgets['stepping_video_scene_threshold'].setDecimals(2)
        self.widgets['stepping_video_scene_threshold'].setToolTip(
            "Scene detection sensitivity (only used in 'scenes' mode).\n"
            "Lower = more sensitive (detects subtle transitions)\n"
            "Higher = less sensitive (only major scene changes)\n"
            "Range: 0.1 (very sensitive) to 1.0 (very insensitive)\n"
            "Typical: 0.3-0.5\n"
            "Default: 0.4"
        )

        segment_layout.addRow(self.widgets['stepping_snap_to_video_frames'])
        segment_layout.addRow("    Video Snap Mode:", self.widgets['stepping_video_snap_mode'])
        segment_layout.addRow("    Max Snap Distance:", self.widgets['stepping_video_snap_max_offset_s'])
        segment_layout.addRow("    Scene Threshold:", self.widgets['stepping_video_scene_threshold'])

        segment_layout.addRow(QLabel("<i>Quality Assurance:</i>"))
        segment_layout.addRow("  QA Threshold:", self.widgets['segmented_qa_threshold'])
        segment_layout.addRow("  QA Chunk Count:", self.widgets['segment_qa_chunk_count'])
        segment_layout.addRow("  QA Min Accepted:", self.widgets['segment_qa_min_accepted_chunks'])

        # ===== SECTION 5: AUDIO PROCESSING =====
        # Controls resampling, rubberband, gap filling, and internal drift correction
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Audio Processing ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls audio correction methods and quality</i>"))

        # Resampling engine
        self.widgets['segment_resample_engine'] = QComboBox()
        self.widgets['segment_resample_engine'].addItems(['aresample', 'atempo', 'rubberband'])
        self.widgets['segment_resample_engine'].setToolTip(
            "Audio resampling engine for drift correction:\n"
            "• aresample: High quality, no pitch correction (Recommended)\n"
            "• atempo: Fast, standard quality, no pitch correction\n"
            "• rubberband: Slowest, highest quality, preserves pitch"
        )
        segment_layout.addRow("Resample Engine:", self.widgets['segment_resample_engine'])

        # Rubberband settings
        self.rb_group = QGroupBox("Rubberband Settings")
        rb_layout = QFormLayout(self.rb_group)

        self.widgets['segment_rb_pitch_correct'] = QCheckBox("Enable Pitch Correction")
        self.widgets['segment_rb_pitch_correct'].setToolTip(
            "Preserves original audio pitch (slower).\n"
            "When disabled, acts as high-quality resampler where pitch changes with speed (faster)."
        )

        self.widgets['segment_rb_transients'] = QComboBox()
        self.widgets['segment_rb_transients'].addItems(['crisp', 'mixed', 'smooth'])
        self.widgets['segment_rb_transients'].setToolTip(
            "How to handle transients (sharp sounds like consonants).\n"
            "'crisp' is usually best for dialogue."
        )

        self.widgets['segment_rb_smoother'] = QCheckBox("Enable Phase Smoothing (Higher Quality)")
        self.widgets['segment_rb_smoother'].setToolTip(
            "Improves quality by smoothing phase shifts between processing windows.\n"
            "Disabling can be slightly faster."
        )

        self.widgets['segment_rb_pitchq'] = QCheckBox("Enable High-Quality Pitch Algorithm")
        self.widgets['segment_rb_pitchq'].setToolTip("Uses higher-quality, more CPU-intensive pitch processing algorithm.")

        rb_layout.addRow(self.widgets['segment_rb_pitch_correct'])
        rb_layout.addRow("Transient Handling:", self.widgets['segment_rb_transients'])
        rb_layout.addRow(self.widgets['segment_rb_smoother'])
        rb_layout.addRow(self.widgets['segment_rb_pitchq'])
        segment_layout.addRow(self.rb_group)

        # Gap filling
        segment_layout.addRow(QLabel("<i>Gap Filling (when delay increases):</i>"))

        self.widgets['stepping_fill_mode'] = QComboBox()
        self.widgets['stepping_fill_mode'].addItems(['silence', 'auto', 'content'])
        self.widgets['stepping_fill_mode'].setToolTip(
            "How to fill gaps when delay increases:\n"
            "• silence: Insert pure silence (RECOMMENDED - safe and professional)\n"
            "• auto: Intelligently decide between content and silence (experimental)\n"
            "• content: Always extract content from reference (experimental, may cause artifacts)"
        )

        self.widgets['stepping_content_correlation_threshold'] = QDoubleSpinBox()
        self.widgets['stepping_content_correlation_threshold'].setRange(0.1, 1.0)
        self.widgets['stepping_content_correlation_threshold'].setDecimals(2)
        self.widgets['stepping_content_correlation_threshold'].setSingleStep(0.05)
        self.widgets['stepping_content_correlation_threshold'].setToolTip(
            "In 'auto' mode, correlation threshold for content extraction.\n"
            "Lower = more aggressive extraction\n"
            "Higher = more conservative (prefers silence)\n"
            "Default: 0.5"
        )

        self.widgets['stepping_content_search_window_s'] = QDoubleSpinBox()
        self.widgets['stepping_content_search_window_s'].setRange(1.0, 30.0)
        self.widgets['stepping_content_search_window_s'].setSuffix(" s")
        self.widgets['stepping_content_search_window_s'].setDecimals(1)
        self.widgets['stepping_content_search_window_s'].setToolTip(
            "Time window to search for matching content around stepping boundaries.\n"
            "Larger = more thorough but slower\n"
            "Default: 5.0s"
        )

        segment_layout.addRow("  Fill Mode:", self.widgets['stepping_fill_mode'])
        segment_layout.addRow("  Content Threshold:", self.widgets['stepping_content_correlation_threshold'])
        segment_layout.addRow("  Search Window:", self.widgets['stepping_content_search_window_s'])

        # Internal drift correction
        segment_layout.addRow(QLabel("<i>Internal Drift Correction (within segments):</i>"))

        self.widgets['segment_drift_r2_threshold'] = QDoubleSpinBox()
        self.widgets['segment_drift_r2_threshold'].setRange(0.5, 1.0)
        self.widgets['segment_drift_r2_threshold'].setDecimals(2)
        self.widgets['segment_drift_r2_threshold'].setToolTip("Inside a segment, how linear drift must be to correct.")

        self.widgets['segment_drift_slope_threshold'] = QDoubleSpinBox()
        self.widgets['segment_drift_slope_threshold'].setRange(0.1, 5.0)
        self.widgets['segment_drift_slope_threshold'].setSuffix(" ms/s")
        self.widgets['segment_drift_slope_threshold'].setToolTip("Inside a segment, minimum drift rate to trigger correction.")

        self.widgets['segment_drift_outlier_sensitivity'] = QDoubleSpinBox()
        self.widgets['segment_drift_outlier_sensitivity'].setRange(1.0, 3.0)
        self.widgets['segment_drift_outlier_sensitivity'].setDecimals(1)
        self.widgets['segment_drift_outlier_sensitivity'].setToolTip(
            "How aggressively to reject inconsistent measurements before calculating drift.\n"
            "Lower = stricter"
        )

        self.widgets['segment_drift_scan_buffer_pct'] = QDoubleSpinBox()
        self.widgets['segment_drift_scan_buffer_pct'].setRange(0.0, 10.0)
        self.widgets['segment_drift_scan_buffer_pct'].setSuffix(" %")
        self.widgets['segment_drift_scan_buffer_pct'].setToolTip("% of segment start/end to ignore during drift scan.")

        segment_layout.addRow("  R² Threshold:", self.widgets['segment_drift_r2_threshold'])
        segment_layout.addRow("  Slope Threshold:", self.widgets['segment_drift_slope_threshold'])
        segment_layout.addRow("  Outlier Sensitivity:", self.widgets['segment_drift_outlier_sensitivity'])
        segment_layout.addRow("  Scan Buffer %:", self.widgets['segment_drift_scan_buffer_pct'])

        # ===== SECTION 6: TRACK NAMING =====
        # Controls track naming in final MKV output
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Track Naming ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls track naming in final MKV output</i>"))

        self.widgets['stepping_corrected_track_label'] = QLineEdit()
        self.widgets['stepping_corrected_track_label'].setPlaceholderText("Leave empty for no label")
        self.widgets['stepping_corrected_track_label'].setToolTip(
            "Label added to corrected audio tracks in final MKV.\n"
            "If original track has a name, label is added in brackets.\n"
            "If original track has no name, only the label is used.\n\n"
            "Examples:\n"
            "  Label = 'Stepping Corrected':\n"
            "    'Surround 5.1' → 'Surround 5.1 (Stepping Corrected)'\n"
            "    (no name) → 'Stepping Corrected'\n\n"
            "  Label = '' (empty):\n"
            "    'Surround 5.1' → 'Surround 5.1'\n"
            "    (no name) → (no name)\n\n"
            "Temp files still use 'corrected' for tracking.\n"
            "Default: Empty (no label)"
        )

        self.widgets['stepping_preserved_track_label'] = QLineEdit()
        self.widgets['stepping_preserved_track_label'].setPlaceholderText("Leave empty for no label")
        self.widgets['stepping_preserved_track_label'].setToolTip(
            "Label added to preserved original tracks in final MKV.\n"
            "Preserved originals are kept when 'Preserve Original' is enabled.\n"
            "Follows same naming rules as corrected tracks.\n\n"
            "Examples:\n"
            "  Label = 'Original':\n"
            "    'Surround 5.1' → 'Surround 5.1 (Original)'\n"
            "    (no name) → 'Original'\n\n"
            "  Label = '' (empty):\n"
            "    'Surround 5.1' → 'Surround 5.1'\n"
            "    (no name) → (no name)\n\n"
            "Default: Empty (no label)"
        )

        segment_layout.addRow("Corrected Track Label:", self.widgets['stepping_corrected_track_label'])
        segment_layout.addRow("Preserved Track Label:", self.widgets['stepping_preserved_track_label'])

        # ===== SECTION 7: SUBTITLE ADJUSTMENT =====
        # Controls subtitle timestamp adjustments for stepped sources
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Subtitle Adjustment ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls subtitle timing adjustments for stepped sources</i>"))

        self.widgets['stepping_adjust_subtitles'] = QCheckBox("Adjust subtitle timestamps for stepped sources")
        self.widgets['stepping_adjust_subtitles'].setToolTip(
            "Automatically adjusts subtitle timestamps to match audio corrections (insertions/removals).\n"
            "Keeps subtitles in sync with corrected audio.\n"
            "Recommended: Keep enabled unless troubleshooting subtitle timing.\n"
            "Only applies when stepping correction is detected."
        )

        self.widgets['stepping_adjust_subtitles_no_audio'] = QCheckBox("Apply stepping to subtitles when no audio is merged")
        self.widgets['stepping_adjust_subtitles_no_audio'].setToolTip(
            "Applies stepping correction to subtitles even when no audio from that source is merged.\n"
            "Uses correlation results to generate timing adjustment map.\n\n"
            "Useful for subtitle-only merges from sources with stepped delays.\n"
            "Less precise than full audio correction but usually sufficient.\n"
            "Only applies when stepping is detected during correlation analysis."
        )

        self.widgets['stepping_boundary_mode'] = QComboBox()
        self.widgets['stepping_boundary_mode'].addItems(['start', 'majority', 'midpoint'])
        self.widgets['stepping_boundary_mode'].setToolTip(
            "How to handle subtitles spanning stepping boundaries:\n\n"
            "• start: Use subtitle's start timestamp (Default - fast, works for short subs)\n"
            "• majority: Use region where subtitle spends most time (Best for long subs/songs)\n"
            "• midpoint: Use middle timestamp (start + end) / 2 (Compromise)\n\n"
            "Recommended: 'start' for dialogue, 'majority' for songs/karaoke"
        )

        segment_layout.addRow(self.widgets['stepping_adjust_subtitles'])
        segment_layout.addRow(self.widgets['stepping_adjust_subtitles_no_audio'])
        segment_layout.addRow("Boundary Spanning Mode:", self.widgets['stepping_boundary_mode'])

        # ===== SECTION 8: DIAGNOSTICS =====
        # Controls diagnostic logging and debugging output
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>═══ Diagnostics ═══</b>"))
        segment_layout.addRow(QLabel("<i>Controls diagnostic logging for debugging</i>"))

        self.widgets['stepping_diagnostics_verbose'] = QCheckBox("Enable detailed cluster diagnostics")
        self.widgets['stepping_diagnostics_verbose'].setToolTip(
            "Logs detailed cluster composition, transition patterns, and likely causes.\n"
            "Helps understand stepping origins: reel changes, commercials, scene edits, etc.\n"
            "Recommended: Keep enabled for debugging stepping issues."
        )

        segment_layout.addRow(self.widgets['stepping_diagnostics_verbose'])

        # Connect signal handlers
        self.widgets['segment_resample_engine'].currentTextChanged.connect(self._update_rb_group_visibility)
        self._update_rb_group_visibility(self.widgets['segment_resample_engine'].currentText())

        main_layout.addWidget(segment_group)


    def _update_rb_group_visibility(self, text: str):
        self.rb_group.setVisible(text == 'rubberband')


class SubtitleSyncTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        sync_group = QGroupBox("Subtitle Synchronization Mode")
        sync_layout = QFormLayout(sync_group)

        self.widgets['subtitle_sync_mode'] = QComboBox()
        self.widgets['subtitle_sync_mode'].addItems(['time-based', 'duration-align', 'correlation-frame-snap'])
        self.widgets['subtitle_sync_mode'].setToolTip(
            "Subtitle synchronization method:\n\n"
            "• time-based (Default): Apply delays using millisecond timestamps\n"
            "  - Simple and fast, uses mkvmerge --sync\n"
            "  - Optional: Enable 'Use raw correlation values' to embed\n"
            "    delay directly in subtitle file using pysubs2\n"
            "  - Works with all subtitle formats\n\n"
            "• duration-align: Frame alignment via total duration difference\n"
            "  - Calculates: target_duration - source_duration\n"
            "  - Applies this offset to all subtitle times\n"
            "  - Then adds global shift (if any)\n"
            "  - Example: Source 23:40.003, Target 23:41.002 → +999ms offset\n"
            "  - Ignores audio correlation completely\n"
            "  - Best for frame-aligned videos with different total durations\n"
            "  - Optional hybrid frame verification for accuracy\n"
            "  - Requires both source and target video files\n\n"
            "• correlation-frame-snap: Correlation + frame boundary refinement (RECOMMENDED)\n"
            "  - Uses audio correlation as authoritative offset\n"
            "  - Verifies frame alignment using scene change anchors\n"
            "  - Applies precise refinement based on frame matching\n"
            "  - Handles global shift correctly (no double-application)\n"
            "  - Uses floor rounding for final timestamps\n"
            "  - Detects drift/stepping via checkpoint disagreement\n"
            "  - Perfect for frame-aligned videos where correlation is accurate\n"
            "  - Requires both source and target video files\n\n"
            "Note: Stepping correction (if enabled) takes precedence over this setting."
        )

        # Time-based mode options
        self.widgets['time_based_use_raw_values'] = QCheckBox("Use raw correlation values (pysubs)")
        self.widgets['time_based_use_raw_values'].setToolTip(
            "Apply delay directly to subtitle timestamps using pysubs2:\n\n"
            "• Unchecked (Default): Use mkvmerge --sync for delay\n"
            "  - Delay stored in container, subtitle file unchanged\n"
            "  - Most compatible with all players\n\n"
            "• Checked: Embed delay in subtitle timestamps\n"
            "  - Uses raw correlation values with rounding\n"
            "  - Subtitle file modified directly\n"
            "  - Useful when mkvmerge delay causes issues\n\n"
            "When enabled, the 'Rounding' setting below controls\n"
            "how timestamps are rounded to centisecond precision."
        )

        self.widgets['raw_delay_rounding'] = QComboBox()
        self.widgets['raw_delay_rounding'].addItems(['floor', 'round', 'ceil'])
        self.widgets['raw_delay_rounding'].setToolTip(
            "Rounding mode for subtitle timestamps:\n\n"
            "Controls how timestamps are rounded to ASS centisecond precision (10ms).\n\n"
            "• floor (Default): Round down to nearest 10ms\n"
            "  - Example: 1065.458ms → 1060ms\n"
            "  - Conservative (subtitles appear slightly earlier)\n"
            "  - Recommended for most cases\n\n"
            "• round: Round to nearest 10ms\n"
            "  - Example: 1065.458ms → 1070ms\n"
            "  - Statistically balanced\n\n"
            "• ceil: Round up to nearest 10ms\n"
            "  - Example: 1065.458ms → 1070ms\n"
            "  - Aggressive (subtitles appear slightly later)\n\n"
            "Used when 'Use raw correlation values' is enabled."
        )

        # Duration-Align settings
        self.widgets['duration_align_use_vapoursynth'] = QCheckBox("Use VapourSynth indexing")
        self.widgets['duration_align_use_vapoursynth'].setChecked(True)
        self.widgets['duration_align_use_vapoursynth'].setToolTip(
            "Use VapourSynth for frame indexing (duration-align mode):\n\n"
            "• Checked (Default): Use VapourSynth to get frame count/timestamps\n"
            "  - MUCH faster after first run (~1s vs 60s)\n"
            "  - Generates .lwi index files (cached)\n"
            "  - More accurate for VFR videos\n"
            "  - Requires VapourSynth installed\n"
            "  - Falls back to ffprobe if unavailable\n\n"
            "• Unchecked: Always use ffprobe -count_frames\n"
            "  - Slower (30-60 seconds per video)\n"
            "  - No dependencies\n"
            "  - Reliable fallback\n\n"
            "VapourSynth indexing speeds up duration-align significantly!"
        )

        self.widgets['duration_align_validate'] = QCheckBox("Validate frame alignment")
        self.widgets['duration_align_validate'].setChecked(True)
        self.widgets['duration_align_validate'].setToolTip(
            "Validate frame alignment using perceptual hashing:\n\n"
            "• Checked (Default): Verify videos are actually frame-aligned\n"
            "  - Compares frames at key subtitle positions\n"
            "  - Warns if videos don't match (wrong mode selected)\n"
            "  - Adds ~2-5 seconds to processing\n"
            "  - HIGH CONFIDENCE validation\n\n"
            "• Unchecked: Skip validation\n"
            "  - Faster, but no confirmation sync is correct\n"
            "  - Risk of applying wrong sync offset\n\n"
            "Highly recommended to leave enabled!"
        )

        self.widgets['duration_align_validate_points'] = QComboBox()
        self.widgets['duration_align_validate_points'].addItems(['1 point (fast)', '3 points (thorough)'])
        self.widgets['duration_align_validate_points'].setCurrentIndex(1)  # Default to 3 points
        self.widgets['duration_align_validate_points'].setToolTip(
            "Number of checkpoints to validate:\n\n"
            "• 1 point (fast): Only check first subtitle\n"
            "  - Fastest (~1-2 seconds)\n"
            "  - Good if videos are known to be same cut\n"
            "  - May miss issues later in video\n\n"
            "• 3 points (thorough) [DEFAULT]: Check first, middle, last subtitles\n"
            "  - Takes ~3-5 seconds\n"
            "  - Catches scene cut differences\n"
            "  - Detects credits length differences\n"
            "  - RECOMMENDED for unknown videos\n\n"
            "For each checkpoint, validates 11 frames (center ± 5)."
        )

        self.widgets['duration_align_hash_threshold'] = QSpinBox()
        self.widgets['duration_align_hash_threshold'].setRange(0, 30)
        self.widgets['duration_align_hash_threshold'].setValue(5)
        self.widgets['duration_align_hash_threshold'].setToolTip(
            "Perceptual hash similarity threshold:\n\n"
            "Maximum hamming distance for frames to be considered matching.\n\n"
            "• 0: Perfect match only (too strict for compression differences)\n"
            "• 3-5 (Default): Very similar frames\n"
            "  - Tolerates minor compression differences\n"
            "  - Good for Remux ↔ WebDL\n"
            "• 8-15: More tolerant\n"
            "  - Heavy re-encoding (Remux ↔ Encode)\n"
            "  - Color grading differences\n"
            "• 20-30: Very loose\n"
            "  - Different filters/processing\n"
            "  - May match wrong scenes if too high\n\n"
            "Increase if validation fails on visually identical scenes."
        )

        self.widgets['duration_align_hash_algorithm'] = QComboBox()
        self.widgets['duration_align_hash_algorithm'].addItems(['dhash', 'phash', 'average_hash', 'whash'])
        self.widgets['duration_align_hash_algorithm'].setToolTip(
            "Perceptual hash algorithm:\n\n"
            "Different algorithms have different tolerance to visual changes:\n\n"
            "• dhash (Default): Difference hash\n"
            "  - Fast and accurate\n"
            "  - Good for compression artifacts\n"
            "  - Best for: Remux ↔ WebDL, light transcodes\n"
            "  - Use with threshold 3-8\n\n"
            "• phash: Perceptual hash (DCT-based)\n"
            "  - More robust to re-encoding\n"
            "  - Handles color grading, filtering\n"
            "  - Best for: Remux ↔ Heavy Encode\n"
            "  - Use with threshold 10-20\n\n"
            "• average_hash: Simple averaging\n"
            "  - Fastest but least accurate\n"
            "  - Use for testing only\n\n"
            "• whash: Wavelet hash\n"
            "  - Most robust, but slowest\n"
            "  - Best for heavily processed videos\n"
            "  - Use with threshold 15-30\n\n"
            "Start with dhash, try phash if validation fails on same-source videos."
        )

        self.widgets['duration_align_hash_size'] = QComboBox()
        self.widgets['duration_align_hash_size'].addItems(['4', '8', '16'])
        self.widgets['duration_align_hash_size'].setCurrentIndex(1)  # Default to 8
        self.widgets['duration_align_hash_size'].setToolTip(
            "Hash size (resolution):\n\n"
            "Larger hash = more precise but less tolerant to differences.\n\n"
            "• 4x4 (16 bits):\n"
            "  - Very tolerant to changes\n"
            "  - Less precise\n"
            "  - Good for heavily re-encoded content\n\n"
            "• 8x8 (64 bits) [DEFAULT]:\n"
            "  - Balanced precision and tolerance\n"
            "  - Recommended for most cases\n\n"
            "• 16x16 (256 bits):\n"
            "  - Very precise\n"
            "  - Less tolerant to compression\n"
            "  - Good for near-identical encodes\n\n"
            "Keep at 8 unless you need more tolerance (use 4) or precision (use 16)."
        )

        self.widgets['duration_align_strictness'] = QSpinBox()
        self.widgets['duration_align_strictness'].setRange(50, 100)
        self.widgets['duration_align_strictness'].setValue(80)
        self.widgets['duration_align_strictness'].setSuffix("%")
        self.widgets['duration_align_strictness'].setToolTip(
            "Validation strictness (match percentage required):\n\n"
            "Percentage of frames that must match at each checkpoint for validation to pass.\n\n"
            "• 90-100%: Very strict\n"
            "  - Requires near-perfect matches\n"
            "  - Good for identical encodes\n\n"
            "• 80% (Default): Balanced\n"
            "  - Allows some mismatches\n"
            "  - Good for light transcodes\n\n"
            "• 60-70%: Tolerant\n"
            "  - Accepts more differences\n"
            "  - Good for heavy re-encodes\n\n"
            "Lower this if validation fails on same-source videos with different encoding."
        )

        # Hybrid verification settings
        self.widgets['duration_align_verify_with_frames'] = QCheckBox("Verify alignment with frame matching (hybrid mode)")
        self.widgets['duration_align_verify_with_frames'].setChecked(False)
        self.widgets['duration_align_verify_with_frames'].setToolTip(
            "Enable hybrid verification mode:\n\n"
            "Combines duration-align (fast rough estimate) with sliding window\n"
            "frame matching (precise verification) for maximum accuracy.\n\n"
            "How it works:\n"
            "1. Calculate duration offset (fast, approximate)\n"
            "2. Extract frames at 3 checkpoints (first/mid/last subtitles)\n"
            "3. Use sliding window to find actual frame alignment\n"
            "4. Verify all measurements agree (within tolerance)\n"
            "5. Use precise measurement if agreement, fallback if not\n\n"
            "Benefits:\n"
            "• More accurate than pure duration-align\n"
            "• Faster than full frame-matched mode\n"
            "• Self-validates - knows if sync is correct\n"
            "• Works even with small encode differences\n\n"
            "Adds ~10-20 seconds but gives high-confidence sync.\n\n"
            "Recommended for important syncs where accuracy matters."
        )

        self.widgets['duration_align_verify_search_window'] = QSpinBox()
        self.widgets['duration_align_verify_search_window'].setRange(500, 10000)
        self.widgets['duration_align_verify_search_window'].setValue(2000)
        self.widgets['duration_align_verify_search_window'].setSingleStep(500)
        self.widgets['duration_align_verify_search_window'].setSuffix(" ms")
        self.widgets['duration_align_verify_search_window'].setToolTip(
            "Search window for frame matching verification:\n\n"
            "How far to search around the duration-based estimate.\n\n"
            "• 2000ms (Default): Search ±2 seconds\n"
            "  - Good for most encode differences\n"
            "  - Catches frame shift of ~48-60 frames at 24fps\n\n"
            "• 5000ms: Search ±5 seconds\n"
            "  - For heavily different encodes\n"
            "  - If duration estimate might be very wrong\n\n"
            "Larger = more thorough but slower.\n"
            "Only used when hybrid mode enabled."
        )

        self.widgets['duration_align_verify_tolerance'] = QSpinBox()
        self.widgets['duration_align_verify_tolerance'].setRange(10, 500)
        self.widgets['duration_align_verify_tolerance'].setValue(100)
        self.widgets['duration_align_verify_tolerance'].setSingleStep(10)
        self.widgets['duration_align_verify_tolerance'].setSuffix(" ms")
        self.widgets['duration_align_verify_tolerance'].setToolTip(
            "Agreement tolerance for measurements:\n\n"
            "All 3 checkpoints must agree within this tolerance.\n\n"
            "• 100ms (Default): Tight agreement\n"
            "  - Ensures all measurements are consistent\n"
            "  - ~2-3 frames at 24fps\n\n"
            "• 200ms: Looser tolerance\n"
            "  - For VFR or borderline cases\n"
            "  - ~5 frames at 24fps\n\n"
            "If measurements disagree, uses fallback mode setting.\n"
            "Only used when hybrid mode enabled."
        )

        self.widgets['duration_align_fallback_mode'] = QComboBox()
        self.widgets['duration_align_fallback_mode'].addItems(['none', 'abort', 'auto-fallback', 'duration-offset'])
        self.widgets['duration_align_fallback_mode'].setToolTip(
            "What to do if frame validation fails:\n\n"
            "• none (Default): Warn but continue\n"
            "  - Shows warning in logs\n"
            "  - Applies duration-align sync anyway\n"
            "  - User can review and re-run if needed\n\n"
            "• abort: Fail the job\n"
            "  - Returns error, job shows as failed\n"
            "  - Good for batch processing to identify problems\n"
            "  - Forces manual review and correction\n\n"
            "• duration-offset: Use duration offset\n"
            "  - Falls back to simple duration calculation\n"
            "  - Skips frame verification entirely\n"
            "  - For hybrid mode: use if measurements disagree\n\n"
            "• auto-fallback: Try different sync mode\n"
            "  - Automatically uses fallback mode (configured below)\n"
            "  - Seamless recovery from validation failures\n"
            "  - Good for automated workflows\n\n"
            "Recommended: 'abort' for batch, 'duration-offset' for hybrid mode."
        )

        self.widgets['duration_align_fallback_target'] = QComboBox()
        self.widgets['duration_align_fallback_target'].addItems([
            'not-implemented'
        ])
        self.widgets['duration_align_fallback_target'].setToolTip(
            "Fallback sync mode if validation fails:\n\n"
            "NOTE: Auto-fallback is not yet implemented.\n"
            "If 'auto-fallback' is selected above, the system will\n"
            "fall back to using duration-offset instead."
        )

        # Skip validation for generated tracks
        self.widgets['duration_align_skip_validation_generated_tracks'] = QCheckBox("Skip validation for generated tracks (recommended)")
        self.widgets['duration_align_skip_validation_generated_tracks'].setChecked(True)
        self.widgets['duration_align_skip_validation_generated_tracks'].setToolTip(
            "Automatically skip frame validation for generated tracks:\n\n"
            "Generated tracks are created by filtering styles from an already-synced\n"
            "source track. They inherit the same timing, so re-validating is redundant.\n\n"
            "• Checked (Default): Skip validation for all generated tracks\n"
            "  - Faster processing\n"
            "  - Safe since source was already validated\n\n"
            "• Unchecked: Validate generated tracks like normal tracks\n"
            "  - May fail validation on sparse events (signs tracks)\n"
            "  - Slower but more thorough\n\n"
            "Recommendation: Keep enabled for faster, safer processing."
        )

        # Correlation + Frame Snap settings
        self.widgets['correlation_snap_fallback_mode'] = QComboBox()
        self.widgets['correlation_snap_fallback_mode'].addItems(['snap-to-frame', 'use-raw', 'abort'])
        self.widgets['correlation_snap_fallback_mode'].setToolTip(
            "What to do if frame verification fails (correlation-frame-snap mode):\n\n"
            "• snap-to-frame (Default): Snap correlation to nearest frame\n"
            "  - Rounds pure correlation to nearest frame boundary\n"
            "  - Safe fallback when checkpoints disagree\n"
            "  - Ensures frame-aligned timing\n\n"
            "• use-raw: Use raw correlation delay\n"
            "  - No frame correction applied\n"
            "  - May be off by partial frame\n"
            "  - Good if frame matching is unreliable\n\n"
            "• abort: Fail the job\n"
            "  - Returns error, job shows as failed\n"
            "  - Use when accurate sync is critical\n\n"
            "Recommendation: 'snap-to-frame' for most cases."
        )

        self.widgets['correlation_snap_hash_algorithm'] = QComboBox()
        self.widgets['correlation_snap_hash_algorithm'].addItems(['dhash', 'phash', 'average_hash'])
        self.widgets['correlation_snap_hash_algorithm'].setToolTip(
            "Hash algorithm for frame comparison (correlation-frame-snap):\n\n"
            "• dhash (Default): Difference hash - fast and robust\n"
            "  - Compares adjacent pixels\n"
            "  - Good for detecting scene cuts\n"
            "  - Recommended for most cases\n\n"
            "• phash: Perceptual hash - more accurate\n"
            "  - DCT-based frequency analysis\n"
            "  - Better with compression artifacts\n"
            "  - Slightly slower\n\n"
            "• average_hash: Simple average-based hash\n"
            "  - Very fast but less accurate\n"
            "  - May have false positives"
        )

        self.widgets['correlation_snap_hash_threshold'] = QSpinBox()
        self.widgets['correlation_snap_hash_threshold'].setRange(0, 64)
        self.widgets['correlation_snap_hash_threshold'].setValue(5)
        self.widgets['correlation_snap_hash_threshold'].setToolTip(
            "Hash threshold (hamming distance) for frame matching:\n\n"
            "Maximum allowed difference between frame hashes.\n"
            "For 8x8 hash, range is 0-64 bits.\n\n"
            "• 0: Perfect match only (too strict)\n"
            "• 5 (Default): Similar frames (recommended)\n"
            "• 10-15: More tolerant (for heavy compression)\n"
            "• 20+: Too loose (may match wrong frames)\n\n"
            "Lower = stricter matching."
        )

        self.widgets['correlation_snap_window_radius'] = QSpinBox()
        self.widgets['correlation_snap_window_radius'].setRange(1, 10)
        self.widgets['correlation_snap_window_radius'].setValue(3)
        self.widgets['correlation_snap_window_radius'].setToolTip(
            "Sliding window radius (frames before/after center):\n\n"
            "Creates a window of (2*N+1) frames centered on scene change.\n"
            "Used to match a sequence of frames, not just one.\n\n"
            "• 1: 3 frame window (minimal)\n"
            "• 3 (Default): 7 frame window (recommended)\n"
            "• 5: 11 frame window (more robust)\n\n"
            "Larger = more robust matching but slower."
        )

        self.widgets['correlation_snap_search_range'] = QSpinBox()
        self.widgets['correlation_snap_search_range'].setRange(1, 30)
        self.widgets['correlation_snap_search_range'].setValue(5)
        self.widgets['correlation_snap_search_range'].setToolTip(
            "Search range around correlation prediction (±N frames):\n\n"
            "After correlation predicts target position, we search\n"
            "±N frames to find the best frame alignment.\n\n"
            "• 5 (Default): Good for remux vs remux (~200ms)\n"
            "• 10-15: For encodes or larger timing differences\n"
            "• 20-30: For very different sources\n\n"
            "Increase if best match is at edge of search window."
        )

        # Layout - Sync Mode
        sync_layout.addRow("Sync Mode:", self.widgets['subtitle_sync_mode'])

        # Time-based mode options
        sync_layout.addRow("", self.widgets['time_based_use_raw_values'])
        sync_layout.addRow("Rounding:", self.widgets['raw_delay_rounding'])

        # Duration-Align mode options
        sync_layout.addRow("", self.widgets['duration_align_use_vapoursynth'])
        sync_layout.addRow("", self.widgets['duration_align_validate'])
        sync_layout.addRow("Validation Points:", self.widgets['duration_align_validate_points'])
        sync_layout.addRow("Hash Algorithm:", self.widgets['duration_align_hash_algorithm'])
        sync_layout.addRow("Hash Size:", self.widgets['duration_align_hash_size'])
        sync_layout.addRow("Hash Threshold:", self.widgets['duration_align_hash_threshold'])
        sync_layout.addRow("Strictness:", self.widgets['duration_align_strictness'])
        sync_layout.addRow("", self.widgets['duration_align_verify_with_frames'])
        sync_layout.addRow("Verify Search Window:", self.widgets['duration_align_verify_search_window'])
        sync_layout.addRow("Verify Tolerance:", self.widgets['duration_align_verify_tolerance'])
        sync_layout.addRow("Fallback Mode:", self.widgets['duration_align_fallback_mode'])
        sync_layout.addRow("Fallback Target:", self.widgets['duration_align_fallback_target'])
        sync_layout.addRow("", self.widgets['duration_align_skip_validation_generated_tracks'])

        # Correlation+FrameSnap mode options
        sync_layout.addRow("Corr+Snap Fallback:", self.widgets['correlation_snap_fallback_mode'])
        sync_layout.addRow("Corr+Snap Hash:", self.widgets['correlation_snap_hash_algorithm'])
        sync_layout.addRow("Corr+Snap Threshold:", self.widgets['correlation_snap_hash_threshold'])
        sync_layout.addRow("Corr+Snap Window:", self.widgets['correlation_snap_window_radius'])
        sync_layout.addRow("Corr+Snap Search:", self.widgets['correlation_snap_search_range'])

        main_layout.addWidget(sync_group)
        main_layout.addStretch(1)

        # Connect signals for visibility updates
        self.widgets['subtitle_sync_mode'].currentTextChanged.connect(self._update_mode_visibility)
        self.widgets['time_based_use_raw_values'].toggled.connect(
            lambda: self._update_mode_visibility(self.widgets['subtitle_sync_mode'].currentText())
        )
        self.widgets['duration_align_verify_with_frames'].toggled.connect(
            lambda: self._update_mode_visibility(self.widgets['subtitle_sync_mode'].currentText())
        )
        self._update_mode_visibility(self.widgets['subtitle_sync_mode'].currentText())

    def _update_mode_visibility(self, text: str):
        """Show/hide settings based on selected sync mode."""
        is_time_based = (text == 'time-based')
        is_duration_align = (text == 'duration-align')
        is_correlation_snap = (text == 'correlation-frame-snap')

        # Time-based mode options
        self.widgets['time_based_use_raw_values'].setEnabled(is_time_based)
        use_raw = is_time_based and self.widgets['time_based_use_raw_values'].isChecked()
        self.widgets['raw_delay_rounding'].setEnabled(use_raw)

        # Duration-align mode options
        self.widgets['duration_align_use_vapoursynth'].setEnabled(is_duration_align)
        self.widgets['duration_align_validate'].setEnabled(is_duration_align)
        self.widgets['duration_align_validate_points'].setEnabled(is_duration_align)
        self.widgets['duration_align_hash_algorithm'].setEnabled(is_duration_align)
        self.widgets['duration_align_hash_size'].setEnabled(is_duration_align)
        self.widgets['duration_align_hash_threshold'].setEnabled(is_duration_align)
        self.widgets['duration_align_strictness'].setEnabled(is_duration_align)
        self.widgets['duration_align_verify_with_frames'].setEnabled(is_duration_align)
        self.widgets['duration_align_skip_validation_generated_tracks'].setEnabled(is_duration_align)
        self.widgets['duration_align_fallback_mode'].setEnabled(is_duration_align)

        # Hybrid mode sub-settings (only when duration-align AND hybrid enabled)
        hybrid_enabled = is_duration_align and self.widgets['duration_align_verify_with_frames'].isChecked()
        self.widgets['duration_align_verify_search_window'].setEnabled(hybrid_enabled)
        self.widgets['duration_align_verify_tolerance'].setEnabled(hybrid_enabled)
        self.widgets['duration_align_fallback_target'].setEnabled(hybrid_enabled)

        # Correlation-frame-snap mode options
        self.widgets['correlation_snap_fallback_mode'].setEnabled(is_correlation_snap)
        self.widgets['correlation_snap_hash_algorithm'].setEnabled(is_correlation_snap)
        self.widgets['correlation_snap_hash_threshold'].setEnabled(is_correlation_snap)
        self.widgets['correlation_snap_window_radius'].setEnabled(is_correlation_snap)
        self.widgets['correlation_snap_search_range'].setEnabled(is_correlation_snap)

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
