# vsg_qt/job_queue_dialog/ui.py
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from vsg_qt.add_job_dialog import AddJobDialog

from .logic import JobQueueLogic


class JobQueueDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        log_callback: Callable[[str], None],
        layout_manager: JobLayoutManager,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Job Queue")
        self.setMinimumSize(1200, 600)

        self.config = config
        self.log_callback = log_callback
        self._logic = JobQueueLogic(self, layout_manager)

        self._build_ui()
        self._connect_signals()
        self.setAcceptDrops(True)
        self.populate_table()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls()]
            add_dialog = AddJobDialog(self)
            add_dialog.populate_sources_from_paths(paths)
            if add_dialog.exec():
                new_jobs = add_dialog.get_discovered_jobs()
                if new_jobs:
                    self._logic.add_jobs(new_jobs)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setAcceptDrops(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.add_job_btn = QPushButton("Add Job(s)...")
        self.remove_btn = QPushButton("Remove Selected")
        self.move_up_btn = QPushButton("Move Up")
        self.move_down_btn = QPushButton("Move Down")

        button_layout.addWidget(self.add_job_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.move_up_btn)
        button_layout.addWidget(self.move_down_btn)
        button_layout.addWidget(self.remove_btn)
        layout.addLayout(button_layout)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Start Processing Queue")
        layout.addWidget(dialog_btns)

        self.ok_button.clicked.connect(self.accept)
        dialog_btns.rejected.connect(self.reject)

    def _connect_signals(self):
        self.table.itemDoubleClicked.connect(
            lambda item: self._logic.configure_job_at_row(item.row())
        )
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.add_job_btn.clicked.connect(self._logic.add_jobs_from_dialog)
        self.remove_btn.clicked.connect(self._logic.remove_selected_jobs)
        self.move_up_btn.clicked.connect(lambda: self.move_selected_jobs(-1))
        self.move_down_btn.clicked.connect(lambda: self.move_selected_jobs(1))
        QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_Up), self, lambda: self.move_selected_jobs(-1)
        )
        QShortcut(
            QKeySequence(Qt.CTRL | Qt.Key_Down),
            self,
            lambda: self.move_selected_jobs(1),
        )

    def move_selected_jobs(self, direction: int):
        selected_rows = sorted(
            [r.row() for r in self.table.selectionModel().selectedRows()]
        )
        if not selected_rows:
            return

        if direction == -1 and selected_rows[0] > 0:
            for row_index in selected_rows:
                self._logic.jobs.insert(row_index - 1, self._logic.jobs.pop(row_index))
            new_selection_start = selected_rows[0] - 1
        elif direction == 1 and selected_rows[-1] < len(self._logic.jobs) - 1:
            for row_index in reversed(selected_rows):
                self._logic.jobs.insert(row_index + 1, self._logic.jobs.pop(row_index))
            new_selection_start = selected_rows[0] + 1
        else:
            return

        self.populate_table()
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        for i in range(len(selected_rows)):
            index = self.table.model().index(new_selection_start + i, 0)
            selection_model.select(
                index, QItemSelectionModel.Select | QItemSelectionModel.Rows
            )

    def populate_table(self):
        self.table.selectionModel().clear()
        self._logic.populate_table()

    def _show_context_menu(self, pos: Qt.Point):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        menu = QMenu()
        config_action = menu.addAction("Configure...")
        remove_action = menu.addAction("Remove from Queue")
        menu.addSeparator()
        copy_action = menu.addAction("Copy Layout")
        paste_action = menu.addAction("Paste Layout")

        config_action.setEnabled(len(selected_rows) == 1)

        # Enable "Copy" if a single, configured job is selected
        source_job_index = selected_rows[0].row()
        source_job = self._logic.jobs[source_job_index]
        is_configured = source_job.get("status") == "Configured"
        copy_action.setEnabled(len(selected_rows) == 1 and is_configured)

        # Enable "Paste" if the clipboard has content
        paste_action.setEnabled(self._logic._layout_clipboard is not None)

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == config_action:
            self._logic.configure_job_at_row(source_job_index)
        elif action == remove_action:
            self._logic.remove_selected_jobs()
        elif action == copy_action:
            self._logic.copy_layout(source_job_index)
        elif action == paste_action:
            self._logic.paste_layout()

    def get_final_jobs(self) -> list[dict]:
        return self._logic.get_final_jobs()
