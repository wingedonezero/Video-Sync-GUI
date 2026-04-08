# vsg_qt/options_dialog/tabs.py
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vsg_core.analysis.source_separation import (
    get_installed_models,
    get_installed_models_json_path,
)


# --- Helper functions ---
def _dir_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le)
    h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_dir(le))
    return w


def _file_input() -> QWidget:
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    le = QLineEdit()
    btn = QPushButton("Browse…")
    h.addWidget(le)
    h.addWidget(btn)
    btn.clicked.connect(lambda: _browse_for_file(le))
    return w


def _browse_for_dir(line_edit: QLineEdit) -> None:
    path = QFileDialog.getExistingDirectory(None, "Select Directory", line_edit.text())
    if path:
        line_edit.setText(path)


def _browse_for_file(line_edit: QLineEdit, nameFilter: str = "All Files (*)") -> None:
    path, _ = QFileDialog.getOpenFileName(
        None, "Select File", line_edit.text(), nameFilter
    )
    if path:
        line_edit.setText(path)


class StorageTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # Paths section
        paths_group = QGroupBox("Paths")
        f = QFormLayout(paths_group)
        self.widgets["output_folder"] = _dir_input()
        self.widgets["output_folder"].setToolTip(
            "The default directory where final merged files will be saved."
        )
        self.widgets["temp_root"] = _dir_input()
        self.widgets["temp_root"].setToolTip(
            "The root directory for storing temporary files during processing (e.g., extracted tracks, logs)."
        )
        self.widgets["logs_folder"] = _dir_input()
        self.widgets["logs_folder"].setToolTip(
            "Directory for batch report files. Reports are saved after each job completes for persistent tracking."
        )
        self.widgets["videodiff_path"] = _file_input()
        self.widgets["videodiff_path"].setToolTip(
            "Optional. The full path to the 'videodiff' executable if it's not in your system's PATH."
        )
        self.widgets["ocr_custom_wordlist_path"] = _file_input()
        self.widgets["ocr_custom_wordlist_path"].setToolTip(
            "Path to custom wordlist file for OCR. Contains words to not flag as unknown (anime names, romaji, etc.). One word per line."
        )
        f.addRow("Output Directory:", self.widgets["output_folder"])
        f.addRow("Temporary Directory:", self.widgets["temp_root"])
        f.addRow("Reports Directory:", self.widgets["logs_folder"])
        f.addRow("VideoDiff Path (optional):", self.widgets["videodiff_path"])
        f.addRow("OCR Custom Wordlist:", self.widgets["ocr_custom_wordlist_path"])
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
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # --- OCR Settings Group ---
        ocr_group = QGroupBox("OCR Settings")
        ocr_layout = QFormLayout(ocr_group)

        self.widgets["ocr_enabled"] = QCheckBox("Enable OCR for image-based subtitles")
        self.widgets["ocr_enabled"].setToolTip(
            "Automatically OCR VobSub and PGS subtitle tracks."
        )

        self.widgets["ocr_engine"] = QComboBox()
        self.widgets["ocr_engine"].addItem("PaddleOCR-VL 1.5 (Spotting + Positions)", "paddleocr-vl")
        self.widgets["ocr_engine"].setToolTip(
            "OCR engine to use.\n"
            "• PaddleOCR-VL 1.5: Fast VLM via llama.cpp with line detection + positions (239ms/sub, 1.7GB VRAM)."
        )

        self.widgets["ocr_language"] = QComboBox()
        self.widgets["ocr_language"].addItem("English", "eng")
        self.widgets["ocr_language"].addItem("Japanese", "jpn")
        self.widgets["ocr_language"].addItem("Spanish", "spa")
        self.widgets["ocr_language"].addItem("French", "fra")
        self.widgets["ocr_language"].addItem("German", "deu")
        self.widgets["ocr_language"].addItem("Chinese (Simplified)", "chi_sim")
        self.widgets["ocr_language"].addItem("Chinese (Traditional)", "chi_tra")
        self.widgets["ocr_language"].addItem("Korean", "kor")
        self.widgets["ocr_language"].setToolTip(
            "OCR language to use for text recognition."
        )

        ocr_layout.addRow(self.widgets["ocr_enabled"])
        ocr_layout.addRow("OCR Engine:", self.widgets["ocr_engine"])
        ocr_layout.addRow("Language:", self.widgets["ocr_language"])
        main_layout.addWidget(ocr_group)

        # --- Post-Processing Group ---
        postprocess_group = QGroupBox("Post-Processing")
        postprocess_layout = QFormLayout(postprocess_group)

        self.widgets["ocr_cleanup_enabled"] = QCheckBox("Enable OCR text cleanup")
        self.widgets["ocr_cleanup_enabled"].setToolTip(
            "Apply pattern-based fixes for common OCR errors (I/l confusion, rn→m, etc.)."
        )

        self.widgets["ocr_low_confidence_threshold"] = QDoubleSpinBox()
        self.widgets["ocr_low_confidence_threshold"].setRange(0.0, 100.0)
        self.widgets["ocr_low_confidence_threshold"].setSuffix(" %")
        self.widgets["ocr_low_confidence_threshold"].setToolTip(
            "Lines with confidence below this will be flagged in the report."
        )

        # Edit Dictionaries button
        self.edit_dictionaries_btn = QPushButton("Edit Dictionaries...")
        self.edit_dictionaries_btn.setToolTip(
            "Open the dictionary editor to manage:\n"
            "• Replacement rules (character/pattern corrections)\n"
            "• User dictionary (custom valid words)\n"
            "• Names (character names, proper nouns)"
        )
        self.edit_dictionaries_btn.clicked.connect(self._open_dictionary_editor)

        postprocess_layout.addRow(self.widgets["ocr_cleanup_enabled"])
        postprocess_layout.addRow(
            "Low Confidence Threshold:", self.widgets["ocr_low_confidence_threshold"]
        )
        postprocess_layout.addRow("", self.edit_dictionaries_btn)
        main_layout.addWidget(postprocess_group)

        # --- Output Group ---
        output_group = QGroupBox("Output")
        output_layout = QFormLayout(output_group)

        self.widgets["ocr_output_format"] = QComboBox()
        self.widgets["ocr_output_format"].addItem("ASS (recommended)", "ass")
        self.widgets["ocr_output_format"].addItem("SRT", "srt")
        self.widgets["ocr_output_format"].setToolTip(
            "Output format. ASS supports position tags, SRT does not."
        )

        # Font size ratio with live preview
        self.widgets["ocr_font_size_ratio"] = QDoubleSpinBox()
        self.widgets["ocr_font_size_ratio"].setRange(3.00, 10.00)
        self.widgets["ocr_font_size_ratio"].setDecimals(2)
        self.widgets["ocr_font_size_ratio"].setSingleStep(0.05)
        self.widgets["ocr_font_size_ratio"].setSuffix(" %")
        self.widgets["ocr_font_size_ratio"].setToolTip(
            "Font size as percentage of video height (PlayResY).\n"
            "Ensures consistent visual size across resolutions.\n\n"
            "Examples at 5.80%:\n"
            "• 480p → 28pt\n"
            "• 720p → 42pt\n"
            "• 1080p → 63pt"
        )
        self._font_preview_label = QLabel()
        self._font_preview_label.setStyleSheet("color: gray; font-size: 11px;")
        self.widgets["ocr_font_size_ratio"].valueChanged.connect(
            self._update_font_preview
        )

        self.widgets["ocr_generate_report"] = QCheckBox("Generate detailed OCR report")
        self.widgets["ocr_generate_report"].setToolTip(
            "Save a JSON report with unknown words, confidence scores, and applied fixes."
        )

        self.widgets["ocr_debug_output"] = QCheckBox(
            "Debug OCR output (analyze issues)"
        )
        self.widgets["ocr_debug_output"].setToolTip(
            "Save debug output organized by issue type:\n"
            "• all_subtitles/ - All images and OCR text for verification\n"
            "• annotated/ - Images with line bboxes drawn\n"
            "• verification/ - Pixel verification results (empty, missed, bleed)\n"
            "• unknown_words/ - Images with unknown words\n"
            "• fixes_applied/ - Images showing what fixes were made\n\n"
            "Creates a folder in logs with the same name as the report."
        )

        output_layout.addRow("Output Format:", self.widgets["ocr_output_format"])
        output_layout.addRow("Font Size Ratio:", self.widgets["ocr_font_size_ratio"])
        output_layout.addRow("", self._font_preview_label)
        output_layout.addRow(self.widgets["ocr_generate_report"])
        output_layout.addRow(self.widgets["ocr_debug_output"])

        # PGS-specific settings
        pgs_group = QGroupBox("PGS (Blu-ray) Settings")
        pgs_layout = QFormLayout(pgs_group)

        self.widgets["ocr_pgs_save_object_crops"] = QCheckBox(
            "Save raw PGS object crops in debug output"
        )
        self.widgets["ocr_pgs_save_object_crops"].setToolTip(
            "Save individual PGS composition object bitmaps before compositing.\n"
            "Useful for analyzing how PGS objects map to regions.\n"
            "Requires debug output to be enabled."
        )

        self.widgets["ocr_pgs_keep_bot_colors"] = QCheckBox(
            "Keep bottom dialogue colors"
        )
        self.widgets["ocr_pgs_keep_bot_colors"].setToolTip(
            "Preserve original subtitle colors for bottom (dialogue) lines.\n"
            "Extracts the dominant color from each line's pixels and applies\n"
            "it as a color override in the ASS output."
        )

        self.widgets["ocr_pgs_keep_top_colors"] = QCheckBox(
            "Keep top dialogue colors"
        )
        self.widgets["ocr_pgs_keep_top_colors"].setToolTip(
            "Preserve original subtitle colors for top (title card) lines."
        )

        self.widgets["ocr_pgs_keep_pos_colors"] = QCheckBox(
            "Keep positioned (sign) colors"
        )
        self.widgets["ocr_pgs_keep_pos_colors"].setToolTip(
            "Preserve original subtitle colors for positioned (sign) lines.\n"
            "Signs often use distinctive colors that should be kept."
        )

        pgs_layout.addRow(self.widgets["ocr_pgs_save_object_crops"])
        pgs_layout.addRow(self.widgets["ocr_pgs_keep_bot_colors"])
        pgs_layout.addRow(self.widgets["ocr_pgs_keep_top_colors"])
        pgs_layout.addRow(self.widgets["ocr_pgs_keep_pos_colors"])

        main_layout.addWidget(output_group)
        main_layout.addWidget(pgs_group)

        main_layout.addStretch(1)

    def _open_dictionary_editor(self) -> None:
        """Open the OCR Dictionary Editor dialog."""
        from vsg_qt.ocr_dictionary_dialog import OCRDictionaryDialog

        dialog = OCRDictionaryDialog(self)
        dialog.exec()

    def _update_font_preview(self, ratio: float | None = None) -> None:
        """Update the font size preview label with calculated values."""
        if ratio is None:
            ratio = self.widgets["ocr_font_size_ratio"].value()

        # Calculate font sizes for common resolutions
        sizes = {
            "480p": round(480 * ratio / 100),
            "576p": round(576 * ratio / 100),
            "720p": round(720 * ratio / 100),
            "1080p": round(1080 * ratio / 100),
        }

        preview_text = f"480p: {sizes['480p']}  |  720p: {sizes['720p']}  |  1080p: {sizes['1080p']}"
        self._font_preview_label.setText(preview_text)

    def initialize_font_preview(self) -> None:
        """Initialize the font preview after settings are loaded."""
        self._update_font_preview()


class AnalysisTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        prep_group = QGroupBox("Step 1: Audio Pre-Processing")
        prep_layout = QFormLayout(prep_group)
        self.widgets["source_separation_mode"] = QComboBox()
        self.widgets["source_separation_mode"].addItem(
            "None (Use Original Audio)", "none"
        )
        self.widgets["source_separation_mode"].addItem(
            "Instrumental (No Vocals)", "instrumental"
        )
        self.widgets["source_separation_mode"].addItem("Vocals Only", "vocals")
        self.widgets["source_separation_mode"].setToolTip(
            "Enable audio separation before correlation.\n\n"
            "• None - Use original audio (default)\n"
            "• Instrumental - Remove vocals for cross-language sync (JP↔EN)\n"
            "• Vocals Only - Isolate dialogue for speech-based correlation"
        )

        self.widgets["source_separation_model"] = QComboBox()
        self._populate_model_dropdown()

        self.widgets["source_separation_model_dir"] = _dir_input()
        self.widgets["source_separation_model_dir"].setToolTip(
            "Directory where audio-separator stores models.\n\n"
            "Defaults to the application's audio_separator_models folder.\n"
            "Models are downloaded automatically on first use."
        )

        # Manage Models button
        self.manage_models_btn = QPushButton("Manage Models...")
        self.manage_models_btn.setToolTip(
            "Open the model manager to browse, download, and manage audio separation models."
        )
        self.manage_models_btn.clicked.connect(self._open_model_manager)

        self.widgets["filtering_method"] = QComboBox()
        self.widgets["filtering_method"].addItems(
            ["None", "Low-Pass Filter", "Dialogue Band-Pass Filter"]
        )
        self.widgets["filtering_method"].setToolTip(
            "Apply a filter to the audio before analysis to improve the signal-to-noise ratio.\n'Dialogue Band-Pass' is recommended for most content."
        )
        self.cutoff_container = QWidget()
        cutoff_layout = QFormLayout(self.cutoff_container)
        cutoff_layout.setContentsMargins(0, 0, 0, 0)
        self.widgets["audio_bandlimit_hz"] = QSpinBox()
        self.widgets["audio_bandlimit_hz"].setRange(0, 22000)
        self.widgets["audio_bandlimit_hz"].setSuffix(" Hz")
        self.widgets["audio_bandlimit_hz"].setToolTip(
            "For the Low-Pass Filter, specifies the frequency (in Hz) above which audio data is cut off."
        )
        cutoff_layout.addRow("Low-Pass Cutoff:", self.widgets["audio_bandlimit_hz"])
        prep_layout.addRow("Source Separation:", self.widgets["source_separation_mode"])
        prep_layout.addRow("Separation Model:", self.widgets["source_separation_model"])
        prep_layout.addRow(
            "Model Directory:", self.widgets["source_separation_model_dir"]
        )
        prep_layout.addRow("", self.manage_models_btn)
        prep_layout.addRow("Audio Filtering:", self.widgets["filtering_method"])
        prep_layout.addRow(self.cutoff_container)
        main_layout.addWidget(prep_group)

        core_group = QGroupBox("Step 2: Core Analysis Engine")
        core_layout = QFormLayout(core_group)
        self.widgets["correlation_method"] = QComboBox()
        self.widgets["correlation_method"].addItems(
            [
                "Standard Correlation (SCC)",
                "Phase Correlation (GCC-PHAT)",
                "Onset Detection",
                "GCC-SCOT",
                "Whitened Cross-Correlation",
                "Spectrogram Correlation",
                "VideoDiff",
            ]
        )
        self.widgets["correlation_method"].setToolTip(
            "The correlation algorithm used to find the time offset between audio sources.\n"
            "Applied to each sliding window independently.\n\n"
            "• SCC - Standard cross-correlation. Precise for identical audio sources.\n"
            "• GCC-PHAT - Phase correlation. Most robust to noise and different mixes.\n"
            "• Onset Detection - Matches audio transients (hits, speech onsets). Best for\n"
            "  different releases/mixes where waveforms differ but events align.\n"
            "• GCC-SCOT - Smoothed Coherence Transform. Better when one signal is noisier.\n"
            "• Whitened - GCC with spectral whitening. Similar to PHAT but less aggressive.\n"
            "• Spectrogram - Correlates mel spectrograms. Captures frequency+time structure.\n"
            "• VideoDiff - External tool for video-based sync (not GPU-accelerated)."
        )
        self.widgets["correlation_method_source_separated"] = QComboBox()
        self.widgets["correlation_method_source_separated"].addItems(
            [
                "Standard Correlation (SCC)",
                "Phase Correlation (GCC-PHAT)",
                "Onset Detection",
                "GCC-SCOT",
                "Whitened Cross-Correlation",
                "Spectrogram Correlation",
            ]
        )
        self.widgets["correlation_method_source_separated"].setToolTip(
            "Correlation method used ONLY for sources that undergo source separation.\n\n"
            "This method is automatically applied when:\n"
            "• Source Separation is enabled (Instrumental or Vocals)\n"
            "• AND the comparison matches 'Apply To' setting\n\n"
            "Recommended: Phase Correlation (GCC-PHAT)\n"
            "• More robust to noise and artifacts from stem separation\n"
            "• Works well with Demucs/RoFormer separated audio\n\n"
            "Note: Ignored when Multi-Correlation Comparison is enabled."
        )
        # Dense sliding window settings
        self.widgets["dense_window_s"] = QDoubleSpinBox()
        self.widgets["dense_window_s"].setRange(2.0, 60.0)
        self.widgets["dense_window_s"].setDecimals(1)
        self.widgets["dense_window_s"].setSuffix(" s")
        self.widgets["dense_window_s"].setToolTip(
            "Duration of each analysis window in seconds.\n\n"
            "The full file is analyzed using overlapping windows of this size.\n"
            "Larger windows = more robust per-window results but coarser time resolution.\n"
            "Smaller windows = finer resolution but may be less reliable individually.\n\n"
            "Must be larger than the expected delay between sources.\n"
            "Default: 10s"
        )
        self.widgets["dense_hop_s"] = QDoubleSpinBox()
        self.widgets["dense_hop_s"].setRange(0.5, 30.0)
        self.widgets["dense_hop_s"].setDecimals(1)
        self.widgets["dense_hop_s"].setSuffix(" s")
        self.widgets["dense_hop_s"].setToolTip(
            "Step size between consecutive analysis windows in seconds.\n\n"
            "Controls how densely the file is sampled. A 23-minute file with 2s hop\n"
            "produces ~650 windows. Smaller hops = more windows = finer resolution\n"
            "but slower processing.\n\n"
            "Default: 2s"
        )
        self.widgets["dense_silence_threshold_db"] = QDoubleSpinBox()
        self.widgets["dense_silence_threshold_db"].setRange(-120.0, 0.0)
        self.widgets["dense_silence_threshold_db"].setDecimals(1)
        self.widgets["dense_silence_threshold_db"].setSuffix(" dB")
        self.widgets["dense_silence_threshold_db"].setToolTip(
            "RMS energy threshold below which a window is considered silent and skipped.\n\n"
            "Silent windows produce unreliable correlation results.\n"
            "Lower values = only skip near-total silence.\n"
            "Higher values = also skip quiet passages.\n\n"
            "Default: -60 dB"
        )
        self.widgets["dense_outlier_threshold_ms"] = QDoubleSpinBox()
        self.widgets["dense_outlier_threshold_ms"].setRange(5.0, 500.0)
        self.widgets["dense_outlier_threshold_ms"].setDecimals(1)
        self.widgets["dense_outlier_threshold_ms"].setSuffix(" ms")
        self.widgets["dense_outlier_threshold_ms"].setToolTip(
            "Distance from median delay beyond which a window is flagged as an outlier.\n\n"
            "Used in summary statistics and logging. Does not remove outliers from\n"
            "delay selection — it only reports them.\n\n"
            "Default: 50ms"
        )
        self.widgets["min_match_pct"] = QDoubleSpinBox()
        self.widgets["min_match_pct"].setRange(0.1, 100.0)
        self.widgets["min_match_pct"].setDecimals(1)
        self.widgets["min_match_pct"].setSingleStep(1.0)
        self.widgets["min_match_pct"].setToolTip(
            "Minimum correlation confidence (%) for a window to be accepted.\n\n"
            "Windows below this threshold are rejected and excluded from delay selection.\n"
            "Higher values = stricter, fewer accepted windows.\n"
            "Lower values = more permissive, may include noisy results.\n\n"
            "Default: 10%"
        )
        self.widgets["delay_selection_mode"] = QComboBox()
        self.widgets["delay_selection_mode"].addItems(
            [
                "Mode (Most Common)",
                "Mode (Clustered)",
                "Mode (Early Cluster)",
                "First Stable",
                "Average",
            ]
        )
        self.widgets["delay_selection_mode"].setToolTip(
            "How to choose the final delay from hundreds of window measurements:\n\n"
            "• Mode (Most Common) - Picks the delay that appears most frequently. (Default)\n"
            "  Best for: Files with stable sync throughout.\n\n"
            "• Mode (Clustered) - Most common delay, then averages all windows within ±1ms.\n"
            "  Best for: Source-separated audio where rounding splits votes across\n"
            "  adjacent millisecond values.\n\n"
            "• Mode (Early Cluster) - Finds the EARLIEST delay cluster with enough\n"
            "  presence in the early portion of the file.\n"
            "  Best for: Stepping files where the first segment's delay is the correct one,\n"
            "  even if later segments have a different (more common) delay.\n\n"
            "• First Stable - Picks the DOMINANT delay in the early portion of the file.\n"
            "  Best for: Files where sync changes mid-file. Picks whichever delay\n"
            "  has the most agreement early on (may not be the very first segment).\n\n"
            "• Average - Mean of all delay measurements.\n"
            "  Best for: Files with small jitter around a central value."
        )
        # First Stable sub-settings
        self.widgets["first_stable_early_pct"] = QDoubleSpinBox()
        self.widgets["first_stable_early_pct"].setRange(5.0, 75.0)
        self.widgets["first_stable_early_pct"].setDecimals(1)
        self.widgets["first_stable_early_pct"].setSuffix(" %")
        self.widgets["first_stable_early_pct"].setToolTip(
            "[First Stable mode]\n\n"
            "Percentage of accepted windows to examine as the 'early region'.\n\n"
            "The dominant delay in this region becomes the selected delay,\n"
            "provided it has >=60% agreement. Scales automatically with file length:\n"
            "a 23-min file with 650 windows at 15% examines ~97 windows.\n\n"
            "Lower values = focus on the very start of the file.\n"
            "Higher values = consider a larger early portion.\n\n"
            "Default: 15%"
        )
        # Early Cluster sub-settings
        self.widgets["early_cluster_early_pct"] = QDoubleSpinBox()
        self.widgets["early_cluster_early_pct"].setRange(5.0, 75.0)
        self.widgets["early_cluster_early_pct"].setDecimals(1)
        self.widgets["early_cluster_early_pct"].setSuffix(" %")
        self.widgets["early_cluster_early_pct"].setToolTip(
            "[Early Cluster mode]\n\n"
            "Percentage of accepted windows to examine as the 'early region'.\n\n"
            "All delay clusters present in this region are evaluated.\n"
            "The cluster that appears FIRST in time (with enough presence)\n"
            "is selected — even if it's not the most common.\n\n"
            "Default: 15%"
        )
        self.widgets["early_cluster_min_presence_pct"] = QDoubleSpinBox()
        self.widgets["early_cluster_min_presence_pct"].setRange(1.0, 50.0)
        self.widgets["early_cluster_min_presence_pct"].setDecimals(1)
        self.widgets["early_cluster_min_presence_pct"].setSuffix(" %")
        self.widgets["early_cluster_min_presence_pct"].setToolTip(
            "[Early Cluster mode]\n\n"
            "Minimum presence a delay cluster must have in the early region\n"
            "to be considered a real segment (not noise).\n\n"
            "For example, 10% of 100 early windows = at least 10 windows.\n"
            "Prevents noisy windows from being picked as the 'earliest cluster'.\n\n"
            "Lower values = more sensitive to short first segments.\n"
            "Higher values = require stronger evidence.\n\n"
            "Default: 10%"
        )
        self.widgets["delay_selection_mode_source_separated"] = QComboBox()
        self.widgets["delay_selection_mode_source_separated"].addItems(
            [
                "Mode (Most Common)",
                "Mode (Clustered)",
                "Mode (Early Cluster)",
                "First Stable",
                "Average",
            ]
        )
        self.widgets["delay_selection_mode_source_separated"].setToolTip(
            "Delay selection mode used ONLY for sources that undergo source separation.\n\n"
            "Recommended: Mode (Clustered)\n"
            "• Handles sporadic outliers from stem separation (Demucs, RoFormer)\n"
            "• Clusters delays within ±1ms tolerance\n"
            "• Excludes extreme outliers that poison averages\n\n"
            "Note: Sources without separation use the normal 'Delay Selection Method'."
        )
        core_layout.addRow("Correlation Method:", self.widgets["correlation_method"])
        core_layout.addRow(
            "Correlation (Source-Separated):",
            self.widgets["correlation_method_source_separated"],
        )
        core_layout.addRow("Window Duration:", self.widgets["dense_window_s"])
        core_layout.addRow("Hop (Step) Size:", self.widgets["dense_hop_s"])
        core_layout.addRow(
            "Silence Threshold:", self.widgets["dense_silence_threshold_db"]
        )
        core_layout.addRow(
            "Outlier Threshold:", self.widgets["dense_outlier_threshold_ms"]
        )
        core_layout.addRow(
            "Minimum Match Confidence (%):", self.widgets["min_match_pct"]
        )
        core_layout.addRow(
            "Delay Selection Method:", self.widgets["delay_selection_mode"]
        )
        core_layout.addRow(
            "Delay Selection (Source-Separated):",
            self.widgets["delay_selection_mode_source_separated"],
        )
        core_layout.addRow(
            "  ↳ Early Region %:", self.widgets["first_stable_early_pct"]
        )
        core_layout.addRow(
            "  ↳ Early Region %:", self.widgets["early_cluster_early_pct"]
        )
        core_layout.addRow(
            "  ↳ Min Presence %:", self.widgets["early_cluster_min_presence_pct"]
        )
        main_layout.addWidget(core_group)

        # --- Multi-Correlation Comparison (Analyze Only) ---
        multi_corr_group = QGroupBox("Multi-Correlation Comparison (Analyze Only)")
        multi_corr_layout = QVBoxLayout(multi_corr_group)
        self.widgets["multi_correlation_enabled"] = QCheckBox(
            "Enable Multi-Correlation Comparison"
        )
        self.widgets["multi_correlation_enabled"].setToolTip(
            "When enabled in Analyze Only mode, runs multiple correlation methods on the same\n"
            "audio windows and outputs results for each. Useful for comparing method accuracy.\n\n"
            "• Only affects Analyze Only mode - real jobs use the Correlation Method dropdown\n"
            "• Audio is decoded once, windows extracted once, then each method runs on same data\n"
            "• Results are labeled by method for easy comparison"
        )
        multi_corr_layout.addWidget(self.widgets["multi_correlation_enabled"])

        # Method checkboxes container
        self.multi_corr_methods_container = QWidget()
        methods_layout = QVBoxLayout(self.multi_corr_methods_container)
        methods_layout.setContentsMargins(20, 0, 0, 0)  # Indent
        self.widgets["multi_corr_scc"] = QCheckBox("Standard Correlation (SCC)")
        self.widgets["multi_corr_gcc_phat"] = QCheckBox("Phase Correlation (GCC-PHAT)")
        self.widgets["multi_corr_onset"] = QCheckBox("Onset Detection")
        self.widgets["multi_corr_gcc_scot"] = QCheckBox("GCC-SCOT")
        self.widgets["multi_corr_gcc_whiten"] = QCheckBox("Whitened Cross-Correlation")
        self.widgets["multi_corr_spectrogram"] = QCheckBox("Spectrogram Correlation")
        methods_layout.addWidget(self.widgets["multi_corr_scc"])
        methods_layout.addWidget(self.widgets["multi_corr_gcc_phat"])
        methods_layout.addWidget(self.widgets["multi_corr_onset"])
        methods_layout.addWidget(self.widgets["multi_corr_gcc_scot"])
        methods_layout.addWidget(self.widgets["multi_corr_gcc_whiten"])
        methods_layout.addWidget(self.widgets["multi_corr_spectrogram"])
        multi_corr_layout.addWidget(self.multi_corr_methods_container)
        main_layout.addWidget(multi_corr_group)

        # Connect enable checkbox to show/hide methods
        self.widgets["multi_correlation_enabled"].toggled.connect(
            self._update_multi_corr_visibility
        )
        self._update_multi_corr_visibility(False)

        adv_filter_group = QGroupBox("Step 3: Advanced Filtering & Scan Controls")
        adv_filter_layout = QFormLayout(adv_filter_group)
        self.widgets["scan_start_percentage"] = QDoubleSpinBox()
        self.widgets["scan_start_percentage"].setRange(0.0, 99.0)
        self.widgets["scan_start_percentage"].setSuffix(" %")
        self.widgets["scan_start_percentage"].setToolTip(
            "Where to begin the analysis scan, as a percentage of the file's total duration."
        )
        self.widgets["scan_end_percentage"] = QDoubleSpinBox()
        self.widgets["scan_end_percentage"].setRange(1.0, 100.0)
        self.widgets["scan_end_percentage"].setSuffix(" %")
        self.widgets["scan_end_percentage"].setToolTip(
            "Where to end the analysis scan, as a percentage of the file's total duration."
        )
        self.widgets["filter_bandpass_lowcut_hz"] = QDoubleSpinBox()
        self.widgets["filter_bandpass_lowcut_hz"].setRange(20.0, 10000.0)
        self.widgets["filter_bandpass_lowcut_hz"].setSuffix(" Hz")
        self.widgets["filter_bandpass_lowcut_hz"].setToolTip(
            "The lower frequency for the Dialogue Band-Pass filter."
        )
        self.widgets["filter_bandpass_highcut_hz"] = QDoubleSpinBox()
        self.widgets["filter_bandpass_highcut_hz"].setRange(100.0, 22000.0)
        self.widgets["filter_bandpass_highcut_hz"].setSuffix(" Hz")
        self.widgets["filter_bandpass_highcut_hz"].setToolTip(
            "The upper frequency for the Dialogue Band-Pass filter."
        )
        self.widgets["filter_bandpass_order"] = QSpinBox()
        self.widgets["filter_bandpass_order"].setRange(1, 10)
        self.widgets["filter_bandpass_order"].setToolTip(
            "The steepness of the band-pass filter. Higher values have a sharper cutoff."
        )
        self.widgets["filter_lowpass_taps"] = QSpinBox()
        self.widgets["filter_lowpass_taps"].setRange(11, 501)
        self.widgets["filter_lowpass_taps"].setToolTip(
            "The number of taps (quality) for the Low-Pass filter. Must be an odd number."
        )
        self.widgets["filter_lowpass_taps"].setSingleStep(2)
        adv_filter_layout.addRow(
            "Scan Start Position:", self.widgets["scan_start_percentage"]
        )
        adv_filter_layout.addRow(
            "Scan End Position:", self.widgets["scan_end_percentage"]
        )
        adv_filter_layout.addRow(
            "Band-Pass Low Cutoff:", self.widgets["filter_bandpass_lowcut_hz"]
        )
        adv_filter_layout.addRow(
            "Band-Pass High Cutoff:", self.widgets["filter_bandpass_highcut_hz"]
        )
        adv_filter_layout.addRow(
            "Band-Pass Filter Order:", self.widgets["filter_bandpass_order"]
        )
        adv_filter_layout.addRow(
            "Low-Pass Filter Taps:", self.widgets["filter_lowpass_taps"]
        )
        main_layout.addWidget(adv_filter_group)

        lang_group = QGroupBox("Step 4: Audio Track Selection")
        lang_layout = QFormLayout(lang_group)
        self.widgets["analysis_lang_source1"] = QLineEdit()
        self.widgets["analysis_lang_source1"].setPlaceholderText(
            "e.g., eng (blank = first audio track)"
        )
        self.widgets["analysis_lang_source1"].setToolTip(
            "The 3-letter language code (e.g., eng, jpn) for the audio track to use from Source 1.\nLeave blank to use the first available audio track."
        )
        self.widgets["analysis_lang_others"] = QLineEdit()
        self.widgets["analysis_lang_others"].setPlaceholderText(
            "e.g., jpn (blank = first audio track)"
        )
        self.widgets["analysis_lang_others"].setToolTip(
            "The 3-letter language code for audio tracks in all other sources.\nLeave blank to use their first available audio track."
        )
        lang_layout.addRow(
            "Source 1 (Reference) Language:", self.widgets["analysis_lang_source1"]
        )
        lang_layout.addRow(
            "Other Sources Language:", self.widgets["analysis_lang_others"]
        )
        main_layout.addWidget(lang_group)

        timing_mode_group = QGroupBox("Step 5: Timing Sync Mode")
        timing_mode_layout = QFormLayout(timing_mode_group)
        self.widgets["sync_mode"] = QComboBox()
        self.widgets["sync_mode"].addItems(["positive_only", "allow_negative"])
        self.widgets["sync_mode"].setToolTip(
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
        timing_mode_layout.addRow("Sync Mode:", self.widgets["sync_mode"])
        main_layout.addWidget(timing_mode_group)

        adv_group = QGroupBox("Step 6: Advanced Tweaks & Diagnostics")
        adv_layout = QVBoxLayout(adv_group)
        self.widgets["use_soxr"] = QCheckBox("Use High-Quality Resampling (SoXR)")
        self.widgets["use_soxr"].setToolTip(
            "Use the high-quality SoXR resampler library when decoding audio.\nSlower but more accurate than the default resampler."
        )
        self.widgets["audio_peak_fit"] = QCheckBox(
            "Enable Sub-Sample Peak Fitting (SCC only)"
        )
        self.widgets["audio_peak_fit"].setToolTip(
            "For Standard Correlation (SCC), use parabolic interpolation to find a more precise, sub-sample peak.\nMay improve accuracy slightly."
        )
        self.widgets["log_audio_drift"] = QCheckBox("Log Audio Drift Metric")
        self.widgets["log_audio_drift"].setToolTip(
            "Calculate and log a metric that indicates potential audio drift or speed differences between sources."
        )
        adv_layout.addWidget(self.widgets["use_soxr"])
        adv_layout.addWidget(self.widgets["audio_peak_fit"])
        adv_layout.addWidget(self.widgets["log_audio_drift"])
        main_layout.addWidget(adv_group)

        self.widgets["filtering_method"].currentTextChanged.connect(
            self._update_filter_options
        )
        self.widgets["delay_selection_mode"].currentTextChanged.connect(
            self._update_delay_mode_options
        )
        self._update_filter_options(self.widgets["filtering_method"].currentText())
        self._update_delay_mode_options(
            self.widgets["delay_selection_mode"].currentText()
        )

    def _update_filter_options(self, text: str):
        self.cutoff_container.setVisible(text == "Low-Pass Filter")

    def _update_delay_mode_options(self, text: str):
        is_first_stable = text == "First Stable"
        is_early_cluster = text == "Mode (Early Cluster)"
        self.widgets["first_stable_early_pct"].setVisible(is_first_stable)
        self.widgets["early_cluster_early_pct"].setVisible(is_early_cluster)
        self.widgets["early_cluster_min_presence_pct"].setVisible(is_early_cluster)

    def _update_multi_corr_visibility(self, enabled: bool):
        self.multi_corr_methods_container.setVisible(enabled)

    def _populate_model_dropdown(self):
        """Populate the model dropdown from installed_models.json."""
        self.widgets["source_separation_model"].clear()
        self.widgets["source_separation_model"].addItem(
            "Default (Audio Separator)", "default"
        )

        # Get model directory (may be empty initially)
        model_dir = self._get_model_dir()

        # Load installed models
        installed_models = get_installed_models(model_dir)

        if not installed_models:
            # No models installed - show message
            self.widgets["source_separation_model"].addItem(
                "(No models installed - click Manage Models)", ""
            )
            self.widgets["source_separation_model"].setToolTip(
                "No models are installed yet.\n\n"
                "Click 'Manage Models...' to browse and download models."
            )
        else:
            # Sort installed models by rank (best first)
            sorted_models = sorted(
                installed_models,
                key=lambda m: (
                    m.get("rank", 999),
                    m.get("name", m.get("filename", "")),
                ),
            )

            # Add installed models with rich tooltips
            for model in sorted_models:
                # Friendly display name with quality indicator
                name = model.get("name", model["filename"])
                if model.get("recommended"):
                    name = f"⭐ {name}"

                display_name = name
                quality_tier = model.get("quality_tier")
                if quality_tier and quality_tier in ["S-Tier", "A-Tier"]:
                    display_name = f"{name} ({quality_tier})"

                self.widgets["source_separation_model"].addItem(
                    display_name, model["filename"]
                )

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

                if model.get("sdr_vocals"):
                    tooltip_lines.append(
                        f"<b>Vocal SDR:</b> {model['sdr_vocals']:.1f} dB"
                    )
                if model.get("sdr_instrumental"):
                    tooltip_lines.append(
                        f"<b>Instrumental SDR:</b> {model['sdr_instrumental']:.1f} dB"
                    )

                use_cases = model.get("use_cases", [])
                if use_cases:
                    tooltip_lines.append(f"<b>Best For:</b> {', '.join(use_cases)}")

                if model.get("description"):
                    tooltip_lines.append("")
                    tooltip_lines.append(model["description"])

                # Set tooltip for this item (note: QComboBox doesn't support per-item tooltips perfectly,
                # so we set it on the widget which applies to the current selection)
                # For now, set a general tooltip

            self.widgets["source_separation_model"].setToolTip(
                "Select an installed audio-separator model.\n\n"
                "Select a model and view its details in the status bar.\n"
                "Click 'Manage Models...' to download more models."
            )

    def _get_model_dir(self) -> str:
        """Get the current model directory from the widget."""
        # Check if the widget exists yet (it might not during initialization)
        if "source_separation_model_dir" not in self.widgets:
            return None

        dir_widget = self.widgets["source_separation_model_dir"]
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

        model_dir = self._get_model_dir() or str(
            get_installed_models_json_path().parent
        )

        dialog = ModelManagerDialog(model_dir, parent=self)
        if dialog.exec():
            # Refresh the dropdown after closing the dialog
            self._populate_model_dropdown()


class SteppingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        segment_group = QGroupBox(
            "Stepping Correction (Audio with Mid-File Timing Changes)"
        )
        segment_layout = QFormLayout(segment_group)

        # Enable toggle
        self.widgets["stepping_enabled"] = QCheckBox("Enable stepping correction")
        self.widgets["stepping_enabled"].setToolTip(
            "Detects and corrects audio with stepped timing changes\n"
            "(e.g., reel changes, commercial breaks, scene edits).\n\n"
            "When enabled, the analysis step uses dense sliding-window\n"
            "correlation + DBSCAN clustering to detect delay transitions.\n"
            "The correction step then finds silence zones at each transition\n"
            "and splices the audio to produce a continuous, uniform delay."
        )
        segment_layout.addRow(self.widgets["stepping_enabled"])

        # ===== SECTION 1: DETECTION SETTINGS =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Detection Settings</b>"))
        segment_layout.addRow(
            QLabel(
                "<i>How timing clusters are detected from dense correlation data</i>"
            )
        )

        self.widgets["detection_dbscan_epsilon_ms"] = QDoubleSpinBox()
        self.widgets["detection_dbscan_epsilon_ms"].setRange(5.0, 100.0)
        self.widgets["detection_dbscan_epsilon_ms"].setSuffix(" ms")
        self.widgets["detection_dbscan_epsilon_ms"].setToolTip(
            "DBSCAN clustering tolerance - maximum delay difference\n"
            "for correlation windows to be grouped into the same cluster.\n"
            "Smaller = stricter grouping (more distinct clusters)\n"
            "Larger = looser grouping (fewer, larger clusters)\n"
            "Default: 20ms"
        )

        self.widgets["detection_dbscan_min_samples_pct"] = QDoubleSpinBox()
        self.widgets["detection_dbscan_min_samples_pct"].setRange(0.5, 10.0)
        self.widgets["detection_dbscan_min_samples_pct"].setDecimals(1)
        self.widgets["detection_dbscan_min_samples_pct"].setSuffix("%")
        self.widgets["detection_dbscan_min_samples_pct"].setToolTip(
            "DBSCAN minimum samples — percentage of correlation windows\n"
            "needed to form a core cluster.\n"
            "Scales with file length (more windows = higher absolute threshold).\n"
            "Higher = requires more evidence before creating a cluster\n"
            "Lower = more sensitive to brief timing changes\n"
            "Example: 1.5% of 600 windows = cluster needs at least 9 windows\n"
            "Default: 1.5%"
        )

        self.widgets["stepping_triage_std_dev_ms"] = QSpinBox()
        self.widgets["stepping_triage_std_dev_ms"].setRange(10, 200)
        self.widgets["stepping_triage_std_dev_ms"].setSuffix(" ms")
        self.widgets["stepping_triage_std_dev_ms"].setToolTip(
            "Triage threshold - minimum delay variation (std dev) to\n"
            "trigger stepping correction. Prevents unnecessary processing\n"
            "on files with stable, uniform delays.\n"
            "Default: 50ms"
        )

        # Drift detection thresholds
        self.widgets["drift_detection_r2_threshold"] = QDoubleSpinBox()
        self.widgets["drift_detection_r2_threshold"].setRange(0.5, 1.0)
        self.widgets["drift_detection_r2_threshold"].setDecimals(2)
        self.widgets["drift_detection_r2_threshold"].setToolTip(
            "R-squared threshold for lossy codecs - how linear the\n"
            "delay pattern must be to classify as drift vs stepping.\n"
            "Higher = stricter (requires very linear drift pattern)\n"
            "Default: 0.90"
        )

        self.widgets["drift_detection_r2_threshold_lossless"] = QDoubleSpinBox()
        self.widgets["drift_detection_r2_threshold_lossless"].setRange(0.5, 1.0)
        self.widgets["drift_detection_r2_threshold_lossless"].setDecimals(2)
        self.widgets["drift_detection_r2_threshold_lossless"].setToolTip(
            "R-squared threshold for lossless codecs.\nDefault: 0.95"
        )

        self.widgets["drift_detection_slope_threshold_lossy"] = QDoubleSpinBox()
        self.widgets["drift_detection_slope_threshold_lossy"].setRange(0.1, 5.0)
        self.widgets["drift_detection_slope_threshold_lossy"].setSuffix(" ms/s")
        self.widgets["drift_detection_slope_threshold_lossy"].setToolTip(
            "Minimum drift rate for lossy codecs to trigger\n"
            "drift correction instead of stepping.\n"
            "Default: 0.7 ms/s"
        )

        self.widgets["drift_detection_slope_threshold_lossless"] = QDoubleSpinBox()
        self.widgets["drift_detection_slope_threshold_lossless"].setRange(0.1, 5.0)
        self.widgets["drift_detection_slope_threshold_lossless"].setSuffix(" ms/s")
        self.widgets["drift_detection_slope_threshold_lossless"].setToolTip(
            "Minimum drift rate for lossless codecs.\nDefault: 0.2 ms/s"
        )

        segment_layout.addRow(
            "DBSCAN Epsilon:", self.widgets["detection_dbscan_epsilon_ms"]
        )
        segment_layout.addRow(
            "DBSCAN Min Samples:", self.widgets["detection_dbscan_min_samples_pct"]
        )
        segment_layout.addRow(
            "Triage Threshold:", self.widgets["stepping_triage_std_dev_ms"]
        )
        segment_layout.addRow(
            "Lossy R-squared:", self.widgets["drift_detection_r2_threshold"]
        )
        segment_layout.addRow(
            "Lossless R-squared:",
            self.widgets["drift_detection_r2_threshold_lossless"],
        )
        segment_layout.addRow(
            "Lossy Slope Threshold:",
            self.widgets["drift_detection_slope_threshold_lossy"],
        )
        segment_layout.addRow(
            "Lossless Slope Threshold:",
            self.widgets["drift_detection_slope_threshold_lossless"],
        )

        # ===== SECTION 2: QUALITY VALIDATION =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Quality Validation</b>"))
        segment_layout.addRow(
            QLabel("<i>Which detected timing clusters are considered valid</i>")
        )

        self.widgets["stepping_correction_mode"] = QComboBox()
        self.widgets["stepping_correction_mode"].addItems(
            ["full", "filtered", "strict", "disabled"]
        )
        self.widgets["stepping_correction_mode"].setToolTip(
            "How to handle detected timing clusters:\n\n"
            "full (Default): All-or-nothing - uses ALL clusters,\n"
            "  rejects entire correction if ANY fail validation.\n\n"
            "filtered: Smart filtering - filters out unreliable clusters,\n"
            "  uses only stable ones. See 'Filtered Fallback' below.\n\n"
            "strict: Extra strict all-or-nothing.\n\n"
            "disabled: Skip stepping correction entirely."
        )

        self.widgets["stepping_quality_mode"] = QComboBox()
        self.widgets["stepping_quality_mode"].addItems(
            ["strict", "normal", "lenient", "custom"]
        )
        self.widgets["stepping_quality_mode"].setToolTip(
            "What makes a cluster 'valid' - clusters must pass ALL checks:\n"
            "  1. Minimum % of total correlation windows\n"
            "  2. Minimum duration in seconds\n"
            "  3. Minimum match quality\n\n"
            "strict: 10%+, 30s+, 90%+ match (Blu-ray quality)\n"
            "normal: 5%+, 20s+, 85%+ match (Default)\n"
            "lenient: 3%+, 10s+, 75%+ match (Edge cases)\n"
            "custom: Configure thresholds manually below"
        )

        self.widgets["stepping_filtered_fallback"] = QComboBox()
        self.widgets["stepping_filtered_fallback"].addItems(
            ["nearest", "interpolate", "uniform", "skip", "reject"]
        )
        self.widgets["stepping_filtered_fallback"].setToolTip(
            "How to handle invalid cluster regions\n"
            "(Only used when Correction Mode = 'filtered'):\n\n"
            "nearest: Use closest valid cluster's delay (Recommended)\n"
            "interpolate: Smooth transition between valid clusters\n"
            "uniform: Use median delay of all accepted windows\n"
            "skip: Keep original timing (may cause jumps)\n"
            "reject: Reject entire correction if any cluster filtered"
        )

        segment_layout.addRow(
            "Correction Mode:", self.widgets["stepping_correction_mode"]
        )
        segment_layout.addRow("Quality Mode:", self.widgets["stepping_quality_mode"])
        segment_layout.addRow(
            "Filtered Fallback:", self.widgets["stepping_filtered_fallback"]
        )

        # Custom quality thresholds
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(
            QLabel("<i>Custom Quality Thresholds (for 'custom' mode):</i>")
        )

        self.widgets["stepping_min_cluster_percentage"] = QDoubleSpinBox()
        self.widgets["stepping_min_cluster_percentage"].setRange(1.0, 50.0)
        self.widgets["stepping_min_cluster_percentage"].setSuffix(" %")
        self.widgets["stepping_min_cluster_percentage"].setDecimals(1)
        self.widgets["stepping_min_cluster_percentage"].setToolTip(
            "Minimum percentage of total correlation windows a cluster\n"
            "must represent to be considered valid.\n\n"
            "Example: 5% of 500 windows = cluster needs at least 25 windows.\n"
            "Scales automatically with file length and window settings.\n"
            "Default: 5%"
        )

        self.widgets["stepping_min_cluster_duration_s"] = QDoubleSpinBox()
        self.widgets["stepping_min_cluster_duration_s"].setRange(0.0, 120.0)
        self.widgets["stepping_min_cluster_duration_s"].setSuffix(" s")
        self.widgets["stepping_min_cluster_duration_s"].setDecimals(1)
        self.widgets["stepping_min_cluster_duration_s"].setToolTip(
            "Minimum duration in seconds for a cluster to be valid."
        )

        self.widgets["stepping_min_match_quality_pct"] = QDoubleSpinBox()
        self.widgets["stepping_min_match_quality_pct"].setRange(50.0, 100.0)
        self.widgets["stepping_min_match_quality_pct"].setSuffix(" %")
        self.widgets["stepping_min_match_quality_pct"].setDecimals(1)
        self.widgets["stepping_min_match_quality_pct"].setToolTip(
            "Minimum average correlation match quality %."
        )

        self.widgets["stepping_min_total_clusters"] = QSpinBox()
        self.widgets["stepping_min_total_clusters"].setRange(1, 10)
        self.widgets["stepping_min_total_clusters"].setToolTip(
            "Minimum total number of valid clusters required."
        )

        segment_layout.addRow(
            "  Min Cluster Size:", self.widgets["stepping_min_cluster_percentage"]
        )
        segment_layout.addRow(
            "  Min Cluster Duration:", self.widgets["stepping_min_cluster_duration_s"]
        )
        segment_layout.addRow(
            "  Min Match Quality:", self.widgets["stepping_min_match_quality_pct"]
        )
        segment_layout.addRow(
            "  Min Total Clusters:", self.widgets["stepping_min_total_clusters"]
        )

        # ===== SECTION 3: BOUNDARY REFINEMENT =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Boundary Refinement</b>"))
        segment_layout.addRow(
            QLabel("<i>How splice points are placed at each transition zone</i>")
        )

        segment_layout.addRow(
            QLabel(
                "<i>The pipeline decodes Source 2 to PCM in memory, then for each\n"
                "transition uses combined RMS + VAD to find the best silence zone\n"
                "and centers the splice point within it.</i>"
            )
        )

        # VAD settings
        self.widgets["stepping_vad_enabled"] = QCheckBox(
            "Enable speech protection (VAD)"
        )
        self.widgets["stepping_vad_enabled"].setToolTip(
            "Uses WebRTC Voice Activity Detection to find non-speech gaps.\n"
            "Combined with RMS silence detection - the intersection of\n"
            "both (quiet AND no speech) produces the safest splice points.\n"
            "Requires: pip install webrtcvad-wheels\n"
            "Default: Enabled"
        )

        self.widgets["stepping_vad_aggressiveness"] = QSpinBox()
        self.widgets["stepping_vad_aggressiveness"].setRange(0, 3)
        self.widgets["stepping_vad_aggressiveness"].setToolTip(
            "VAD aggressiveness level (0-3):\n"
            "0 = Least aggressive (classifies more audio as speech)\n"
            "1 = Moderate\n"
            "2 = Aggressive (recommended)\n"
            "3 = Very aggressive (may miss some speech)\n"
            "Default: 2"
        )

        # Silence detection settings
        self.widgets["stepping_silence_search_window_s"] = QDoubleSpinBox()
        self.widgets["stepping_silence_search_window_s"].setRange(0.5, 15.0)
        self.widgets["stepping_silence_search_window_s"].setSuffix(" s")
        self.widgets["stepping_silence_search_window_s"].setDecimals(1)
        self.widgets["stepping_silence_search_window_s"].setToolTip(
            "Search radius around each transition midpoint (in seconds).\n"
            "Larger = more flexibility finding silence, but splice moves further\n"
            "Smaller = keeps splice closer to the detected transition\n"
            "Default: 5.0s"
        )

        self.widgets["stepping_silence_threshold_db"] = QDoubleSpinBox()
        self.widgets["stepping_silence_threshold_db"].setRange(-60.0, -20.0)
        self.widgets["stepping_silence_threshold_db"].setSuffix(" dB")
        self.widgets["stepping_silence_threshold_db"].setDecimals(1)
        self.widgets["stepping_silence_threshold_db"].setToolTip(
            "RMS energy threshold to consider audio as 'silence'.\n"
            "More negative = stricter (quieter required)\n"
            "Less negative = more lenient\n"
            "Default: -40.0 dB"
        )

        self.widgets["stepping_silence_min_duration_ms"] = QDoubleSpinBox()
        self.widgets["stepping_silence_min_duration_ms"].setRange(50.0, 1000.0)
        self.widgets["stepping_silence_min_duration_ms"].setSuffix(" ms")
        self.widgets["stepping_silence_min_duration_ms"].setDecimals(0)
        self.widgets["stepping_silence_min_duration_ms"].setToolTip(
            "Minimum silence duration for a zone to be a splice candidate.\n"
            "Prevents splicing in brief pauses between words.\n"
            "Default: 100ms"
        )

        # Scoring weights
        self.widgets["stepping_fusion_weight_silence"] = QSpinBox()
        self.widgets["stepping_fusion_weight_silence"].setRange(0, 20)
        self.widgets["stepping_fusion_weight_silence"].setToolTip(
            "Weight for silence depth when scoring splice candidates.\n"
            "Higher = prefer quieter zones more strongly.\n"
            "Default: 10"
        )

        self.widgets["stepping_fusion_weight_duration"] = QSpinBox()
        self.widgets["stepping_fusion_weight_duration"].setRange(0, 20)
        self.widgets["stepping_fusion_weight_duration"].setToolTip(
            "Weight for zone duration when scoring splice candidates.\n"
            "Higher = prefer longer silence zones.\n"
            "Default: 2"
        )

        segment_layout.addRow(self.widgets["stepping_vad_enabled"])
        segment_layout.addRow(
            "  VAD Aggressiveness:", self.widgets["stepping_vad_aggressiveness"]
        )
        segment_layout.addRow(
            "Search Window:", self.widgets["stepping_silence_search_window_s"]
        )
        segment_layout.addRow(
            "Silence Threshold:", self.widgets["stepping_silence_threshold_db"]
        )
        segment_layout.addRow(
            "Min Silence Duration:",
            self.widgets["stepping_silence_min_duration_ms"],
        )
        segment_layout.addRow(
            "Silence Weight:", self.widgets["stepping_fusion_weight_silence"]
        )
        segment_layout.addRow(
            "Duration Weight:", self.widgets["stepping_fusion_weight_duration"]
        )

        # Transient detection settings
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<i>Transient Detection (click prevention):</i>"))

        self.widgets["stepping_transient_detection_enabled"] = QCheckBox(
            "Avoid transients when picking splice points"
        )
        self.widgets["stepping_transient_detection_enabled"].setToolTip(
            "Scans the search region for sudden amplitude jumps (drum hits,\n"
            "impacts, consonant onsets) and penalises silence zones that\n"
            "contain or border a transient. Splicing on a transient causes\n"
            "audible clicks even inside a 'quiet' zone.\n"
            "Default: Enabled"
        )

        self.widgets["stepping_transient_threshold"] = QDoubleSpinBox()
        self.widgets["stepping_transient_threshold"].setRange(3.0, 20.0)
        self.widgets["stepping_transient_threshold"].setSuffix(" dB")
        self.widgets["stepping_transient_threshold"].setDecimals(1)
        self.widgets["stepping_transient_threshold"].setToolTip(
            "Minimum frame-to-frame RMS jump (in dB) to flag as a transient.\n"
            "Lower = more sensitive (catches more transients)\n"
            "Higher = less sensitive (only catches large impacts)\n"
            "Default: 8.0 dB"
        )

        segment_layout.addRow(self.widgets["stepping_transient_detection_enabled"])
        segment_layout.addRow(
            "  Transient Threshold:", self.widgets["stepping_transient_threshold"]
        )

        # Video-aware boundary snapping
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<i>Video Keyframe Snapping (optional):</i>"))

        self.widgets["stepping_snap_to_video_frames"] = QCheckBox(
            "Snap boundaries to video keyframes"
        )
        self.widgets["stepping_snap_to_video_frames"].setToolTip(
            "After finding the best silence zone, optionally snap\n"
            "the splice point to the nearest video keyframe.\n"
            "Useful when stepping is caused by scene changes.\n"
            "Default: Disabled"
        )

        self.widgets["stepping_video_snap_max_offset_s"] = QDoubleSpinBox()
        self.widgets["stepping_video_snap_max_offset_s"].setRange(0.1, 10.0)
        self.widgets["stepping_video_snap_max_offset_s"].setSuffix(" s")
        self.widgets["stepping_video_snap_max_offset_s"].setDecimals(1)
        self.widgets["stepping_video_snap_max_offset_s"].setToolTip(
            "Maximum distance to snap to a keyframe.\n"
            "If no keyframe is within this range, the audio-based\n"
            "splice point is kept.\n"
            "Default: 2.0s"
        )

        segment_layout.addRow(self.widgets["stepping_snap_to_video_frames"])
        segment_layout.addRow(
            "  Max Snap Distance:", self.widgets["stepping_video_snap_max_offset_s"]
        )

        # ===== SECTION 4: QUALITY ASSURANCE =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Quality Assurance</b>"))
        segment_layout.addRow(
            QLabel(
                "<i>Post-correction verification via fresh dense correlation</i>"
            )
        )

        self.widgets["stepping_qa_threshold"] = QDoubleSpinBox()
        self.widgets["stepping_qa_threshold"].setRange(50.0, 99.0)
        self.widgets["stepping_qa_threshold"].setSuffix("%")
        self.widgets["stepping_qa_threshold"].setToolTip(
            "Corrected audio must correlate above this % with reference.\n"
            "Dense correlation runs on the full corrected file using\n"
            "the same window/hop settings as the main analysis.\n"
            "Default: 85%"
        )

        self.widgets["stepping_qa_min_accepted_pct"] = QDoubleSpinBox()
        self.widgets["stepping_qa_min_accepted_pct"].setRange(50.0, 100.0)
        self.widgets["stepping_qa_min_accepted_pct"].setSuffix("%")
        self.widgets["stepping_qa_min_accepted_pct"].setDecimals(1)
        self.widgets["stepping_qa_min_accepted_pct"].setToolTip(
            "Minimum percentage of dense correlation windows that must\n"
            "pass for the correction to be accepted. QA runs the same\n"
            "dense sliding-window correlation as the main analysis.\n"
            "90% means 90% of all scanned windows must agree.\n"
            "Default: 90%"
        )

        segment_layout.addRow("QA Threshold:", self.widgets["stepping_qa_threshold"])
        segment_layout.addRow(
            "QA Min Accepted:", self.widgets["stepping_qa_min_accepted_pct"]
        )

        # ===== SECTION 5: AUDIO PROCESSING =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Audio Processing</b>"))
        segment_layout.addRow(
            QLabel("<i>Resampling engine for per-segment drift correction</i>")
        )

        self.widgets["segment_resample_engine"] = QComboBox()
        self.widgets["segment_resample_engine"].addItems(
            ["aresample", "atempo", "rubberband"]
        )
        self.widgets["segment_resample_engine"].setToolTip(
            "Audio resampling engine (shared with linear drift correction):\n"
            "aresample: High quality, no pitch correction (Recommended)\n"
            "atempo: Fast, standard quality\n"
            "rubberband: Slowest, highest quality, preserves pitch"
        )
        segment_layout.addRow(
            "Resample Engine:", self.widgets["segment_resample_engine"]
        )

        # Rubberband settings
        self.rb_group = QGroupBox("Rubberband Settings")
        rb_layout = QFormLayout(self.rb_group)

        self.widgets["segment_rb_pitch_correct"] = QCheckBox("Enable Pitch Correction")
        self.widgets["segment_rb_pitch_correct"].setToolTip(
            "Preserves original audio pitch (slower).\n"
            "When disabled, pitch changes with speed."
        )

        self.widgets["segment_rb_transients"] = QComboBox()
        self.widgets["segment_rb_transients"].addItems(["crisp", "mixed", "smooth"])
        self.widgets["segment_rb_transients"].setToolTip(
            "How to handle transients (sharp sounds like consonants).\n"
            "'crisp' is usually best for dialogue."
        )

        self.widgets["segment_rb_smoother"] = QCheckBox(
            "Enable Phase Smoothing (Higher Quality)"
        )
        self.widgets["segment_rb_smoother"].setToolTip(
            "Smooths phase shifts between processing windows."
        )

        self.widgets["segment_rb_pitchq"] = QCheckBox(
            "Enable High-Quality Pitch Algorithm"
        )
        self.widgets["segment_rb_pitchq"].setToolTip(
            "Uses higher-quality, more CPU-intensive pitch processing."
        )

        rb_layout.addRow(self.widgets["segment_rb_pitch_correct"])
        rb_layout.addRow("Transient Handling:", self.widgets["segment_rb_transients"])
        rb_layout.addRow(self.widgets["segment_rb_smoother"])
        rb_layout.addRow(self.widgets["segment_rb_pitchq"])
        segment_layout.addRow(self.rb_group)

        # ===== SECTION 6: TRACK NAMING =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Track Naming</b>"))

        self.widgets["stepping_corrected_track_label"] = QLineEdit()
        self.widgets["stepping_corrected_track_label"].setPlaceholderText(
            "Leave empty for no label"
        )
        self.widgets["stepping_corrected_track_label"].setToolTip(
            "Label appended to corrected audio track name in the output MKV.\n"
            "e.g. 'Surround 5.1' becomes 'Surround 5.1 (Stepping Corrected)'\n"
            "Default: Empty (no label)"
        )

        self.widgets["stepping_preserved_track_label"] = QLineEdit()
        self.widgets["stepping_preserved_track_label"].setPlaceholderText(
            "Leave empty for no label"
        )
        self.widgets["stepping_preserved_track_label"].setToolTip(
            "Label appended to the preserved original track name.\n"
            "e.g. 'Surround 5.1' becomes 'Surround 5.1 (Original)'\n"
            "Default: Empty (no label)"
        )

        segment_layout.addRow(
            "Corrected Track Label:", self.widgets["stepping_corrected_track_label"]
        )
        segment_layout.addRow(
            "Preserved Track Label:", self.widgets["stepping_preserved_track_label"]
        )

        # ===== SECTION 7: SUBTITLE ADJUSTMENT =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Subtitle Adjustment</b>"))

        self.widgets["stepping_adjust_subtitles"] = QCheckBox(
            "Adjust subtitle timestamps for stepped sources"
        )
        self.widgets["stepping_adjust_subtitles"].setToolTip(
            "Adjusts subtitle timestamps to match audio corrections.\n"
            "Keeps subtitles in sync with the corrected audio."
        )

        self.widgets["stepping_adjust_subtitles_no_audio"] = QCheckBox(
            "Apply stepping to subtitles when no audio is merged"
        )
        self.widgets["stepping_adjust_subtitles_no_audio"].setToolTip(
            "Applies stepping correction to subtitles even when no\n"
            "audio from that source is in the merge layout.\n"
            "Uses the EDL from correlation analysis."
        )

        self.widgets["stepping_boundary_mode"] = QComboBox()
        self.widgets["stepping_boundary_mode"].addItems(
            ["start", "majority", "midpoint"]
        )
        self.widgets["stepping_boundary_mode"].setToolTip(
            "How to handle subtitles spanning stepping boundaries:\n\n"
            "start: Use subtitle's start time (Default, good for dialogue)\n"
            "majority: Use region with most overlap (good for songs)\n"
            "midpoint: Use (start + end) / 2"
        )

        segment_layout.addRow(self.widgets["stepping_adjust_subtitles"])
        segment_layout.addRow(self.widgets["stepping_adjust_subtitles_no_audio"])
        segment_layout.addRow("Boundary Mode:", self.widgets["stepping_boundary_mode"])

        # ===== SECTION 8: DIAGNOSTICS =====
        segment_layout.addRow(QLabel(""))
        segment_layout.addRow(QLabel("<b>Diagnostics</b>"))

        self.widgets["stepping_diagnostics_verbose"] = QCheckBox(
            "Enable detailed cluster diagnostics"
        )
        self.widgets["stepping_diagnostics_verbose"].setToolTip(
            "Logs cluster composition, transition patterns, and likely causes.\n"
            "Useful for understanding stepping origins."
        )

        segment_layout.addRow(self.widgets["stepping_diagnostics_verbose"])

        # Connect signal handlers
        self.widgets["segment_resample_engine"].currentTextChanged.connect(
            self._update_rb_group_visibility
        )
        self._update_rb_group_visibility(
            self.widgets["segment_resample_engine"].currentText()
        )

        main_layout.addWidget(segment_group)

    def _update_rb_group_visibility(self, text: str):
        self.rb_group.setVisible(text == "rubberband")


class SubtitleSyncTab(QWidget):
    """Subtitle sync settings tab.

    Video-verified mode uses a single sliding-window matcher with six
    pluggable backends (ISC, SSCD mixup, SSCD large, pHash, dHash, SSIM).
    The backend dropdown selects the primary; an optional cross-check
    dropdown runs a second backend in parallel for disagreement warnings.

    Widget keys map 1:1 to ``AppSettings`` field names via
    ``options_dialog/logic.py``, so adding a new field is a two-line
    change here + one field in ``vsg_core/models/settings.py``.
    """

    # Backend dropdown entries — (value, display label).
    # Must match vsg_core/models/types.py::VideoVerifiedBackendStr exactly.
    _BACKEND_CHOICES: tuple[tuple[str, str], ...] = (
        ("isc", "ISC ft_v107 (Neural, 52M params, 512² input)"),
        ("sscd_mixup", "SSCD disc_mixup (Neural, 25M, faster)"),
        ("sscd_large", "SSCD disc_large (Neural, 44M)"),
        ("phash", "pHash GPU (Classical, sharpest)"),
        ("dhash", "dHash GPU (Classical, fast)"),
        ("ssim", "SSIM GPU (Classical, pairwise)"),
    )

    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # ===== SYNC MODE SELECTION =====
        mode_group = QGroupBox("Sync Mode")
        mode_layout = QFormLayout(mode_group)

        self.widgets["subtitle_sync_mode"] = QComboBox()
        self.widgets["subtitle_sync_mode"].addItems(
            [
                "time-based",
                "video-verified",
            ]
        )
        self.widgets["subtitle_sync_mode"].setToolTip(
            "Subtitle synchronization method:\n\n"
            "• time-based: Simple delay via mkvmerge --sync (fastest)\n"
            "• video-verified: Audio correlation verified against video frames\n"
            "  (catches cases where audio is offset but subs should be 0ms)"
        )
        mode_layout.addRow("Mode:", self.widgets["subtitle_sync_mode"])
        main_layout.addWidget(mode_group)

        # ===== SHARED OUTPUT SETTINGS =====
        output_group = QGroupBox("Output Settings")
        output_layout = QFormLayout(output_group)

        self.widgets["subtitle_rounding"] = QComboBox()
        self.widgets["subtitle_rounding"].addItems(["floor", "round", "ceil"])
        self.widgets["subtitle_rounding"].setToolTip(
            "Final rounding mode for subtitle timestamps:\n\n"
            "Controls how timestamps are rounded to ASS centisecond precision (10ms).\n\n"
            "• floor (Default): Round down - subtitles appear slightly earlier\n"
            "• round: Nearest - statistically balanced\n"
            "• ceil: Round up - subtitles appear slightly later"
        )
        output_layout.addRow("Rounding:", self.widgets["subtitle_rounding"])
        main_layout.addWidget(output_group)

        # ===== TIME-BASED SETTINGS =====
        time_group = QGroupBox("Time-Based Settings")
        time_layout = QFormLayout(time_group)

        self.widgets["time_based_use_raw_values"] = QCheckBox(
            "Apply delay directly to subtitle file"
        )
        self.widgets["time_based_use_raw_values"].setToolTip(
            "How to apply the delay:\n\n"
            "• Unchecked (Default): Use mkvmerge --sync (delay in container)\n"
            "• Checked: Modify subtitle timestamps directly in the file"
        )
        time_layout.addRow("", self.widgets["time_based_use_raw_values"])
        main_layout.addWidget(time_group)

        # ===== VIDEO-VERIFIED SETTINGS =====
        vv_group = QGroupBox("Video-Verified Settings (Sliding-Window Matcher)")
        vv_layout = QFormLayout(vv_group)

        # --- Backend selection ---

        self.widgets["video_verified_backend"] = QComboBox()
        for value, label in self._BACKEND_CHOICES:
            self.widgets["video_verified_backend"].addItem(label, value)
        self.widgets["video_verified_backend"].setToolTip(
            "Primary feature-extraction backend for sliding-window matching.\n\n"
            "Neural backends (weights required, downloaded via setup_gui.py):\n"
            "  • ISC ft_v107       — original ISC competition winner, 52M params\n"
            "  • SSCD disc_mixup   — Meta's ISC successor, 25M params, faster\n"
            "  • SSCD disc_large   — larger SSCD variant, 44M params\n\n"
            "Classical GPU backends (no weights, torch-only):\n"
            "  • pHash  — perceptual hash via GPU DCT, sharpest peaks\n"
            "  • dHash  — difference hash, fastest\n"
            "  • SSIM   — Structural Similarity, pairwise scoring\n\n"
            "All backends share the same sliding protocol — pick based on\n"
            "speed/accuracy trade-off. ISC is the default and matches the\n"
            "pre-refactor behavior."
        )
        vv_layout.addRow("Backend:", self.widgets["video_verified_backend"])

        self.widgets["video_verified_cross_check_backend"] = QComboBox()
        self.widgets["video_verified_cross_check_backend"].addItem(
            "None (single pass)", "none"
        )
        for value, label in self._BACKEND_CHOICES:
            self.widgets["video_verified_cross_check_backend"].addItem(label, value)
        self.widgets["video_verified_cross_check_backend"].setToolTip(
            "Optional cross-check backend — runs a second sliding pass with\n"
            "a different backend after the primary finishes. The primary\n"
            "result always wins; the cross-check only surfaces a warning in\n"
            "the final audit when the two backends disagree by more than the\n"
            "tolerance below.\n\n"
            "Useful for paranoid runs on unusual content. Roughly doubles\n"
            "the preprocessing time when enabled (less if one backend is a\n"
            "fast classical one). Default: None."
        )
        vv_layout.addRow(
            "Cross-check Backend:",
            self.widgets["video_verified_cross_check_backend"],
        )

        self.widgets["video_verified_cross_check_tolerance_frames"] = QSpinBox()
        self.widgets["video_verified_cross_check_tolerance_frames"].setRange(0, 30)
        self.widgets["video_verified_cross_check_tolerance_frames"].setValue(0)
        self.widgets["video_verified_cross_check_tolerance_frames"].setToolTip(
            "Cross-check tolerance — how many frames of disagreement between\n"
            "primary and secondary backends to accept before flagging as a\n"
            "warning in the final audit.\n\n"
            "• 0 (Default): Strict — any disagreement flags a warning\n"
            "• 1: Allow ±1 frame (~42 ms at 24 fps — tolerates single-frame\n"
            "     noise when backends pick adjacent frames in static scenes)\n"
            "• 2+: More forgiving\n\n"
            "Only active when Cross-check Backend is not 'None'."
        )
        vv_layout.addRow(
            "Cross-check Tolerance:",
            self.widgets["video_verified_cross_check_tolerance_frames"],
        )

        # --- Backend-specific settings (conditionally enabled) ---

        self.widgets["video_verified_hash_size"] = QComboBox()
        for bits in (8, 16, 32, 64):
            self.widgets["video_verified_hash_size"].addItem(
                f"{bits} ({bits * bits}-bit)", bits
            )
        self.widgets["video_verified_hash_size"].setCurrentIndex(2)  # default 32
        self.widgets["video_verified_hash_size"].setToolTip(
            "Hash size for pHash and dHash backends — controls the size of\n"
            "the binary descriptor per frame. Larger = more discriminating,\n"
            "slightly slower.\n\n"
            "• 8  (64-bit):   Tiny descriptor, classic pHash default\n"
            "• 16 (256-bit):  Good discrimination, fast\n"
            "• 32 (1024-bit): Default — sharpest peaks in our test runs\n"
            "• 64 (4096-bit): Diminishing returns, more GPU work\n\n"
            "Only active when Backend (or Cross-check) is pHash or dHash."
        )
        vv_layout.addRow(
            "Hash Size (pHash/dHash):",
            self.widgets["video_verified_hash_size"],
        )

        self.widgets["video_verified_ssim_input_size"] = QComboBox()
        for size in (128, 256, 384, 512):
            self.widgets["video_verified_ssim_input_size"].addItem(
                f"{size}×{size}", size
            )
        self.widgets["video_verified_ssim_input_size"].setCurrentIndex(1)  # default 256
        self.widgets["video_verified_ssim_input_size"].setToolTip(
            "Input resize size for the SSIM backend — frames are downsampled\n"
            "to size×size before pairwise SSIM scoring. Larger = sharper\n"
            "peaks but more VRAM and slower per position.\n\n"
            "• 128×128: Fastest, lowest VRAM (~16 MB per position)\n"
            "• 256×256: Default — good balance\n"
            "• 384×384: Sharper peaks (~140 MB per position)\n"
            "• 512×512: Sharpest (~250 MB per position, 8 GB VRAM minimum)\n\n"
            "Only active when Backend (or Cross-check) is SSIM."
        )
        vv_layout.addRow(
            "SSIM Input Size:",
            self.widgets["video_verified_ssim_input_size"],
        )

        # --- Sliding geometry (shared across all backends) ---

        self.widgets["video_verified_window_seconds"] = QSpinBox()
        self.widgets["video_verified_window_seconds"].setRange(5, 30)
        self.widgets["video_verified_window_seconds"].setValue(10)
        self.widgets["video_verified_window_seconds"].setToolTip(
            "Duration of the source frame sequence extracted at each position\n"
            "(in seconds). Longer windows capture more frames for matching\n"
            "but take longer.\n\n"
            "• 5: Fast, fewer frames per position\n"
            "• 10 (Default): Good balance of accuracy and speed\n"
            "• 20+: Very thorough, slower extraction"
        )
        vv_layout.addRow(
            "Window Duration (s):",
            self.widgets["video_verified_window_seconds"],
        )

        self.widgets["video_verified_slide_range_seconds"] = QSpinBox()
        self.widgets["video_verified_slide_range_seconds"].setRange(1, 15)
        self.widgets["video_verified_slide_range_seconds"].setValue(5)
        self.widgets["video_verified_slide_range_seconds"].setToolTip(
            "How far to slide the target window around the expected position\n"
            "(in seconds). The target window slides ±N seconds around the\n"
            "audio correlation offset to find the best visual match.\n\n"
            "• 2: Tight search (audio correlation is very close)\n"
            "• 5 (Default): Standard range\n"
            "• 10+: Wide search (audio correlation may be far off)"
        )
        vv_layout.addRow(
            "Slide Range (s):",
            self.widgets["video_verified_slide_range_seconds"],
        )

        self.widgets["video_verified_num_positions"] = QSpinBox()
        self.widgets["video_verified_num_positions"].setRange(3, 15)
        self.widgets["video_verified_num_positions"].setValue(9)
        self.widgets["video_verified_num_positions"].setToolTip(
            "Number of checkpoint positions across the video:\n\n"
            "Positions are spaced evenly from 10% to 90% of video duration.\n"
            "Each position runs an independent sliding search, then the\n"
            "matcher votes for a consensus offset.\n\n"
            "• 5: Fast, fewer consensus votes\n"
            "• 9 (Default): Strong consensus\n"
            "• 13+: Very thorough, diminishing returns"
        )
        vv_layout.addRow(
            "Num Positions:", self.widgets["video_verified_num_positions"]
        )

        self.widgets["video_verified_batch_size"] = QSpinBox()
        self.widgets["video_verified_batch_size"].setRange(1, 128)
        self.widgets["video_verified_batch_size"].setValue(32)
        self.widgets["video_verified_batch_size"].setToolTip(
            "GPU batch size for feature extraction:\n\n"
            "Higher values use more GPU memory but extract faster. Applies\n"
            "to every backend (neural and classical).\n\n"
            "• 8: Low VRAM GPUs (2-4 GB)\n"
            "• 32 (Default): Standard GPUs (6+ GB)\n"
            "• 64+: High VRAM GPUs (12+ GB)"
        )
        vv_layout.addRow(
            "GPU Batch Size:", self.widgets["video_verified_batch_size"]
        )

        # --- Runtime settings ---

        self.widgets["video_verified_run_in_subprocess"] = QCheckBox()
        self.widgets["video_verified_run_in_subprocess"].setChecked(True)
        self.widgets["video_verified_run_in_subprocess"].setToolTip(
            "Run neural backends in a separate subprocess:\n\n"
            "ON (Default): Isolates GPU memory from the main application.\n"
            "  Prevents memory conflicts with other GPU operations.\n\n"
            "OFF: Run in the main process (faster startup, shared GPU memory).\n\n"
            "Note: classical GPU backends (pHash, dHash, SSIM) always run\n"
            "in-process regardless of this setting — their startup cost is\n"
            "negligible and there's no large VRAM model to isolate."
        )
        vv_layout.addRow(
            "Run in Subprocess:",
            self.widgets["video_verified_run_in_subprocess"],
        )

        self.widgets["video_verified_debug_report"] = QCheckBox()
        self.widgets["video_verified_debug_report"].setChecked(False)
        self.widgets["video_verified_debug_report"].setToolTip(
            "Write detailed sliding-window matching debug report:\n\n"
            "When enabled, writes a per-source report with full score\n"
            "landscapes, per-position results, and timing data to the\n"
            "debug/neural_verify/ directory. File name includes the\n"
            "backend name so primary and cross-check don't collide.\n\n"
            "Useful for diagnosing matching issues or validating results."
        )
        vv_layout.addRow(
            "Debug Report:", self.widgets["video_verified_debug_report"]
        )

        # --- Diagnostics (unchanged from legacy) ---

        self.widgets["video_verified_frame_audit"] = QCheckBox()
        self.widgets["video_verified_frame_audit"].setChecked(False)
        self.widgets["video_verified_frame_audit"].setToolTip(
            "Enable frame alignment audit (diagnostic):\n\n"
            "When enabled, analyzes each subtitle line after sync to check if\n"
            "centisecond rounding will cause frame drift.\n\n"
            "Writes a detailed report to:\n"
            "  .config/sync_checks/\n\n"
            "The report includes:\n"
            "  How many lines land on correct frames\n"
            "  Which lines have start/end frame drift\n"
            "  Duration impact analysis\n"
            "  Suggested rounding mode for your content\n\n"
            "This is diagnostic only - no timing is modified."
        )
        vv_layout.addRow(
            "Frame Alignment Audit:", self.widgets["video_verified_frame_audit"]
        )

        self.widgets["video_verified_visual_verify"] = QCheckBox()
        self.widgets["video_verified_visual_verify"].setChecked(False)
        self.widgets["video_verified_visual_verify"].setToolTip(
            "Enable visual frame verification (diagnostic):\n\n"
            "After calculating the offset, samples frames every 5 seconds\n"
            "across the entire video and compares raw frames between source\n"
            "and target using SSIM to verify the offset is correct.\n\n"
            "Writes a detailed report to:\n"
            "  .config/sync_checks/\n\n"
            "The report includes:\n"
            "  Overall accuracy (exact, within +/-1, +/-2 frames)\n"
            "  Per-region breakdown (early, main, late, credits)\n"
            "  Credits region auto-detection\n"
            "  Drift map showing where frames don't align\n"
            "  GOOD/FAIR/POOR verdict\n\n"
            "This is diagnostic only - no timing is modified."
        )
        vv_layout.addRow(
            "Visual Frame Verify:", self.widgets["video_verified_visual_verify"]
        )

        main_layout.addWidget(vv_group)
        main_layout.addStretch(1)

        # Connect signals
        self.widgets["subtitle_sync_mode"].currentTextChanged.connect(
            self._update_mode_visibility
        )
        self.widgets["video_verified_backend"].currentIndexChanged.connect(
            lambda _: self._update_mode_visibility(
                self.widgets["subtitle_sync_mode"].currentText()
            )
        )
        self.widgets["video_verified_cross_check_backend"].currentIndexChanged.connect(
            lambda _: self._update_mode_visibility(
                self.widgets["subtitle_sync_mode"].currentText()
            )
        )
        self._update_mode_visibility(self.widgets["subtitle_sync_mode"].currentText())

    def _update_mode_visibility(self, text: str):
        """Show/hide (enable/disable) settings based on selected sync mode + backend.

        Fields that apply to every backend are enabled whenever
        video-verified mode is selected. Backend-specific fields
        (hash_size for pHash/dHash, ssim_input_size for SSIM, cross-check
        tolerance when cross-check is active) are conditionally enabled
        so the user only sees relevant knobs light up.
        """
        is_time_based = text == "time-based"
        is_video_verified = text == "video-verified"

        # Look up the currently-selected backend + cross-check backend.
        backend = (
            self.widgets["video_verified_backend"].currentData() or "isc"
        )
        cross = (
            self.widgets["video_verified_cross_check_backend"].currentData()
            or "none"
        )

        # Time-based specific
        self.widgets["time_based_use_raw_values"].setEnabled(is_time_based)

        # Shared video-verified toggles (always enabled in video-verified mode)
        for key in (
            "video_verified_backend",
            "video_verified_cross_check_backend",
            "video_verified_window_seconds",
            "video_verified_slide_range_seconds",
            "video_verified_num_positions",
            "video_verified_batch_size",
            "video_verified_run_in_subprocess",
            "video_verified_debug_report",
            "video_verified_frame_audit",
            "video_verified_visual_verify",
        ):
            self.widgets[key].setEnabled(is_video_verified)

        # Cross-check tolerance — only meaningful when cross-check is active.
        self.widgets[
            "video_verified_cross_check_tolerance_frames"
        ].setEnabled(is_video_verified and cross != "none")

        # Hash size — only relevant when primary OR cross-check uses a hash backend.
        needs_hash = backend in ("phash", "dhash") or cross in ("phash", "dhash")
        self.widgets["video_verified_hash_size"].setEnabled(
            is_video_verified and needs_hash
        )

        # SSIM input size — only relevant when primary OR cross-check uses SSIM.
        needs_ssim = backend == "ssim" or cross == "ssim"
        self.widgets["video_verified_ssim_input_size"].setEnabled(
            is_video_verified and needs_ssim
        )


class ChaptersTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        f = QFormLayout(self)
        self.widgets["rename_chapters"] = QCheckBox('Rename to "Chapter NN"')
        self.widgets["rename_chapters"].setToolTip(
            "Automatically rename all chapters to a standard format (e.g., 'Chapter 01', 'Chapter 02')."
        )
        self.widgets["snap_chapters"] = QCheckBox(
            "Snap chapter timestamps to nearest keyframe"
        )
        self.widgets["snap_chapters"].setToolTip(
            "Adjust chapter timestamps to align with the nearest video keyframe, which can improve seeking performance."
        )
        snap_mode = QComboBox()
        # Store string value as data for combo box selection
        snap_mode.addItem("previous", "previous")
        snap_mode.addItem("nearest", "nearest")
        snap_mode.setToolTip(
            "'previous': Always snaps to the last keyframe before the chapter time.\n'nearest': Snaps to the closest keyframe, either before or after."
        )
        self.widgets["snap_mode"] = snap_mode
        thr = QSpinBox()
        thr.setRange(0, 5000)
        thr.setToolTip(
            "The maximum time (in milliseconds) a chapter can be from a keyframe to be snapped.\nChapters further away will be left untouched."
        )
        self.widgets["snap_threshold_ms"] = thr
        self.widgets["snap_starts_only"] = QCheckBox(
            "Only snap chapter start times (not end times)"
        )
        self.widgets["snap_starts_only"].setToolTip(
            "If checked, only chapter start times are snapped. If unchecked, both start and end times are snapped."
        )
        f.addWidget(self.widgets["rename_chapters"])
        f.addWidget(self.widgets["snap_chapters"])
        f.addRow("Snap Mode:", self.widgets["snap_mode"])
        f.addRow("Snap Threshold (ms):", self.widgets["snap_threshold_ms"])
        f.addWidget(self.widgets["snap_starts_only"])


class MergeBehaviorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)
        general_group = QGroupBox("General")
        form1 = QFormLayout(general_group)
        self.widgets["apply_dialog_norm_gain"] = QCheckBox(
            "Remove dialog normalization gain (AC3/E-AC3)"
        )
        self.widgets["apply_dialog_norm_gain"].setToolTip(
            "For AC3/E-AC3 audio tracks, remove the DialNorm metadata.\nThis can sometimes prevent players from lowering the volume."
        )
        self.widgets["disable_track_statistics_tags"] = QCheckBox(
            "Disable track statistics tags (for purist remuxes)"
        )
        self.widgets["disable_track_statistics_tags"].setToolTip(
            "Prevent mkvmerge from writing metadata tags about the track's statistics (e.g., BPS, DURATION)."
        )
        self.widgets["disable_header_compression"] = QCheckBox(
            "Disable header removal compression for all tracks"
        )
        self.widgets["disable_header_compression"].setToolTip(
            "Prevents mkvmerge from using header removal compression.\nThis is enabled by default as it can sometimes cause issues."
        )
        form1.addWidget(self.widgets["apply_dialog_norm_gain"])
        form1.addWidget(self.widgets["disable_track_statistics_tags"])
        form1.addWidget(self.widgets["disable_header_compression"])
        main_layout.addWidget(general_group)
        post_merge_group = QGroupBox("Post-Merge Finalization")
        form2 = QFormLayout(post_merge_group)
        self.widgets["post_mux_normalize_timestamps"] = QCheckBox(
            "Rebase timestamps to fix thumbnails (requires FFmpeg)"
        )
        self.widgets["post_mux_normalize_timestamps"].setToolTip(
            "If a file's video track doesn't start at timestamp zero (due to a global shift),\nthis option will perform a fast, lossless remux with FFmpeg to fix it.\nThis resolves issues with thumbnail generation in most file managers."
        )
        self.widgets["post_mux_strip_tags"] = QCheckBox(
            "Strip ENCODER tag added by FFmpeg (requires mkvpropedit)"
        )
        self.widgets["post_mux_strip_tags"].setToolTip(
            "If the timestamp normalization step is run, FFmpeg will add an 'ENCODER' tag to the file.\nThis option will run a quick update with mkvpropedit to remove that tag for a cleaner file."
        )
        form2.addWidget(self.widgets["post_mux_normalize_timestamps"])
        form2.addWidget(self.widgets["post_mux_strip_tags"])
        main_layout.addWidget(post_merge_group)
        main_layout.addStretch(1)


