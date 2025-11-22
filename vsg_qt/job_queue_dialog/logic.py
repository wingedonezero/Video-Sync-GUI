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
from vsg_core.job_layouts import JobLayoutManager
from vsg_qt.manual_selection_dialog import ManualSelectionDialog
from vsg_qt.add_job_dialog import AddJobDialog

def natural_sort_key(s: str) -> List[Any]:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

class JobQueueLogic:
    def __init__(self, view: "JobQueueDialog", layout_manager: JobLayoutManager):
        self.v = view
        self.jobs: List[Dict[str, Any]] = []
        self.layout_manager = layout_manager

        self._layout_clipboard: Dict | None = None

        self.runner = CommandRunner(self.v.config.settings, self.v.log_callback)
        self.tool_paths = {t: shutil.which(t) for t in ['mkvmerge', 'mkvextract', 'ffmpeg', 'ffprobe']}

    def add_jobs(self, new_jobs: List[Dict]):
        """Initializes and adds new jobs to the queue."""
        for job in new_jobs:
            job['status'] = "Needs Configuration" # Set initial in-memory status
        new_jobs.sort(key=lambda j: natural_sort_key(Path(j['sources']['Source 1']).name))
        self.jobs.extend(new_jobs)
        self.populate_table()

    def add_jobs_from_dialog(self):
        dialog = AddJobDialog(self.v)
        if dialog.exec():
            self.add_jobs(dialog.get_discovered_jobs())

    def populate_table(self):
        """Fills the QTableWidget with the current list of jobs."""
        self.v.table.setRowCount(0)
        self.v.table.setColumnCount(3)
        headers = ["#", "Status", "Sources"]
        self.v.table.setHorizontalHeaderLabels(headers)
        header = self.v.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

        self.v.table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            self._update_row(row, job)

    def _update_row(self, row: int, job: Dict):
        """Updates a single row based on its on-disk and in-memory state."""
        job_id = self.layout_manager.generate_job_id(job['sources'])
        status_text = "Configured" if self.layout_manager.layout_exists(job_id) else "Needs Configuration"

        # *** THE FIX IS HERE ***
        # Update the in-memory status to match the on-disk reality.
        job['status'] = status_text

        order_item = QTableWidgetItem(str(row + 1)); order_item.setTextAlignment(Qt.AlignCenter)
        self.v.table.setItem(row, 0, order_item)
        self.v.table.setItem(row, 1, QTableWidgetItem(status_text))

        source_names = [Path(p).name for p in job['sources'].values()]
        item = QTableWidgetItem(" + ".join(source_names))
        item.setToolTip("\n".join(job['sources'].values()))
        self.v.table.setItem(row, 2, item)

    def _get_track_info_for_job(self, job: Dict) -> Dict | None:
        """Retrieves and caches track info for a job."""
        if 'track_info' not in job or job['track_info'] is None:
            try:
                # Pass subtitle folder info if available in job data
                subtitle_folder_path = job.get('subtitle_folder_path')
                subtitle_folder_sync_source = job.get('subtitle_folder_sync_source', 'Source 1')

                job['track_info'] = get_track_info_for_dialog(
                    job['sources'],
                    self.runner,
                    self.tool_paths,
                    subtitle_folder_path=subtitle_folder_path,
                    subtitle_folder_sync_source=subtitle_folder_sync_source
                )
            except Exception as e:
                QMessageBox.critical(self.v, "Error Analyzing Tracks", f"Could not analyze tracks for {Path(job['sources']['Source 1']).name}:\n{e}")
                return None
        return job['track_info']

    def configure_job_at_row(self, row: int):
        """Opens the ManualSelectionDialog and saves the result to disk."""
        job = self.jobs[row]
        job_id = self.layout_manager.generate_job_id(job['sources'])
        track_info = self._get_track_info_for_job(job)
        if not track_info: return

        existing_layout = self.layout_manager.load_job_layout(job_id)
        previous_layout = self._convert_enhanced_to_dialog_format(existing_layout.get('enhanced_layout')) if existing_layout else []
        previous_attachments = existing_layout.get('attachment_sources', []) if existing_layout else []

        dialog = ManualSelectionDialog(
            track_info, config=self.v.config, log_callback=self.v.log_callback, parent=self.v,
            previous_layout=previous_layout, previous_attachment_sources=previous_attachments
        )
        if dialog.exec():
            layout, attachment_sources = dialog.get_manual_layout_and_attachment_sources()
            if layout:
                save_ok = self.layout_manager.save_job_layout(job_id, layout, attachment_sources, job['sources'], track_info)
                if save_ok:
                    self._update_row(row, job)
                else:
                    QMessageBox.critical(self.v, "Save Failed", "Could not save the job layout. Check log for details.")

    def _convert_enhanced_to_dialog_format(self, enhanced_layout: List[Dict]) -> List[Dict]:
        if not enhanced_layout: return []
        return sorted(enhanced_layout, key=lambda x: x.get('user_order_index', 0))

    def copy_layout(self, source_job_index: int):
        """Loads a configured layout from disk into the in-memory clipboard."""
        job = self.jobs[source_job_index]
        job_id = self.layout_manager.generate_job_id(job['sources'])
        layout_data = self.layout_manager.load_job_layout(job_id)

        if layout_data:
            self._layout_clipboard = layout_data
            self.v.log_callback(f"[Queue] Copied layout from {Path(job['sources']['Source 1']).name}.")
        else:
            QMessageBox.warning(self.v, "Copy Failed", "Could not load the layout file to copy.")
            self._layout_clipboard = None

    def paste_layout(self):
        """Pastes the clipboard layout to selected jobs if compatible."""
        if not self._layout_clipboard:
            QMessageBox.warning(self.v, "Paste Failed", "Clipboard is empty. Please copy a layout first.")
            return

        selected_indices = {r.row() for r in self.v.table.selectionModel().selectedRows()}
        if not selected_indices:
            QMessageBox.information(self.v, "No Selection", "Please select one or more target jobs to paste to.")
            return

        source_struct_sig = self._layout_clipboard['structure_signature']
        updated_count = 0

        for target_index in selected_indices:
            target_job = self.jobs[target_index]
            target_track_info = self._get_track_info_for_job(target_job)
            if not target_track_info: continue

            target_struct_sig = self.layout_manager.signature_gen.generate_structure_signature(target_track_info)

            if self.layout_manager.signature_gen.structures_are_compatible(source_struct_sig, target_struct_sig):
                new_layout = self._replace_paths_in_layout(self._layout_clipboard['enhanced_layout'], target_job['sources'])

                target_job_id = self.layout_manager.generate_job_id(target_job['sources'])
                save_ok = self.layout_manager.save_job_layout(
                    target_job_id, new_layout, self._layout_clipboard['attachment_sources'],
                    target_job['sources'], target_track_info
                )
                if save_ok:
                    self._update_row(target_index, target_job)
                    updated_count += 1
            else:
                self.v.log_callback(f"Skipped pasting to {Path(target_job['sources']['Source 1']).name}: Incompatible track structure.")

        if updated_count > 0:
            QMessageBox.information(self.v, "Paste Successful", f"Successfully pasted layout to {updated_count} job(s).")
        else:
            QMessageBox.warning(self.v, "Paste Failed", "Could not paste layout to any selected jobs due to incompatible track structures.")

    def _replace_paths_in_layout(self, layout_template: List[Dict], target_sources: Dict[str, str]) -> List[Dict]:
        """Creates a new layout with file paths updated for the target job."""
        new_layout = []
        for track_template in layout_template:
            new_track = track_template.copy()
            source_key = new_track.get('source')
            if source_key in target_sources:
                new_track['original_path'] = target_sources[source_key]
            new_layout.append(new_track)
        return new_layout

    def remove_selected_jobs(self):
        """Removes selected jobs and deletes their layout files."""
        selected_rows = sorted([r.row() for r in self.v.table.selectionModel().selectedRows()], reverse=True)
        if not selected_rows: return
        for row in selected_rows:
            job_id = self.layout_manager.generate_job_id(self.jobs[row]['sources'])
            self.layout_manager.delete_layout(job_id)
            del self.jobs[row]
        self.populate_table()

    def get_final_jobs(self) -> List[Dict]:
        """Returns all jobs that have a configured layout saved to disk."""
        final_jobs = []
        unconfigured_names = []
        for job in self.jobs:
            if job.get('status') != 'Configured':
                unconfigured_names.append(Path(job['sources']['Source 1']).name)
                continue

            # Load from disk to ensure we have the definitive version
            job_id = self.layout_manager.generate_job_id(job['sources'])
            layout_data = self.layout_manager.load_job_layout(job_id)
            if layout_data:
                job['manual_layout'] = self._convert_enhanced_to_dialog_format(layout_data['enhanced_layout'])
                job['attachment_sources'] = layout_data.get('attachment_sources', [])
                final_jobs.append(job)
            else:
                unconfigured_names.append(Path(job['sources']['Source 1']).name)

        if unconfigured_names:
            QMessageBox.warning(self.v, "Unconfigured Jobs", f"{len(unconfigured_names)} job(s) are not configured and will be skipped.")

        return final_jobs
