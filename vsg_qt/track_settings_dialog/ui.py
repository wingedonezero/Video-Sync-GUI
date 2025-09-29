from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QDialogButtonBox,
    QCheckBox, QDoubleSpinBox
)
from .logic import TrackSettingsLogic

class TrackSettingsDialog(QDialog):
    """Small popup dialog to edit per-track options."""
    def __init__(self, track_type: str, codec_id: str, **kwargs):
        super().__init__()
        self.setWindowTitle("Track Settings")

        # --- UI Elements ---
        self.cb_ocr = QCheckBox("Perform OCR")
        self.cb_cleanup = QCheckBox("Perform Post-OCR Cleanup")
        self.cb_convert = QCheckBox("Convert to ASS (SRT only)")
        self.cb_rescale = QCheckBox("Rescale to video resolution")
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 10.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setDecimals(2)
        self.size_multiplier.setPrefix("Size multiplier: ")
        self.size_multiplier.setSuffix("x")

        # --- Logic ---
        self._logic = TrackSettingsLogic(self)

        # --- Layout ---
        layout = QVBoxLayout(self)
        layout.addWidget(self.cb_ocr)
        layout.addWidget(self.cb_cleanup)
        layout.addWidget(self.cb_convert)
        layout.addWidget(self.cb_rescale)
        layout.addWidget(self.size_multiplier)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # --- Initial State ---
        self._logic.apply_initial_values(**kwargs)
        self._logic.init_for_type_and_codec(track_type, codec_id)

    def read_values(self) -> dict:
        """Public method to retrieve the dialog's current values."""
        return self._logic.read_values()
