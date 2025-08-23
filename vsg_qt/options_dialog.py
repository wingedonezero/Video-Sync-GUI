# -*- coding: utf-8 -*-

"""
The settings/options dialog window for the PyQt application.
"""

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox,
    QListWidget, QListWidgetItem, QLabel
)
from PySide6.QtCore import Qt

class RuleDialog(QDialog):
    """A dialog for creating and editing a merge profile rule."""
    def __init__(self, rule=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Edit Merge Rule')

        self.source_combo = QComboBox()
        self.source_combo.addItems(['REF', 'SEC', 'TER'])
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Video', 'Audio', 'Subtitles'])
        self.lang_edit = QLineEdit('any')
        self.exclude_langs_edit = QLineEdit()
        self.enabled_check = QCheckBox('Enabled')
        self.enabled_check.setChecked(True)
        self.default_check = QCheckBox('⭐ Make Default Track')
        self.swap_check = QCheckBox('Swap order of first two tracks found')

        layout = QFormLayout(self)
        layout.addRow('Source:', self.source_combo)
        layout.addRow('Track Type:', self.type_combo)
        layout.addRow('Include Languages (any, eng, ...):', self.lang_edit)
        layout.addRow('Exclude Languages (eng, jpn, ...):', self.exclude_langs_edit)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self.default_check)
        layout.addWidget(self.swap_check)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        self.type_combo.currentTextChanged.connect(self.on_type_changed)

        if rule:
            self.source_combo.setCurrentText(rule.get('source', 'REF'))
            self.type_combo.setCurrentText(rule.get('type', 'Video'))
            self.lang_edit.setText(rule.get('lang', 'any'))
            self.exclude_langs_edit.setText(rule.get('exclude_langs', ''))
            self.enabled_check.setChecked(rule.get('enabled', True))
            self.default_check.setChecked(rule.get('is_default', False))
            self.swap_check.setChecked(rule.get('swap_first_two', False))

        self.on_type_changed(self.type_combo.currentText())

    def on_type_changed(self, text):
        """Show/hide options based on track type."""
        is_video = text == 'Video'
        is_subs = text == 'Subtitles'
        self.default_check.setVisible(not is_video)
        self.swap_check.setVisible(is_subs)

    def get_rule(self):
        rule_type = self.type_combo.currentText()
        return {
            'source': self.source_combo.currentText(),
            'type': rule_type,
            'lang': self.lang_edit.text().strip().lower() or 'any',
            'exclude_langs': self.exclude_langs_edit.text().strip().lower(),
            'enabled': self.enabled_check.isChecked(),
            'is_default': self.default_check.isChecked() and rule_type != 'Video',
            'swap_first_two': self.swap_check.isChecked() and rule_type == 'Subtitles'
        }

class OptionsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle('Application Settings')
        self.setMinimumWidth(600)
        self.tabs = QTabWidget()
        self.storage_widgets, self.analysis_widgets, self.chapters_widgets, self.merge_widgets, self.logging_widgets = {}, {}, {}, {}, {}
        self.profile_list_widget = QListWidget()
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.tabs)
        self.tabs.addTab(self._create_merge_plan_tab(), 'Merge Plan')
        self.tabs.addTab(self._create_storage_tab(), 'Storage')
        self.tabs.addTab(self._create_analysis_tab(), 'Analysis')
        self.tabs.addTab(self._create_chapters_tab(), 'Chapters')
        self.tabs.addTab(self._create_merge_behavior_tab(), 'Merge Behavior')
        self.tabs.addTab(self._create_logging_tab(), 'Logging')
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept); button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)
        self.load_settings()

    def _create_merge_plan_tab(self):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.addWidget(self.profile_list_widget, 3)
        button_layout = QVBoxLayout()
        for text, slot in [('Add Rule...', self.add_rule), ('Edit Rule...', self.edit_rule), ('Remove Rule', self.remove_rule)]:
            btn = QPushButton(text); btn.clicked.connect(slot); button_layout.addWidget(btn)
        button_layout.addStretch()
        for text, slot in [('Move Up', self.move_rule_up), ('Move Down', self.move_rule_down)]:
            btn = QPushButton(text); btn.clicked.connect(slot); button_layout.addWidget(btn)
        layout.addLayout(button_layout, 1)
        return widget

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
        self.analysis_widgets['analysis_mode'] = QComboBox(); self.analysis_widgets['analysis_mode'].addItems(['Audio Correlation', 'VideoDiff'])
        self.analysis_widgets['scan_chunk_count'] = QSpinBox(minimum=1, maximum=100)
        self.analysis_widgets['scan_chunk_duration'] = QSpinBox(minimum=1, maximum=120)
        self.analysis_widgets['min_match_pct'] = QDoubleSpinBox(minimum=0.1, maximum=100.0, decimals=1, singleStep=1.0)
        self.analysis_widgets['videodiff_error_min'] = QDoubleSpinBox(minimum=0.0, maximum=500.0, decimals=2)
        self.analysis_widgets['videodiff_error_max'] = QDoubleSpinBox(minimum=0.0, maximum=500.0, decimals=2)
        self.analysis_widgets['analysis_lang_ref'] = QLineEdit(); self.analysis_widgets['analysis_lang_ref'].setPlaceholderText('Blank = first available')
        self.analysis_widgets['analysis_lang_sec'] = QLineEdit(); self.analysis_widgets['analysis_lang_sec'].setPlaceholderText('Blank = first available')
        self.analysis_widgets['analysis_lang_ter'] = QLineEdit(); self.analysis_widgets['analysis_lang_ter'].setPlaceholderText('Blank = first available')
        layout.addRow('Analysis Mode:', self.analysis_widgets['analysis_mode'])
        layout.addRow('Audio: Scan Chunks:', self.analysis_widgets['scan_chunk_count']); layout.addRow('Audio: Chunk Duration (s):', self.analysis_widgets['scan_chunk_duration'])
        layout.addRow('Audio: Minimum Match %:', self.analysis_widgets['min_match_pct']); layout.addRow('VideoDiff: Min Allowed Error:', self.analysis_widgets['videodiff_error_min'])
        layout.addRow('VideoDiff: Max Allowed Error:', self.analysis_widgets['videodiff_error_max']); layout.addRow(QLabel('<b>Analysis Audio Track Selection</b>'))
        layout.addRow('REF Language:', self.analysis_widgets['analysis_lang_ref']); layout.addRow('SEC Language:', self.analysis_widgets['analysis_lang_sec'])
        layout.addRow('TER Language:', self.analysis_widgets['analysis_lang_ter'])
        return widget

    def _create_chapters_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.chapters_widgets['rename_chapters'] = QCheckBox('Rename to "Chapter NN"')
        self.chapters_widgets['snap_chapters'] = QCheckBox('Snap chapter timestamps to nearest keyframe')
        self.chapters_widgets['snap_mode'] = QComboBox(); self.chapters_widgets['snap_mode'].addItems(['previous', 'nearest'])
        self.chapters_widgets['snap_threshold_ms'] = QSpinBox(minimum=0, maximum=5000, singleStep=50)
        self.chapters_widgets['snap_starts_only'] = QCheckBox('Only snap chapter start times (not end times)')
        layout.addWidget(self.chapters_widgets['rename_chapters']); layout.addWidget(self.chapters_widgets['snap_chapters'])
        layout.addRow('Snap Mode:', self.chapters_widgets['snap_mode']); layout.addRow('Snap Threshold (ms):', self.chapters_widgets['snap_threshold_ms'])
        layout.addWidget(self.chapters_widgets['snap_starts_only'])
        return widget

    def _create_merge_behavior_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.merge_widgets['apply_dialog_norm_gain'] = QCheckBox('Remove dialog normalization gain (AC3/E-AC3)')
        self.merge_widgets['exclude_codecs'] = QLineEdit()
        self.merge_widgets['exclude_codecs'].setPlaceholderText('e.g., ac3, dts, pcm')

        layout.addRow(self.merge_widgets['apply_dialog_norm_gain'])
        layout.addRow('Exclude codecs (comma-separated):', self.merge_widgets['exclude_codecs'])
        return widget

    def _create_logging_tab(self):
        widget = QWidget()
        layout = QFormLayout(widget)
        self.logging_widgets['log_compact'] = QCheckBox('Use compact logging'); self.logging_widgets['log_autoscroll'] = QCheckBox('Auto-scroll log view during jobs')
        self.logging_widgets['log_progress_step'] = QSpinBox(minimum=1, maximum=100, suffix='%')
        self.logging_widgets['log_error_tail'] = QSpinBox(minimum=0, maximum=1000, suffix=' lines')
        self.logging_widgets['log_show_options_pretty'] = QCheckBox('Show mkvmerge options in log (pretty text)')
        self.logging_widgets['log_show_options_json'] = QCheckBox('Show mkvmerge options in log (raw JSON)')
        layout.addRow(self.logging_widgets['log_compact']); layout.addRow(self.logging_widgets['log_autoscroll'])
        layout.addRow('Progress Step:', self.logging_widgets['log_progress_step']); layout.addRow('Error Tail:', self.logging_widgets['log_error_tail'])
        layout.addRow(self.logging_widgets['log_show_options_pretty']); layout.addRow(self.logging_widgets['log_show_options_json'])
        return widget

    def load_settings(self):
        for key, widget_map in [('storage_widgets', self.storage_widgets), ('analysis_widgets', self.analysis_widgets), ('chapters_widgets', self.chapters_widgets), ('merge_widgets', self.merge_widgets), ('logging_widgets', self.logging_widgets)]:
            for key, widget in widget_map.items(): self._set_widget_val(widget, self.config.get(key))
        self.populate_profile_list()

    def accept(self):
        for key, widget_map in [('storage_widgets', self.storage_widgets), ('analysis_widgets', self.analysis_widgets), ('chapters_widgets', self.chapters_widgets), ('merge_widgets', self.merge_widgets), ('logging_widgets', self.logging_widgets)]:
            for key, widget in widget_map.items(): self.config.set(key, self._get_widget_val(widget))
        self.save_profile_from_list()
        super().accept()

    def populate_profile_list(self):
        self.profile_list_widget.clear()
        profile = self.config.get('merge_profile', [])
        for rule in profile:
            item = QListWidgetItem(); item.setData(Qt.UserRole, rule); self.update_item_text(item); self.profile_list_widget.addItem(item)

    def update_item_text(self, item: QListWidgetItem):
        rule = item.data(Qt.UserRole)
        status = "✅" if rule.get('enabled') else "❌"
        default = "⭐" if rule.get('is_default') else ""
        swap = "🔄" if rule.get('swap_first_two') else ""
        include_lang = rule.get('lang', 'any')
        exclude_lang = rule.get('exclude_langs', '')

        lang_str = f"In: {include_lang}"
        if exclude_lang:
            lang_str += f", Ex: {exclude_lang}"

        text = f"{status} {rule['source']} -> {rule['type']} ({lang_str}) {swap}{default}"
        item.setText(text.strip())

    def add_rule(self):
        dialog = RuleDialog(parent=self)
        if dialog.exec():
            new_rule = dialog.get_rule(); self.handle_flag_rules(new_rule)
            item = QListWidgetItem(); item.setData(Qt.UserRole, new_rule); self.update_item_text(item); self.profile_list_widget.addItem(item)

    def edit_rule(self):
        item = self.profile_list_widget.currentItem()
        if not item: return
        dialog = RuleDialog(rule=item.data(Qt.UserRole), parent=self)
        if dialog.exec():
            updated_rule = dialog.get_rule(); self.handle_flag_rules(updated_rule, item)
            item.setData(Qt.UserRole, updated_rule); self.update_item_text(item)

    def handle_flag_rules(self, new_rule, current_item=None):
        """Ensure only one default rule per track type."""
        if new_rule.get('is_default'):
            for i in range(self.profile_list_widget.count()):
                item = self.profile_list_widget.item(i)
                if item == current_item: continue
                rule = item.data(Qt.UserRole)
                if rule.get('type') == new_rule.get('type'):
                    rule['is_default'] = False
                    self.update_item_text(item)

    def remove_rule(self):
        item = self.profile_list_widget.currentItem()
        if item: self.profile_list_widget.takeItem(self.profile_list_widget.row(item))

    def move_rule_up(self):
        row = self.profile_list_widget.currentRow()
        if row > 0:
            item = self.profile_list_widget.takeItem(row); self.profile_list_widget.insertItem(row - 1, item); self.profile_list_widget.setCurrentRow(row - 1)

    def move_rule_down(self):
        row = self.profile_list_widget.currentRow()
        if row < self.profile_list_widget.count() - 1:
            item = self.profile_list_widget.takeItem(row); self.profile_list_widget.insertItem(row + 1, item); self.profile_list_widget.setCurrentRow(row + 1)

    def save_profile_from_list(self):
        new_profile = []
        for i in range(self.profile_list_widget.count()):
            item = self.profile_list_widget.item(i); rule = item.data(Qt.UserRole)
            rule['priority'] = (i + 1) * 10; new_profile.append(rule)
        self.config.set('merge_profile', new_profile)

    def _create_dir_input(self):
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(); button = QPushButton('Browse…'); layout.addWidget(line_edit); layout.addWidget(button)
        button.clicked.connect(lambda: self._browse_for_dir(line_edit)); return widget

    def _create_file_input(self):
        widget = QWidget(); layout = QHBoxLayout(widget); layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(); button = QPushButton('Browse…'); layout.addWidget(line_edit); layout.addWidget(button)
        button.clicked.connect(lambda: self._browse_for_file(line_edit)); return widget

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
        if isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            return widget.layout().itemAt(0).widget().text()
        return widget.text() if isinstance(widget, QLineEdit) else None

    def _set_widget_val(self, widget, value):
        if isinstance(widget, QCheckBox): widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)): widget.setValue(value)
        elif isinstance(widget, QComboBox): widget.setCurrentText(str(value))
        elif isinstance(widget, QLineEdit): widget.setText(str(value))
        elif isinstance(widget, QWidget) and widget.layout() and isinstance(widget.layout().itemAt(0).widget(), QLineEdit):
            widget.layout().itemAt(0).widget().setText(str(value))
