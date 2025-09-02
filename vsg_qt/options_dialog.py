# vsg_qt/options_dialog.py
# -*- coding: utf-8 -*-
"""
Settings dialog (without Merge Plan tab).
"""
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QLabel, QScrollArea
)
from PySide6.QtCore import Qt


class OptionsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('Application Settings')
        self.setMinimumSize(900, 600)

        self.tabs = QTabWidget()
        self.storage_widgets, self.analysis_widgets, self.chapters_widgets, self.merge_widgets, self.logging_widgets = {}, {}, {}, {}, {}

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)

        # Only the functional tabs remain
        self.tabs.addTab(self._wrap_scroll(self._create_storage_tab()), 'Storage')
        self.tabs.addTab(self._wrap_scroll(self._create_analysis_tab()), 'Analysis')
        self.tabs.addTab(self._wrap_scroll(self._create_chapters_tab()), 'Chapters')
        self.tabs.addTab(self._wrap_scroll(self._create_merge_behavior_tab()), 'Merge Behavior')
        self.tabs.addTab(self._wrap_scroll(self._create_logging_tab()), 'Logging')

        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.load_settings()

    # ---- Scroll wrapper helper ----
    def _wrap_scroll(self, widget: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(widget)
        return sa

    # ---- Tabs ----
    def _create_storage_tab(self):
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
        widget = QWidget()
        layout = QFormLayout(widget)
        self.analysis_widgets['analysis_mode'] = QComboBox()
        self.analysis_widgets['analysis_mode'].addItems(['Audio Correlation', 'VideoDiff'])

        self.analysis_widgets['scan_chunk_count'] = QSpinBox()
        self.analysis_widgets['scan_chunk_count'].setRange(1, 100)

        self.analysis_widgets['scan_chunk_duration'] = QSpinBox()
        self.analysis_widgets['scan_chunk_duration'].setRange(1, 120)

        self.analysis_widgets['min_match_pct'] = QDoubleSpinBox()
        self.analysis_widgets['min_match_pct'].setRange(0.1, 100.0)
        self.analysis_widgets['min_match_pct'].setDecimals(1)
        self.analysis_widgets['min_match_pct'].setSingleStep(1.0)

        self.analysis_widgets['videodiff_error_min'] = QDoubleSpinBox()
        self.analysis_widgets['videodiff_error_min'].setRange(0.0, 500.0)
        self.analysis_widgets['videodiff_error_min'].setDecimals(2)

        self.analysis_widgets['videodiff_error_max'] = QDoubleSpinBox()
        self.analysis_widgets['videodiff_error_max'].setRange(0.0, 500.0)
        self.analysis_widgets['videodiff_error_max'].setDecimals(2)

        self.analysis_widgets['analysis_lang_ref'] = QLineEdit(); self.analysis_widgets['analysis_lang_ref'].setPlaceholderText('Blank = first available')
        self.analysis_widgets['analysis_lang_sec'] = QLineEdit(); self.analysis_widgets['analysis_lang_sec'].setPlaceholderText('Blank = first available')
        self.analysis_widgets['analysis_lang_ter'] = QLineEdit(); self.analysis_widgets['analysis_lang_ter'].setPlaceholderText('Blank = first available')

        layout.addRow('Analysis Mode:', self.analysis_widgets['analysis_mode'])
        layout.addRow('Audio: Scan Chunks:', self.analysis_widgets['scan_chunk_count'])
        layout.addRow('Audio: Chunk Duration (s):', self.analysis_widgets['scan_chunk_duration'])
        layout.addRow('Audio: Minimum Match %:', self.analysis_widgets['min_match_pct'])
        layout.addRow('VideoDiff: Min Allowed Error:', self.analysis_widgets['videodiff_error_min'])
        layout.addRow('VideoDiff: Max Allowed Error:', self.analysis_widgets['videodiff_error_max'])
        layout.addRow(QLabel('<b>Analysis Audio Track Selection</b>'))
        layout.addRow('REF Language:', self.analysis_widgets['analysis_lang_ref'])
        layout.addRow('SEC Language:', self.analysis_widgets['analysis_lang_sec'])
        layout.addRow('TER Language:', self.analysis_widgets['analysis_lang_ter'])
        return widget

    def _create_chapters_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.chapters_widgets['rename_chapters'] = QCheckBox('Rename to "Chapter NN"')
        self.chapters_widgets['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe')
        self.chapters_widgets['snap_mode'] = QComboBox(); self.chapters_widgets['snap_mode'].addItems(['previous', 'nearest'])
        self.chapters_widgets['snap_threshold_ms'] = QSpinBox(); self.chapters_widgets['snap_threshold_ms'].setRange(0, 5000)
        self.chapters_widgets['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)')
        layout.addWidget(self.chapters_widgets['rename_chapters'])
        layout.addWidget(self.chapters_widgets['snap_chapters'])
        layout.addRow('Snap Mode:', self.chapters_widgets['snap_mode'])
        layout.addRow('Snap Threshold (ms):', self.chapters_widgets['snap_threshold_ms'])
        layout.addWidget(self.chapters_widgets['snap_starts_only'])
        return widget

    def _create_merge_behavior_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.merge_widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.merge_widgets['exclude_codecs'] = QLineEdit()
        self.merge_widgets['exclude_codecs'].setPlaceholderText('e.g., ac3, dts, pcm')
        self.merge_widgets['disable_track_statistics_tags'] = QCheckBox('Disable track statistics tags (for purist remuxes)')
        layout.addRow(self.merge_widgets['apply_dialog_norm_gain'])
        layout.addRow('Exclude codecs (comma-separated):', self.merge_widgets['exclude_codecs'])
        layout.addRow(self.merge_widgets['disable_track_statistics_tags'])
        return widget

    def _create_logging_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.logging_widgets['log_compact'] = QCheckBox('Use compact logging')
        self.logging_widgets['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs')
        self.logging_widgets['log_progress_step'] = QSpinBox(); self.logging_widgets['log_progress_step'].setRange(1, 100); self.logging_widgets['log_progress_step'].setSuffix('%')
        self.logging_widgets['log_error_tail'] = QSpinBox(); self.logging_widgets['log_error_tail'].setRange(0, 1000); self.logging_widgets['log_error_tail'].setSuffix(' lines')
        self.logging_widgets['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)')
        self.logging_widgets['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)')
        layout.addRow(self.logging_widgets['log_compact'])
        layout.addRow(self.logging_widgets['log_autoscroll'])
        layout.addRow('Progress Step:', self.logging_widgets['log_progress_step'])
        layout.addRow('Error Tail:', self.logging_widgets['log_error_tail'])
        layout.addRow(self.logging_widgets['log_show_options_pretty'])
        layout.addRow(self.logging_widgets['log_show_options_json'])
        return widget

    # ---- Settings I/O ----
    def load_settings(self):
        for _, widget_map in [('storage_widgets', self.storage_widgets),
                              ('analysis_widgets', self.analysis_widgets),
                              ('chapters_widgets', self.chapters_widgets),
                              ('merge_widgets', self.merge_widgets),
                              ('logging_widgets', self.logging_widgets)]:
            for key, widget in widget_map.items():
                self._set_widget_val(widget, self.config.get(key))

    def accept(self):
        for _, widget_map in [('storage_widgets', self.storage_widgets),
                              ('analysis_widgets', self.analysis_widgets),
                              ('chapters_widgets', self.chapters_widgets),
                              ('merge_widgets', self.merge_widgets),
                              ('logging_widgets', self.logging_widgets)]:
            for key, widget in widget_map.items():
                self.config.set(key, self._get_widget_val(widget))
        super().accept()

    # ---- generic widget helpers ----
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
        if path:
            line_edit.setText(path)

    def _browse_for_file(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select File", line_edit.text())
        if path:
            line_edit.setText(path)

    def _get_widget_val(self, widget):
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            return widget.value()
        if isinstance(widget, QComboBox):
            return widget.currentText()
        if isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            return widget.layout().itemAt(0).widget().text()
        return widget.text() if isinstance(widget, QLineEdit) else None

    def _set_widget_val(self, widget, value):
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox
        if isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentText(str(value))
        elif isinstance(widget, QLineEdit):
            widget.setText(str(value))
        elif isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            widget.layout().itemAt(0).widget().setText(str(value))
