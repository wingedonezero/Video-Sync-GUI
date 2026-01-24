# vsg_qt/options_dialog/tabs.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QHBoxLayout, QLineEdit, QPushButton, QFileDialog, QLabel, QGroupBox, QVBoxLayout
)

from vsg_core.analysis.source_separation import get_installed_models, get_installed_models_json_path

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
        main_layout = QVBoxLayout(self)

        # Paths section
        paths_group = QGroupBox("Paths")
        f = QFormLayout(paths_group)
        self.widgets['output_folder'] = _dir_input()
        self.widgets['output_folder'].setToolTip("The default directory where final merged files will be saved.")
        self.widgets['temp_root'] = _dir_input()
        self.widgets['temp_root'].setToolTip("The root directory for storing temporary files during processing (e.g., extracted tracks, logs).")
        self.widgets['logs_folder'] = _dir_input()
        self.widgets['logs_folder'].setToolTip("Directory for batch report files. Reports are saved after each job completes for persistent tracking.")
        self.widgets['videodiff_path'] = _file_input()
        self.widgets['videodiff_path'].setToolTip("Optional. The full path to the 'videodiff' executable if it's not in your system's PATH.")
        self.widgets['ocr_custom_wordlist_path'] = _file_input()
        self.widgets['ocr_custom_wordlist_path'].setToolTip("Path to custom wordlist file for OCR. Contains words to not flag as unknown (anime names, romaji, etc.). One word per line.")
        f.addRow('Output Directory:', self.widgets['output_folder'])
        f.addRow('Temporary Directory:', self.widgets['temp_root'])
        f.addRow('Reports Directory:', self.widgets['logs_folder'])
        f.addRow('VideoDiff Path (optional):', self.widgets['videodiff_path'])
        f.addRow('OCR Custom Wordlist:', self.widgets['ocr_custom_wordlist_path'])
        main_layout.addWidget(paths_group)

        # Config Maintenance section
        maint_group = QGroupBox("Config Maintenance")
        maint_layout = QVBoxLayout(maint_group)
        self.remove_invalid_btn = QPushButton("Remove Invalid Config Entries")
        self.remove_invalid_btn.setToolTip(
            "Removes orphaned/invalid keys from settings.json that are no longer used.\n"
            "This cleans up entries from old versions or deprecated features.\n"
            "Your valid settings will not be affected."
        )
        maint_layout.addWidget(self.remove_invalid_btn)
        main_layout.addWidget(maint_group)

        main_layout.addStretch()

