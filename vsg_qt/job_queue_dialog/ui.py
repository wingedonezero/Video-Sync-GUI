# vsg_qt/job_queue_dialog/ui.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Dict, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QDialogButtonBox,
    QTableWidget, QAbstractItemView, QHeaderView, QMenu
)

from .logic import JobQueueLogic

class JobQueueDialog(QDialog):
    def __init__(self, config: "AppConfig", log_callback: Callable[[str], None], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Job Queue")
        self.setMinimumSize(1200, 600)

        self.config = config
        self.log_callback = log_callback
        self._logic = JobQueueLogic(self)
        self._build_ui()
        self._connect_signals()

        self._logic.populate_table()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.table = QTableWidget()
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
        self.configure_btn = QPushButton("Configure Selected Job...")
        self.apply_layout_btn = QPushButton("Apply Layout to All Matching")
        self.remove_btn = QPushButton("Remove Selected")

        button_layout.addWidget(self.add_job_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.configure_btn)
        button_layout.addWidget(self.apply_layout_btn)
        button_layout.addWidget(self.remove_btn)
        layout.addLayout(button_layout)

        dialog_btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = dialog_btns.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Start Processing Queue")
        layout.addWidget(dialog_btns)

        self.ok_button.clicked.connect(self.accept)
        dialog_btns.rejected.connect(self.reject)

    def _connect_signals(self):
        self.table.itemDoubleClicked.connect(lambda item: self._logic.configure_job_at_row(item.row()))
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.add_job_btn.clicked.connect(self._logic.add_jobs_from_dialog)
        self.configure_btn.clicked.connect(self._logic.configure_selected_job)
        self.apply_layout_btn.clicked.connect(self._logic.apply_layout_to_matching)
        self.remove_btn.clicked.connect(self._logic.remove_selected_jobs)

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
