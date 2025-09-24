from __future__ import annotations

class TrackSettingsLogic:
    """Logic layer for TrackSettingsDialog."""

    def __init__(self, view):
        self.v = view

    def init_for_type_and_codec(self, track_type: str, codec_id: str):
        """Shows or hides widgets based on the track type."""
        is_subs = (track_type == "subtitles")

        # Hide all controls for non-subtitle tracks
        self.v.cb_convert.setVisible(is_subs)
        self.v.cb_rescale.setVisible(is_subs)
        self.v.size_multiplier.setVisible(is_subs)

        # Enable convert-to-ASS only for SRT tracks
        self.v.cb_convert.setEnabled(is_subs and "S_TEXT/UTF8" in (codec_id or "").upper())

    def apply_initial_values(
        self,
        *,
        convert_to_ass: bool,
        rescale: bool,
        size_multiplier: float,
        **kwargs # Accept and ignore any other arguments
    ):
        """Applies the starting values to the widgets."""
        # --- MODIFICATION: 'is_forced_display' is no longer handled here ---
        self.v.cb_convert.setChecked(bool(convert_to_ass))
        self.v.cb_rescale.setChecked(bool(rescale))
        self.v.size_multiplier.setValue(float(size_multiplier))

    def read_values(self) -> dict:
        """Returns a dictionary of the current values from the widgets."""
        # --- MODIFICATION: 'is_forced_display' is no longer read from here ---
        return {
            "convert_to_ass": self.v.cb_convert.isChecked(),
            "rescale": self.v.cb_rescale.isChecked(),
            "size_multiplier": self.v.size_multiplier.value(),
        }
