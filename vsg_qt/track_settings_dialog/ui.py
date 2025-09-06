from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QDialogButtonBox,
    QCheckBox, QLabel, QDoubleSpinBox, QWidget
)
from PySide6.QtCore import Qt
from .logic import TrackSettingsLogic

class TrackSettingsDialog(QDialog):
    """
    Small popup dialog to edit per-track options.
    Public API preserved:
      - __init__(track_type, codec_id, is_default, is_forced_display, apply_track_name, convert_to_ass, rescale, size_multiplier, parent)
      - get_values() -> dict
    """
    def __init__(
        self, *,
        track_type: str,
        codec_id: str,
        is_default: bool,
        is_forced_display: bool,
        apply_track_name: bool,
        convert_to_ass: bool,
        rescale: bool,
        size_multiplier: float,
        parent: QWidget = None
    ):
        super().__init__(parent)
        self.setWindowTitle("Track Settings")
        self.setMinimumWidth(360)

        # ---- controls (public attributes kept for compatibility) ----
        self.cb_default = QCheckBox("Default")
        self.cb_forced = QCheckBox("Forced")
        self.cb_convert = QCheckBox("Convert to ASS (SRT only)")
        self.cb_rescale = QCheckBox("Rescale to video resolution")
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 5.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setSuffix("x")
        self.cb_name = QCheckBox("Keep Name")

        # ---- layout ----
        vbox = QVBoxLayout(self)

        vbox.addWidget(self.cb_default)

        # Subtitle-only controls (visibility/enablement handled by logic)
        vbox.addWidget(self.cb_forced)
        vbox.addWidget(self.cb_convert)
        vbox.addWidget(self.cb_rescale)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Size multiplier:"))
        size_row.addWidget(self.size_multiplier, 1)
        vbox.addLayout(size_row)

        vbox.addWidget(self.cb_name)
        vbox.addStretch(1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        vbox.addWidget(btns)

        # ---- logic wiring ----
        self._logic = TrackSettingsLogic(self)
        self._logic.init_for_type_and_codec(track_type, codec_id)
        self._logic.apply_initial_values(
            is_default=is_default,
            is_forced_display=is_forced_display,
            apply_track_name=apply_track_name,
            convert_to_ass=convert_to_ass,
            rescale=rescale,
            size_multiplier=size_multiplier
        )

    # ---- public API ----
    def get_values(self) -> dict:
        return self._logic.read_values()
