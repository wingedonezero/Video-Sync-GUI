from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QDialogButtonBox,
    QCheckBox, QDoubleSpinBox, QComboBox, QFormLayout, QGroupBox, QLineEdit
)
from .logic import TrackSettingsLogic

class TrackSettingsDialog(QDialog):
    """Small popup dialog to edit per-track options."""
    def __init__(self, track_type: str, codec_id: str, **kwargs):
        super().__init__()
        self.setWindowTitle("Track Settings")
        self.setMinimumWidth(400)

        # --- UI Elements ---
        # Language selector (for all track types)
        self.lang_combo = QComboBox()

        # Custom track name (for all track types)
        self.custom_name_input = QLineEdit()

        # Subtitle-specific controls
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

        # Language section (always visible)
        lang_group = QGroupBox("Language Settings")
        lang_layout = QFormLayout(lang_group)
        lang_layout.addRow("Language Code:", self.lang_combo)
        layout.addWidget(lang_group)

        # Track name section (always visible)
        name_group = QGroupBox("Track Name")
        name_layout = QFormLayout(name_group)
        name_layout.addRow("Custom Name:", self.custom_name_input)
        layout.addWidget(name_group)

        # Subtitle section (conditionally visible)
        self.subtitle_group = QGroupBox("Subtitle Options")
        subtitle_layout = QVBoxLayout(self.subtitle_group)
        subtitle_layout.addWidget(self.cb_ocr)
        subtitle_layout.addWidget(self.cb_cleanup)
        subtitle_layout.addWidget(self.cb_convert)
        subtitle_layout.addWidget(self.cb_rescale)
        subtitle_layout.addWidget(self.size_multiplier)
        layout.addWidget(self.subtitle_group)

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