class OCRTab(QWidget):
    """
    Combined OCR settings tab - replaces old Timing and Subtitle Cleanup tabs.

    Contains:
        - OCR engine settings (language, preprocessing)
        - Post-processing settings (cleanup, normalization)
        - Timing corrections (overlaps, duration, CPS)
        - Output settings (format, position handling)
    """
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # --- OCR Settings Group ---
        ocr_group = QGroupBox("OCR Settings")
        ocr_layout = QFormLayout(ocr_group)

        self.widgets['ocr_enabled'] = QCheckBox("Enable OCR for image-based subtitles")
        self.widgets['ocr_enabled'].setToolTip("Automatically OCR VobSub and PGS subtitle tracks.")

        self.widgets['ocr_engine'] = QComboBox()
        self.widgets['ocr_engine'].addItem('Tesseract (Traditional)', 'tesseract')
        self.widgets['ocr_engine'].addItem('EasyOCR (Deep Learning)', 'easyocr')
        self.widgets['ocr_engine'].addItem('PaddleOCR (State-of-Art)', 'paddleocr')
        self.widgets['ocr_engine'].setToolTip(
            "OCR engine to use.\n"
            "• Tesseract: Fast, traditional OCR. Good for clean text.\n"
            "• EasyOCR: Deep learning based. Better for varied fonts. Requires: pip install easyocr\n"
            "• PaddleOCR: State-of-art accuracy. Requires: pip install paddleocr"
        )

        self.widgets['ocr_language'] = QComboBox()
        self.widgets['ocr_language'].addItem('English', 'eng')
        self.widgets['ocr_language'].addItem('Japanese', 'jpn')
        self.widgets['ocr_language'].addItem('Spanish', 'spa')
        self.widgets['ocr_language'].addItem('French', 'fra')
        self.widgets['ocr_language'].addItem('German', 'deu')
        self.widgets['ocr_language'].addItem('Chinese (Simplified)', 'chi_sim')
        self.widgets['ocr_language'].addItem('Chinese (Traditional)', 'chi_tra')
        self.widgets['ocr_language'].addItem('Korean', 'kor')
        self.widgets['ocr_language'].setToolTip("Tesseract language pack to use. Requires the corresponding language data to be installed.")

        self.widgets['ocr_char_blacklist'] = QLineEdit()
        self.widgets['ocr_char_blacklist'].setToolTip("Characters to exclude from OCR results (e.g., '|/_~').")

        ocr_layout.addRow(self.widgets['ocr_enabled'])
        ocr_layout.addRow("OCR Engine:", self.widgets['ocr_engine'])
        ocr_layout.addRow("Language:", self.widgets['ocr_language'])
        ocr_layout.addRow("Character Blacklist:", self.widgets['ocr_char_blacklist'])
        main_layout.addWidget(ocr_group)

        # --- Preprocessing Group ---
        preprocess_group = QGroupBox("Preprocessing")
        preprocess_layout = QFormLayout(preprocess_group)

        self.widgets['ocr_preprocess_auto'] = QCheckBox("Auto-detect optimal settings")
        self.widgets['ocr_preprocess_auto'].setToolTip("Automatically determine best preprocessing for each subtitle image.")

        self.widgets['ocr_force_binarization'] = QCheckBox("Force binarization")
        self.widgets['ocr_force_binarization'].setToolTip("Always apply binary thresholding. May help with low-contrast subtitles.")

        self.widgets['ocr_upscale_threshold'] = QSpinBox()
        self.widgets['ocr_upscale_threshold'].setRange(20, 100)
        self.widgets['ocr_upscale_threshold'].setSuffix(" px")
        self.widgets['ocr_upscale_threshold'].setToolTip("Upscale subtitle images if height is below this threshold.")

        preprocess_layout.addRow(self.widgets['ocr_preprocess_auto'])
        preprocess_layout.addRow(self.widgets['ocr_force_binarization'])
        preprocess_layout.addRow("Upscale Threshold:", self.widgets['ocr_upscale_threshold'])
        main_layout.addWidget(preprocess_group)

        # --- Post-Processing Group ---
        postprocess_group = QGroupBox("Post-Processing")
        postprocess_layout = QFormLayout(postprocess_group)

        self.widgets['ocr_cleanup_enabled'] = QCheckBox("Enable OCR text cleanup")
        self.widgets['ocr_cleanup_enabled'].setToolTip("Apply pattern-based fixes for common OCR errors (I/l confusion, rn→m, etc.).")

        self.widgets['ocr_cleanup_normalize_ellipsis'] = QCheckBox("Normalize ellipsis (… → ...)")
        self.widgets['ocr_cleanup_normalize_ellipsis'].setToolTip("Replace Unicode ellipsis character with three periods.")

        self.widgets['ocr_low_confidence_threshold'] = QDoubleSpinBox()
        self.widgets['ocr_low_confidence_threshold'].setRange(0.0, 100.0)
        self.widgets['ocr_low_confidence_threshold'].setSuffix(" %")
        self.widgets['ocr_low_confidence_threshold'].setToolTip("Lines with confidence below this will be flagged in the report.")

        # Edit Dictionaries button
        self.edit_dictionaries_btn = QPushButton("Edit Dictionaries...")
        self.edit_dictionaries_btn.setToolTip(
            "Open the dictionary editor to manage:\n"
            "• Replacement rules (character/pattern corrections)\n"
            "• User dictionary (custom valid words)\n"
            "• Names (character names, proper nouns)"
        )
        self.edit_dictionaries_btn.clicked.connect(self._open_dictionary_editor)

        postprocess_layout.addRow(self.widgets['ocr_cleanup_enabled'])
        postprocess_layout.addRow(self.widgets['ocr_cleanup_normalize_ellipsis'])
        postprocess_layout.addRow("Low Confidence Threshold:", self.widgets['ocr_low_confidence_threshold'])
        postprocess_layout.addRow("", self.edit_dictionaries_btn)
        main_layout.addWidget(postprocess_group)

        # --- Timing Corrections Group ---
        timing_group = QGroupBox("Timing Corrections")
        timing_layout = QFormLayout(timing_group)

        self.widgets['timing_fix_enabled'] = QCheckBox("Enable subtitle timing corrections")
        self.widgets['timing_fix_enabled'].setToolTip("Apply automated timing fixes after OCR.")

        self.widgets['timing_fix_overlaps'] = QCheckBox("Fix overlapping subtitles")
        self.widgets['timing_overlap_min_gap_ms'] = QSpinBox()
        self.widgets['timing_overlap_min_gap_ms'].setRange(0, 1000)
        self.widgets['timing_overlap_min_gap_ms'].setSuffix(" ms")
        self.widgets['timing_overlap_min_gap_ms'].setToolTip("Minimum gap to enforce between subtitles.")

        self.widgets['timing_fix_short_durations'] = QCheckBox("Fix short durations")
        self.widgets['timing_min_duration_ms'] = QSpinBox()
        self.widgets['timing_min_duration_ms'].setRange(100, 5000)
        self.widgets['timing_min_duration_ms'].setSuffix(" ms")
        self.widgets['timing_min_duration_ms'].setToolTip("Minimum subtitle display duration.")

        self.widgets['timing_fix_long_durations'] = QCheckBox("Enforce reading speed (CPS)")
        self.widgets['timing_max_cps'] = QDoubleSpinBox()
        self.widgets['timing_max_cps'].setRange(5.0, 100.0)
        self.widgets['timing_max_cps'].setSuffix(" CPS")
        self.widgets['timing_max_cps'].setToolTip("Maximum characters per second. Longer subtitles will be trimmed.")

        timing_layout.addRow(self.widgets['timing_fix_enabled'])
        timing_layout.addRow(self.widgets['timing_fix_overlaps'])
        timing_layout.addRow("Minimum Gap:", self.widgets['timing_overlap_min_gap_ms'])
        timing_layout.addRow(self.widgets['timing_fix_short_durations'])
        timing_layout.addRow("Minimum Duration:", self.widgets['timing_min_duration_ms'])
        timing_layout.addRow(self.widgets['timing_fix_long_durations'])
        timing_layout.addRow("Max CPS:", self.widgets['timing_max_cps'])
        main_layout.addWidget(timing_group)

        # --- Output Group ---
        output_group = QGroupBox("Output")
        output_layout = QFormLayout(output_group)

        self.widgets['ocr_output_format'] = QComboBox()
        self.widgets['ocr_output_format'].addItem('ASS (recommended)', 'ass')
        self.widgets['ocr_output_format'].addItem('SRT', 'srt')
        self.widgets['ocr_output_format'].setToolTip("Output format. ASS supports position tags, SRT does not.")

        # Font size ratio with live preview
        self.widgets['ocr_font_size_ratio'] = QDoubleSpinBox()
        self.widgets['ocr_font_size_ratio'].setRange(3.00, 10.00)
        self.widgets['ocr_font_size_ratio'].setDecimals(2)
        self.widgets['ocr_font_size_ratio'].setSingleStep(0.05)
        self.widgets['ocr_font_size_ratio'].setSuffix(" %")
        self.widgets['ocr_font_size_ratio'].setToolTip(
            "Font size as percentage of video height (PlayResY).\n"
            "Ensures consistent visual size across resolutions.\n\n"
            "Examples at 5.80%:\n"
            "• 480p → 28pt\n"
            "• 720p → 42pt\n"
            "• 1080p → 63pt"
        )
        self._font_preview_label = QLabel()
        self._font_preview_label.setStyleSheet("color: gray; font-size: 11px;")
        self.widgets['ocr_font_size_ratio'].valueChanged.connect(self._update_font_preview)

        self.widgets['ocr_preserve_positions'] = QCheckBox("Preserve subtitle positions (non-bottom only)")
        self.widgets['ocr_preserve_positions'].setToolTip("Keep original position for subtitles not at the bottom of the screen.")

        self.widgets['ocr_bottom_threshold'] = QDoubleSpinBox()
        self.widgets['ocr_bottom_threshold'].setRange(50.0, 95.0)
        self.widgets['ocr_bottom_threshold'].setSuffix(" %")
        self.widgets['ocr_bottom_threshold'].setToolTip("Y position threshold. Subtitles above this are considered 'not bottom' and will have position preserved.")

        self.widgets['ocr_generate_report'] = QCheckBox("Generate detailed OCR report")
        self.widgets['ocr_generate_report'].setToolTip("Save a JSON report with unknown words, confidence scores, and applied fixes.")

        self.widgets['ocr_save_debug_images'] = QCheckBox("Save debug images (for troubleshooting)")
        self.widgets['ocr_save_debug_images'].setToolTip("Save preprocessed images to temp folder for debugging OCR issues.")

        self.widgets['ocr_debug_output'] = QCheckBox("Debug VobSub OCR (analyze issues)")
        self.widgets['ocr_debug_output'].setToolTip(
            "Save debug output organized by issue type:\n"
            "• unknown_words/ - Images and text for subtitles with unknown words\n"
            "• fixes_applied/ - Images showing what fixes were made\n"
            "• low_confidence/ - Images for low confidence OCR results\n\n"
            "Creates a folder in logs with the same name as the report."
        )

        output_layout.addRow("Output Format:", self.widgets['ocr_output_format'])
        output_layout.addRow("Font Size Ratio:", self.widgets['ocr_font_size_ratio'])
        output_layout.addRow("", self._font_preview_label)
        output_layout.addRow(self.widgets['ocr_preserve_positions'])
        output_layout.addRow("Bottom Threshold:", self.widgets['ocr_bottom_threshold'])
        output_layout.addRow(self.widgets['ocr_generate_report'])
        output_layout.addRow(self.widgets['ocr_save_debug_images'])
        output_layout.addRow(self.widgets['ocr_debug_output'])
        main_layout.addWidget(output_group)

        main_layout.addStretch(1)

    def _open_dictionary_editor(self):
        """Open the OCR Dictionary Editor dialog."""
        from vsg_qt.ocr_dictionary_dialog import OCRDictionaryDialog
        dialog = OCRDictionaryDialog(self)
        dialog.exec()

    def _update_font_preview(self, ratio: float = None):
        """Update the font size preview label with calculated values."""
        if ratio is None:
            ratio = self.widgets['ocr_font_size_ratio'].value()

        # Calculate font sizes for common resolutions
        sizes = {
            '480p': round(480 * ratio / 100),
            '576p': round(576 * ratio / 100),
            '720p': round(720 * ratio / 100),
            '1080p': round(1080 * ratio / 100),
        }

        preview_text = f"480p: {sizes['480p']}  |  720p: {sizes['720p']}  |  1080p: {sizes['1080p']}"
        self._font_preview_label.setText(preview_text)

    def initialize_font_preview(self):
        """Initialize the font preview after settings are loaded."""
        self._update_font_preview()

class AnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: Dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        prep_group = QGroupBox("Step 1: Audio Pre-Processing")
        prep_layout = QFormLayout(prep_group)
        self.widgets['source_separation_mode'] = QComboBox()
        self.widgets['source_separation_mode'].addItem('None (Use Original Audio)', 'none')
        self.widgets['source_separation_mode'].addItem('Instrumental (No Vocals)', 'instrumental')
        self.widgets['source_separation_mode'].addItem('Vocals Only', 'vocals')
        self.widgets['source_separation_mode'].setToolTip(
            "Enable audio separation before correlation.\n\n"
            "• None - Use original audio (default)\n"
            "• Instrumental - Remove vocals for cross-language sync (JP↔EN)\n"
            "• Vocals Only - Isolate dialogue for speech-based correlation"
        )

        self.widgets['source_separation_model'] = QComboBox()
        self._populate_model_dropdown()

        self.widgets['source_separation_model_dir'] = _dir_input()
        self.widgets['source_separation_model_dir'].setToolTip(
            "Directory where audio-separator stores models.\n\n"
            "Defaults to the application's audio_separator_models folder.\n"
            "Models are downloaded automatically on first use."
        )

        # Manage Models button
        self.manage_models_btn = QPushButton("Manage Models...")
        self.manage_models_btn.setToolTip("Open the model manager to browse, download, and manage audio separation models.")
        self.manage_models_btn.clicked.connect(self._open_model_manager)

        self.widgets['filtering_method'] = QComboBox(); self.widgets['filtering_method'].addItems(['None', 'Low-Pass Filter', 'Dialogue Band-Pass Filter']); self.widgets['filtering_method'].setToolTip("Apply a filter to the audio before analysis to improve the signal-to-noise ratio.\n'Dialogue Band-Pass' is recommended for most content.")
        self.cutoff_container = QWidget()
        cutoff_layout = QFormLayout(self.cutoff_container); cutoff_layout.setContentsMargins(0, 0, 0, 0)
        self.widgets['audio_bandlimit_hz'] = QSpinBox(); self.widgets['audio_bandlimit_hz'].setRange(0, 22000); self.widgets['audio_bandlimit_hz'].setSuffix(" Hz"); self.widgets['audio_bandlimit_hz'].setToolTip("For the Low-Pass Filter, specifies the frequency (in Hz) above which audio data is cut off.")
        cutoff_layout.addRow("Low-Pass Cutoff:", self.widgets['audio_bandlimit_hz'])
        prep_layout.addRow("Source Separation:", self.widgets['source_separation_mode'])
        prep_layout.addRow("Separation Model:", self.widgets['source_separation_model'])
        prep_layout.addRow("Model Directory:", self.widgets['source_separation_model_dir'])
        prep_layout.addRow("", self.manage_models_btn)
        prep_layout.addRow("Audio Filtering:", self.widgets['filtering_method'])
        prep_layout.addRow(self.cutoff_container)
        main_layout.addWidget(prep_group)

        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_layout = QFormLayout(core_group)
        self.widgets['correlation_method'] = QComboBox(); self.widgets['correlation_method'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'Onset Detection', 'GCC-SCOT', 'DTW (Dynamic Time Warping)', 'Spectrogram Correlation', 'VideoDiff']); self.widgets['correlation_method'].setToolTip("The core algorithm used to find the time offset.\n\n• SCC - Standard cross-correlation. Precise for identical audio sources.\n• GCC-PHAT - Phase correlation. More robust to noise and different mixes.\n• Onset Detection - Matches audio transients (hits, speech onsets). Best for\n  different releases/mixes where waveforms differ but events align.\n• GCC-SCOT - Smoothed Coherence Transform. Better when one signal is noisier.\n• DTW - Dynamic Time Warping on MFCC features. Handles tempo variations.\n• Spectrogram - Correlates mel spectrograms. Captures frequency+time structure.\n• VideoDiff - External tool for video-based sync.")
        self.widgets['correlation_method_source_separated'] = QComboBox(); self.widgets['correlation_method_source_separated'].addItems(['Standard Correlation (SCC)', 'Phase Correlation (GCC-PHAT)', 'Onset Detection', 'GCC-SCOT', 'DTW (Dynamic Time Warping)', 'Spectrogram Correlation']); self.widgets['correlation_method_source_separated'].setToolTip("Correlation method used ONLY for sources that undergo source separation.\n\nThis method is automatically applied when:\n• Source Separation is enabled (Instrumental or Vocals)\n• AND the comparison matches 'Apply To' setting\n\nRecommended: Phase Correlation (GCC-PHAT)\n• More robust to noise and artifacts from stem separation\n• Works well with Demucs/RoFormer separated audio\n• Less sensitive to spectral differences between stems\n\nNote: All other settings (peak fitting, SOXR, filtering, etc.) remain unchanged.\nNote: Ignored when Multi-Correlation Comparison is enabled (uses checkboxes instead).")
        self.widgets['scan_chunk_count'] = QSpinBox(); self.widgets['scan_chunk_count'].setRange(1, 100); self.widgets['scan_chunk_count'].setToolTip("The number of separate audio segments to analyze across the file's duration.")
        self.widgets['scan_chunk_duration'] = QSpinBox(); self.widgets['scan_chunk_duration'].setRange(1, 120); self.widgets['scan_chunk_duration'].setToolTip("The length (in seconds) of each individual audio segment to be analyzed.")
        self.widgets['min_match_pct'] = QDoubleSpinBox(); self.widgets['min_match_pct'].setRange(0.1, 100.0); self.widgets['min_match_pct'].setDecimals(1); self.widgets['min_match_pct'].setSingleStep(1.0); self.widgets['min_match_pct'].setToolTip("The minimum correlation score for an audio chunk to be considered a valid match.")
        self.widgets['min_accepted_chunks'] = QSpinBox(); self.widgets['min_accepted_chunks'].setRange(1, 100); self.widgets['min_accepted_chunks'].setToolTip("The minimum number of valid chunks required for the analysis to be considered successful.")
        self.widgets['delay_selection_mode'] = QComboBox(); self.widgets['delay_selection_mode'].addItems(['Mode (Most Common)', 'Mode (Clustered)', 'Mode (Early Cluster)', 'First Stable', 'Average']); self.widgets['delay_selection_mode'].setToolTip("How to choose the final delay from multiple chunk measurements:\n\n• Mode (Most Common) - Picks the delay that appears most frequently (Default)\n  Best for: Files with stable sync throughout most of the duration\n\n• Mode (Clustered) - Finds most common delay, then averages all chunks within ±1ms\n  Best for: Source-separated audio with sporadic outliers (Demucs, RoFormer)\n  Handles vote-splitting and excludes extreme outliers\n\n• Mode (Early Cluster) - Prioritizes clusters stable in the first N chunks\n  Best for: Files with edits/cuts mid-file where beginning sync is most reliable\n  Uses ±1ms clustering but prefers delays appearing early and stable\n\n• First Stable - Uses the delay from the first stable segment\n  Best for: Files where sync changes mid-file due to authoring issues\n  (Note: For stepping correction, use the Segmented Audio settings instead)\n\n• Average - Calculates the mean of all delay measurements\n  Best for: Files with small variations around a central value")
        self.widgets['first_stable_min_chunks'] = QSpinBox(); self.widgets['first_stable_min_chunks'].setRange(1, 100); self.widgets['first_stable_min_chunks'].setToolTip("[First Stable mode only]\n\nMinimum number of consecutive chunks with the same delay required\nfor a segment to be considered 'stable'.\n\nHigher values = more strict (avoids false positives at file start)\nLower values = more lenient (may catch brief stable periods)\n\nRecommended: 3-5 chunks")
        self.widgets['first_stable_skip_unstable'] = QCheckBox(); self.widgets['first_stable_skip_unstable'].setToolTip("[First Stable mode only]\n\nWhen enabled, skips segments that don't meet the minimum chunk count\nand looks for the next stable segment.\n\nUseful for avoiding offset beginnings (e.g., 2 chunks at wrong delay\nbefore the rest of the file stabilizes).\n\nWhen disabled, always uses the very first segment regardless of size.")
        self.widgets['early_cluster_window'] = QSpinBox(); self.widgets['early_cluster_window'].setRange(1, 100); self.widgets['early_cluster_window'].setToolTip("[Mode (Early Cluster) only]\n\nNumber of chunks at the beginning of the file to check for early stability.\n\nThe algorithm prioritizes clusters that appear frequently in this window.\n\nRecommended: 10 chunks (checks roughly first 15% of file with default settings)")
        self.widgets['early_cluster_threshold'] = QSpinBox(); self.widgets['early_cluster_threshold'].setRange(1, 100); self.widgets['early_cluster_threshold'].setToolTip("[Mode (Early Cluster) only]\n\nMinimum number of chunks a cluster must have within the early window\nto be considered 'early stable'.\n\nLower values = more lenient (may pick transient early delays)\nHigher values = more strict (requires strong early presence)\n\nRecommended: 5 chunks (50% of default window)")
        self.widgets['delay_selection_mode_source_separated'] = QComboBox(); self.widgets['delay_selection_mode_source_separated'].addItems(['Mode (Most Common)', 'Mode (Clustered)', 'Mode (Early Cluster)', 'First Stable', 'Average']); self.widgets['delay_selection_mode_source_separated'].setToolTip("Delay selection mode used ONLY for sources that undergo source separation.\n\nThis mode is automatically applied when:\n• Source Separation is enabled (Instrumental or Vocals)\n• AND the comparison matches 'Apply To' setting\n\nRecommended: Mode (Clustered)\n• Handles sporadic outliers from stem separation (Demucs, RoFormer)\n• Clusters delays within ±1ms tolerance\n• Excludes extreme outliers that poison averages\n\nNote: Sources without separation still use the normal 'Delay Selection Method'")
        core_layout.addRow("Correlation Method:", self.widgets['correlation_method'])
        core_layout.addRow("Correlation (Source-Separated):", self.widgets['correlation_method_source_separated'])
        core_layout.addRow("Number of Chunks:", self.widgets['scan_chunk_count'])
        core_layout.addRow("Duration of Chunks (s):", self.widgets['scan_chunk_duration'])
        core_layout.addRow("Minimum Match Confidence (%):", self.widgets['min_match_pct'])
        core_layout.addRow("Minimum Accepted Chunks:", self.widgets['min_accepted_chunks'])
        core_layout.addRow("Delay Selection Method:", self.widgets['delay_selection_mode'])
        core_layout.addRow("Delay Selection (Source-Separated):", self.widgets['delay_selection_mode_source_separated'])
        core_layout.addRow("  ↳ Min Chunks for Stability:", self.widgets['first_stable_min_chunks'])
        core_layout.addRow("  ↳ Skip Unstable Segments:", self.widgets['first_stable_skip_unstable'])
        core_layout.addRow("  ↳ Early Cluster Window:", self.widgets['early_cluster_window'])
        core_layout.addRow("  ↳ Early Cluster Threshold:", self.widgets['early_cluster_threshold'])
        main_layout.addWidget(core_group)

        # --- Multi-Correlation Comparison (Analyze Only) ---
        multi_corr_group = QGroupBox("Multi-Correlation Comparison (Analyze Only)")
        multi_corr_layout = QVBoxLayout(multi_corr_group)
        self.widgets['multi_correlation_enabled'] = QCheckBox("Enable Multi-Correlation Comparison")
        self.widgets['multi_correlation_enabled'].setToolTip(
            "When enabled in Analyze Only mode, runs multiple correlation methods on the same\n"
            "audio chunks and outputs results for each. Useful for comparing method accuracy.\n\n"
            "• Only affects Analyze Only mode - real jobs use the Correlation Method dropdown\n"
            "• Audio is decoded once, chunks extracted once, then each method runs on same data\n"
            "• Results are labeled by method for easy comparison"
        )
        multi_corr_layout.addWidget(self.widgets['multi_correlation_enabled'])

        # Method checkboxes container
        self.multi_corr_methods_container = QWidget()
        methods_layout = QVBoxLayout(self.multi_corr_methods_container)
        methods_layout.setContentsMargins(20, 0, 0, 0)  # Indent
        self.widgets['multi_corr_scc'] = QCheckBox("Standard Correlation (SCC)")
        self.widgets['multi_corr_gcc_phat'] = QCheckBox("Phase Correlation (GCC-PHAT)")
        self.widgets['multi_corr_onset'] = QCheckBox("Onset Detection")
        self.widgets['multi_corr_gcc_scot'] = QCheckBox("GCC-SCOT")
        self.widgets['multi_corr_gcc_whiten'] = QCheckBox("Whitened Cross-Correlation")
        self.widgets['multi_corr_dtw'] = QCheckBox("DTW (Dynamic Time Warping)")
        self.widgets['multi_corr_spectrogram'] = QCheckBox("Spectrogram Correlation")
        methods_layout.addWidget(self.widgets['multi_corr_scc'])
        methods_layout.addWidget(self.widgets['multi_corr_gcc_phat'])
        methods_layout.addWidget(self.widgets['multi_corr_onset'])
        methods_layout.addWidget(self.widgets['multi_corr_gcc_scot'])
        methods_layout.addWidget(self.widgets['multi_corr_gcc_whiten'])
        methods_layout.addWidget(self.widgets['multi_corr_dtw'])
        methods_layout.addWidget(self.widgets['multi_corr_spectrogram'])
        multi_corr_layout.addWidget(self.multi_corr_methods_container)
        main_layout.addWidget(multi_corr_group)

        # Connect enable checkbox to show/hide methods
        self.widgets['multi_correlation_enabled'].toggled.connect(self._update_multi_corr_visibility)
        self._update_multi_corr_visibility(False)

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
        is_early_cluster = (text == "Mode (Early Cluster)")
        self.widgets['first_stable_min_chunks'].setEnabled(is_first_stable)
        self.widgets['first_stable_skip_unstable'].setEnabled(is_first_stable)
        self.widgets['early_cluster_window'].setEnabled(is_early_cluster)
        self.widgets['early_cluster_threshold'].setEnabled(is_early_cluster)

    def _update_multi_corr_visibility(self, enabled: bool):
        self.multi_corr_methods_container.setVisible(enabled)

    def _populate_model_dropdown(self):
        """Populate the model dropdown from installed_models.json."""
        self.widgets['source_separation_model'].clear()
        self.widgets['source_separation_model'].addItem('Default (Audio Separator)', 'default')

        # Get model directory (may be empty initially)
        model_dir = self._get_model_dir()

        # Load installed models
        installed_models = get_installed_models(model_dir)

        if not installed_models:
            # No models installed - show message
            self.widgets['source_separation_model'].addItem('(No models installed - click Manage Models)', '')
            self.widgets['source_separation_model'].setToolTip(
                "No models are installed yet.\n\n"
                "Click 'Manage Models...' to browse and download models."
            )
        else:
            # Sort installed models by rank (best first)
            sorted_models = sorted(
                installed_models,
                key=lambda m: (m.get('rank', 999), m.get('name', m.get('filename', '')))
            )

            # Add installed models with rich tooltips
            for model in sorted_models:
                # Friendly display name with quality indicator
                name = model.get('name', model['filename'])
                if model.get('recommended'):
                    name = f"⭐ {name}"

                display_name = name
                quality_tier = model.get('quality_tier')
                if quality_tier and quality_tier in ['S-Tier', 'A-Tier']:
                    display_name = f"{name} ({quality_tier})"

                self.widgets['source_separation_model'].addItem(display_name, model['filename'])

                # Build rich tooltip with metadata
                tooltip_lines = [
                    f"<b>{name}</b>",
                    "",
                    f"<b>File:</b> {model['filename']}",
                    f"<b>Type:</b> {model.get('type', 'Unknown')}",
                ]

                if quality_tier:
                    tooltip_lines.append(f"<b>Quality:</b> {quality_tier}")

                tooltip_lines.append(f"<b>Stems:</b> {model.get('stems', 'Unknown')}")

                if model.get('sdr_vocals'):
                    tooltip_lines.append(f"<b>Vocal SDR:</b> {model['sdr_vocals']:.1f} dB")
                if model.get('sdr_instrumental'):
                    tooltip_lines.append(f"<b>Instrumental SDR:</b> {model['sdr_instrumental']:.1f} dB")

                use_cases = model.get('use_cases', [])
                if use_cases:
                    tooltip_lines.append(f"<b>Best For:</b> {', '.join(use_cases)}")

                if model.get('description'):
                    tooltip_lines.append("")
                    tooltip_lines.append(model['description'])

                # Set tooltip for this item (note: QComboBox doesn't support per-item tooltips perfectly,
                # so we set it on the widget which applies to the current selection)
                # For now, set a general tooltip

            self.widgets['source_separation_model'].setToolTip(
                "Select an installed audio-separator model.\n\n"
                "Select a model and view its details in the status bar.\n"
                "Click 'Manage Models...' to download more models."
            )

    def _get_model_dir(self) -> str:
        """Get the current model directory from the widget."""
        # Check if the widget exists yet (it might not during initialization)
        if 'source_separation_model_dir' not in self.widgets:
            return None

        dir_widget = self.widgets['source_separation_model_dir']
        # The directory widget is a custom widget with a QLineEdit child
        line_edit = dir_widget.findChild(QLineEdit)
        if line_edit:
            dir_path = line_edit.text().strip()
            if dir_path:
                return dir_path

        # Return None to use default
        return None

    def _open_model_manager(self):
        """Open the model manager dialog."""
        from vsg_qt.options_dialog.model_manager_dialog import ModelManagerDialog

        model_dir = self._get_model_dir() or str(get_installed_models_json_path().parent)

        dialog = ModelManagerDialog(model_dir, parent=self)
        if dialog.exec():
            # Refresh the dropdown after closing the dialog
            self._populate_model_dropdown()

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

        # ===== SYNC MODE SELECTION =====
        mode_group = QGroupBox("Sync Mode")
        mode_layout = QFormLayout(mode_group)

        self.widgets['subtitle_sync_mode'] = QComboBox()
        self.widgets['subtitle_sync_mode'].addItems([
            'time-based',
            'timebase-frame-delay',
            'timebase-frame-locked-timestamps',
            'duration-align',
            'correlation-frame-snap',
            'subtitle-anchored-frame-snap',
            'correlation-guided-frame-anchor'
        ])
        self.widgets['subtitle_sync_mode'].setToolTip(
            "Subtitle synchronization method:\n\n"
            "• time-based: Simple delay via mkvmerge --sync (fastest)\n"
            "• timebase-frame-delay: Frame-rounded delay, no per-event snapping\n"
            "• timebase-frame-locked: Time-based + VideoTimestamps frame-alignment\n"
            "• duration-align: Align by video duration difference\n"
            "• correlation-frame-snap: Correlation + scene-based frame verification\n"
            "• subtitle-anchored-frame-snap: Visual-only using subtitle positions\n"
            "• correlation-guided-frame-anchor: Correlation-guided robust matching"
        )
        mode_layout.addRow("Mode:", self.widgets['subtitle_sync_mode'])
        main_layout.addWidget(mode_group)

        # ===== SHARED FRAME MATCHING SETTINGS =====
        frame_group = QGroupBox("Frame Matching Settings (All Frame-Based Modes)")
        frame_layout = QFormLayout(frame_group)

        self.widgets['frame_hash_algorithm'] = QComboBox()
        self.widgets['frame_hash_algorithm'].addItems(['dhash', 'phash', 'average_hash', 'whash'])
        self.widgets['frame_hash_algorithm'].setToolTip(
            "Hash algorithm for frame comparison:\n\n"
            "• dhash (Default): Difference hash - fast, good for scene cuts\n"
            "• phash: Perceptual hash - better for heavy re-encoding\n"
            "• average_hash: Simple averaging - fastest but less accurate\n"
            "• whash: Wavelet hash - most robust for processed videos"
        )

        self.widgets['frame_hash_size'] = QComboBox()
        self.widgets['frame_hash_size'].addItems(['4', '8', '16'])
        self.widgets['frame_hash_size'].setCurrentIndex(1)  # Default 8
        self.widgets['frame_hash_size'].setToolTip(
            "Hash size (resolution):\n\n"
            "• 4: Very tolerant (16-bit hash)\n"
            "• 8 (Default): Balanced precision (64-bit hash)\n"
            "• 16: Very precise (256-bit hash)"
        )

        self.widgets['frame_hash_threshold'] = QSpinBox()
        self.widgets['frame_hash_threshold'].setRange(0, 30)
        self.widgets['frame_hash_threshold'].setValue(5)
        self.widgets['frame_hash_threshold'].setToolTip(
            "Max hamming distance for frame match:\n\n"
            "• 0-3: Strict (near-perfect match required)\n"
            "• 5 (Default): Balanced (minor compression differences OK)\n"
            "• 10-15: Tolerant (heavy re-encoding OK)\n"
            "• 20+: Very loose (may match wrong frames)"
        )

        self.widgets['frame_window_radius'] = QSpinBox()
        self.widgets['frame_window_radius'].setRange(1, 10)
        self.widgets['frame_window_radius'].setValue(5)
        self.widgets['frame_window_radius'].setToolTip(
            "Sliding window radius (frames before/after):\n\n"
            "Window size = 2*N+1 frames for temporal consistency.\n\n"
            "• 3: 7-frame window (faster)\n"
            "• 5 (Default): 11-frame window (recommended)\n"
            "• 7+: 15+ frame window (more robust, slower)"
        )

        self.widgets['frame_search_range_ms'] = QSpinBox()
        self.widgets['frame_search_range_ms'].setRange(500, 10000)
        self.widgets['frame_search_range_ms'].setValue(2000)
        self.widgets['frame_search_range_ms'].setSingleStep(500)
        self.widgets['frame_search_range_ms'].setSuffix(" ms")
        self.widgets['frame_search_range_ms'].setToolTip(
            "Search range around expected position (±N ms):\n\n"
            "• 1000ms: Tight search (~24 frames at 24fps)\n"
            "• 2000ms (Default): Standard search (~48 frames)\n"
            "• 5000ms: Wide search for large timing differences"
        )

        self.widgets['frame_agreement_tolerance_ms'] = QSpinBox()
        self.widgets['frame_agreement_tolerance_ms'].setRange(10, 500)
        self.widgets['frame_agreement_tolerance_ms'].setValue(100)
        self.widgets['frame_agreement_tolerance_ms'].setSingleStep(10)
        self.widgets['frame_agreement_tolerance_ms'].setSuffix(" ms")
        self.widgets['frame_agreement_tolerance_ms'].setToolTip(
            "Agreement tolerance for checkpoint measurements:\n\n"
            "All checkpoints must agree within this tolerance.\n\n"
            "• 50ms: Strict (~1-2 frames)\n"
            "• 100ms (Default): Standard (~2-3 frames)\n"
            "• 200ms: Loose (~5 frames)"
        )

        self.widgets['frame_use_vapoursynth'] = QCheckBox("Use VapourSynth indexing")
        self.widgets['frame_use_vapoursynth'].setChecked(True)
        self.widgets['frame_use_vapoursynth'].setToolTip(
            "Use VapourSynth for frame extraction:\n\n"
            "• Checked (Default): Much faster after first run (cached .lwi index)\n"
            "• Unchecked: Use ffprobe/ffmpeg fallback (slower but no dependencies)"
        )

        frame_layout.addRow("Hash Algorithm:", self.widgets['frame_hash_algorithm'])
        frame_layout.addRow("Hash Size:", self.widgets['frame_hash_size'])
        frame_layout.addRow("Hash Threshold:", self.widgets['frame_hash_threshold'])
        frame_layout.addRow("Window Radius:", self.widgets['frame_window_radius'])
        frame_layout.addRow("Search Range:", self.widgets['frame_search_range_ms'])
        frame_layout.addRow("Tolerance:", self.widgets['frame_agreement_tolerance_ms'])
        frame_layout.addRow("", self.widgets['frame_use_vapoursynth'])
        main_layout.addWidget(frame_group)

        # ===== SHARED OUTPUT SETTINGS =====
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout(output_group)

        self.widgets['subtitle_rounding'] = QComboBox()
        self.widgets['subtitle_rounding'].addItems(['floor', 'round', 'ceil'])
        self.widgets['subtitle_rounding'].setToolTip(
            "Final rounding mode for subtitle timestamps:\n\n"
            "Controls how timestamps are rounded to ASS centisecond precision (10ms).\n\n"
            "• floor (Default): Round down - subtitles appear slightly earlier\n"
            "• round: Nearest - statistically balanced\n"
            "• ceil: Round up - subtitles appear slightly later"
        )
        output_layout.addRow("Rounding:", self.widgets['subtitle_rounding'])
        main_layout.addWidget(output_group)

        # ===== MODE-SPECIFIC SETTINGS =====
        specific_group = QGroupBox("Mode-Specific Settings")
        specific_layout = QFormLayout(specific_group)

        # --- Time-based options ---
        self.widgets['time_based_use_raw_values'] = QCheckBox("Apply delay directly to subtitle file")
        self.widgets['time_based_use_raw_values'].setToolTip(
            "How to apply the delay:\n\n"
            "• Unchecked (Default): Use mkvmerge --sync (delay in container)\n"
            "• Checked: Modify subtitle timestamps directly in the file"
        )
        specific_layout.addRow("", self.widgets['time_based_use_raw_values'])

        # --- Timebase-frame-delay options ---
        self.widgets['frame_delay_rounding'] = QComboBox()
        self.widgets['frame_delay_rounding'].addItems(['nearest', 'floor', 'ceil'])
        self.widgets['frame_delay_rounding'].setToolTip(
            "How to round the delay to whole frames:\n\n"
            "• nearest (Default): Round to closest frame\n"
            "• floor: Round down - subtitles appear slightly earlier\n"
            "• ceil: Round up - subtitles appear slightly later"
        )
        specific_layout.addRow("Frame Rounding:", self.widgets['frame_delay_rounding'])

        # --- Duration-align options ---
        self.widgets['duration_align_validate'] = QCheckBox("Validate frame alignment")
        self.widgets['duration_align_validate'].setChecked(True)
        self.widgets['duration_align_validate'].setToolTip(
            "Verify videos are actually frame-aligned using perceptual hashing."
        )

        self.widgets['duration_align_validate_points'] = QComboBox()
        self.widgets['duration_align_validate_points'].addItem('1 point (fast)', 1)
        self.widgets['duration_align_validate_points'].addItem('3 points (thorough)', 3)
        self.widgets['duration_align_validate_points'].setCurrentIndex(1)
        self.widgets['duration_align_validate_points'].setToolTip(
            "Number of checkpoints to validate (first, middle, last)."
        )

        self.widgets['duration_align_strictness'] = QSpinBox()
        self.widgets['duration_align_strictness'].setRange(50, 100)
        self.widgets['duration_align_strictness'].setValue(80)
        self.widgets['duration_align_strictness'].setSuffix("%")
        self.widgets['duration_align_strictness'].setToolTip(
            "Percentage of frames that must match at each checkpoint."
        )

        self.widgets['duration_align_verify_with_frames'] = QCheckBox("Hybrid mode: verify with sliding window")
        self.widgets['duration_align_verify_with_frames'].setToolTip(
            "Combine duration-align with sliding window frame matching for higher accuracy."
        )

        self.widgets['duration_align_skip_validation_generated_tracks'] = QCheckBox("Skip validation for generated tracks")
        self.widgets['duration_align_skip_validation_generated_tracks'].setChecked(True)
        self.widgets['duration_align_skip_validation_generated_tracks'].setToolTip(
            "Generated tracks inherit timing from source - no need to re-validate."
        )

        self.widgets['duration_align_fallback_mode'] = QComboBox()
        self.widgets['duration_align_fallback_mode'].addItems(['none', 'abort', 'duration-offset'])
        self.widgets['duration_align_fallback_mode'].setToolTip(
            "What to do if validation fails:\n"
            "• none: Warn but continue\n"
            "• abort: Fail the job\n"
            "• duration-offset: Use duration calculation only"
        )

        specific_layout.addRow("", self.widgets['duration_align_validate'])
        specific_layout.addRow("Validation Points:", self.widgets['duration_align_validate_points'])
        specific_layout.addRow("Strictness:", self.widgets['duration_align_strictness'])
        specific_layout.addRow("", self.widgets['duration_align_verify_with_frames'])
        specific_layout.addRow("", self.widgets['duration_align_skip_validation_generated_tracks'])
        specific_layout.addRow("DA Fallback:", self.widgets['duration_align_fallback_mode'])

        # --- Timebase-frame-locked options ---
        self.widgets['frame_lock_submillisecond_precision'] = QCheckBox("Use sub-millisecond precision")
        self.widgets['frame_lock_submillisecond_precision'].setToolTip(
            "Experimental: Preserve sub-millisecond precision when calculating frame boundaries.\n\n"
            "Default (unchecked): Truncates to integer milliseconds before frame calculation.\n"
            "  e.g., 1234.567ms → 1234ms → frame lookup\n\n"
            "Checked: Preserves fractional milliseconds in frame calculation.\n"
            "  e.g., 1234.567ms → 1234.567ms → frame lookup\n\n"
            "The difference only matters when timing is very close to a frame boundary.\n"
            "Since ASS format saves at 10ms (centisecond) precision anyway, this rarely matters.\n"
            "Try enabling if you see 1-frame alignment issues."
        )
        specific_layout.addRow("", self.widgets['frame_lock_submillisecond_precision'])

        # --- Correlation-frame-snap options ---
        self.widgets['correlation_snap_fallback_mode'] = QComboBox()
        self.widgets['correlation_snap_fallback_mode'].addItems(['snap-to-frame', 'use-raw', 'abort'])
        self.widgets['correlation_snap_fallback_mode'].setToolTip(
            "What to do if frame verification fails:\n"
            "• snap-to-frame: Snap correlation to nearest frame\n"
            "• use-raw: Use raw correlation delay\n"
            "• abort: Fail the job"
        )
        specific_layout.addRow("CorrSnap Fallback:", self.widgets['correlation_snap_fallback_mode'])

        # --- Subtitle-anchored options ---
        self.widgets['sub_anchor_fallback_mode'] = QComboBox()
        self.widgets['sub_anchor_fallback_mode'].addItems(['abort', 'use-median'])
        self.widgets['sub_anchor_fallback_mode'].setToolTip(
            "What to do if checkpoints disagree:\n"
            "• abort: Fail the job\n"
            "• use-median: Use median offset anyway"
        )
        specific_layout.addRow("SubAnchor Fallback:", self.widgets['sub_anchor_fallback_mode'])

        # --- Correlation-guided options ---
        self.widgets['corr_anchor_fallback_mode'] = QComboBox()
        self.widgets['corr_anchor_fallback_mode'].addItems(['use-correlation', 'use-median', 'abort'])
        self.widgets['corr_anchor_fallback_mode'].setToolTip(
            "What to do if checkpoints disagree:\n"
            "• use-correlation: Fall back to correlation baseline\n"
            "• use-median: Use median offset anyway\n"
            "• abort: Fail the job"
        )

        self.widgets['corr_anchor_refine_per_line'] = QCheckBox("Refine each subtitle to exact frames")
        self.widgets['corr_anchor_refine_per_line'].setToolTip(
            "After checkpoint validation, refine each subtitle line to exact frames."
        )

        self.widgets['corr_anchor_refine_workers'] = QSpinBox()
        self.widgets['corr_anchor_refine_workers'].setRange(1, 16)
        self.widgets['corr_anchor_refine_workers'].setValue(4)
        self.widgets['corr_anchor_refine_workers'].setToolTip(
            "Number of parallel workers for per-line refinement."
        )

        specific_layout.addRow("CorrGuided Fallback:", self.widgets['corr_anchor_fallback_mode'])
        specific_layout.addRow("", self.widgets['corr_anchor_refine_per_line'])
        specific_layout.addRow("Refine Workers:", self.widgets['corr_anchor_refine_workers'])

        main_layout.addWidget(specific_group)
        main_layout.addStretch(1)

        # Connect signals
        self.widgets['subtitle_sync_mode'].currentTextChanged.connect(self._update_mode_visibility)
        self._update_mode_visibility(self.widgets['subtitle_sync_mode'].currentText())

    def _update_mode_visibility(self, text: str):
        """Show/hide settings based on selected sync mode."""
        is_time_based = (text == 'time-based')
        is_frame_delay = (text == 'timebase-frame-delay')
        is_frame_locked = (text == 'timebase-frame-locked-timestamps')
        is_duration_align = (text == 'duration-align')
        is_correlation_snap = (text == 'correlation-frame-snap')
        is_sub_anchor_snap = (text == 'subtitle-anchored-frame-snap')
        is_corr_guided_anchor = (text == 'correlation-guided-frame-anchor')

        # Frame-based modes need frame matching settings
        is_frame_based = is_frame_locked or is_duration_align or is_correlation_snap or is_sub_anchor_snap or is_corr_guided_anchor

        # Shared frame matching settings (enabled for all frame-based modes)
        for key in ['frame_hash_algorithm', 'frame_hash_size', 'frame_hash_threshold',
                    'frame_window_radius', 'frame_search_range_ms', 'frame_agreement_tolerance_ms',
                    'frame_use_vapoursynth']:
            if key in self.widgets:
                self.widgets[key].setEnabled(is_frame_based)

        # Time-based specific
        self.widgets['time_based_use_raw_values'].setEnabled(is_time_based)

        # Timebase-frame-delay specific
        self.widgets['frame_delay_rounding'].setEnabled(is_frame_delay)

        # Timebase-frame-locked specific
        self.widgets['frame_lock_submillisecond_precision'].setEnabled(is_frame_locked)

        # Duration-align specific
        self.widgets['duration_align_validate'].setEnabled(is_duration_align)
        self.widgets['duration_align_validate_points'].setEnabled(is_duration_align)
        self.widgets['duration_align_strictness'].setEnabled(is_duration_align)
        self.widgets['duration_align_verify_with_frames'].setEnabled(is_duration_align)
        self.widgets['duration_align_skip_validation_generated_tracks'].setEnabled(is_duration_align)
        self.widgets['duration_align_fallback_mode'].setEnabled(is_duration_align)

        # Correlation-frame-snap specific
        self.widgets['correlation_snap_fallback_mode'].setEnabled(is_correlation_snap)

        # Subtitle-anchored specific
        self.widgets['sub_anchor_fallback_mode'].setEnabled(is_sub_anchor_snap)

        # Correlation-guided specific
        self.widgets['corr_anchor_fallback_mode'].setEnabled(is_corr_guided_anchor)
        self.widgets['corr_anchor_refine_per_line'].setEnabled(is_corr_guided_anchor)
        self.widgets['corr_anchor_refine_workers'].setEnabled(is_corr_guided_anchor)

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
        main_layout = QVBoxLayout(self)

        # --- Logging Options ---
        log_group = QGroupBox("Log Output")
        f = QFormLayout(log_group)
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
        main_layout.addWidget(log_group)

        # --- Sync Stability (Correlation Variance Detection) ---
        stability_group = QGroupBox("Sync Stability Detection")
        stability_layout = QFormLayout(stability_group)

        self.widgets['sync_stability_enabled'] = QCheckBox('Enable sync stability detection')
        self.widgets['sync_stability_enabled'].setToolTip("Detect variance in correlation results that may indicate sync issues.\nFlags jobs where chunk delays aren't perfectly consistent.")
        stability_layout.addRow(self.widgets['sync_stability_enabled'])

        variance_thresh = QDoubleSpinBox()
        variance_thresh.setRange(0.0, 10.0)
        variance_thresh.setDecimals(3)
        variance_thresh.setSingleStep(0.001)
        variance_thresh.setSuffix(' ms')
        variance_thresh.setToolTip("Maximum allowed variance in raw delay values.\n0 = flag any variance (strictest)\nHigher values allow more tolerance.")
        self.widgets['sync_stability_variance_threshold'] = variance_thresh
        stability_layout.addRow('Variance Threshold:', variance_thresh)

        min_chunks = QSpinBox()
        min_chunks.setRange(2, 30)
        min_chunks.setToolTip("Minimum number of chunks needed to calculate variance.\nNeeds at least this many chunks to report stability issues.")
        self.widgets['sync_stability_min_chunks'] = min_chunks
        stability_layout.addRow('Min Chunks:', min_chunks)

        outlier_mode = QComboBox()
        outlier_mode.addItem('Any Variance', 'any')
        outlier_mode.addItem('Custom Threshold', 'threshold')
        outlier_mode.setToolTip("How to detect outliers:\n- Any Variance: flag if ANY chunk differs from others\n- Custom Threshold: only flag if difference exceeds threshold")
        self.widgets['sync_stability_outlier_mode'] = outlier_mode
        stability_layout.addRow('Outlier Mode:', outlier_mode)

        outlier_thresh = QDoubleSpinBox()
        outlier_thresh.setRange(0.001, 100.0)
        outlier_thresh.setDecimals(3)
        outlier_thresh.setSingleStep(0.1)
        outlier_thresh.setSuffix(' ms')
        outlier_thresh.setToolTip("Custom outlier threshold (when mode = Custom Threshold).\nChunks differing by more than this from the mean are flagged as outliers.")
        self.widgets['sync_stability_outlier_threshold'] = outlier_thresh
        stability_layout.addRow('Outlier Threshold:', outlier_thresh)

        main_layout.addWidget(stability_group)
        main_layout.addStretch(1)
