from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .logic import TrackSettingsLogic


class TrackSettingsDialog(QDialog):
    """Small popup dialog to edit per-track options."""
    def __init__(self, track_type: str, codec_id: str, track_data: dict = None, **kwargs):
        super().__init__()
        self.setWindowTitle("Track Settings")
        self.setMinimumWidth(400)
        self.track_data = track_data or {}

        # --- UI Elements ---
        # Language selector (for all track types)
        self.lang_combo = QComboBox()

        # Custom track name (for all track types)
        self.custom_name_input = QLineEdit()

        # Subtitle-specific controls
        self.cb_ocr = QCheckBox("Perform OCR")
        self.cb_convert = QCheckBox("Convert to ASS (SRT only)")
        self.cb_rescale = QCheckBox("Rescale to video resolution")
        self.size_multiplier = QDoubleSpinBox()
        self.size_multiplier.setRange(0.1, 10.0)
        self.size_multiplier.setSingleStep(0.1)
        self.size_multiplier.setDecimals(2)
        self.size_multiplier.setPrefix("Size multiplier: ")
        self.size_multiplier.setSuffix("x")

        # Frame sync exclusions button (ASS/SSA only)
        self.sync_exclusion_btn = QPushButton("Configure Frame Sync Exclusions...")
        self.sync_exclusion_btn.clicked.connect(self._open_sync_exclusion_dialog)

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
        subtitle_layout.addWidget(self.cb_convert)
        subtitle_layout.addWidget(self.cb_rescale)
        subtitle_layout.addWidget(self.size_multiplier)
        subtitle_layout.addWidget(self.sync_exclusion_btn)
        layout.addWidget(self.subtitle_group)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # --- Initial State ---
        self._logic.apply_initial_values(**kwargs)
        self._logic.init_for_type_and_codec(track_type, codec_id)

    def _open_sync_exclusion_dialog(self):
        """Open the sync exclusion configuration dialog."""
        from vsg_qt.sync_exclusion_dialog import SyncExclusionDialog

        # Get existing config if available
        existing_config = None
        if self.track_data.get('sync_exclusion_styles'):
            existing_config = {
                'mode': self.track_data.get('sync_exclusion_mode', 'exclude'),
                'styles': self.track_data.get('sync_exclusion_styles', []),
            }

        dialog = SyncExclusionDialog(
            track_data=self.track_data,
            existing_config=existing_config,
            parent=self
        )

        if dialog.exec():
            config = dialog.get_exclusion_config()
            if config:
                # Store in track_data temporarily (will be saved when main dialog is accepted)
                self.track_data['sync_exclusion_styles'] = config['styles']
                self.track_data['sync_exclusion_mode'] = config['mode']
                self.track_data['sync_exclusion_original_style_list'] = config['original_style_list']
            else:
                # Clear exclusions if None returned
                self.track_data.pop('sync_exclusion_styles', None)
                self.track_data.pop('sync_exclusion_mode', None)
                self.track_data.pop('sync_exclusion_original_style_list', None)

    def read_values(self) -> dict:
        """Public method to retrieve the dialog's current values."""
        values = self._logic.read_values()

        # Include sync exclusion config in the returned values
        values['sync_exclusion_styles'] = self.track_data.get('sync_exclusion_styles', [])
        values['sync_exclusion_mode'] = self.track_data.get('sync_exclusion_mode', 'exclude')
        values['sync_exclusion_original_style_list'] = self.track_data.get('sync_exclusion_original_style_list', [])

        return values
