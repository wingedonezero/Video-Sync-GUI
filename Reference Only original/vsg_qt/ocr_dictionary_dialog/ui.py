# vsg_qt/ocr_dictionary_dialog/ui.py
"""
OCR Dictionary Editor Dialog

Provides a GUI for editing the three OCR correction databases:
    - Replacements (pattern-based corrections)
    - User Dictionary (custom valid words)
    - Names (proper names, character names)
"""

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vsg_core.subtitles.ocr.dictionaries import (
    OCRDictionaries,
    ReplacementRule,
    get_dictionaries,
)
from vsg_core.subtitles.ocr.subtitle_edit import (
    SEDictionaryConfig,
    SubtitleEditParser,
    load_se_config,
    save_se_config,
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

    def get_rule(self) -> ReplacementRule | None:
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
        self._se_rules = []  # Cache for SE rules
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Show:"))
        self.source_filter = QComboBox()
        self.source_filter.addItem("User Rules", "user")
        self.source_filter.addItem("SE Rules (read-only)", "se")
        self.source_filter.addItem("All Rules", "all")
        self.source_filter.currentIndexChanged.connect(self._load_data)
        filter_layout.addWidget(self.source_filter)
        filter_layout.addStretch()

        self.rules_count_label = QLabel()
        filter_layout.addWidget(self.rules_count_label)
        layout.addLayout(filter_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Source", "Pattern", "Replacement", "Type", "Conf. Gated", "Description"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.Stretch
        )
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

    def _load_se_rules(self):
        """Load SE replacement rules from all available OCR fix files."""
        if self._se_rules:
            return self._se_rules

        se_dir = self.dictionaries.config_dir / "subtitleedit"
        if not se_dir.exists():
            return []

        parser = SubtitleEditParser(se_dir)
        available = parser.get_available_files()
        ocr_fix_files = available.get("ocr_fix", [])

        rules = []
        for path in ocr_fix_files:
            se_dicts = parser.parse_ocr_fix_list(path)
            # Combine all rule types
            for rule in se_dicts.whole_lines:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.partial_lines_always:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.partial_lines:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.begin_lines:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.end_lines:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.whole_words:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.partial_words_always:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.partial_words:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )
            for rule in se_dicts.regex_rules:
                rules.append(
                    ("SE", rule.from_text, rule.to_text, rule.rule_type, False, rule)
                )

        self._se_rules = rules
        return rules

    def _load_data(self):
        """Load rules into table based on source filter."""
        source_filter = self.source_filter.currentData()

        all_rows = []

        # Load user rules
        if source_filter in ("user", "all"):
            user_rules = self.dictionaries.load_replacements()
            for rule in user_rules:
                all_rows.append(
                    (
                        "User",
                        rule.pattern,
                        rule.replacement,
                        rule.rule_type,
                        rule.confidence_gated,
                        rule.description or "",
                        rule,
                        True,
                    )
                )

        # Load SE rules
        if source_filter in ("se", "all"):
            se_rules = self._load_se_rules()
            for (
                source,
                pattern,
                replacement,
                rule_type,
                conf_gated,
                rule_obj,
            ) in se_rules:
                all_rows.append(
                    (
                        source,
                        pattern,
                        replacement,
                        rule_type,
                        conf_gated,
                        "",
                        rule_obj,
                        False,
                    )
                )

        self.table.setRowCount(len(all_rows))

        for row, (
            source,
            pattern,
            replacement,
            rule_type,
            conf_gated,
            desc,
            rule_obj,
            is_user,
        ) in enumerate(all_rows):
            # Source column
            source_item = QTableWidgetItem(source)
            source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not is_user:
                source_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 0, source_item)

            # Pattern column
            pattern_item = QTableWidgetItem(pattern)
            if not is_user:
                pattern_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 1, pattern_item)

            # Replacement column
            replacement_item = QTableWidgetItem(replacement)
            if not is_user:
                replacement_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 2, replacement_item)

            # Type column
            type_item = QTableWidgetItem(rule_type)
            if not is_user:
                type_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 3, type_item)

            # Confidence gated column
            conf_item = QTableWidgetItem("Yes" if conf_gated else "No")
            if not is_user:
                conf_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 4, conf_item)

            # Description column
            desc_item = QTableWidgetItem(desc)
            if not is_user:
                desc_item.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, 5, desc_item)

            # Store rule object and user flag in first column
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, rule_obj)
            self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole + 1, is_user)

        # Update count label
        user_count = sum(1 for r in all_rows if r[7])
        se_count = sum(1 for r in all_rows if not r[7])
        if source_filter == "user":
            self.rules_count_label.setText(f"{user_count} user rules")
        elif source_filter == "se":
            self.rules_count_label.setText(f"{se_count} SE rules (read-only)")
        else:
            self.rules_count_label.setText(f"{user_count} user + {se_count} SE rules")

    def _on_selection_changed(self):
        """Handle table selection change."""
        rows = self.table.selectionModel().selectedRows()
        has_selection = len(rows) > 0

        if has_selection:
            row = rows[0].row()
            source_item = self.table.item(row, 0)
            rule = source_item.data(Qt.ItemDataRole.UserRole)
            is_user = source_item.data(Qt.ItemDataRole.UserRole + 1)

            # Only enable edit/delete for user rules
            self.update_btn.setEnabled(is_user if is_user else False)
            self.delete_btn.setEnabled(is_user if is_user else False)
            self.add_btn.setEnabled(True)

            if rule:
                # For user rules, populate the edit widget
                if is_user and hasattr(rule, "pattern"):
                    self.edit_widget.set_rule(rule)
                elif not is_user:
                    # For SE rules, show in edit widget but user can't save changes
                    self.edit_widget.pattern_edit.setText(
                        rule.from_text if hasattr(rule, "from_text") else ""
                    )
                    self.edit_widget.replacement_edit.setText(
                        rule.to_text if hasattr(rule, "to_text") else ""
                    )
                    # Find closest match for type
                    se_type = (
                        rule.rule_type if hasattr(rule, "rule_type") else "literal"
                    )
                    type_map = {
                        "whole_line": "literal",
                        "partial_line": "literal",
                        "partial_line_always": "literal",
                        "begin_line": "word_start",
                        "end_line": "word_end",
                        "whole_word": "word",
                        "partial_word": "word_middle",
                        "partial_word_always": "word_middle",
                        "regex": "regex",
                    }
                    mapped_type = type_map.get(se_type, "literal")
                    idx = self.edit_widget.type_combo.findData(mapped_type)
                    if idx >= 0:
                        self.edit_widget.type_combo.setCurrentIndex(idx)
                    self.edit_widget.confidence_gated.setChecked(False)
                    self.edit_widget.description_edit.setText(f"(SE: {se_type})")
        else:
            self.update_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

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
        source_item = self.table.item(row, 0)
        old_rule = source_item.data(Qt.ItemDataRole.UserRole)
        is_user = source_item.data(Qt.ItemDataRole.UserRole + 1)

        if not is_user:
            QMessageBox.warning(self, "Cannot Edit", "SE rules are read-only.")
            return

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
        source_item = self.table.item(row, 0)
        rule = source_item.data(Qt.ItemDataRole.UserRole)
        is_user = source_item.data(Qt.ItemDataRole.UserRole + 1)

        if not is_user:
            QMessageBox.warning(self, "Cannot Delete", "SE rules are read-only.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete rule '{rule.pattern}' -> '{rule.replacement}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            success, msg = self.dictionaries.remove_replacement(
                rule.pattern, rule.rule_type
            )
            if success:
                self._load_data()
                self.edit_widget.clear()
            else:
                QMessageBox.warning(self, "Error", msg)

    def _import_rules(self):
        """Import rules from file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Replacement Rules", "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        added, skipped, errors = self.dictionaries.import_replacements(Path(path))

        msg = f"Imported {added} rules, skipped {skipped} duplicates."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n...and {len(errors) - 10} more errors"

        QMessageBox.information(self, "Import Complete", msg)
        self._load_data()

    def _export_rules(self):
        """Export rules to file."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Replacement Rules",
            "replacements.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        if self.dictionaries.export_replacements(Path(path)):
            QMessageBox.information(
                self, "Export Complete", f"Rules exported to {path}"
            )
        else:
            QMessageBox.warning(self, "Export Failed", "Failed to export rules.")

    def _reset_defaults(self):
        """Reset to default rules."""
        reply = QMessageBox.question(
            self,
            "Reset to Defaults",
            "This will replace all current rules with the defaults. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            from vsg_core.subtitles.ocr.dictionaries import DEFAULT_REPLACEMENT_RULES

            self.dictionaries.save_replacements(list(DEFAULT_REPLACEMENT_RULES))
            self._load_data()


class WordListTab(QWidget):
    """Tab for managing a simple word list (user dictionary or names)."""

    def __init__(
        self, dictionaries: OCRDictionaries, list_type: str = "user", parent=None
    ):
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
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
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
        visible = sum(
            1 for i in range(total) if not self.list_widget.item(i).isHidden()
        )
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
            self,
            "Confirm Delete",
            f"Delete {len(selected)} selected word(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
            self, "Import Words", "", "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        added, skipped = self.dictionaries.import_wordlist(Path(path), self.list_type)
        QMessageBox.information(
            self,
            "Import Complete",
            f"Imported {added} words, skipped {skipped} duplicates.",
        )
        self._load_data()

    def _export_words(self):
        """Export words to file."""
        default_name = (
            "names.txt" if self.list_type == "names" else "user_dictionary.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Words", default_name, "Text Files (*.txt);;All Files (*)"
        )
        if not path:
            return

        if self.dictionaries.export_wordlist(Path(path), self.list_type):
            QMessageBox.information(
                self, "Export Complete", f"Words exported to {path}"
            )
        else:
            QMessageBox.warning(self, "Export Failed", "Failed to export words.")

    def _clear_all(self):
        """Clear all words."""
        reply = QMessageBox.question(
            self,
            "Clear All",
            "This will delete all words from this dictionary. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
        toggles_layout.addRow(
            "OCR Fix Replace List (*_OCRFixReplaceList.xml):", self.ocr_fix_check
        )

        self.names_check = QCheckBox()
        self.names_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Names (*_names.xml):", self.names_check)

        self.no_break_check = QCheckBox()
        self.no_break_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow(
            "No Break After List (*_NoBreakAfterList.xml):", self.no_break_check
        )

        self.spell_words_check = QCheckBox()
        self.spell_words_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow("Spell Check Words (*_se.xml):", self.spell_words_check)

        self.interjections_check = QCheckBox()
        self.interjections_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow(
            "Interjections (*_interjections_se.xml):", self.interjections_check
        )

        self.word_split_check = QCheckBox()
        self.word_split_check.stateChanged.connect(self._save_config)
        toggles_layout.addRow(
            "Word Split List (*_WordSplitList.txt):", self.word_split_check
        )

        layout.addWidget(toggles_group)

        # Available files list
        files_group = QGroupBox("Available Files")
        files_layout = QVBoxLayout(files_group)

        self.files_table = QTableWidget()
        self.files_table.setColumnCount(3)
        self.files_table.setHorizontalHeaderLabels(["File", "Type", "Status"])
        self.files_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.files_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
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
            "ocr_fix": "OCR Fix List",
            "names": "Names",
            "no_break": "No Break After",
            "spell_words": "Spell Words",
            "interjections": "Interjections",
            "word_split": "Word Split",
        }
        type_enabled = {
            "ocr_fix": config.ocr_fix_enabled,
            "names": config.names_enabled,
            "no_break": config.no_break_enabled,
            "spell_words": config.spell_words_enabled,
            "interjections": config.interjections_enabled,
            "word_split": config.word_split_enabled,
        }

        for file_type, files in available.items():
            for path in files:
                enabled = type_enabled.get(file_type, True)
                all_files.append(
                    (path.name, type_names.get(file_type, file_type), enabled)
                )

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
            self.stats_label.setText(
                "No Subtitle Edit dictionary files found. Add files to the folder above."
            )
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

        if sys.platform == "darwin":
            subprocess.run(["open", str(self.se_dir)])
        elif sys.platform == "win32":
            subprocess.run(["explorer", str(self.se_dir)])
        else:
            subprocess.run(["xdg-open", str(self.se_dir)])


class WordListsConfigTab(QWidget):
    """
    Tab for configuring word list behavior and priority.

    Shows all word lists with checkboxes for:
    - Enabled: Whether the list is active
    - Validates: Words in this list won't show as "unknown"
    - Protects: Words in this list won't be auto-corrected
    - Accept Fix: Words in this list are valid correction targets

    Lists can be reordered by dragging or using up/down buttons.
    """

    def __init__(self, dictionaries: OCRDictionaries, parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries
        self.config_dir = dictionaries.config_dir
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info section
        info_group = QGroupBox("Word List Configuration")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "Configure how each word list is used during OCR processing. "
            "Lists are checked in order from top to bottom.\n\n"
            "Flags:\n"
            "  - Enabled: List is active\n"
            "  - Validates: Words won't be flagged as 'unknown'\n"
            "  - Protects: Words won't be auto-corrected by fix rules\n"
            "  - Accept Fix: Words are valid targets for OCR corrections"
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)
        layout.addWidget(info_group)

        # Word lists table
        table_group = QGroupBox("Word Lists (Priority Order)")
        table_layout = QVBoxLayout(table_group)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Order", "Name", "Source", "Words", "Validates", "Protects", "Accept Fix"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            5, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(
            6, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table_layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()

        self.move_up_btn = QPushButton("Move Up")
        self.move_up_btn.clicked.connect(self._move_up)
        btn_layout.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton("Move Down")
        self.move_down_btn.clicked.connect(self._move_down)
        btn_layout.addWidget(self.move_down_btn)

        btn_layout.addStretch()

        self.reset_btn = QPushButton("Reset to Defaults")
        self.reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(self.reset_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._load_data)
        btn_layout.addWidget(self.refresh_btn)

        table_layout.addLayout(btn_layout)
        layout.addWidget(table_group)

        # Status
        self.status_label = QLabel()
        layout.addWidget(self.status_label)

    def _load_data(self):
        """Load word list configurations."""
        # Initialize or get the validation manager
        try:
            manager = self.dictionaries.get_validation_manager()
        except Exception as e:
            self.status_label.setText(f"Error loading word lists: {e}")
            return

        word_lists = manager.get_word_lists()

        self.table.setRowCount(len(word_lists))
        for row, wl in enumerate(word_lists):
            # Order
            order_item = QTableWidgetItem(str(wl.config.order))
            order_item.setFlags(order_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, order_item)

            # Name
            name_item = QTableWidgetItem(wl.config.name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, name_item)

            # Source
            source_item = QTableWidgetItem(wl.config.source)
            source_item.setFlags(source_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, source_item)

            # Word count
            count_item = QTableWidgetItem(f"{wl.word_count:,}")
            count_item.setFlags(count_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, count_item)

            # Validates checkbox
            validates_widget = QWidget()
            validates_layout = QHBoxLayout(validates_widget)
            validates_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            validates_layout.setContentsMargins(0, 0, 0, 0)
            validates_check = QCheckBox()
            validates_check.setChecked(wl.config.validates_known)
            validates_check.stateChanged.connect(
                lambda state, name=wl.config.name: self._on_validates_changed(
                    name, state
                )
            )
            validates_layout.addWidget(validates_check)
            self.table.setCellWidget(row, 4, validates_widget)

            # Protects checkbox
            protects_widget = QWidget()
            protects_layout = QHBoxLayout(protects_widget)
            protects_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            protects_layout.setContentsMargins(0, 0, 0, 0)
            protects_check = QCheckBox()
            protects_check.setChecked(wl.config.protects_from_fix)
            protects_check.stateChanged.connect(
                lambda state, name=wl.config.name: self._on_protects_changed(
                    name, state
                )
            )
            protects_layout.addWidget(protects_check)
            self.table.setCellWidget(row, 5, protects_widget)

            # Accept Fix checkbox
            accept_widget = QWidget()
            accept_layout = QHBoxLayout(accept_widget)
            accept_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            accept_layout.setContentsMargins(0, 0, 0, 0)
            accept_check = QCheckBox()
            accept_check.setChecked(wl.config.accepts_as_fix_result)
            accept_check.stateChanged.connect(
                lambda state, name=wl.config.name: self._on_accept_changed(name, state)
            )
            accept_layout.addWidget(accept_check)
            self.table.setCellWidget(row, 6, accept_widget)

        # Update status
        total_words = sum(wl.word_count for wl in word_lists)
        sum(1 for wl in word_lists if wl.enabled)
        self.status_label.setText(
            f"{len(word_lists)} word lists configured, {total_words:,} total words"
        )

    def _on_validates_changed(self, name: str, state: int):
        """Handle validates checkbox change."""
        manager = self.dictionaries.get_validation_manager()
        manager.update_word_list_config(
            name, validates_known=(state == Qt.CheckState.Checked.value)
        )

    def _on_protects_changed(self, name: str, state: int):
        """Handle protects checkbox change."""
        manager = self.dictionaries.get_validation_manager()
        manager.update_word_list_config(
            name, protects_from_fix=(state == Qt.CheckState.Checked.value)
        )

    def _on_accept_changed(self, name: str, state: int):
        """Handle accept fix checkbox change."""
        manager = self.dictionaries.get_validation_manager()
        manager.update_word_list_config(
            name, accepts_as_fix_result=(state == Qt.CheckState.Checked.value)
        )

    def _move_up(self):
        """Move selected list up in priority."""
        current_row = self.table.currentRow()
        if current_row <= 0:
            return

        manager = self.dictionaries.get_validation_manager()
        word_lists = manager.get_word_lists()

        if current_row < len(word_lists):
            # Swap orders
            current_list = word_lists[current_row]
            above_list = word_lists[current_row - 1]

            current_order = current_list.config.order
            above_order = above_list.config.order

            manager.reorder_word_list(current_list.config.name, above_order)
            manager.reorder_word_list(above_list.config.name, current_order)

            self._load_data()
            self.table.selectRow(current_row - 1)

    def _move_down(self):
        """Move selected list down in priority."""
        current_row = self.table.currentRow()
        manager = self.dictionaries.get_validation_manager()
        word_lists = manager.get_word_lists()

        if current_row < 0 or current_row >= len(word_lists) - 1:
            return

        # Swap orders
        current_list = word_lists[current_row]
        below_list = word_lists[current_row + 1]

        current_order = current_list.config.order
        below_order = below_list.config.order

        manager.reorder_word_list(current_list.config.name, below_order)
        manager.reorder_word_list(below_list.config.name, current_order)

        self._load_data()
        self.table.selectRow(current_row + 1)

    def _reset_defaults(self):
        """Reset to default word list configuration."""
        reply = QMessageBox.question(
            self,
            "Reset Defaults",
            "Reset all word list configurations to defaults?\n"
            "This will reset order and all flag settings.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Delete config file to reset to defaults
            config_path = self.config_dir / "ocr_config.json"
            if config_path.exists():
                config_path.unlink()

            # Reinitialize
            self.dictionaries._validation_manager = None
            self.dictionaries.get_validation_manager()
            self._load_data()


class RomajiBuildWorker(QThread):
    """Worker thread for building the romaji dictionary."""

    progress = Signal(str, int, int)  # status, current, total
    finished = Signal(bool, str)  # success, message

    def __init__(self, dictionaries: OCRDictionaries, parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries

    def run(self):
        """Build the romaji dictionary in a background thread."""
        try:

            def progress_callback(status, current, total):
                self.progress.emit(status, current, total)

            success, message = self.dictionaries.build_romaji_dictionary(
                progress_callback
            )
            self.finished.emit(success, message)
        except Exception as e:
            self.finished.emit(False, f"Error: {e!s}")


class RomajiTab(QWidget):
    """Tab for managing the Romaji (Japanese romanization) dictionary."""

    def __init__(self, dictionaries: OCRDictionaries, parent=None):
        super().__init__(parent)
        self.dictionaries = dictionaries
        self.build_worker = None
        self._setup_ui()
        self._load_data()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Info section
        info_group = QGroupBox("Romaji Dictionary")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "The romaji dictionary contains Japanese words in romanized form (e.g., 'arigatou', "
            "'sugoi', 'kawaii'). This prevents valid Japanese words from being flagged as "
            "unknown by the OCR spell checker.\n\n"
            "Click 'Build Dictionary' to download JMdict (Japanese-English dictionary) and "
            "extract all word readings converted to romaji. This is a one-time setup that "
            "downloads ~20MB and generates ~100,000+ words.\n\n"
            "Note: By default, romaji words validate as 'known' but are NOT accepted as OCR "
            "fix results. This prevents the spell checker from incorrectly 'fixing' words to romaji. "
            "Configure this in the Word Lists tab."
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        layout.addWidget(info_group)

        # Status section
        status_group = QGroupBox("Dictionary Status")
        status_layout = QFormLayout(status_group)

        self.status_label = QLabel("Not loaded")
        status_layout.addRow("Status:", self.status_label)

        self.word_count_label = QLabel("0")
        status_layout.addRow("Word Count:", self.word_count_label)

        self.dict_path_label = QLabel("-")
        self.dict_path_label.setWordWrap(True)
        status_layout.addRow("Dictionary File:", self.dict_path_label)

        self.jmdict_status_label = QLabel("-")
        status_layout.addRow("JMdict Cache:", self.jmdict_status_label)

        # Config status (from word lists)
        self.config_status_label = QLabel("-")
        self.config_status_label.setWordWrap(True)
        status_layout.addRow("Validation Config:", self.config_status_label)

        layout.addWidget(status_group)

        # Progress section (hidden initially)
        self.progress_group = QGroupBox("Build Progress")
        progress_layout = QVBoxLayout(self.progress_group)

        self.progress_label = QLabel("Ready")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # Indeterminate
        progress_layout.addWidget(self.progress_bar)

        self.progress_group.setVisible(False)
        layout.addWidget(self.progress_group)

        # Action buttons
        btn_layout = QHBoxLayout()

        self.build_btn = QPushButton("Build Dictionary (Download JMdict)")
        self.build_btn.clicked.connect(self._build_dictionary)
        btn_layout.addWidget(self.build_btn)

        self.rebuild_btn = QPushButton("Rebuild")
        self.rebuild_btn.setToolTip("Delete cached files and rebuild from scratch")
        self.rebuild_btn.clicked.connect(self._rebuild_dictionary)
        btn_layout.addWidget(self.rebuild_btn)

        btn_layout.addStretch()

        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.clicked.connect(self._load_data)
        btn_layout.addWidget(self.refresh_btn)

        layout.addLayout(btn_layout)

        # Spacer
        layout.addStretch()

        # Source info
        source_label = QLabel(
            "Data source: JMdict/EDICT (Electronic Dictionary Research and Development Group)\n"
            "https://www.edrdg.org/jmdict/j_jmdict.html"
        )
        source_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(source_label)

    def _load_data(self):
        """Load and display dictionary status."""
        try:
            stats = self.dictionaries.get_romaji_stats()

            word_count = stats.get("word_count", 0)
            dict_exists = stats.get("dict_exists", False)
            jmdict_cached = stats.get("jmdict_cached", False)
            dict_path = stats.get("dict_path", "-")

            if dict_exists and word_count > 0:
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("color: green; font-weight: bold;")
                self.build_btn.setText("Update Dictionary")
            elif dict_exists:
                self.status_label.setText("Empty (needs rebuild)")
                self.status_label.setStyleSheet("color: orange;")
                self.build_btn.setText("Build Dictionary")
            else:
                self.status_label.setText("Not built yet")
                self.status_label.setStyleSheet("color: gray;")
                self.build_btn.setText("Build Dictionary (Download JMdict)")

            self.word_count_label.setText(f"{word_count:,}")
            self.dict_path_label.setText(dict_path)
            self.jmdict_status_label.setText(
                "Cached" if jmdict_cached else "Not downloaded"
            )

            # Get romaji config from validation manager
            try:
                manager = self.dictionaries.get_validation_manager()
                romaji_list = None
                for wl in manager.get_word_lists():
                    if wl.config.name == "Romaji":
                        romaji_list = wl
                        break

                if romaji_list:
                    cfg = romaji_list.config
                    flags = []
                    if cfg.validates_known:
                        flags.append("Validates")
                    if cfg.protects_from_fix:
                        flags.append("Protects")
                    if cfg.accepts_as_fix_result:
                        flags.append("Accept Fix")
                    else:
                        flags.append("No Fix Accept")

                    self.config_status_label.setText(", ".join(flags))
                else:
                    self.config_status_label.setText("Not configured")
            except Exception:
                self.config_status_label.setText("-")

        except Exception as e:
            self.status_label.setText(f"Error: {e}")
            self.status_label.setStyleSheet("color: red;")

    def _build_dictionary(self):
        """Start building the romaji dictionary."""
        if self.build_worker and self.build_worker.isRunning():
            return

        # Show progress UI
        self.progress_group.setVisible(True)
        self.progress_label.setText("Starting...")
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.build_btn.setEnabled(False)
        self.rebuild_btn.setEnabled(False)

        # Start worker thread
        self.build_worker = RomajiBuildWorker(self.dictionaries, self)
        self.build_worker.progress.connect(self._on_progress)
        self.build_worker.finished.connect(self._on_finished)
        self.build_worker.start()

    def _rebuild_dictionary(self):
        """Delete cached files and rebuild."""
        reply = QMessageBox.question(
            self,
            "Rebuild Dictionary",
            "This will delete the cached JMdict file and rebuild the dictionary from scratch. "
            "This requires re-downloading ~20MB.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            # Delete cached files
            romaji_dict = self.dictionaries._get_romaji_dictionary()
            if romaji_dict.dict_path.exists():
                romaji_dict.dict_path.unlink()
            if romaji_dict.jmdict_path.exists():
                romaji_dict.jmdict_path.unlink()

            # Clear cached data
            romaji_dict._words = None

            self._load_data()
            self._build_dictionary()

        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to clear cache: {e}")

    def _on_progress(self, status: str, current: int, total: int):
        """Handle progress updates from worker."""
        self.progress_label.setText(status)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)  # Indeterminate

    def _on_finished(self, success: bool, message: str):
        """Handle worker completion."""
        self.progress_group.setVisible(False)
        self.build_btn.setEnabled(True)
        self.rebuild_btn.setEnabled(True)

        if success:
            QMessageBox.information(self, "Build Complete", message)
        else:
            QMessageBox.warning(self, "Build Failed", message)

        self._load_data()


class OCRDictionaryDialog(QDialog):
    """
    Dialog for editing OCR correction dictionaries.

    Provides tabs for:
        - Replacement rules (pattern-based corrections)
        - User dictionary (custom valid words)
        - Names dictionary (proper names)
        - Subtitle Edit dictionaries (external OCR fix lists)
    """

    def __init__(self, parent=None, config_dir: Path | None = None):
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

        # Romaji tab
        self.romaji_tab = RomajiTab(self.dictionaries)
        self.tabs.addTab(self.romaji_tab, "Romaji")

        # Word Lists Config tab
        self.word_lists_tab = WordListsConfigTab(self.dictionaries)
        self.tabs.addTab(self.word_lists_tab, "Word Lists")

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
            "Romaji: Japanese words in romanized form from JMdict. "
            "Click 'Build Dictionary' to download and generate ~100k words. "
            "Prevents words like 'arigatou', 'sugoi' from being flagged.",
            "Word Lists: Configure behavior for all word lists. "
            "Set which lists validate words, protect from fixes, or accept as fix results. "
            "Drag or use buttons to reorder priority.",
        ]
        if index < len(help_texts):
            self.help_label.setText(help_texts[index])
        else:
            self.help_label.setText("")
