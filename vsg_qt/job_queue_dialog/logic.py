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

        # NEW: Additional check for generated tracks and sync exclusions (doesn't affect existing validation)
        validation_warning = ""
        all_issues = []
        if status_text == "Configured":
            # Only check if layout exists
            layout_data = self.layout_manager.load_job_layout(job_id)
            if layout_data:
                gen_issues = self._validate_generated_tracks(layout_data, job)
                sync_exclusion_issues = self._validate_sync_exclusions(layout_data, job)

                if gen_issues:
                    all_issues.extend([f"Generated: {issue}" for issue in gen_issues])
                if sync_exclusion_issues:
                    all_issues.extend([f"Sync Exclusion: {issue}" for issue in sync_exclusion_issues])

                if all_issues:
                    validation_warning = " ⚠️"
                    # Store issues for tooltip or dialog display
                    job['validation_issues'] = all_issues

        # *** THE FIX IS HERE ***
        # Update the in-memory status to match the on-disk reality.
        job['status'] = status_text + validation_warning

        order_item = QTableWidgetItem(str(row + 1)); order_item.setTextAlignment(Qt.AlignCenter)
        self.v.table.setItem(row, 0, order_item)
        status_item = QTableWidgetItem(status_text + validation_warning)
        if validation_warning:
            # Add tooltip showing what's wrong
            issues_text = job.get('validation_issues', [])
            status_item.setToolTip("Layout validation warnings:\n" + "\n".join(issues_text))
        self.v.table.setItem(row, 1, status_item)

        source_names = [Path(p).name for p in job['sources'].values()]
        item = QTableWidgetItem(" + ".join(source_names))
        item.setToolTip("\n".join(job['sources'].values()))
        self.v.table.setItem(row, 2, item)

    def _validate_generated_tracks(self, layout_data: Dict, job: Dict) -> List[str]:
        """
        Validates that generated tracks in the layout have valid style filters.
        This is an ADDITIONAL check that doesn't affect existing layout matching.

        Auto-fixes safe mismatches:
        - If ONLY missing styles (styles in original but not in current): Auto-update baseline, no warning
        - If ANY extra styles (styles in current but not in original): Show warning, requires manual review

        Returns list of warning messages if there are issues, empty list if OK.
        """
        from vsg_core.subtitles.style_filter import StyleFilterEngine

        issues = []
        enhanced_layout = layout_data.get('enhanced_layout', [])
        layout_modified = False

        for track in enhanced_layout:
            # Skip non-generated tracks
            if not track.get('is_generated'):
                continue

            # Get the source track details
            source_id = track.get('generated_source_track_id')
            source_key = track.get('source')
            original_style_list = track.get('generated_original_style_list', [])
            track_name = track.get('custom_name') or track.get('name', 'Unknown')

            if not original_style_list:
                # No original style list stored - can't validate
                # This might happen for older layouts created before this feature
                continue

            # Get the actual source file path from the job
            source_file = job['sources'].get(source_key)
            if not source_file:
                issues.append(f"'{track_name}': Source '{source_key}' not found")
                continue

            try:
                # Extract the source subtitle temporarily to check styles
                import tempfile
                import time
                from pathlib import Path
                from vsg_core.extraction.tracks import extract_tracks

                # CRITICAL FIX: Include job_id to make temp path unique per episode
                # Without this, all episodes would share the same temp directory and could
                # validate against the wrong episode's subtitle file
                job_id = self.layout_manager.generate_job_id(job['sources'])
                timestamp = int(time.time() * 1000)  # milliseconds for uniqueness
                temp_dir = Path(tempfile.gettempdir()) / f"vsg_gen_validate_{job_id}_{source_key}_{source_id}_{timestamp}"
                temp_dir.mkdir(parents=True, exist_ok=True)

                try:
                    extracted = extract_tracks(source_file, temp_dir, self.runner, self.tool_paths, 'validate', specific_tracks=[source_id])
                    if not extracted:
                        issues.append(f"'{track_name}': Could not extract source track for validation")
                        continue

                    # Get available styles from the extracted file
                    available_styles = StyleFilterEngine.get_styles_from_file(extracted[0]['path'])
                    available_style_set = set(available_styles.keys())

                    # ADDITIONAL CHECK: Validate that the filter styles actually exist
                    # This catches cases where style names changed (e.g., "Default" -> "Dialogue")
                    filter_styles = track.get('generated_filter_styles', [])
                    if filter_styles:
                        missing_filter_styles = [s for s in filter_styles if s not in available_style_set]
                        if missing_filter_styles:
                            issues.append(
                                f"'{track_name}': Filter styles not found in target file: "
                                f"{', '.join(missing_filter_styles)} - Generated track may not filter any events"
                            )

                    # Compare complete style sets
                    original_style_set = set(original_style_list)

                    if original_style_set != available_style_set:
                        # Style sets don't match - find what's different
                        missing_styles = original_style_set - available_style_set
                        extra_styles = available_style_set - original_style_set

                        # AUTO-FIX: If ONLY missing styles (no extras), update baseline silently
                        # This is SAFE because missing styles can't include unwanted dialogue
                        if missing_styles and not extra_styles:
                            # Update the baseline to match current file (remove missing styles)
                            track['generated_original_style_list'] = sorted(available_styles.keys())
                            layout_modified = True
                            # Don't add to issues - this is safe and auto-fixed

                        # WARN: If ANY extra styles exist, require manual review
                        # This is RISKY because extra styles might contain unwanted dialogue
                        elif extra_styles:
                            warning_parts = []
                            if missing_styles:
                                warning_parts.append(f"Missing: {', '.join(sorted(missing_styles))}")
                            warning_parts.append(f"Extra: {', '.join(sorted(extra_styles))}")
                            issues.append(f"'{track_name}': Style set mismatch ({'; '.join(warning_parts)})")

                finally:
                    # Clean up temp extraction
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)

            except Exception as e:
                # If validation fails, warn but don't block
                issues.append(f"'{track_name}': Could not validate styles ({str(e)})")

        # If we auto-fixed any tracks, save the updated layout
        if layout_modified:
            job_id = self.layout_manager.generate_job_id(job['sources'])
            self.layout_manager.persistence.save_layout(job_id, layout_data)

        return issues

    def _validate_sync_exclusions(self, layout_data: Dict, job: Dict) -> List[str]:
        """
        Validates that sync exclusion styles in the layout match the current file.
        This is an ADDITIONAL check that doesn't affect existing layout matching.

        Auto-fixes safe mismatches:
        - If ONLY missing styles (styles in original but not in current): Auto-update baseline, no warning
        - If ANY extra styles (styles in current but not in original): Show warning, requires manual review

        Returns list of warning messages if there are issues, empty list if OK.
        """
        from vsg_core.subtitles.style_filter import StyleFilterEngine

        issues = []
        enhanced_layout = layout_data.get('enhanced_layout', [])
        layout_modified = False

        for track in enhanced_layout:
            # Skip tracks without sync exclusions
            if not track.get('sync_exclusion_styles'):
                continue

            # Skip non-subtitle tracks (shouldn't happen, but be safe)
            if track.get('type') != 'subtitles':
                continue

            track_name = track.get('custom_name') or track.get('description', 'Unknown')
            original_style_list = track.get('sync_exclusion_original_style_list', [])

            if not original_style_list:
                # No original style list stored - can't validate
                continue

            # Get the actual subtitle file path
            source_key = track.get('source')
            source_file = job['sources'].get(source_key)
            if not source_file:
                issues.append(f"'{track_name}': Source '{source_key}' not found")
                continue

            try:
                # For sync exclusions, we need to check the current file's styles
                # If it's a generated track, we need to extract it first
                # Otherwise, we can check the original path directly

                subtitle_path = None
                if track.get('is_generated'):
                    # For generated tracks, we need to extract the source track temporarily
                    import tempfile
                    import time
                    from pathlib import Path
                    from vsg_core.extraction.tracks import extract_tracks

                    source_id = track.get('id')  # Use the generated track's own ID
                    job_id = self.layout_manager.generate_job_id(job['sources'])
                    timestamp = int(time.time() * 1000)
                    temp_dir = Path(tempfile.gettempdir()) / f"vsg_sync_validate_{job_id}_{source_key}_{source_id}_{timestamp}"
                    temp_dir.mkdir(parents=True, exist_ok=True)

                    try:
                        extracted = extract_tracks(source_file, temp_dir, self.runner, self.tool_paths, 'validate', specific_tracks=[source_id])
                        if extracted:
                            subtitle_path = extracted[0]['path']
                    except:
                        subtitle_path = None

                    if not subtitle_path:
                        issues.append(f"'{track_name}': Could not extract track for sync exclusion validation")
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        continue
                else:
                    # For non-generated tracks, use the source file directly
                    # Extract the specific track temporarily
                    import tempfile
                    import time
                    from pathlib import Path
                    from vsg_core.extraction.tracks import extract_tracks

                    track_id = track.get('id')
                    job_id = self.layout_manager.generate_job_id(job['sources'])
                    timestamp = int(time.time() * 1000)
                    temp_dir = Path(tempfile.gettempdir()) / f"vsg_sync_validate_{job_id}_{source_key}_{track_id}_{timestamp}"
                    temp_dir.mkdir(parents=True, exist_ok=True)

                    try:
                        extracted = extract_tracks(source_file, temp_dir, self.runner, self.tool_paths, 'validate', specific_tracks=[track_id])
                        if extracted:
                            subtitle_path = extracted[0]['path']
                    except:
                        subtitle_path = None

                    if not subtitle_path:
                        issues.append(f"'{track_name}': Could not extract track for sync exclusion validation")
                        import shutil
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        continue

                try:
                    # Get available styles from the file
                    available_styles = StyleFilterEngine.get_styles_from_file(subtitle_path)
                    available_style_set = set(available_styles.keys())

                    # Validate that the exclusion styles actually exist
                    exclusion_styles = track.get('sync_exclusion_styles', [])
                    if exclusion_styles:
                        missing_exclusion_styles = [s for s in exclusion_styles if s not in available_style_set]
                        if missing_exclusion_styles:
                            issues.append(
                                f"'{track_name}': Sync exclusion styles not found: "
                                f"{', '.join(missing_exclusion_styles)}"
                            )

                    # Compare complete style sets
                    original_style_set = set(original_style_list)

                    if original_style_set != available_style_set:
                        missing_styles = original_style_set - available_style_set
                        extra_styles = available_style_set - original_style_set

                        # AUTO-FIX: If ONLY missing styles, update baseline silently
                        if missing_styles and not extra_styles:
                            track['sync_exclusion_original_style_list'] = sorted(available_styles.keys())
                            layout_modified = True

                        # WARN: If ANY extra styles exist, require manual review
                        elif extra_styles:
                            warning_parts = []
                            if missing_styles:
                                warning_parts.append(f"Missing: {', '.join(sorted(missing_styles))}")
                            warning_parts.append(f"Extra: {', '.join(sorted(extra_styles))}")
                            issues.append(f"'{track_name}': Sync exclusion style mismatch ({'; '.join(warning_parts)})")

                finally:
                    # Clean up temp extraction
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)

            except Exception as e:
                # If validation fails, warn but don't block
                issues.append(f"'{track_name}': Could not validate sync exclusion styles ({str(e)})")

        # If we auto-fixed any tracks, save the updated layout
        if layout_modified:
            job_id = self.layout_manager.generate_job_id(job['sources'])
            self.layout_manager.persistence.save_layout(job_id, layout_data)

        return issues

    def _get_track_info_for_job(self, job: Dict) -> Dict | None:
        """Retrieves and caches track info for a job."""
        if 'track_info' not in job or job['track_info'] is None:
            try:
                job['track_info'] = get_track_info_for_dialog(job['sources'], self.runner, self.tool_paths)
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
        previous_source_settings = existing_layout.get('source_settings', {}) if existing_layout else {}

        dialog = ManualSelectionDialog(
            track_info, config=self.v.config, log_callback=self.v.log_callback, parent=self.v,
            previous_layout=previous_layout, previous_attachment_sources=previous_attachments,
            previous_source_settings=previous_source_settings
        )
        if dialog.exec():
            layout, attachment_sources, source_settings = dialog.get_manual_layout_and_attachment_sources()
            if layout:
                save_ok = self.layout_manager.save_job_layout(
                    job_id, layout, attachment_sources, job['sources'], track_info,
                    source_settings=source_settings
                )
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
                    target_job['sources'], target_track_info,
                    source_settings=self._layout_clipboard.get('source_settings', {})
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
                # CRITICAL FIX: Also update generated_source_path for generated tracks
                # This ensures the Edit dialog extracts from the correct source file
                if new_track.get('is_generated'):
                    new_track['generated_source_path'] = target_sources[source_key]
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
            # Check if status starts with "Configured" (might have ⚠️ suffix)
            if not job.get('status', '').startswith('Configured'):
                unconfigured_names.append(Path(job['sources']['Source 1']).name)
                continue

            # Load from disk to ensure we have the definitive version
            job_id = self.layout_manager.generate_job_id(job['sources'])
            layout_data = self.layout_manager.load_job_layout(job_id)
            if layout_data:
                job['manual_layout'] = self._convert_enhanced_to_dialog_format(layout_data['enhanced_layout'])
                job['attachment_sources'] = layout_data.get('attachment_sources', [])
                job['source_settings'] = layout_data.get('source_settings', {})
                final_jobs.append(job)
            else:
                unconfigured_names.append(Path(job['sources']['Source 1']).name)

        if unconfigured_names:
            QMessageBox.warning(self.v, "Unconfigured Jobs", f"{len(unconfigured_names)} job(s) are not configured and will be skipped.")

        return final_jobs
