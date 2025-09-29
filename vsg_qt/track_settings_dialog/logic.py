from __future__ import annotations

class TrackSettingsLogic:
    """Logic layer for TrackSettingsDialog."""

    def __init__(self, view):
        self.v = view

    def init_for_type_and_codec(self, track_type: str, codec_id: str):
        """Shows or hides widgets based on the track type."""
        is_subs = (track_type == "subtitles")
        codec_upper = (codec_id or "").upper()

        # Hide all controls for non-subtitle tracks
        self.v.cb_ocr.setVisible(is_subs)
        self.v.cb_cleanup.setVisible(is_subs)
        self.v.cb_convert.setVisible(is_subs)
        self.v.cb_rescale.setVisible(is_subs)
        self.v.size_multiplier.setVisible(is_subs)

        # Enable OCR only for image-based subtitles
        is_ocr_compatible = is_subs and ('VOBSUB' in codec_upper or 'PGS' in codec_upper)
        self.v.cb_ocr.setEnabled(is_ocr_compatible)
        self.v.cb_cleanup.setEnabled(is_ocr_compatible)

        # Enable convert-to-ASS only for SRT tracks
        self.v.cb_convert.setEnabled(is_subs and "S_TEXT/UTF8" in codec_upper)

    def apply_initial_values(
        self,
        *,
        perform_ocr: bool,
        perform_ocr_cleanup: bool,
        convert_to_ass: bool,
        rescale: bool,
        size_multiplier: float,
        **kwargs # Accept and ignore any other arguments
    ):
        """Applies the starting values to the widgets."""
        self.v.cb_ocr.setChecked(bool(perform_ocr))
        self.v.cb_cleanup.setChecked(bool(perform_ocr_cleanup))
        self.v.cb_convert.setChecked(bool(convert_to_ass))
        self.v.cb_rescale.setChecked(bool(rescale))
        self.v.size_multiplier.setValue(float(size_multiplier))

    def read_values(self) -> dict:
        """Returns a dictionary of the current values from the widgets."""
        return {
            "perform_ocr": self.v.cb_ocr.isChecked(),
            "perform_ocr_cleanup": self.v.cb_cleanup.isChecked(),
            "convert_to_ass": self.v.cb_convert.isChecked(),
            "rescale": self.v.cb_rescale.isChecked(),
            "size_multiplier": self.v.size_multiplier.value(),
        }
