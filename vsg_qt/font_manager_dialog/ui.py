# vsg_qt/font_manager_dialog/ui.py
# -*- coding: utf-8 -*-
"""
Font Manager Dialog

A dialog for managing font replacements in subtitle files.
Shows fonts used in the file, available user fonts, and allows
setting up font replacements.
"""
from pathlib import Path
from typing import Optional, Dict, List, Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QGroupBox,
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QComboBox,
    QMessageBox, QHeaderView, QFrame
)

from vsg_core.font_manager import (
    FontScanner, SubtitleFontAnalyzer, FontReplacementManager, FontInfo
)
from vsg_core.config import AppConfig


class FontManagerDialog(QDialog):
    """
    Dialog for managing font replacements in subtitle files.

    Shows:
    - Left pane: Fonts used in the current subtitle file
    - Right pane: Available fonts from user's fonts folder
    - Bottom: Current replacements and controls
    """

    def __init__(
        self,
        subtitle_path: str,
        current_replacements: Optional[Dict[str, Dict[str, Any]]] = None,
        parent=None
    ):
        super().__init__(parent)
        self.subtitle_path = subtitle_path
        self.setWindowTitle("Font Manager")
        self.setMinimumSize(900, 600)

        # Initialize managers
        config = AppConfig()
        self.fonts_dir = config.get_fonts_dir()
        self.scanner = FontScanner(self.fonts_dir)
        self.analyzer = SubtitleFontAnalyzer(subtitle_path)
        self.replacement_manager = FontReplacementManager(self.fonts_dir)

        # Load existing replacements if provided
        if current_replacements:
            for orig_font, repl_data in current_replacements.items():
                self.replacement_manager.add_replacement(
                    orig_font,
                    repl_data['new_font_name'],
                    Path(repl_data['font_file_path']),
                    repl_data.get('affected_styles', [])
                )

        self._build_ui()
        self._connect_signals()
        self._refresh_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Main splitter for left/right panes
        splitter = QSplitter(Qt.Horizontal)

        # Left pane: Fonts in file
        left_group = QGroupBox("Fonts in Subtitle File")
        left_layout = QVBoxLayout(left_group)

        self.file_fonts_tree = QTreeWidget()
        self.file_fonts_tree.setHeaderLabels(["Font Name", "Used By", "Variants Needed"])
        self.file_fonts_tree.setAlternatingRowColors(True)
        self.file_fonts_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        left_layout.addWidget(self.file_fonts_tree)

        # Inline fonts warning
        self.inline_fonts_label = QLabel()
        self.inline_fonts_label.setStyleSheet("color: #E0A800;")
        self.inline_fonts_label.setWordWrap(True)
        self.inline_fonts_label.setVisible(False)
        left_layout.addWidget(self.inline_fonts_label)

        splitter.addWidget(left_group)

        # Right pane: User fonts
        right_group = QGroupBox("Available User Fonts")
        right_layout = QVBoxLayout(right_group)

        fonts_dir_label = QLabel(f"Folder: {self.fonts_dir}")
        fonts_dir_label.setStyleSheet("color: #888;")
        right_layout.addWidget(fonts_dir_label)

        self.user_fonts_tree = QTreeWidget()
        self.user_fonts_tree.setHeaderLabels(["Font Family", "Style", "File"])
        self.user_fonts_tree.setAlternatingRowColors(True)
        self.user_fonts_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        right_layout.addWidget(self.user_fonts_tree)

        self.open_folder_btn = QPushButton("Open Fonts Folder")
        right_layout.addWidget(self.open_folder_btn)

        splitter.addWidget(right_group)

        # Set initial splitter sizes
        splitter.setSizes([450, 450])
        layout.addWidget(splitter, 1)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        # Replacement controls
        replacement_group = QGroupBox("Font Replacement")
        replacement_layout = QVBoxLayout(replacement_group)

        # Replacement selection row
        selection_row = QHBoxLayout()

        selection_row.addWidget(QLabel("Replace:"))
        self.original_font_combo = QComboBox()
        self.original_font_combo.setMinimumWidth(200)
        selection_row.addWidget(self.original_font_combo)

        selection_row.addWidget(QLabel("with:"))
        self.replacement_font_combo = QComboBox()
        self.replacement_font_combo.setMinimumWidth(200)
        selection_row.addWidget(self.replacement_font_combo)

        self.add_replacement_btn = QPushButton("Add Replacement")
        selection_row.addWidget(self.add_replacement_btn)

        selection_row.addStretch()
        replacement_layout.addLayout(selection_row)

        # Current replacements list
        self.replacements_tree = QTreeWidget()
        self.replacements_tree.setHeaderLabels(["Original Font", "Replacement Font", "Affected Styles"])
        self.replacements_tree.setAlternatingRowColors(True)
        self.replacements_tree.setMaximumHeight(150)
        replacement_layout.addWidget(self.replacements_tree)

        # Replacement actions
        replacement_actions = QHBoxLayout()
        self.remove_replacement_btn = QPushButton("Remove Selected")
        self.remove_replacement_btn.setEnabled(False)
        self.clear_all_btn = QPushButton("Clear All")
        replacement_actions.addWidget(self.remove_replacement_btn)
        replacement_actions.addWidget(self.clear_all_btn)
        replacement_actions.addStretch()
        replacement_layout.addLayout(replacement_actions)

        layout.addWidget(replacement_group)

        # Bottom buttons
        button_row = QHBoxLayout()
        button_row.addStretch()

        self.cancel_btn = QPushButton("Cancel")
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setDefault(True)

        button_row.addWidget(self.cancel_btn)
        button_row.addWidget(self.ok_btn)
        layout.addLayout(button_row)

    def _connect_signals(self):
        self.file_fonts_tree.currentItemChanged.connect(self._on_file_font_selected)
        self.user_fonts_tree.currentItemChanged.connect(self._on_user_font_selected)
        self.open_folder_btn.clicked.connect(self._open_fonts_folder)
        self.add_replacement_btn.clicked.connect(self._add_replacement)
        self.remove_replacement_btn.clicked.connect(self._remove_replacement)
        self.clear_all_btn.clicked.connect(self._clear_all_replacements)
        self.replacements_tree.currentItemChanged.connect(self._on_replacement_selected)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._on_ok)

    def _refresh_data(self):
        """Refresh all data displays."""
        self._refresh_file_fonts()
        self._refresh_user_fonts()
        self._refresh_replacements()
        self._update_combos()

    def _refresh_file_fonts(self):
        """Refresh the fonts-in-file tree."""
        self.file_fonts_tree.clear()

        analysis = self.analyzer.analyze()

        if 'error' in analysis and analysis['error']:
            item = QTreeWidgetItem(["Error analyzing file", "", ""])
            self.file_fonts_tree.addTopLevelItem(item)
            return

        fonts_info = analysis.get('fonts', {})
        inline_fonts = analysis.get('inline_fonts', [])

        for font_name, info in fonts_info.items():
            styles = info.get('styles', [])
            styles_text = ', '.join(styles[:3])
            if len(styles) > 3:
                styles_text += f" (+{len(styles) - 3} more)"

            # Determine variants needed
            variants = []
            if info.get('has_bold_styles'):
                variants.append("Bold")
            if info.get('has_italic_styles'):
                variants.append("Italic")
            variants_text = ', '.join(variants) if variants else "Regular only"

            item = QTreeWidgetItem([font_name, styles_text, variants_text])
            item.setData(0, Qt.UserRole, font_name)
            self.file_fonts_tree.addTopLevelItem(item)

        # Show inline fonts warning if any
        if inline_fonts:
            self.inline_fonts_label.setText(
                f"Note: {len(inline_fonts)} font(s) used in inline tags: {', '.join(inline_fonts[:3])}"
                + ("..." if len(inline_fonts) > 3 else "")
            )
            self.inline_fonts_label.setVisible(True)
        else:
            self.inline_fonts_label.setVisible(False)

    def _refresh_user_fonts(self):
        """Refresh the user fonts tree."""
        self.user_fonts_tree.clear()

        fonts = self.scanner.scan()

        if not fonts:
            item = QTreeWidgetItem(["No fonts found", "", ""])
            item.setForeground(0, Qt.gray)
            self.user_fonts_tree.addTopLevelItem(item)
            return

        # Group by family
        families = self.scanner.get_font_families()

        for family_name, family_fonts in sorted(families.items()):
            # Create family item
            if len(family_fonts) == 1:
                # Single font, show directly
                font = family_fonts[0]
                item = QTreeWidgetItem([
                    font.family_name,
                    font.subfamily or "Regular",
                    font.filename
                ])
                item.setData(0, Qt.UserRole, font)
                self.user_fonts_tree.addTopLevelItem(item)
            else:
                # Multiple fonts in family, create expandable group
                family_item = QTreeWidgetItem([family_name, f"{len(family_fonts)} variants", ""])
                family_item.setData(0, Qt.UserRole, None)

                for font in family_fonts:
                    child = QTreeWidgetItem([
                        "",
                        font.subfamily or "Regular",
                        font.filename
                    ])
                    child.setData(0, Qt.UserRole, font)
                    family_item.addChild(child)

                self.user_fonts_tree.addTopLevelItem(family_item)

    def _refresh_replacements(self):
        """Refresh the replacements tree."""
        self.replacements_tree.clear()

        replacements = self.replacement_manager.get_replacements()

        for original_font, repl_data in replacements.items():
            styles = repl_data.get('affected_styles', [])
            styles_text = ', '.join(styles[:3])
            if len(styles) > 3:
                styles_text += f" (+{len(styles) - 3} more)"

            item = QTreeWidgetItem([
                original_font,
                repl_data['new_font_name'],
                styles_text
            ])
            item.setData(0, Qt.UserRole, original_font)
            self.replacements_tree.addTopLevelItem(item)

        self.remove_replacement_btn.setEnabled(False)

    def _update_combos(self):
        """Update the combo boxes."""
        # Original font combo
        self.original_font_combo.clear()
        analysis = self.analyzer.analyze()
        fonts_info = analysis.get('fonts', {})
        existing_replacements = set(self.replacement_manager.get_replacements().keys())

        for font_name in sorted(fonts_info.keys()):
            if font_name not in existing_replacements:
                self.original_font_combo.addItem(font_name, font_name)

        # Replacement font combo
        self.replacement_font_combo.clear()
        fonts = self.scanner.scan()
        for font in sorted(fonts, key=lambda f: f.family_name):
            display_name = font.family_name
            if font.subfamily and font.subfamily.lower() != 'regular':
                display_name += f" ({font.subfamily})"
            self.replacement_font_combo.addItem(display_name, font)

    def _on_file_font_selected(self, current, previous):
        """Handle selection in file fonts tree."""
        if current:
            font_name = current.data(0, Qt.UserRole)
            if font_name:
                # Select in combo
                idx = self.original_font_combo.findData(font_name)
                if idx >= 0:
                    self.original_font_combo.setCurrentIndex(idx)

    def _on_user_font_selected(self, current, previous):
        """Handle selection in user fonts tree."""
        if current:
            font_info = current.data(0, Qt.UserRole)
            if font_info:
                # Find and select in combo
                for i in range(self.replacement_font_combo.count()):
                    combo_font = self.replacement_font_combo.itemData(i)
                    if combo_font and combo_font.file_path == font_info.file_path:
                        self.replacement_font_combo.setCurrentIndex(i)
                        break

    def _on_replacement_selected(self, current, previous):
        """Handle selection in replacements tree."""
        self.remove_replacement_btn.setEnabled(current is not None)

    def _open_fonts_folder(self):
        """Open the fonts folder in the system file manager."""
        import subprocess
        import sys

        self.fonts_dir.mkdir(parents=True, exist_ok=True)

        if sys.platform == 'win32':
            subprocess.run(['explorer', str(self.fonts_dir)])
        elif sys.platform == 'darwin':
            subprocess.run(['open', str(self.fonts_dir)])
        else:
            subprocess.run(['xdg-open', str(self.fonts_dir)])

    def _add_replacement(self):
        """Add a new font replacement."""
        original_font = self.original_font_combo.currentData()
        replacement_font = self.replacement_font_combo.currentData()

        if not original_font:
            QMessageBox.warning(self, "Error", "Please select a font to replace.")
            return

        if not replacement_font:
            QMessageBox.warning(self, "Error", "Please select a replacement font.")
            return

        # Get affected styles
        analysis = self.analyzer.analyze()
        fonts_info = analysis.get('fonts', {})
        affected_styles = fonts_info.get(original_font, {}).get('styles', [])

        self.replacement_manager.add_replacement(
            original_font,
            replacement_font.family_name,
            replacement_font.file_path,
            affected_styles
        )

        self._refresh_replacements()
        self._update_combos()

    def _remove_replacement(self):
        """Remove the selected replacement."""
        current = self.replacements_tree.currentItem()
        if current:
            original_font = current.data(0, Qt.UserRole)
            if original_font:
                self.replacement_manager.remove_replacement(original_font)
                self._refresh_replacements()
                self._update_combos()

    def _clear_all_replacements(self):
        """Clear all replacements."""
        if self.replacement_manager.get_replacements():
            reply = QMessageBox.question(
                self,
                "Clear All",
                "Remove all font replacements?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.replacement_manager.clear_replacements()
                self._refresh_replacements()
                self._update_combos()

    def _on_ok(self):
        """Handle OK button - validate and accept."""
        errors = self.replacement_manager.validate_replacement_files()
        if errors:
            QMessageBox.warning(
                self,
                "Validation Error",
                "Some font files are missing:\n\n" + "\n".join(errors)
            )
            return

        self.accept()

    def get_replacements(self) -> Dict[str, Dict[str, Any]]:
        """Get the configured font replacements."""
        return self.replacement_manager.get_replacements()
