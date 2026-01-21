# vsg_qt/ocr_dictionary_dialog/ui.py
# -*- coding: utf-8 -*-
"""
OCR Dictionary Editor Dialog

Provides a GUI for editing the three OCR correction databases:
    - Replacements (pattern-based corrections)
    - User Dictionary (custom valid words)
    - Names (proper names, character names)
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QComboBox, QCheckBox, QLabel,
    QGroupBox, QFormLayout, QMessageBox, QFileDialog,
    QDialogButtonBox, QSplitter, QFrame
)

from vsg_core.subtitles.ocr.dictionaries import (
    OCRDictionaries, ReplacementRule, RuleType, get_dictionaries
)
from vsg_core.subtitles.ocr.subtitle_edit import (
    SubtitleEditParser, SEDictionaryConfig, load_se_config, save_se_config
)


class ReplacementEditWidget(QWidget):
    """Widget for adding/editing a replacement rule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.pattern_edit = QLineEdit()
        self.pattern_edit.setPlaceholderText("e.g., l'm")
        layout.addRow("Pattern:", self.pattern_edit)

        self.replacement_edit = QLineEdit()
        self.replacement_edit.setPlaceholderText("e.g., I'm")
        layout.addRow("Replacement:", self.replacement_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Literal (exact match)", "literal")
        self.type_combo.addItem("Word (whole word only)", "word")
        self.type_combo.addItem("Word Start", "word_start")
        self.type_combo.addItem("Word End", "word_end")
        self.type_combo.addItem("Word Middle", "word_middle")
        self.type_combo.addItem("Regex", "regex")
        layout.addRow("Type:", self.type_combo)

        self.confidence_gated = QCheckBox("Only apply when OCR confidence is low")
        layout.addRow("", self.confidence_gated)

        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional description")
        layout.addRow("Description:", self.description_edit)

    def get_rule(self) -> Optional[ReplacementRule]:
        """Get the rule from current inputs."""
        pattern = self.pattern_edit.text().strip()
        replacement = self.replacement_edit.text()  # Can be empty

        if not pattern:
            return None

        return ReplacementRule(
            pattern=pattern,
            replacement=replacement,
            rule_type=self.type_combo.currentData(),
            confidence_gated=self.confidence_gated.isChecked(),
            enabled=True,
            description=self.description_edit.text().strip(),
        )

    def set_rule(self, rule: ReplacementRule):
        """Populate widget with rule data."""
        self.pattern_edit.setText(rule.pattern)
        self.replacement_edit.setText(rule.replacement)

        # Set type combo
        idx = self.type_combo.findData(rule.rule_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)

        self.confidence_gated.setChecked(rule.confidence_gated)
        self.description_edit.setText(rule.description or "")

    def clear(self):
        """Clear all inputs."""
        self.pattern_edit.clear()
        self.replacement_edit.clear()
        self.type_combo.setCurrentIndex(0)
        self.confidence_gated.setChecked(False)
        self.description_edit.clear()


class ReplacementsTab(QWidget):
    """Tab for managing replacement rules."""

    def __init__(self, dictionaries: OCRDictionaries, parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Pattern", "Replacement", "Type", "Conf. Gated", "Description"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table)

        # Edit widget
        edit_group = QGroupBox("Add/Edit Rule")
        self.edit_widget = ReplacementEditWidget()
        edit_layout = QVBoxLayout(edit_group)
        edit_layout.addWidget(self.edit_widget)

        # Buttons for edit
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add New")
        self.add_btn.clicked.connect(self._add_rule)
        self.update_btn = QPushButton("Update Selected")
        self.update_btn.clicked.connect(self._update_rule)
        self.update_btn.setEnabled(False)
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.clicked.connect(self._delete_rule)
        self.delete_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear Form")
        self.clear_btn.clicked.connect(self.edit_widget.clear)

        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.update_btn)
        btn_layout.addWidget(self.delete_btn)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        edit_layout.addLayout(btn_layout)

        layout.addWidget(edit_group)

        # Import/Export buttons
        io_layout = QHBoxLayout()
        import_btn = QPushButton("Import from File...")
        import_btn.clicked.connect(self._import_rules)
        export_btn = QPushButton("Export to File...")
        export_btn.clicked.connect(self._export_rules)
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._reset_defaults)

        io_layout.addWidget(import_btn)
        io_layout.addWidget(export_btn)
        io_layout.addStretch()
        io_layout.addWidget(reset_btn)
        layout.addLayout(io_layout)

    def _load_data(self):
        """Load rules into table."""
        rules = self.dictionaries.load_replacements()
        self.table.setRowCount(len(rules))

        for row, rule in enumerate(rules):
            self.table.setItem(row, 0, QTableWidgetItem(rule.pattern))
            self.table.setItem(row, 1, QTableWidgetItem(rule.replacement))
            self.table.setItem(row, 2, QTableWidgetItem(rule.rule_type))
            self.table.setItem(row, 3, QTableWidgetItem("Yes" if rule.confidence_gated else "No"))
            self.table.setItem(row, 4, QTableWidgetItem(rule.description or ""))

            # Store rule object in first column
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, rule)

    def _on_selection_changed(self):
        """Handle table selection change."""
        rows = self.table.selectionModel().selectedRows()
        has_selection = len(rows) > 0

        self.update_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

        if has_selection:
            row = rows[0].row()
            rule = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
            if rule:
                self.edit_widget.set_rule(rule)

    def _add_rule(self):
        """Add a new rule."""
        rule = self.edit_widget.get_rule()
        if not rule:
            QMessageBox.warning(self, "Invalid Rule", "Pattern cannot be empty.")
            return

        success, msg = self.dictionaries.add_replacement(rule)
        if success:
            self._load_data()
            self.edit_widget.clear()
        else:
            QMessageBox.warning(self, "Error", msg)

    def _update_rule(self):
        """Update the selected rule."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return

        row = rows[0].row()
        old_rule = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        new_rule = self.edit_widget.get_rule()

        if not new_rule:
            QMessageBox.warning(self, "Invalid Rule", "Pattern cannot be empty.")
            return

        success, msg = self.dictionaries.update_replacement(old_rule.pattern, new_rule)
        if success:
            self._load_data()
        else:
            QMessageBox.warning(self, "Error", msg)

    def _delete_rule(self):
        """Delete the selected rule."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return

        row = rows[0].row()
        rule = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete rule '{rule.pattern}' -> '{rule.replacement}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            success, msg = self.dictionaries.remove_replacement(rule.pattern, rule.rule_type)
            if success:
                self._load_data()
                self.edit_widget.clear()
            else:
                QMessageBox.warning(self, "Error", msg)

    def _import_rules(self):
        """Import rules from file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Replacement Rules",
            "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        added, skipped, errors = self.dictionaries.import_replacements(Path(path))

        msg = f"Imported {added} rules, skipped {skipped} duplicates."
        if errors:
            msg += f"\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n...and {len(errors) - 10} more errors"

        QMessageBox.information(self, "Import Complete", msg)
        self._load_data()

    def _export_rules(self):
        """Export rules to file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Replacement Rules",
            "replacements.txt", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        if self.dictionaries.export_replacements(Path(path)):
            QMessageBox.information(self, "Export Complete", f"Rules exported to {path}")
        else:
            QMessageBox.warning(self, "Export Failed", "Failed to export rules.")

    def _reset_defaults(self):
        """Reset to default rules."""
        reply = QMessageBox.question(
            self, "Reset to Defaults",
            "This will replace all current rules with the defaults. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            from vsg_core.subtitles.ocr.dictionaries import DEFAULT_REPLACEMENT_RULES
            self.dictionaries.save_replacements(list(DEFAULT_REPLACEMENT_RULES))
            self._load_data()


class WordListTab(QWidget):
    """Tab for managing a simple word list (user dictionary or names)."""

    def __init__(self, dictionaries: OCRDictionaries, list_type: str = "user", parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries
        self.list_type = list_type  # "user" or "names"
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Search/filter
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Type to filter...")
        self.filter_edit.textChanged.connect(self._apply_filter)
        filter_layout.addWidget(self.filter_edit)
        layout.addLayout(filter_layout)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.setSortingEnabled(True)
        layout.addWidget(self.list_widget)

        # Add word input
        add_layout = QHBoxLayout()
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText("Enter word to add...")
        self.add_edit.returnPressed.connect(self._add_word)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_word)
        add_layout.addWidget(self.add_edit)
        add_layout.addWidget(add_btn)
        layout.addLayout(add_layout)

        # Action buttons
        btn_layout = QHBoxLayout()
        delete_btn = QPushButton("Delete Selected")
        delete_btn.clicked.connect(self._delete_selected)
        import_btn = QPushButton("Import from File...")
        import_btn.clicked.connect(self._import_words)
        export_btn = QPushButton("Export to File...")
        export_btn.clicked.connect(self._export_words)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)

        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(export_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(clear_btn)
        layout.addLayout(btn_layout)

        # Stats label
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)

    def _load_data(self):
        """Load words into list."""
        if self.list_type == "names":
            words = self.dictionaries.load_names()
        else:
            words = self.dictionaries.load_user_dictionary()

        self.list_widget.clear()
        for word in sorted(words, key=str.lower):
            self.list_widget.addItem(word)

        self._update_stats()
        self._apply_filter()

    def _update_stats(self):
        """Update stats label."""
        total = self.list_widget.count()
        visible = sum(1 for i in range(total) if not self.list_widget.item(i).isHidden())
        if visible == total:
            self.stats_label.setText(f"{total} words")
        else:
            self.stats_label.setText(f"Showing {visible} of {total} words")

    def _apply_filter(self):
        """Filter the list based on search text."""
        filter_text = self.filter_edit.text().lower()

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if filter_text:
                item.setHidden(filter_text not in item.text().lower())
            else:
                item.setHidden(False)

        self._update_stats()

    def _add_word(self):
        """Add a word to the list."""
        word = self.add_edit.text().strip()
        if not word:
            return

        if self.list_type == "names":
            success, msg = self.dictionaries.add_name(word)
        else:
            success, msg = self.dictionaries.add_user_word(word)

        if success:
            self._load_data()
            self.add_edit.clear()
        else:
            QMessageBox.warning(self, "Error", msg)

    def _delete_selected(self):
        """Delete selected words."""
        selected = self.list_widget.selectedItems()
        if not selected:
            return

        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {len(selected)} selected word(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        for item in selected:
            word = item.text()
            if self.list_type == "names":
                self.dictionaries.remove_name(word)
            else:
                self.dictionaries.remove_user_word(word)

        self._load_data()

    def _import_words(self):
        """Import words from file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Words",
            "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        added, skipped = self.dictionaries.import_wordlist(Path(path), self.list_type)
        QMessageBox.information(
            self, "Import Complete",
            f"Imported {added} words, skipped {skipped} duplicates."
        )
        self._load_data()

    def _export_words(self):
        """Export words to file."""
        default_name = "names.txt" if self.list_type == "names" else "user_dictionary.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Words",
            default_name, "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        if self.dictionaries.export_wordlist(Path(path), self.list_type):
            QMessageBox.information(self, "Export Complete", f"Words exported to {path}")
        else:
            QMessageBox.warning(self, "Export Failed", "Failed to export words.")

    def _clear_all(self):
        """Clear all words."""
        reply = QMessageBox.question(
            self, "Clear All",
            "This will delete all words from this dictionary. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            if self.list_type == "names":
                self.dictionaries.save_names(set())
            else:
                self.dictionaries.save_user_dictionary(set())
            self._load_data()


class SubtitleEditTab(QWidget):
    """Tab for managing Subtitle Edit dictionary integration."""

    def __init__(self, dictionaries: OCRDictionaries, parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries
        self.se_dir = dictionaries.config_dir / "subtitleedit"
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info section
        info_group = QGroupBox("Subtitle Edit Dictionaries")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "Place Subtitle Edit dictionary files in the folder below. "
            "Files are loaded automatically when OCR processing starts.\n\n"
            "Download files from: github.com/SubtitleEdit/subtitleedit/tree/main/Dictionaries"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        # Folder path display
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("Folder:"))
        self.folder_label = QLineEdit()
        self.folder_label.setReadOnly(True)
        self.folder_label.setText(str(self.se_dir))
        folder_layout.addWidget(self.folder_label)

        open_folder_btn = QPushButton("Open Folder")
        open_folder_btn.clicked.connect(self._open_folder)
        folder_layout.addWidget(open_folder_btn)
        info_layout.addLayout(folder_layout)

        layout.addWidget(info_group)

        # Enable/Disable switches
        toggles_group = QGroupBox("Dictionary Types")
        toggles_layout = QFormLayout(toggles_group)

        self.ocr_fix_check = QCheckBox()
        self.ocr_fix_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("OCR Fix Replace List (*_OCRFixReplaceList.xml):", self.ocr_fix_check)

        self.names_check = QCheckBox()
        self.names_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Names (*_names.xml):", self.names_check)

        self.no_break_check = QCheckBox()
        self.no_break_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("No Break After List (*_NoBreakAfterList.xml):", self.no_break_check)

        self.spell_words_check = QCheckBox()
        self.spell_words_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Spell Check Words (*_se.xml):", self.spell_words_check)

        self.interjections_check = QCheckBox()
        self.interjections_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Interjections (*_interjections_se.xml):", self.interjections_check)

        self.word_split_check = QCheckBox()
        self.word_split_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Word Split List (*_WordSplitList.txt):", self.word_split_check)

        layout.addWidget(toggles_group)

        # Available files list
        files_group = QGroupBox("Available Files")
        files_layout = QVBoxLayout(files_group)

        self.files_table = QTableWidget()
        self.files_table.setColumnCount(3)
        self.files_table.setHorizontalHeaderLabels(["File", "Type", "Status"])
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        files_layout.addWidget(self.files_table)

        # Refresh button
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Available Files")
        refresh_btn.clicked.connect(self._load_data)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addStretch()
        files_layout.addLayout(btn_layout)

        layout.addWidget(files_group)

        # Stats label
        self.stats_label = QLabel()
        layout.addWidget(self.stats_label)

    def _load_data(self):
        """Load available SE files and configuration."""
        # Ensure folder exists
        self.se_dir.mkdir(parents=True, exist_ok=True)

        # Load config
        config = load_se_config(self.dictionaries.config_dir)

        # Set checkboxes (block signals to avoid saving during load)
        self.ocr_fix_check.blockSignals(True)
        self.names_check.blockSignals(True)
        self.no_break_check.blockSignals(True)
        self.spell_words_check.blockSignals(True)
        self.interjections_check.blockSignals(True)
        self.word_split_check.blockSignals(True)

        self.ocr_fix_check.setChecked(config.ocr_fix_enabled)
        self.names_check.setChecked(config.names_enabled)
        self.no_break_check.setChecked(config.no_break_enabled)
        self.spell_words_check.setChecked(config.spell_words_enabled)
        self.interjections_check.setChecked(config.interjections_enabled)
        self.word_split_check.setChecked(config.word_split_enabled)

        self.ocr_fix_check.blockSignals(False)
        self.names_check.blockSignals(False)
        self.no_break_check.blockSignals(False)
        self.spell_words_check.blockSignals(False)
        self.interjections_check.blockSignals(False)
        self.word_split_check.blockSignals(False)

        # Scan for available files
        parser = SubtitleEditParser(self.se_dir)
        available = parser.get_available_files()

        # Populate table
        all_files = []
        type_names = {
            'ocr_fix': 'OCR Fix List',
            'names': 'Names',
            'no_break': 'No Break After',
            'spell_words': 'Spell Words',
            'interjections': 'Interjections',
            'word_split': 'Word Split',
        }
        type_enabled = {
            'ocr_fix': config.ocr_fix_enabled,
            'names': config.names_enabled,
            'no_break': config.no_break_enabled,
            'spell_words': config.spell_words_enabled,
            'interjections': config.interjections_enabled,
            'word_split': config.word_split_enabled,
        }

        for file_type, files in available.items():
            for path in files:
                enabled = type_enabled.get(file_type, True)
                all_files.append((path.name, type_names.get(file_type, file_type), enabled))

        self.files_table.setRowCount(len(all_files))
        for row, (name, file_type, enabled) in enumerate(all_files):
            self.files_table.setItem(row, 0, QTableWidgetItem(name))
            self.files_table.setItem(row, 1, QTableWidgetItem(file_type))
            status = "Enabled" if enabled else "Disabled"
            status_item = QTableWidgetItem(status)
            if not enabled:
                status_item.setForeground(Qt.GlobalColor.gray)
            self.files_table.setItem(row, 2, status_item)

        # Update stats
        total_files = len(all_files)
        enabled_files = sum(1 for _, _, enabled in all_files if enabled)
        if total_files == 0:
            self.stats_label.setText("No Subtitle Edit dictionary files found. Add files to the folder above.")
        else:
            self.stats_label.setText(f"{enabled_files} of {total_files} files enabled")

    def _save_config(self):
        """Save current configuration."""
        config = SEDictionaryConfig(
            ocr_fix_enabled=self.ocr_fix_check.isChecked(),
            names_enabled=self.names_check.isChecked(),
            no_break_enabled=self.no_break_check.isChecked(),
            spell_words_enabled=self.spell_words_check.isChecked(),
            interjections_enabled=self.interjections_check.isChecked(),
            word_split_enabled=self.word_split_check.isChecked(),
        )
        save_se_config(self.dictionaries.config_dir, config)
        # Refresh to update status column
        self._load_data()

    def _open_folder(self):
        """Open the SE dictionaries folder in file manager."""
        import subprocess
        import sys

        self.se_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == 'darwin':
            subprocess.run(['open', str(self.se_dir)])
        elif sys.platform == 'win32':
            subprocess.run(['explorer', str(self.se_dir)])
        else:
            subprocess.run(['xdg-open', str(self.se_dir)])


class OCRDictionaryDialog(QDialog):
    """
    Dialog for editing OCR correction dictionaries.

    Provides tabs for:
        - Replacement rules (pattern-based corrections)
        - User dictionary (custom valid words)
        - Names dictionary (proper names)
        - Subtitle Edit dictionaries (external OCR fix lists)
    """

    def __init__(self, parent=None, config_dir: Optional[Path] = None):
        super().__init__(parent)
        self.dictionaries = get_dictionaries(config_dir)
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle("OCR Dictionary Editor")
        self.setMinimumSize(700, 500)
        self.resize(800, 600)

        layout = QVBoxLayout(self)

        # Description
        desc = QLabel(
            "Edit the dictionaries used for OCR text correction. "
            "Changes are saved automatically."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Tabs
        self.tabs = QTabWidget()

        # Replacements tab
        self.replacements_tab = ReplacementsTab(self.dictionaries)
        self.tabs.addTab(self.replacements_tab, "Replacements")

        # User Dictionary tab
        self.user_dict_tab = WordListTab(self.dictionaries, "user")
        self.tabs.addTab(self.user_dict_tab, "User Dictionary")

        # Names tab
        self.names_tab = WordListTab(self.dictionaries, "names")
        self.tabs.addTab(self.names_tab, "Names")

        # Subtitle Edit tab
        self.subtitle_edit_tab = SubtitleEditTab(self.dictionaries)
        self.tabs.addTab(self.subtitle_edit_tab, "Subtitle Edit")

        layout.addWidget(self.tabs)

        # Help text based on selected tab
        self.help_label = QLabel()
        self.help_label.setWordWrap(True)
        self.help_label.setStyleSheet("color: gray; font-size: 11px;")
        self._update_help_text(0)
        self.tabs.currentChanged.connect(self._update_help_text)
        layout.addWidget(self.help_label)

        # Close button
        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_box.rejected.connect(self.accept)
        layout.addWidget(btn_box)

    def _update_help_text(self, index: int):
        """Update help text based on selected tab."""
        help_texts = [
            "Replacements: Pattern-based corrections for OCR errors. "
            "'Literal' matches exact text, 'Word' matches whole words only. "
            "Import format: pattern|replacement|type|confidence_gated",

            "User Dictionary: Words that won't be flagged as unknown. "
            "Add custom words, technical terms, or foreign words here.",

            "Names: Proper names (characters, places) that won't be flagged. "
            "Useful for anime/movie character names, romaji, etc.",

            "Subtitle Edit: Use dictionary files from Subtitle Edit. "
            "Download from GitHub and place in the subtitleedit folder. "
            "Includes OCR fixes, names, word splitting, and more.",
        ]
        if index < len(help_texts):
            self.help_label.setText(help_texts[index])
        else:
            self.help_label.setText("")
