# vsg_qt/subtitle_editor/tabs/fonts_tab.py
# -*- coding: utf-8 -*-
"""
Fonts tab for subtitle editor.

Provides font management functionality with visual font preview dropdown.
"""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QPushButton, QComboBox, QStyledItemDelegate, QStyle,
    QStyleOptionViewItem, QApplication
)

from .base_tab import BaseTab

if TYPE_CHECKING:
    from ..state import EditorState


class FontPreviewDelegate(QStyledItemDelegate):
    """
    Delegate that renders each font name in its own typeface.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._preview_text = "AaBbCc 123"

    def paint(self, painter, option, index):
        """Paint the item with font preview."""
        # Get the font name from the item
        font_name = index.data(Qt.DisplayRole)
        font_path = index.data(Qt.UserRole)

        # Save painter state
        painter.save()

        # Draw selection background if selected
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        # Set up the font
        if font_path:
            # Try to use the actual font file
            font_id = QFontDatabase.addApplicationFont(font_path)
            if font_id >= 0:
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    font = QFont(families[0], 11)
                else:
                    font = QFont(font_name, 11)
            else:
                font = QFont(font_name, 11)
        else:
            font = QFont(font_name, 11)

        painter.setFont(font)

        # Draw the font name and preview
        text_rect = option.rect.adjusted(4, 2, -4, -2)
        display_text = f"{font_name}"
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, display_text)

        painter.restore()

    def sizeHint(self, option, index):
        """Return size hint for item."""
        return QSize(200, 28)


class FontPreviewComboBox(QComboBox):
    """
    ComboBox that shows font previews in its dropdown.
    Each font is rendered in its own typeface.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(FontPreviewDelegate(self))
        self.setMinimumWidth(200)
        # Make dropdown wider to show previews
        self.view().setMinimumWidth(250)

    def add_font(self, font_name: str, font_path: Optional[str] = None):
        """Add a font to the dropdown."""
        self.addItem(font_name)
        index = self.count() - 1
        self.setItemData(index, font_path, Qt.UserRole)


