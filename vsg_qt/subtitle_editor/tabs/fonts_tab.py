# vsg_qt/subtitle_editor/tabs/fonts_tab.py
# -*- coding: utf-8 -*-
"""
Fonts tab for subtitle editor.

Provides font management functionality with visual font preview dropdown.
Uses FontScanner from vsg_core for proper font scanning.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any, List

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
    QPushButton, QComboBox, QStyledItemDelegate, QStyle
)

from .base_tab import BaseTab

if TYPE_CHECKING:
    from ..state import EditorState


class FontPreviewDelegate(QStyledItemDelegate):
    """
    Delegate that renders each font name in its own typeface.
    """

    def __init__(self, loaded_fonts: Dict[str, str], parent=None):
        super().__init__(parent)
        self._loaded_fonts = loaded_fonts  # file_path -> qt_family_name

    def paint(self, painter, option, index):
        """Paint the item with font preview."""
        font_name = index.data(Qt.DisplayRole)
        font_path = index.data(Qt.UserRole)

        painter.save()

        # Draw selection background if selected
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        # Set up the font for preview
        if font_path and font_path in self._loaded_fonts:
            qt_family = self._loaded_fonts[font_path]
            font = QFont(qt_family, 11)
        else:
            font = QFont(font_name, 11)

        painter.setFont(font)

        # Draw the font name
        text_rect = option.rect.adjusted(4, 2, -4, -2)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, font_name)

        painter.restore()

    def sizeHint(self, option, index):
        """Return size hint for item."""
        return QSize(200, 28)


class FontPreviewComboBox(QComboBox):
    """
    ComboBox that shows font previews in its dropdown.
    Each font is rendered in its own typeface.
    """

    def __init__(self, loaded_fonts: Dict[str, str], parent=None):
        super().__init__(parent)
        self._loaded_fonts = loaded_fonts
        self._delegate = FontPreviewDelegate(loaded_fonts, self)
        self.setItemDelegate(self._delegate)
        self.setMinimumWidth(200)
        self.view().setMinimumWidth(300)

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
    - Loads fonts from app config fonts directory (recursive)
    - Shows original font name alongside replacement selection
    """

    TAB_NAME = "Fonts"

    fonts_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fonts_dir: Optional[Path] = None
        self._replacements: Dict[str, Dict[str, Any]] = {}
        self._available_fonts: List[Any] = []  # List of FontInfo objects
        self._font_combos: Dict[str, FontPreviewComboBox] = {}
        self._loaded_fonts: Dict[str, str] = {}  # file_path -> qt_family_name
        self._scanner = None

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

        # Fonts folder label
        self._folder_label = QLabel("Fonts folder: (not set)")
        self._folder_label.setStyleSheet("color: #888;")
        layout.addWidget(self._folder_label)

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
        if fonts_dir:
            self._fonts_dir = Path(fonts_dir)
        else:
            # Use default from AppConfig
            from vsg_core.config import AppConfig
            config = AppConfig()
            self._fonts_dir = config.get_fonts_dir()

        if self._fonts_dir:
            self._folder_label.setText(f"Fonts folder: {self._fonts_dir}")

        self._scan_available_fonts()

    def set_replacements(self, replacements: Dict[str, Dict[str, Any]]):
        """Set existing font replacements."""
        self._replacements = replacements.copy() if replacements else {}
        self._populate_fonts()

    def _scan_available_fonts(self):
        """Scan fonts directory using FontScanner."""
        from vsg_core.font_manager import FontScanner

        self._available_fonts = []
        self._loaded_fonts.clear()

        if not self._fonts_dir or not self._fonts_dir.exists():
            print(f"[FontsTab] Fonts directory not found: {self._fonts_dir}")
            return

        print(f"[FontsTab] Scanning fonts from: {self._fonts_dir}")

        # Create scanner and scan recursively
        self._scanner = FontScanner(self._fonts_dir)
        self._available_fonts = self._scanner.scan(include_subdirs=True)

        print(f"[FontsTab] Found {len(self._available_fonts)} fonts")

        # Load fonts into Qt for preview rendering
        for font_info in self._available_fonts:
            file_path_str = str(font_info.file_path)
            if file_path_str not in self._loaded_fonts:
                font_id = QFontDatabase.addApplicationFont(file_path_str)
                if font_id >= 0:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        self._loaded_fonts[file_path_str] = families[0]

    def _scan_and_populate(self):
        """Rescan fonts and repopulate."""
        if self._scanner:
            self._scanner.clear_cache()
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
            combo = FontPreviewComboBox(self._loaded_fonts)
            combo.setProperty('style_name', style_name)
            combo.setProperty('original_font', original_font)

            # Add "(none)" option first
            combo.addItem("(none)")
            combo.setItemData(0, None, Qt.UserRole)

            # Add available fonts from the fonts directory
            for font_info in sorted(self._available_fonts, key=lambda f: f.family_name.lower()):
                display_name = font_info.family_name
                if font_info.subfamily and font_info.subfamily.lower() != 'regular':
                    display_name += f" ({font_info.subfamily})"
                combo.add_font(display_name, str(font_info.file_path))

            # Set current selection if replacement exists
            replacement = self._replacements.get(style_name, {})
            new_font = replacement.get('new_font_name', '')
            if new_font:
                # Find matching font in dropdown
                for i in range(1, combo.count()):
                    if combo.itemText(i).startswith(new_font):
                        combo.setCurrentIndex(i)
                        break
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
            # Remove replacement - restore original
            if style_name in self._replacements:
                del self._replacements[style_name]
        else:
            # Extract font family name (remove subfamily if present)
            font_name = selected_text.split(' (')[0] if ' (' in selected_text else selected_text

            # Set replacement
            self._replacements[style_name] = {
                'original_font': original_font,
                'new_font_name': font_name,
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
