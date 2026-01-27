# vsg_qt/subtitle_editor/tabs/fonts_tab.py
# -*- coding: utf-8 -*-
"""
Fonts tab for subtitle editor.

Provides font management functionality embedded as a tab.
"""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Optional, Dict, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QPushButton, QFileDialog, QMessageBox
)

from .base_tab import BaseTab

if TYPE_CHECKING:
    from ..state import EditorState


class FontsTab(BaseTab):
    """
    Tab for managing font replacements.

    Allows replacing fonts in the subtitle file with alternative fonts.
    """

    TAB_NAME = "Fonts"

    # Signal emitted when fonts are changed
    fonts_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts_dir: Optional[Path] = None
        self._replacements: Dict[str, Dict[str, Any]] = {}

        self._build_ui()

    def _build_ui(self):
        """Build the fonts tab UI."""
        layout = self.content_layout

        # Description
        desc = QLabel(
            "Replace fonts used in subtitle styles. This is useful when the original "
            "fonts are unavailable or need to be substituted for compatibility."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Fonts table
        fonts_group = QGroupBox("Font Replacements")
        fonts_layout = QVBoxLayout(fonts_group)

        self._fonts_table = QTableWidget()
        self._fonts_table.setColumnCount(4)
        self._fonts_table.setHorizontalHeaderLabels([
            "Style", "Original Font", "Replacement", "Action"
        ])
        self._fonts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._fonts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        header = self._fonts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)

        fonts_layout.addWidget(self._fonts_table)

        # Buttons
        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._populate_fonts)
        self._clear_all_btn = QPushButton("Clear All Replacements")
        self._clear_all_btn.clicked.connect(self._clear_all_replacements)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addWidget(self._clear_all_btn)
        btn_layout.addStretch()
        fonts_layout.addLayout(btn_layout)

        layout.addWidget(fonts_group)

        # Info section
        info_group = QGroupBox("Information")
        info_layout = QVBoxLayout(info_group)

        info_text = QLabel(
            "Font replacements are applied to the subtitle file during muxing.\n"
            "Click 'Replace...' to select a replacement font file.\n"
            "Click 'Clear' to remove a replacement."
        )
        info_text.setWordWrap(True)
        info_layout.addWidget(info_text)

        layout.addWidget(info_group)

        layout.addStretch()

    def set_fonts_dir(self, fonts_dir: Optional[Path]):
        """Set the fonts directory for preview."""
        self._fonts_dir = fonts_dir

    def set_replacements(self, replacements: Dict[str, Dict[str, Any]]):
        """Set existing font replacements."""
        self._replacements = replacements.copy() if replacements else {}
        self._populate_fonts()

    def _on_state_set(self):
        """Initialize from state when set."""
        self._populate_fonts()

    def _populate_fonts(self):
        """Populate the fonts table from state."""
        if not self._state:
            return

        self._fonts_table.setRowCount(0)

        # Get unique fonts from styles
        fonts_by_style = {}
        for style_name, style in self._state.styles.items():
            font = getattr(style, 'fontname', None)
            if font:
                fonts_by_style[style_name] = font

        self._fonts_table.setRowCount(len(fonts_by_style))

        for row, (style_name, original_font) in enumerate(fonts_by_style.items()):
            # Style name
            style_item = QTableWidgetItem(style_name)
            self._fonts_table.setItem(row, 0, style_item)

            # Original font
            font_item = QTableWidgetItem(original_font)
            self._fonts_table.setItem(row, 1, font_item)

            # Replacement (if any)
            replacement = self._replacements.get(style_name, {})
            new_font = replacement.get('new_font_name', '')
            repl_item = QTableWidgetItem(new_font if new_font else "(none)")
            if new_font:
                repl_item.setForeground(Qt.green)
            else:
                repl_item.setForeground(Qt.gray)
            self._fonts_table.setItem(row, 2, repl_item)

            # Action buttons cell
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(2, 2, 2, 2)
            btn_layout.setSpacing(4)

            replace_btn = QPushButton("Replace...")
            replace_btn.setProperty('style_name', style_name)
            replace_btn.setProperty('original_font', original_font)
            replace_btn.clicked.connect(self._on_replace_clicked)
            btn_layout.addWidget(replace_btn)

            if new_font:
                clear_btn = QPushButton("Clear")
                clear_btn.setProperty('style_name', style_name)
                clear_btn.clicked.connect(self._on_clear_clicked)
                btn_layout.addWidget(clear_btn)

            self._fonts_table.setCellWidget(row, 3, btn_widget)

        self._fonts_table.resizeRowsToContents()

    def _on_replace_clicked(self):
        """Handle replace button click."""
        btn = self.sender()
        if not btn:
            return

        style_name = btn.property('style_name')
        original_font = btn.property('original_font')

        # Open file dialog for font selection
        font_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select replacement font for '{original_font}'",
            "",
            "Font Files (*.ttf *.otf *.woff *.woff2);;All Files (*)"
        )

        if not font_path:
            return

        font_path = Path(font_path)
        if not font_path.exists():
            QMessageBox.warning(self, "Error", "Selected font file does not exist.")
            return

        # Get font name from file (simplified - use filename stem)
        new_font_name = font_path.stem

        # Store replacement
        self._replacements[style_name] = {
            'original_font': original_font,
            'new_font_name': new_font_name,
            'font_file_path': str(font_path)
        }

        # Copy to fonts dir if set
        if self._fonts_dir:
            try:
                dst = self._fonts_dir / font_path.name
                if not dst.exists():
                    shutil.copy2(font_path, dst)
            except Exception as e:
                QMessageBox.warning(self, "Warning",
                                   f"Could not copy font to preview directory: {e}")

        # Update state
        if self._state:
            self._state.set_font_replacements(self._replacements)

        self._populate_fonts()
        self.fonts_changed.emit()

    def _on_clear_clicked(self):
        """Handle clear button click."""
        btn = self.sender()
        if not btn:
            return

        style_name = btn.property('style_name')

        if style_name in self._replacements:
            del self._replacements[style_name]

        if self._state:
            self._state.set_font_replacements(self._replacements)

        self._populate_fonts()
        self.fonts_changed.emit()

    def _clear_all_replacements(self):
        """Clear all font replacements."""
        if not self._replacements:
            return

        reply = QMessageBox.question(
            self,
            "Clear All Replacements",
            "Are you sure you want to clear all font replacements?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        self._replacements.clear()

        if self._state:
            self._state.set_font_replacements({})

        self._populate_fonts()
        self.fonts_changed.emit()

    def on_activated(self):
        """Called when tab becomes active."""
        self._populate_fonts()

    def get_result(self) -> dict:
        """Get font replacements as result."""
        return {'font_replacements': self._replacements.copy()}

    def get_replacements(self) -> Dict[str, Dict[str, Any]]:
        """Get the current font replacements."""
        return self._replacements.copy()
