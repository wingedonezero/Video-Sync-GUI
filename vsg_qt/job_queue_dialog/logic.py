# vsg_qt/job_queue_dialog/logic.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import shutil
import re
from pathlib import Path
from typing import List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem, QMessageBox, QHeaderView

from vsg_core.io.runner import CommandRunner
from vsg_core.extraction.tracks import get_track_info_for_dialog
from vsg_qt.main_window.helpers import generate_track_signature, materialize_layout, layout_to_template
from vsg_qt.manual_selection_dialog import ManualSelectionDialog
from vsg_qt.add_job_dialog import AddJobDialog

def natural_sort_key(s: str) -> List[Any]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

class JobQueueLogic:
    def __init__(self, view: "JobQueueDialog"):
        self.v = view
        self.jobs: List[Dict[str, Any]] = []
        self._layout_clipboard: Dict | None = None
        self._clipboard_source_job: Dict | None = None

    def add_jobs_from_dialog(self):
        """Opens the AddJobDialog and appends discovered jobs to the queue."""
        dialog = AddJobDialog(self.v)
        if dialog.exec():
            new_jobs = dialog.get_discovered_jobs()
            for job in new_jobs:
                job['status'] = "Not Configured"
                job['manual_layout'] = None
                job['track_info'] = None
                job['signature'] = None

            self.jobs.extend(new_jobs)
            self.jobs.sort(key=lambda j: natural_sort_key(Path(j['sources']['Source 1']).name))
            self.populate_table()

    def populate_table(self):
        """Fills the QTableWidget with the current list of jobs, adding columns if needed."""
        self.v.table.setRowCount(0)

        max_sources = 0
        if self.jobs:
            max_sources = max(len(job['sources']) for job in self.jobs)

        # Base columns: #, Status
        num_base_cols = 2
        # Ensure table has enough columns for #, Status, and all sources
        if self.v.table.columnCount() < num_base_cols + max_sources:
            self.v.table.setColumnCount(num_base_cols + max_sources)
            headers = ["#", "Status"] + [f"Source {i+1}" for i in range(max_sources)]
            headers[2] = "Source 1 (Reference)"
            self.v.table.setHorizontalHeaderLabels(headers)
            self.v.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
            self.v.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
            for i in range(2, self.v.table.columnCount()):
                 self.v.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)

        self.v.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            self._update_row(row, job)

    def _update_row(self, row: int, job: Dict):
        status_text = "Configured ✓" if job['status'] == "Configured" else "Not Configured"
        order_item = QTableWidgetItem(str(row + 1)); order_item.setTextAlignment(Qt.AlignCenter)
        self.v.table.setItem(row, 0, order_item)
        self.v.table.setItem(row, 1, QTableWidgetItem(status_text))

        # Populate source columns dynamically
        for i in range(2, self.v.table.columnCount()):
            source_key = f"Source {i-1}"
            path_str = job['sources'].get(source_key)
            item_text = Path(path_str).name if path_str else ''
            self.v.table.setItem(row, i, QTableWidgetItem(item_text))

    def _get_track_info_for_job(self, job: Dict) -> Dict | None:
        if job and job.get('track_info') is None:
            try:
                runner = CommandRunner(self.v.config.settings, self.v.log_callback)
                tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg']}
                job['track_info'] = get_track_info_for_dialog(job['sources'], runner, tool_paths)
            except Exception as e:
                QMessageBox.critical(self.v, "Error Analyzing Tracks", f"Could not analyze tracks for {Path(job['sources']['Source 1']).name}:\n{e}")
                return None
        return job.get('track_info') if job else None

    def configure_selected_job(self):
        selected_rows = self.v.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self.v, "No Job Selected", "Please select a single job from the list to configure.")
            return
        self.configure_job_at_row(selected_rows[0].row())

    def configure_job_at_row(self, row: int):
        job = self.jobs[row]
        track_info = self._get_track_info_for_job(job)
        if not track_info: return

        dialog = ManualSelectionDialog(track_info, config=self.v.config,
                                     log_callback=self.v.log_callback, parent=self.v,
                                     previous_layout=layout_to_template(job['manual_layout']))
        if dialog.exec():
            job['manual_layout'] = dialog.get_manual_layout()
            job['status'] = "Configured"
            job['signature'] = None
            self._update_row(row, job)

    def apply_layout_to_matching(self):
        selected_rows = self.v.table.selectionModel().selectedRows()
        if not selected_rows:
            QMessageBox.information(self.v, "No Job Selected", "Please select a single configured job to use as a template.")
            return

        source_job = self.jobs[selected_rows[0].row()]
        if source_job['status'] != "Configured" or not source_job['manual_layout']:
            QMessageBox.warning(self.v, "Not Configured", "The selected job has not been configured yet.")
            return

        strict_match = self.v.config.get('auto_apply_strict', False)
        source_track_info = self._get_track_info_for_job(source_job)
        if not source_track_info: return

        source_sig = generate_track_signature(source_track_info, strict=strict_match)
        source_template = layout_to_template(source_job['manual_layout'])

        updated_count = 0
        for i, target_job in enumerate(self.jobs):
            if target_job is source_job or target_job['status'] == 'Configured': continue

            target_track_info = self._get_track_info_for_job(target_job)
            if not target_track_info: continue

            target_sig = generate_track_signature(target_track_info, strict=strict_match)
            if source_sig == target_sig:
                target_job['manual_layout'] = materialize_layout(source_template, target_track_info)
                target_job['status'] = 'Configured'
                self._update_row(i, target_job)
                updated_count += 1

        QMessageBox.information(self.v, "Layout Applied", f"Applied the selected layout to {updated_count} other matching jobs.")

    def remove_selected_jobs(self):
        selected_rows = sorted([r.row() for r in self.v.table.selectionModel().selectedRows()], reverse=True)
        if not selected_rows: return

        for row in selected_rows:
            del self.jobs[row]
        self.populate_table()

    def copy_layout(self):
        selected_rows = self.v.table.selectionModel().selectedRows()
        if not selected_rows: return

        job = self.jobs[selected_rows[0].row()]
        if job['status'] == 'Configured':
            self._layout_clipboard = layout_to_template(job['manual_layout'])
            self._clipboard_source_job = job
            self.v.log_callback(f"[Queue] Copied layout from {Path(job['sources']['Source 1']).name}.")
        else:
            QMessageBox.warning(self.v, "Not Configured", "Cannot copy layout from a job that has not been configured.")

    def paste_layout(self):
        selected_indices = [r.row() for r in self.v.table.selectionModel().selectedRows()]
        if not selected_indices or not self._layout_clipboard: return

        strict_match = self.v.config.get('auto_apply_strict', False)
        source_track_info = self._get_track_info_for_job(self._clipboard_source_job)
        source_sig = generate_track_signature(source_track_info, strict=strict_match)

        for row in selected_indices:
            target_job = self.jobs[row]
            target_track_info = self._get_track_info_for_job(target_job)
            if not target_track_info: continue

            target_sig = generate_track_signature(target_track_info, strict=strict_match)

            proceed = True
            if source_sig != target_sig:
                reply = QMessageBox.warning(self.v, "Signature Mismatch",
                    f"The layout from '{Path(self._clipboard_source_job['sources']['Source 1']).name}' may not be compatible with '{Path(target_job['sources']['Source 1']).name}'.\n\n"
                    "Do you want to apply it anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                proceed = (reply == QMessageBox.Yes)

            if proceed:
                target_job['manual_layout'] = materialize_layout(self._layout_clipboard, target_track_info)
                target_job['status'] = 'Configured'
                self._update_row(row, target_job)

    def get_configured_jobs(self) -> List[Dict]:
        return [job for job in self.jobs if job['status'] == 'Configured']
