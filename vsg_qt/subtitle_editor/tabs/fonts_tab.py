# vsg_qt/subtitle_editor/tabs/fonts_tab.py
"""
Fonts tab for subtitle editor.

Provides font management functionality with visual font preview dropdown.
Uses FontScanner from vsg_core for proper font scanning.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .base_tab import BaseTab


class FontPreviewDelegate(QStyledItemDelegate):
    """
    Delegate that renders each font name in its own typeface.
    """

    def __init__(self, loaded_fonts: dict[str, str], parent=None):
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

    # Custom role for storing font data
    FontDataRole = Qt.UserRole + 1

    def __init__(self, loaded_fonts: dict[str, str], parent=None):
        super().__init__(parent)
        self._loaded_fonts = loaded_fonts
        self._delegate = FontPreviewDelegate(loaded_fonts, self)
        self.setItemDelegate(self._delegate)
        self.setMinimumWidth(200)
        self.view().setMinimumWidth(300)

    def add_font(
        self,
        font_name: str,
        font_path: str | None = None,
        family_name: str | None = None,
    ):
        """Add a font to the dropdown.

        Args:
            font_name: Display name for the dropdown
            font_path: Path to the font file
            family_name: Internal font family name (what libass uses)
        """
        self.addItem(font_name)
        index = self.count() - 1
        # Store path in UserRole for backward compatibility with delegate
        self.setItemData(index, font_path, Qt.UserRole)
        # Store full font data including family_name
        self.setItemData(
            index,
            {"path": font_path, "family_name": family_name or font_name.split(" (")[0]},
            self.FontDataRole,
        )


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
        self._fonts_dir: Path | None = None
        self._replacements: dict[str, dict[str, Any]] = {}
        self._available_fonts: list[Any] = []  # List of FontInfo objects
        self._font_combos: dict[str, FontPreviewComboBox] = {}
        self._loaded_fonts: dict[str, str] = {}  # file_path -> qt_family_name
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
        self._fonts_table.setHorizontalHeaderLabels(
            ["#", "Style", "Original Font", "Replacement"]
        )
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
        self._apply_btn = QPushButton("Apply Replacements")
        self._apply_btn.setToolTip("Apply selected font replacements")
        self._apply_btn.clicked.connect(self._apply_replacements)
        self._refresh_btn = QPushButton("Refresh Fonts")
        self._refresh_btn.setToolTip("Rescan fonts directory")
        self._refresh_btn.clicked.connect(self._scan_and_populate)
        self._clear_all_btn = QPushButton("Clear All")
        self._clear_all_btn.setToolTip("Reset all fonts to original")
        self._clear_all_btn.clicked.connect(self._clear_all_replacements)
        btn_layout.addWidget(self._apply_btn)
        btn_layout.addWidget(self._refresh_btn)
        btn_layout.addWidget(self._clear_all_btn)
        btn_layout.addStretch()
        fonts_layout.addLayout(btn_layout)

        layout.addWidget(fonts_group)

        # Info section
        info_label = QLabel(
            "<i>Tip: Select fonts from the dropdowns, then click 'Apply Replacements' to apply them. "
            "Select '(none)' to keep the original font.</i>"
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: gray;")
        layout.addWidget(info_label)

        layout.addStretch()

    def set_fonts_dir(self, fonts_dir: Path | None):
        """Set the fonts directory for preview."""
        from vsg_core.config import AppConfig

        config = AppConfig()

        # Store attached fonts dir (from subtitle) - this is where libass looks
        if fonts_dir:
            self._attached_fonts_dir = Path(fonts_dir)
        else:
            # Create a temp fonts directory if none provided
            # This ensures we have somewhere to copy replacement fonts
            self._attached_fonts_dir = (
                config.get_style_editor_temp_dir() / "vsg_replacement_fonts"
            )
            self._attached_fonts_dir.mkdir(parents=True, exist_ok=True)
            print(f"[FontsTab] Created temp fonts dir: {self._attached_fonts_dir}")

        # User's fonts dir - this is what we scan for the dropdown
        self._user_fonts_dir = config.get_fonts_dir()

        # For backward compatibility
        self._fonts_dir = self._attached_fonts_dir

        # Show user fonts folder in label
        if self._user_fonts_dir and self._user_fonts_dir.exists():
            self._folder_label.setText(f"Fonts folder: {self._user_fonts_dir}")
        else:
            self._folder_label.setText("Fonts folder: (not set)")

        self._scan_available_fonts()

    def set_replacements(self, replacements: dict[str, dict[str, Any]]):
        """Set existing font replacements."""
        self._replacements = replacements.copy() if replacements else {}
        self._populate_fonts()

    def _scan_available_fonts(self):
        """Scan fonts directory using FontScanner - only user fonts, not attached."""
        from vsg_core.font_manager import FontScanner

        self._available_fonts = []
        self._loaded_fonts.clear()

        # Only scan user's fonts directory (not attached fonts from subtitle)
        # This matches the old working behavior
        if (
            not hasattr(self, "_user_fonts_dir")
            or not self._user_fonts_dir
            or not self._user_fonts_dir.exists()
        ):
            print("[FontsTab] No user fonts directory found")
            return

        print(f"[FontsTab] Scanning fonts from: {self._user_fonts_dir}")

        scanner = FontScanner(self._user_fonts_dir)
        self._available_fonts = scanner.scan(include_subdirs=True)
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

        # Get unique fonts from styles - use ORIGINAL values, not current modified values
        fonts_by_style = {}
        for style_name, style in self._state.styles.items():
            # Try to get original fontname from state's original values
            original_values = getattr(self._state, "_original_style_values", {})
            if style_name in original_values:
                font = original_values[style_name].get("fontname")
            else:
                font = getattr(style, "fontname", None)
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
            combo.setProperty("style_name", style_name)
            combo.setProperty("original_font", original_font)

            # Add "(none)" option first
            combo.addItem("(none)")
            combo.setItemData(0, None, Qt.UserRole)

            # Add available fonts from the fonts directory
            for font_info in sorted(
                self._available_fonts, key=lambda f: f.family_name.lower()
            ):
                # Use full_name to distinguish variants (e.g., "Vesta Pro Bold" vs "Vesta Pro Bold Italic")
                # Fall back to family_name + subfamily if full_name not available
                if font_info.full_name and font_info.full_name != font_info.family_name:
                    display_name = font_info.full_name
                    font_name_for_libass = font_info.full_name
                else:
                    display_name = font_info.family_name
                    if font_info.subfamily and font_info.subfamily.lower() != "regular":
                        display_name += f" ({font_info.subfamily})"
                    font_name_for_libass = font_info.family_name

                # Pass full_name so libass can find the specific font variant
                combo.add_font(
                    display_name, str(font_info.file_path), font_name_for_libass
                )

            # Set current selection if replacement exists
            replacement = self._replacements.get(style_name, {})
            new_font = replacement.get("new_font_name", "")
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

            # No auto-apply on selection - user must click "Apply Replacements" button
            self._fonts_table.setCellWidget(row, 3, combo)
            self._font_combos[style_name] = combo

        self._fonts_table.resizeRowsToContents()

    def _apply_replacements(self):
        """Apply all selected font replacements - triggered by Apply button."""
        import shutil

        fonts_dir = getattr(self, "_attached_fonts_dir", None) or self._fonts_dir
        self._replacements.clear()

        # Go through all combos and apply their selections
        for style_name, combo in self._font_combos.items():
            original_font = combo.property("original_font")
            selected_text = combo.currentText()
            selected_path = combo.currentData(Qt.UserRole)

            if selected_text == "(none)" or not selected_text:
                # No replacement for this style
                continue

            # Get font data including family_name (what libass actually uses)
            font_data = combo.currentData(FontPreviewComboBox.FontDataRole)
            if font_data and isinstance(font_data, dict):
                font_name = font_data.get("family_name", selected_text.split(" (")[0])
            else:
                # Fallback for items without FontDataRole
                font_name = selected_text.split(" (")[0]

            font_path = Path(selected_path) if selected_path else None

            # Copy font to fonts directory so libass can access it
            if font_path and fonts_dir:
                try:
                    fonts_dir.mkdir(parents=True, exist_ok=True)
                    dst = fonts_dir / font_path.name
                    if not dst.exists():
                        shutil.copy2(font_path, dst)
                        print(f"[FontsTab] Copied font to: {dst}")
                except Exception as e:
                    print(f"[FontsTab] Could not copy font: {e}")

            print(
                f"[FontsTab] Replacement: style='{style_name}' font='{font_name}' path='{selected_path}'"
            )

            # Store replacement
            self._replacements[style_name] = {
                "original_font": original_font,
                "new_font_name": font_name,
                "font_file_path": selected_path,
            }

        # Update state and emit signal
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
        # Only rescan if we haven't scanned yet or fonts list is empty
        # This prevents unnecessary repopulation which can cause issues
        if not self._available_fonts:
            self._scan_available_fonts()
            self._populate_fonts()

    def get_result(self) -> dict:
        """Get font replacements as result."""
        return {"font_replacements": self._replacements.copy()}

    def get_replacements(self) -> dict[str, dict[str, Any]]:
        """Get the current font replacements."""
        return self._replacements.copy()

    def get_fonts_dir(self) -> Path | None:
        """Get the fonts directory where replacement fonts are copied.

        This returns the directory that should be passed to libass for
        font lookup. It may be a temp directory if none was originally provided.
        """
        return self._attached_fonts_dir
