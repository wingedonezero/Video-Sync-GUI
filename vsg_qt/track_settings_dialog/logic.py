from __future__ import annotations

# Common language codes with user-friendly names
LANGUAGE_CODES = [
    ("Keep Original", ""),  # Empty string means use original
    ("---", None),  # Separator
    ("Undetermined (und)", "und"),
    ("---", None),
    ("English (eng)", "eng"),
    ("Japanese (jpn)", "jpn"),
    ("Chinese (zho)", "zho"),
    ("Spanish (spa)", "spa"),
    ("French (fra)", "fra"),
    ("German (deu)", "deu"),
    ("Italian (ita)", "ita"),
    ("Portuguese (por)", "por"),
    ("Russian (rus)", "rus"),
    ("Korean (kor)", "kor"),
    ("Arabic (ara)", "ara"),
    ("Turkish (tur)", "tur"),
    ("Polish (pol)", "pol"),
    ("Dutch (nld)", "nld"),
    ("Swedish (swe)", "swe"),
    ("Norwegian (nor)", "nor"),
    ("Finnish (fin)", "fin"),
    ("Danish (dan)", "dan"),
    ("Czech (ces)", "ces"),
    ("Hungarian (hun)", "hun"),
    ("Greek (ell)", "ell"),
    ("Hebrew (heb)", "heb"),
    ("Thai (tha)", "tha"),
    ("Vietnamese (vie)", "vie"),
    ("Hindi (hin)", "hin"),
]

class TrackSettingsLogic:
    """Logic layer for TrackSettingsDialog."""

    def __init__(self, view):
        self.v = view
        self._populate_language_dropdown()

    def _populate_language_dropdown(self):
        """Populates the language dropdown with common codes."""
        for display_name, code in LANGUAGE_CODES:
            if code is None:
                # Add separator
                self.v.lang_combo.insertSeparator(self.v.lang_combo.count())
            else:
                self.v.lang_combo.addItem(display_name, code)

    def init_for_type_and_codec(self, track_type: str, codec_id: str):
        """Shows or hides widgets based on the track type."""
        is_subs = (track_type == "subtitles")

        # Show subtitle group only for subtitles
        self.v.subtitle_group.setVisible(is_subs)

        if is_subs:
            codec_upper = (codec_id or "").upper()

            # Enable OCR only for image-based subtitles
            is_ocr_compatible = 'VOBSUB' in codec_upper or 'PGS' in codec_upper
            self.v.cb_ocr.setEnabled(is_ocr_compatible)
            self.v.cb_cleanup.setEnabled(is_ocr_compatible)

            # Enable convert-to-ASS only for SRT tracks
            self.v.cb_convert.setEnabled("S_TEXT/UTF8" in codec_upper)

    def apply_initial_values(
        self,
        *,
        custom_lang: str = "",
        perform_ocr: bool = False,
        perform_ocr_cleanup: bool = False,
        convert_to_ass: bool = False,
        rescale: bool = False,
        size_multiplier: float = 1.0,
        **kwargs  # Accept and ignore any other arguments
    ):
        """Applies the starting values to the widgets."""
        # Set language
        if custom_lang:
            index = self.v.lang_combo.findData(custom_lang)
            if index >= 0:
                self.v.lang_combo.setCurrentIndex(index)

        # Set subtitle options
        self.v.cb_ocr.setChecked(bool(perform_ocr))
        self.v.cb_cleanup.setChecked(bool(perform_ocr_cleanup))
        self.v.cb_convert.setChecked(bool(convert_to_ass))
        self.v.cb_rescale.setChecked(bool(rescale))
        self.v.size_multiplier.setValue(float(size_multiplier))

    def read_values(self) -> dict:
        """Returns a dictionary of the current values from the widgets."""
        # Get selected language code (empty string means "keep original")
        selected_lang = self.v.lang_combo.currentData()

        return {
            "custom_lang": selected_lang if selected_lang else "",
            "perform_ocr": self.v.cb_ocr.isChecked(),
            "perform_ocr_cleanup": self.v.cb_cleanup.isChecked(),
            "convert_to_ass": self.v.cb_convert.isChecked(),
            "rescale": self.v.cb_rescale.isChecked(),
            "size_multiplier": self.v.size_multiplier.value(),
        }
