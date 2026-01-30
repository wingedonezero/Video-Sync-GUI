# vsg_qt/favorites_dialog/ui.py
"""
Favorites Manager Dialog

A dialog for managing saved favorite colors - view, edit names, delete.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vsg_core.favorite_colors import FavoriteColorsManager


class ColorSwatchWidget(QWidget):
    """A small widget that displays a color swatch."""

    def __init__(self, hex_color: str, size: int = 24, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._hex_color = hex_color
        self.setStyleSheet(
            f"""
            background-color: {QColor(hex_color).name()};
            border: 1px solid #666;
            border-radius: 2px;
        """
        )

    def set_color(self, hex_color: str):
        self._hex_color = hex_color
        self.setStyleSheet(
            f"""
            background-color: {QColor(hex_color).name()};
            border: 1px solid #666;
            border-radius: 2px;
        """
        )


class FavoritesManagerDialog(QDialog):
    """
    Dialog for managing favorite colors.

    Allows users to:
    - View all saved favorite colors
    - Edit color names
    - Edit color values
    - Delete favorites
    - Add new colors
    """

    def __init__(self, favorites_manager: FavoriteColorsManager, parent=None):
        super().__init__(parent)
        self.favorites_manager = favorites_manager
        self.setWindowTitle("Manage Favorite Colors")
        self.setMinimumSize(450, 400)
        self._build_ui()
        self._connect_signals()
        self._refresh_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Header
        header_label = QLabel("Saved favorite colors:")
        layout.addWidget(header_label)

        # Main list
        self.favorites_list = QListWidget()
        self.favorites_list.setAlternatingRowColors(True)
        layout.addWidget(self.favorites_list, 1)

        # Edit section (shown when item selected)
        edit_section = QWidget()
        edit_layout = QHBoxLayout(edit_section)
        edit_layout.setContentsMargins(0, 0, 0, 0)

        self.color_swatch = ColorSwatchWidget("#FFFFFF", size=28)
        edit_layout.addWidget(self.color_swatch)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Color name...")
        edit_layout.addWidget(self.name_edit, 1)

        self.pick_color_btn = QPushButton("Change Color")
        edit_layout.addWidget(self.pick_color_btn)

        self.save_edit_btn = QPushButton("Save")
        self.save_edit_btn.setEnabled(False)
        edit_layout.addWidget(self.save_edit_btn)

        layout.addWidget(edit_section)

        # Action buttons
        button_layout = QHBoxLayout()

        self.add_btn = QPushButton("Add Color...")
        button_layout.addWidget(self.add_btn)

        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setEnabled(False)
        button_layout.addWidget(self.delete_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Close")
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

        # Track currently selected favorite
        self._current_favorite_id: str | None = None
        self._current_hex: str = "#FFFFFFFF"

    def _connect_signals(self):
        self.favorites_list.currentItemChanged.connect(self._on_selection_changed)
        self.name_edit.textChanged.connect(self._on_edit_changed)
        self.pick_color_btn.clicked.connect(self._on_pick_color)
        self.save_edit_btn.clicked.connect(self._on_save_edit)
        self.add_btn.clicked.connect(self._on_add_color)
        self.delete_btn.clicked.connect(self._on_delete)
        self.close_btn.clicked.connect(self.accept)

    def _refresh_list(self):
        """Refresh the list of favorites."""
        self.favorites_list.clear()
        favorites = self.favorites_manager.get_all()

        for fav in favorites:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, fav["id"])

            # Create display text with color preview indicator
            hex_display = fav["hex"]
            if len(hex_display) == 9:  # #AARRGGBB format
                hex_display = "#" + hex_display[3:]  # Show as #RRGGBB for display

            display_text = f"{fav['name']}  ({hex_display})"
            item.setText(display_text)

            # Set background color hint
            color = QColor(fav["hex"])
            # Use a subtle background tint
            color.setAlpha(60)
            item.setBackground(color)

            self.favorites_list.addItem(item)

        # Clear edit section if list is empty
        if not favorites:
            self._current_favorite_id = None
            self.name_edit.clear()
            self.color_swatch.set_color("#FFFFFF")
            self.save_edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)

    def _on_selection_changed(
        self, current: QListWidgetItem, previous: QListWidgetItem
    ):
        """Handle selection change in the favorites list."""
        if current is None:
            self._current_favorite_id = None
            self.delete_btn.setEnabled(False)
            self.save_edit_btn.setEnabled(False)
            return

        favorite_id = current.data(Qt.UserRole)
        favorite = self.favorites_manager.get_by_id(favorite_id)

        if favorite:
            self._current_favorite_id = favorite_id
            self._current_hex = favorite["hex"]

            # Update edit section
            self.name_edit.blockSignals(True)
            self.name_edit.setText(favorite["name"])
            self.name_edit.blockSignals(False)

            self.color_swatch.set_color(favorite["hex"])
            self.delete_btn.setEnabled(True)
            self.save_edit_btn.setEnabled(False)

    def _on_edit_changed(self):
        """Handle changes in the edit fields."""
        if self._current_favorite_id:
            self.save_edit_btn.setEnabled(True)

    def _on_pick_color(self):
        """Open color dialog to change the selected favorite's color."""
        if not self._current_favorite_id:
            return

        initial_color = QColor(self._current_hex)
        color = QColorDialog.getColor(initial_color, self, "Select Color")

        if color.isValid():
            self._current_hex = color.name(QColor.HexArgb)
            self.color_swatch.set_color(self._current_hex)
            self.save_edit_btn.setEnabled(True)

    def _on_save_edit(self):
        """Save changes to the selected favorite."""
        if not self._current_favorite_id:
            return

        new_name = self.name_edit.text().strip()
        if not new_name:
            new_name = "Unnamed Color"

        self.favorites_manager.update(
            self._current_favorite_id, name=new_name, hex_color=self._current_hex
        )

        self.save_edit_btn.setEnabled(False)
        self._refresh_list()

        # Re-select the edited item
        for i in range(self.favorites_list.count()):
            item = self.favorites_list.item(i)
            if item.data(Qt.UserRole) == self._current_favorite_id:
                self.favorites_list.setCurrentItem(item)
                break

    def _on_add_color(self):
        """Add a new favorite color."""
        color = QColorDialog.getColor(QColor("#FFFFFFFF"), self, "Select Color to Add")

        if color.isValid():
            hex_color = color.name(QColor.HexArgb)
            new_id = self.favorites_manager.add("New Color", hex_color)
            self._refresh_list()

            # Select the newly added item
            for i in range(self.favorites_list.count()):
                item = self.favorites_list.item(i)
                if item.data(Qt.UserRole) == new_id:
                    self.favorites_list.setCurrentItem(item)
                    self.name_edit.setFocus()
                    self.name_edit.selectAll()
                    break

    def _on_delete(self):
        """Delete the selected favorite."""
        if not self._current_favorite_id:
            return

        favorite = self.favorites_manager.get_by_id(self._current_favorite_id)
        if not favorite:
            return

        reply = QMessageBox.question(
            self,
            "Delete Favorite",
            f"Delete '{favorite['name']}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.favorites_manager.remove(self._current_favorite_id)
            self._current_favorite_id = None
            self._refresh_list()