class LoggingTab(QWidget):
    def __init__(self):
        super().__init__()
        self.widgets: dict[str, QWidget] = {}
        main_layout = QVBoxLayout(self)

        # --- Logging Options ---
        log_group = QGroupBox("Log Output")
        f = QFormLayout(log_group)
        self.widgets["log_compact"] = QCheckBox("Use compact logging")
        self.widgets["log_compact"].setToolTip(
            "Reduce the verbosity of command-line tool output in the log."
        )
        self.widgets["log_autoscroll"] = QCheckBox("Auto-scroll log view during jobs")
        self.widgets["log_autoscroll"].setToolTip(
            "Automatically scroll the log view to the bottom as new messages arrive."
        )
        step = QSpinBox()
        step.setRange(1, 100)
        step.setSuffix("%")
        step.setToolTip(
            "How often to show 'Progress: X%' messages from mkvmerge in the log.\nA value of 20 means it will log at 20%, 40%, 60%, etc."
        )
        self.widgets["log_progress_step"] = step
        tail = QSpinBox()
        tail.setRange(0, 1000)
        tail.setSuffix(" lines")
        tail.setToolTip(
            "In compact mode, if a command fails, show this many of the last lines of output to help diagnose the error."
        )
        self.widgets["log_error_tail"] = tail
        self.widgets["log_show_options_pretty"] = QCheckBox(
            "Show mkvmerge options in log (pretty text)"
        )
        self.widgets["log_show_options_pretty"].setToolTip(
            "Print the full mkvmerge command to the log in a human-readable format before execution."
        )
        self.widgets["log_show_options_json"] = QCheckBox(
            "Show mkvmerge options in log (raw JSON)"
        )
        self.widgets["log_show_options_json"].setToolTip(
            "Print the full mkvmerge command to the log in the raw JSON format that is passed to the tool."
        )
        f.addRow(self.widgets["log_compact"])
        f.addRow(self.widgets["log_autoscroll"])
        f.addRow("Progress Step:", self.widgets["log_progress_step"])
        f.addRow("Error Tail:", self.widgets["log_error_tail"])
        f.addRow(self.widgets["log_show_options_pretty"])
        f.addRow(self.widgets["log_show_options_json"])
        main_layout.addWidget(log_group)

        # --- Sync Stability (Correlation Variance Detection) ---
        stability_group = QGroupBox("Sync Stability Detection")
        stability_layout = QFormLayout(stability_group)

        self.widgets["sync_stability_enabled"] = QCheckBox(
            "Enable sync stability detection"
        )
        self.widgets["sync_stability_enabled"].setToolTip(
            "Detect variance in correlation results that may indicate sync issues.\nFlags jobs where chunk delays aren't perfectly consistent."
        )
        stability_layout.addRow(self.widgets["sync_stability_enabled"])

        variance_thresh = QDoubleSpinBox()
        variance_thresh.setRange(0.0, 10.0)
        variance_thresh.setDecimals(3)
        variance_thresh.setSingleStep(0.001)
        variance_thresh.setSuffix(" ms")
        variance_thresh.setToolTip(
            "Maximum allowed variance in raw delay values.\n0 = flag any variance (strictest)\nHigher values allow more tolerance."
        )
        self.widgets["sync_stability_variance_threshold"] = variance_thresh
        stability_layout.addRow("Variance Threshold:", variance_thresh)

        min_chunks = QSpinBox()
        min_chunks.setRange(2, 30)
        min_chunks.setToolTip(
            "Minimum number of correlation windows needed to calculate\n"
            "variance. Below this count, stability check is skipped.\n"
            "Default: 3"
        )
        self.widgets["sync_stability_min_windows"] = min_chunks
        stability_layout.addRow("Min Windows:", min_chunks)

        outlier_mode = QComboBox()
        outlier_mode.addItem("Any Variance", "any")
        outlier_mode.addItem("Custom Threshold", "threshold")
        outlier_mode.setToolTip(
            "How to detect outliers:\n- Any Variance: flag if ANY window differs from others\n- Custom Threshold: only flag if difference exceeds threshold"
        )
        self.widgets["sync_stability_outlier_mode"] = outlier_mode
        stability_layout.addRow("Outlier Mode:", outlier_mode)

        outlier_thresh = QDoubleSpinBox()
        outlier_thresh.setRange(0.001, 100.0)
        outlier_thresh.setDecimals(3)
        outlier_thresh.setSingleStep(0.1)
        outlier_thresh.setSuffix(" ms")
        outlier_thresh.setToolTip(
            "Custom outlier threshold (when mode = Custom Threshold).\nChunks differing by more than this from the mean are flagged as outliers."
        )
        self.widgets["sync_stability_outlier_threshold"] = outlier_thresh
        stability_layout.addRow("Outlier Threshold:", outlier_thresh)

        main_layout.addWidget(stability_group)
        main_layout.addStretch(1)
