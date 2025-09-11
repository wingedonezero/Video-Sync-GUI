# vsg_qt/job_queue_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Callable

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
    QTableWidget, QAbstractItemView, QHeaderView, QMenu
)

from .logic import JobQueueLogic
from vsg_qt.add_job_dialog import AddJobDialog
from vsg_qt.manual_selection_dialog import ManualSelectionDialog # <-- BUG FIX: Added missing import
from vsg_qt.main_window.helpers import layout_to_template

class JobQueueDialog(QDialog):
    def __init__(self, config: "AppConfig", log_callback: Callable[[str], None], parent=None,
                 initial_jobs: List[Dict] = None):
        super().__init__(parent)
        self.setWindowTitle("Job Queue")
        self.setMinimumSize(1200, 600)

        self.config = config
        self.log_callback = log_callback
        self._logic = JobQueueLogic(self)
        self._build_ui()
        self._connect_signals()

        # Allow dropping files directly onto this window
        self.setAcceptDrops(True)

        if initial_jobs:
            self._logic.add_jobs(initial_jobs)

        if not initial_jobs:
            self.populate_table()

    def dragEnterEvent(self, event):
        """Accepts the drag event if it contains file paths."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """Handles dropping files by opening the AddJobDialog for review."""
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
        # Enable dropping on the table widget itself
        self.table.setAcceptDrops(True)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection) # Allow multi-select
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["#", "Status", "Source 1 (Reference)", "Source 2", "Source 3"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)

        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)

        layout.addWidget(self.table)

        button_layout = QHBoxLayout()
        self.add_job_btn = QPushButton("Add Job(s)...")
        self.configure_btn = QPushButton("Configure Selected...")
        self.remove_btn = QPushButton("Remove Selected")
        self.move_up_btn = QPushButton("Move Up")
        self.move_down_btn = QPushButton("Move Down")

        button_layout.addWidget(self.add_job_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.move_up_btn)
        button_layout.addWidget(self.move_down_btn)
        button_layout.addWidget(self.configure_btn)
        button_layout.addWidget(self.remove_btn)
        layout.addLayout(button_layout)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Start Processing Queue")
        layout.addWidget(dialog_btns)

        self.ok_button.clicked.connect(self.accept)
        dialog_btns.rejected.connect(self.reject)

    def _connect_signals(self):
        self.table.itemDoubleClicked.connect(lambda item: self.configure_job_at_row(item.row()))
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.add_job_btn.clicked.connect(self._logic.add_jobs_from_dialog)
        self.configure_btn.clicked.connect(self._logic.configure_selected_job)
        self.remove_btn.clicked.connect(self._logic.remove_selected_jobs)

        # Connect move buttons
        self.move_up_btn.clicked.connect(lambda: self.move_selected_jobs(-1))
        self.move_down_btn.clicked.connect(lambda: self.move_selected_jobs(1))

        # Connect keyboard shortcuts
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Up), self, lambda: self.move_selected_jobs(-1))
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Down), self, lambda: self.move_selected_jobs(1))

    def move_selected_jobs(self, direction: int):
        """Moves all selected items in the table up (dir=-1) or down (dir=1)."""
        if not self._logic.jobs:
            return

        selected_rows = sorted([r.row() for r in self.table.selectionModel().selectedRows()])
        if not selected_rows:
            return

        if direction == -1: # Move Up
            if selected_rows[0] == 0:
                return # Can't move top item up

            # Perform swaps from top to bottom
            for row_index in selected_rows:
                self._logic.jobs.insert(row_index - 1, self._logic.jobs.pop(row_index))
            new_selection_start = selected_rows[0] - 1

        elif direction == 1: # Move Down
            if selected_rows[-1] == len(self._logic.jobs) - 1:
                return # Can't move bottom item down

            # Perform swaps from bottom to top to preserve indices
            for row_index in reversed(selected_rows):
                self._logic.jobs.insert(row_index + 1, self._logic.jobs.pop(row_index))
            new_selection_start = selected_rows[0] + 1

        self.populate_table()

        # Restore selection
        selection_model = self.table.selectionModel()
        selection_model.clearSelection()
        for i in range(len(selected_rows)):
            selection_model.select(self.table.model().index(new_selection_start + i, 0),
                                   QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def populate_table(self):
        # This UI class now owns populating, logic class just manages data
        self.table.selectionModel().clear()
        self._logic.populate_table()

    def configure_job_at_row(self, row):
        job = self._logic.jobs[row]
        track_info = self._logic._get_track_info_for_job(job)
        if not track_info: return

        dialog = ManualSelectionDialog(
            track_info,
            config=self.config,
            log_callback=self.log_callback,
            parent=self,
            previous_layout=layout_to_template(job['manual_layout']),
            previous_attachment_sources=job.get('attachment_sources')
        )
        if dialog.exec():
            layout, attachment_sources = dialog.get_manual_layout_and_attachment_sources()
            job['manual_layout'] = layout
            job['attachment_sources'] = attachment_sources
            job['status'] = "Configured"
            job['signature'] = None # Clear signature as it was manually configured
            self._logic._update_row(row, job)

    def _show_context_menu(self, pos):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows: return

        is_single_selection = len(selected_rows) == 1
        selected_job = self._logic.jobs[selected_rows[0].row()] if is_single_selection else None

        menu = QMenu()
        config_action = menu.addAction("Configure...")
        remove_action = menu.addAction("Remove from Queue")
        menu.addSeparator()
        copy_action = menu.addAction("Copy Layout")
        paste_action = menu.addAction("Paste Layout")

        config_action.setEnabled(is_single_selection)
        copy_action.setEnabled(is_single_selection and selected_job and selected_job['status'] == 'Configured')
        paste_action.setEnabled(self._logic._layout_clipboard is not None)

        action = menu.exec(self.table.viewport().mapToGlobal(pos))

        if action == config_action: self._logic.configure_selected_job()
        elif action == remove_action: self._logic.remove_selected_jobs()
        elif action == copy_action: self._logic.copy_layout()
        elif action == paste_action: self._logic.paste_layout()

    def get_configured_jobs(self) -> List[Dict]:
        return self._logic.get_configured_jobs()
