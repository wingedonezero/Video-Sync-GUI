from __future__ import annotations

class TrackSettingsLogic:
    """
    Logic layer for TrackSettingsDialog.
    The view is a dialog exposing the checkbox/spinbox widgets as attributes.
    """

    def __init__(self, view):
        self.v = view

    # ---- initial state helpers ----
    def init_for_type_and_codec(self, track_type: str, codec_id: str):
        v = self.v
        is_subs = (track_type == "subtitles")

        # Show/hide subtitle-only controls
        v.cb_forced.setVisible(is_subs)
        v.cb_convert.setVisible(is_subs)
        v.cb_rescale.setVisible(is_subs)
        v.size_multiplier.setVisible(is_subs)

        # Enable convert-to-ASS only for SRT
        v.cb_convert.setEnabled(is_subs and "S_TEXT/UTF8" in (codec_id or "").upper())

    # ---- reads & writes ----
    def apply_initial_values(
        self,
        *,
        is_default: bool,
        is_forced_display: bool,
        apply_track_name: bool,
        convert_to_ass: bool,
        rescale: bool,
        size_multiplier: float
    ):
        v = self.v
        v.cb_default.setChecked(bool(is_default))
        v.cb_name.setChecked(bool(apply_track_name))

        # Subtitle-only (they may be hidden for non-subs, still safe)
        v.cb_forced.setChecked(bool(is_forced_display))
        v.cb_convert.setChecked(bool(convert_to_ass) and v.cb_convert.isEnabled())
        v.cb_rescale.setChecked(bool(rescale))
        try:
            v.size_multiplier.setValue(float(size_multiplier) if size_multiplier else 1.0)
        except Exception:
            v.size_multiplier.setValue(1.0)

    def read_values(self) -> dict:
        v = self.v
        return {
            "is_default": v.cb_default.isChecked(),
            "is_forced_display": v.cb_forced.isChecked(),
            "apply_track_name": v.cb_name.isChecked(),
            "convert_to_ass": v.cb_convert.isChecked(),
            "rescale": v.cb_rescale.isChecked(),
            "size_multiplier": v.size_multiplier.value(),
        }
