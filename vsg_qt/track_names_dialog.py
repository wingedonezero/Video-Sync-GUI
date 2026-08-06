# vsg_qt/track_names_dialog.py
"""
Saved Track Names dialog.

Used in two modes:
- Picker (from Track Settings on subtitle tracks): choose a saved name to
  fill the Custom Name box. Double-click or "Use Selected" accepts.
- Manager (from Options): maintain the global list; no selection result.

The list is always sorted alphabetically and can be filtered with the
search box at the top.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vsg_core.config import get_config_dir_path
from vsg_core.track_names import TrackNamesManager


class TrackNamesDialog(QDialog):
    """Select and manage the global list of reusable track names."""

    def __init__(
        self,
        *,
        select_mode: bool = True,
        initial_text: str = "",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "Select Custom Name" if select_mode else "Manage Custom Track Names"
        )
        self.setMinimumSize(420, 380)

        self._manager = TrackNamesManager(get_config_dir_path())
        self._select_mode = select_mode
        self._initial_text = initial_text.strip()
        self.selected_name: str = ""

        layout = QVBoxLayout(self)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._refresh_list)
        layout.addWidget(self.search_input)

        self.name_list = QListWidget()
        self.name_list.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.name_list)

        edit_row = QHBoxLayout()
        add_btn = QPushButton("Add…")
        add_btn.clicked.connect(self._on_add)
        rename_btn = QPushButton("Rename…")
        rename_btn.clicked.connect(self._on_rename)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._on_remove)
        edit_row.addWidget(add_btn)
        edit_row.addWidget(rename_btn)
        edit_row.addWidget(remove_btn)
        edit_row.addStretch(1)
        layout.addLayout(edit_row)

        if select_mode:
            btns = QDialogButtonBox()
            use_btn = btns.addButton(
                "Use Selected", QDialogButtonBox.ButtonRole.AcceptRole
            )
            use_btn.setDefault(True)
            btns.addButton(QDialogButtonBox.StandardButton.Cancel)
            btns.accepted.connect(self._on_use_selected)
            btns.rejected.connect(self.reject)
        else:
            btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
            btns.rejected.connect(self.reject)
            btns.clicked.connect(lambda _: self.reject())
        layout.addWidget(btns)

        self._refresh_list()
        self.search_input.setFocus()

    # --- list handling ---

    def _refresh_list(self) -> None:
        query = self.search_input.text().strip().casefold()
        current = self._current_name()
        self.name_list.clear()
        for name in self._manager.get_all():
            if query and query not in name.casefold():
                continue
            item = QListWidgetItem(name)
            self.name_list.addItem(item)
            if name == current:
                self.name_list.setCurrentItem(item)
        if self.name_list.currentRow() < 0 and self.name_list.count() > 0:
            self.name_list.setCurrentRow(0)

    def _current_name(self) -> str:
        item = self.name_list.currentItem()
        return item.text() if item else ""

    # --- actions ---

    def _on_add(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Add Custom Name",
            "Track name:",
            QLineEdit.EchoMode.Normal,
            self._initial_text,
        )
        if not ok or not name.strip():
            return
        self._manager.add(name)
        self._select_after_refresh(name.strip())

    def _on_rename(self) -> None:
        old = self._current_name()
        if not old:
            return
        new, ok = QInputDialog.getText(
            self, "Rename Custom Name", "Track name:", QLineEdit.EchoMode.Normal, old
        )
        if not ok or not new.strip():
            return
        if self._manager.rename(old, new):
            self._select_after_refresh(new.strip())

    def _on_remove(self) -> None:
        name = self._current_name()
        if name:
            self._manager.remove(name)
            self._refresh_list()

    def _select_after_refresh(self, name: str) -> None:
        self._refresh_list()
        matches = self.name_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if matches:
            self.name_list.setCurrentItem(matches[0])

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if self._select_mode:
            self.selected_name = item.text()
            self.accept()

    def _on_use_selected(self) -> None:
        name = self._current_name()
        if not name:
            return
        self.selected_name = name
        self.accept()
