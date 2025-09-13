# vsg_core/job_layouts/manager.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable
from collections import defaultdict

from .signature import EnhancedSignatureGenerator
from .persistence import LayoutPersistence
from .validation import LayoutValidator

class JobLayoutManager:
    """
    Main orchestrator for handling job layout persistence, copying, and validation.
    """
    def __init__(self, temp_root: str, log_callback: Optional[Callable[[str], None]] = None):
        self.log = log_callback or (lambda msg: print(msg))
        self.layouts_dir = Path(temp_root) / "job_layouts"

        self.signature_gen = EnhancedSignatureGenerator()
        self.persistence = LayoutPersistence(self.layouts_dir, self.log)
        self.validator = LayoutValidator()

    def generate_job_id(self, sources: Dict[str, str]) -> str:
        """Generates a consistent and unique job ID from source file paths."""
        sorted_sources = sorted(sources.items())
        source_string = "|".join(f"{key}:{Path(path).name}" for key, path in sorted_sources if path)
        return hashlib.md5(source_string.encode()).hexdigest()[:16]

    def save_job_layout(self, job_id: str, layout: List[Dict[str, Any]],
                        attachment_sources: List[str], sources: Dict[str, str],
                        track_info: Dict[str, List[Dict]]):
        """
        Saves a job layout, generating fresh signatures and enhancing the layout data.
        """
        try:
            enhanced_layout = self._create_enhanced_layout(layout)
            track_sig = self.signature_gen.generate_track_signature(track_info)
            struct_sig = self.signature_gen.generate_structure_signature(track_info)

            layout_data = {
                'job_id': job_id,
                'sources': sources,
                'enhanced_layout': enhanced_layout,
                'attachment_sources': attachment_sources,
                'track_signature': track_sig,
                'structure_signature': struct_sig,
            }

            if self.persistence.save_layout(job_id, layout_data):
                self.log(f"[LayoutManager] Saved layout for job {job_id}")
                return True
        except Exception as e:
            self.log(f"[LayoutManager] CRITICAL: Failed to save layout for {job_id}: {e}")
        return False

    def load_job_layout(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Loads and validates a job layout."""
        layout_data = self.persistence.load_layout(job_id)
        if layout_data:
            is_valid, reason = self.validator.validate(layout_data)
            if is_valid:
                return layout_data
            else:
                self.log(f"[LayoutManager] Validation failed for {job_id}: {reason}")
        return None

    def copy_layout_between_jobs(self, source_job_id: str, target_job_id: str,
                                 target_sources: Dict[str, str],
                                 target_track_info: Dict[str, List[Dict]]) -> bool:
        """Copies a layout if the source and target files are structurally compatible."""
        source_data = self.load_job_layout(source_job_id)
        if not source_data:
            self.log(f"[LayoutManager] Cannot copy: Source layout {source_job_id} not found.")
            return False

        source_struct_sig = source_data['structure_signature']
        target_struct_sig = self.signature_gen.generate_structure_signature(target_track_info)

        if not self.signature_gen.structures_are_compatible(source_struct_sig, target_struct_sig):
            self.log(f"[LayoutManager] Cannot copy: Incompatible track structures between {source_job_id} and {target_job_id}.")
            return False

        # Structures are compatible, create a new layout file for the target
        target_track_sig = self.signature_gen.generate_track_signature(target_track_info)

        target_layout_data = {
            'job_id': target_job_id,
            'sources': target_sources,
            'enhanced_layout': source_data['enhanced_layout'], # The core data being copied
            'attachment_sources': source_data.get('attachment_sources', []),
            'track_signature': target_track_sig,
            'structure_signature': target_struct_sig,
            'copied_from': source_job_id
        }

        return self.persistence.save_layout(target_job_id, target_layout_data)

    def _create_enhanced_layout(self, layout: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Adds positional metadata to a layout for robust ordering."""
        enhanced = []
        source_type_positions = defaultdict(int)
        for user_index, track in enumerate(layout):
            enhanced_track = dict(track)
            source = track['source']
            track_type = track['type']
            source_type_key = f"{source}_{track_type}"

            enhanced_track.update({
                'user_order_index': user_index,
                'position_in_source_type': source_type_positions[source_type_key]
            })
            source_type_positions[source_type_key] += 1
            enhanced.append(enhanced_track)
        return enhanced

    def layout_exists(self, job_id: str) -> bool:
        return self.persistence.layout_exists(job_id)

    def delete_layout(self, job_id: str):
        return self.persistence.delete_layout(job_id)

    def cleanup_all(self):
        """Deletes all temporary layout files."""
        self.persistence.cleanup_all()
