# -*- coding: utf-8 -*-

"""
The settings/options dialog window for the PyQt application.
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox
)

class OptionsDialog(QDialog):
    """A tabbed dialog for managing all application settings."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('Application Settings')
        self.setMinimumWidth(600)

        # --- Widgets ---
        self.tabs = QTabWidget()
        self.storage_widgets = {}
        self.analysis_widgets = {}
        self.chapters_widgets = {}
        self.merge_widgets = {}
        self.logging_widgets = {}

        # --- Layout ---
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)

        self.tabs.addTab(self._create_storage_tab(), 'Storage')
        self.tabs.addTab(self._create_analysis_tab(), 'Analysis')
        self.tabs.addTab(self._create_chapters_tab(), 'Chapters')
        self.tabs.addTab(self._create_merge_tab(), 'Merge Behavior')
        self.tabs.addTab(self._create_logging_tab(), 'Logging')

        # --- Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.load_settings()

    def _create_storage_tab(self):
        """Creates the Storage settings tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.storage_widgets['output_folder'] = self._create_dir_input()
        self.storage_widgets['temp_root'] = self._create_dir_input()
        self.storage_widgets['videodiff_path'] = self._create_file_input()

        layout.addRow('Output Directory:', self.storage_widgets['output_folder'])
        layout.addRow('Temporary Directory:', self.storage_widgets['temp_root'])
        layout.addRow('VideoDiff Path (optional):', self.storage_widgets['videodiff_path'])

        return widget

    def _create_analysis_tab(self):
        """Creates the Analysis settings tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.analysis_widgets['analysis_mode'] = QComboBox()
        self.analysis_widgets['analysis_mode'].addItems(['Audio Correlation', 'VideoDiff'])
        self.analysis_widgets['scan_chunk_count'] = QSpinBox(minimum=1, maximum=100)
        self.analysis_widgets['scan_chunk_duration'] = QSpinBox(minimum=1, maximum=120)
        self.analysis_widgets['min_match_pct'] = QDoubleSpinBox(minimum=0.1, maximum=100.0, decimals=1, singleStep=1.0)
        self.analysis_widgets['videodiff_error_min'] = QDoubleSpinBox(minimum=0.0, maximum=500.0, decimals=2)
        self.analysis_widgets['videodiff_error_max'] = QDoubleSpinBox(minimum=0.0, maximum=500.0, decimals=2)

        layout.addRow('Analysis Mode:', self.analysis_widgets['analysis_mode'])
        layout.addRow('Audio: Scan Chunks:', self.analysis_widgets['scan_chunk_count'])
        layout.addRow('Audio: Chunk Duration (s):', self.analysis_widgets['scan_chunk_duration'])
        layout.addRow('Audio: Minimum Match %:', self.analysis_widgets['min_match_pct'])
        layout.addRow('VideoDiff: Min Allowed Error:', self.analysis_widgets['videodiff_error_min'])
        layout.addRow('VideoDiff: Max Allowed Error:', self.analysis_widgets['videodiff_error_max'])

        return widget

    def _create_chapters_tab(self):
        """Creates the Chapters settings tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.chapters_widgets['rename_chapters'] = QCheckBox('Rename to "Chapter NN"')
        self.chapters_widgets['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe')
        self.chapters_widgets['snap_mode'] = QComboBox()
        self.chapters_widgets['snap_mode'].addItems(['previous', 'nearest'])
        self.chapters_widgets['snap_threshold_ms'] = QSpinBox(minimum=0, maximum=5000, singleStep=50)
        self.chapters_widgets['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)')

        layout.addWidget(self.chapters_widgets['rename_chapters'])
        layout.addWidget(self.chapters_widgets['snap_chapters'])
        layout.addRow('Snap Mode:', self.chapters_widgets['snap_mode'])
        layout.addRow('Snap Threshold (ms):', self.chapters_widgets['snap_threshold_ms'])
        layout.addWidget(self.chapters_widgets['snap_starts_only'])

        return widget

    def _create_merge_tab(self):
        """Creates the Merge Behavior settings tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.merge_widgets['swap_subtitle_order'] = QCheckBox('Swap first 2 subtitle tracks (Secondary only)')
        self.merge_widgets['match_jpn_secondary'] = QCheckBox('Prefer JPN audio stream on Secondary source')
        self.merge_widgets['match_jpn_tertiary'] = QCheckBox('Prefer JPN audio stream on Tertiary source')
        self.merge_widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.merge_widgets['first_sub_default'] = QCheckBox('Make first subtitle in final order the default track')

        for w in self.merge_widgets.values():
            layout.addWidget(w)

        return widget

    def _create_logging_tab(self):
        """Creates the Logging settings tab."""
        widget = QWidget()
        layout = QFormLayout(widget)

        self.logging_widgets['log_compact'] = QCheckBox('Use compact logging')
        self.logging_widgets['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs')
        self.logging_widgets['log_progress_step'] = QSpinBox(minimum=1, maximum=100, suffix='%')
        self.logging_widgets['log_error_tail'] = QSpinBox(minimum=0, maximum=1000, suffix=' lines')
        self.logging_widgets['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)')
        self.logging_widgets['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)')

        layout.addRow(self.logging_widgets['log_compact'])
        layout.addRow(self.logging_widgets['log_autoscroll'])
        layout.addRow('Progress Step:', self.logging_widgets['log_progress_step'])
        layout.addRow('Error Tail:', self.logging_widgets['log_error_tail'])
        layout.addRow(self.logging_widgets['log_show_options_pretty'])
        layout.addRow(self.logging_widgets['log_show_options_json'])

        return widget

    def load_settings(self):
        """Populates all widgets with values from the config object."""
        for key, widget in self.storage_widgets.items(): self._set_widget_val(widget, self.config.get(key))
        for key, widget in self.analysis_widgets.items(): self._set_widget_val(widget, self.config.get(key))
        for key, widget in self.chapters_widgets.items(): self._set_widget_val(widget, self.config.get(key))
        for key, widget in self.merge_widgets.items(): self._set_widget_val(widget, self.config.get(key))
        for key, widget in self.logging_widgets.items(): self._set_widget_val(widget, self.config.get(key))

    def accept(self):
        """Saves widget values back to the config object before closing."""
        for key, widget in self.storage_widgets.items(): self.config.set(key, self._get_widget_val(widget))
        for key, widget in self.analysis_widgets.items(): self.config.set(key, self._get_widget_val(widget))
        for key, widget in self.chapters_widgets.items(): self.config.set(key, self._get_widget_val(widget))
        for key, widget in self.merge_widgets.items(): self.config.set(key, self._get_widget_val(widget))
        for key, widget in self.logging_widgets.items(): self.config.set(key, self._get_widget_val(widget))
        super().accept()

    def _create_dir_input(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit()
        button = QPushButton('Browse…')
        layout.addWidget(line_edit)
        layout.addWidget(button)
        button.clicked.connect(lambda: self._browse_for_dir(line_edit))
        return widget

    def _create_file_input(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit()
        button = QPushButton('Browse…')
        layout.addWidget(line_edit)
        layout.addWidget(button)
        button.clicked.connect(lambda: self._browse_for_file(line_edit))
        return widget

    def _browse_for_dir(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select Directory", line_edit.text())
        if path: line_edit.setText(path)

    def _browse_for_file(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", line_edit.text())
        if path: line_edit.setText(path)

    def _get_widget_val(self, widget):
        if isinstance(widget, QCheckBox): return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)): return widget.value()
        if isinstance(widget, QComboBox): return widget.currentText()
        if isinstance(widget, QWidget) and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            return widget.layout().itemAt(0).widget().text()
        return widget.text() if isinstance(widget, QLineEdit) else None

    def _set_widget_val(self, widget, value):
        if isinstance(widget, QCheckBox): widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): widget.setValue(value)
        elif isinstance(widget, QComboBox): widget.setCurrentText(str(value))
        elif isinstance(widget, QLineEdit): widget.setText(str(value))
        elif isinstance(widget, QWidget) and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            widget.layout().itemAt(0).widget().setText(str(value))