class FontsTab(BaseTab):
    """
    Tab for managing font replacements.

    Features:
    - Visual font preview dropdown for selecting replacement fonts
    - Loads fonts from the extracted fonts directory
    - Shows original font name alongside replacement selection
    """

    TAB_NAME = "Fonts"

    # Signal emitted when fonts are changed
    fonts_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts_dir: Optional[Path] = None
        self._replacements: Dict[str, Dict[str, Any]] = {}
        self._available_fonts: List[Dict[str, str]] = []  # [{name, path}, ...]
        self._font_combos: Dict[str, FontPreviewComboBox] = {}

        self._build_ui()

    def _build_ui(self):
        """Build the fonts tab UI."""
        layout = self.content_layout

        # Description
        desc = QLabel(
            "Replace fonts used in subtitle styles. Select a replacement font "
            "from the dropdown - fonts are shown with a preview of their appearance."
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Fonts table
        fonts_group = QGroupBox("Font Replacements")
        fonts_layout = QVBoxLayout(fonts_group)

        self._fonts_table = QTableWidget()
        self._fonts_table.setColumnCount(4)
        self._fonts_table.setHorizontalHeaderLabels([
            "#", "Style", "Original Font", "Replacement"
        ])
        self._fonts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._fonts_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        header = self._fonts_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.setSectionResizeMode(3, QHeaderView.Stretch)

        self._fonts_table.setColumnWidth(1, 120)
        self._fonts_table.setColumnWidth(2, 150)

        fonts_layout.addWidget(self._fonts_table)

        # Buttons
        btn_layout = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh Fonts")
        self._refresh_btn.setToolTip("Rescan fonts directory")
        self._refresh_btn.clicked.connect(self._scan_and_populate)
        self._clear_all_btn = QPushButton("Clear All")
        self._clear_all_btn.setToolTip("Reset all fonts to original")
        self._clear_all_btn.clicked.connect(self._clear_all_replacements)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addWidget(self._clear_all_btn)
        btn_layout.addStretch()
        fonts_layout.addLayout(btn_layout)

        layout.addWidget(fonts_group)

        # Info section
        info_label = QLabel(
            "<i>Tip: The dropdown shows available fonts with a preview. "
            "Select '(none)' to keep the original font.</i>"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

        layout.addStretch()

    def set_fonts_dir(self, fonts_dir: Optional[Path]):
        """Set the fonts directory for preview."""
        self._fonts_dir = Path(fonts_dir) if fonts_dir else None
        self._scan_available_fonts()

    def set_replacements(self, replacements: Dict[str, Dict[str, Any]]):
        """Set existing font replacements."""
        self._replacements = replacements.copy() if replacements else {}
        self._populate_fonts()

    def _scan_available_fonts(self):
        """Scan both extracted fonts directory and system fonts."""
        self._available_fonts = []
        seen_names = set()

        # First, add fonts from the extracted fonts directory (these take priority)
        if self._fonts_dir and self._fonts_dir.exists():
            for ext in ['*.ttf', '*.otf', '*.TTF', '*.OTF', '*.woff', '*.woff2']:
                for font_path in self._fonts_dir.glob(ext):
                    # Get font family name from the database
                    font_id = QFontDatabase.addApplicationFont(str(font_path))
                    if font_id >= 0:
                        families = QFontDatabase.applicationFontFamilies(font_id)
                        if families:
                            font_name = families[0]
                        else:
                            font_name = font_path.stem
                    else:
                        font_name = font_path.stem

                    if font_name not in seen_names:
                        self._available_fonts.append({
                            'name': font_name,
                            'path': str(font_path),
                            'filename': font_path.name,
                            'source': 'extracted'
                        })
                        seen_names.add(font_name)

        # Then add all system fonts
        for family in QFontDatabase.families():
            if family not in seen_names:
                self._available_fonts.append({
                    'name': family,
                    'path': None,  # System font, no file path
                    'filename': None,
                    'source': 'system'
                })
                seen_names.add(family)

        # Sort by name
        self._available_fonts.sort(key=lambda f: f['name'].lower())

    def _scan_and_populate(self):
        """Rescan fonts and repopulate."""
        self._scan_available_fonts()
        self._populate_fonts()

    def _on_state_set(self):
        """Initialize from state when set."""
        self._populate_fonts()

    def _populate_fonts(self):
        """Populate the fonts table from state."""
        if not self._state:
            return

        self._fonts_table.setRowCount(0)
        self._font_combos.clear()

        # Get unique fonts from styles
        fonts_by_style = {}
        for style_name, style in self._state.styles.items():
            font = getattr(style, 'fontname', None)
            if font:
                fonts_by_style[style_name] = font

        self._fonts_table.setRowCount(len(fonts_by_style))

        for row, (style_name, original_font) in enumerate(fonts_by_style.items()):
            # Row number
            num_item = QTableWidgetItem(str(row + 1))
            num_item.setTextAlignment(Qt.AlignCenter)
            self._fonts_table.setItem(row, 0, num_item)

            # Style name
            style_item = QTableWidgetItem(style_name)
            self._fonts_table.setItem(row, 1, style_item)

            # Original font (read-only)
            font_item = QTableWidgetItem(original_font)
            font_item.setForeground(Qt.gray)
            self._fonts_table.setItem(row, 2, font_item)

            # Replacement dropdown with font preview
            combo = FontPreviewComboBox()
            combo.setProperty('style_name', style_name)
            combo.setProperty('original_font', original_font)

            # Add "(none)" option first
            combo.addItem("(none)")
            combo.setItemData(0, None, Qt.UserRole)

            # Add available fonts
            for font_info in self._available_fonts:
                combo.add_font(font_info['name'], font_info['path'])

            # Set current selection if replacement exists
            replacement = self._replacements.get(style_name, {})
            new_font = replacement.get('new_font_name', '')
            if new_font:
                idx = combo.findText(new_font)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                else:
                    # Font not in list, add it
                    combo.addItem(new_font)
                    combo.setCurrentIndex(combo.count() - 1)

            combo.currentIndexChanged.connect(
                lambda idx, sn=style_name, of=original_font: self._on_font_selected(sn, of)
            )

            self._fonts_table.setCellWidget(row, 3, combo)
            self._font_combos[style_name] = combo

        self._fonts_table.resizeRowsToContents()

    def _on_font_selected(self, style_name: str, original_font: str):
        """Handle font selection change."""
        combo = self._font_combos.get(style_name)
        if not combo:
            return

        selected_text = combo.currentText()
        selected_path = combo.currentData(Qt.UserRole)

        if selected_text == "(none)" or not selected_text:
            # Remove replacement
            if style_name in self._replacements:
                del self._replacements[style_name]
        else:
            # Set replacement
            self._replacements[style_name] = {
                'original_font': original_font,
                'new_font_name': selected_text,
                'font_file_path': selected_path
            }

        # Update state
        if self._state:
            self._state.set_font_replacements(self._replacements)

        self.fonts_changed.emit()

    def _clear_all_replacements(self):
        """Clear all font replacements."""
        self._replacements.clear()

        # Reset all combos to "(none)"
        for combo in self._font_combos.values():
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)

        if self._state:
            self._state.set_font_replacements({})

        self.fonts_changed.emit()

    def on_activated(self):
        """Called when tab becomes active."""
        # Rescan fonts in case directory changed
        self._scan_available_fonts()
        self._populate_fonts()

    def get_result(self) -> dict:
        """Get font replacements as result."""
        return {'font_replacements': self._replacements.copy()}

    def get_replacements(self) -> Dict[str, Dict[str, Any]]:
        """Get the current font replacements."""
        return self._replacements.copy()
