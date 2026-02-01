# vsg_core/job_layouts/manager.py
"""
Job Layout Manager Module

Orchestrates persistent track layout management for batch processing jobs with
identical file structures. Enables reusing user-configured track orders and settings
across multiple files.

Architecture:
- EnhancedSignatureGenerator: Creates track and structure signatures for comparing files
- LayoutPersistence: Handles JSON storage/loading of layout files in temp_root/job_layouts/
- LayoutValidator: Ensures loaded layouts have required fields and valid data
- JobLayoutManager: Main API coordinating save, load, copy, and validation operations

Key Features:
- Track Signatures: Detect changes in codec, language, channels, or sample rate
- Structure Signatures: Compare track counts/types to determine compatibility
- Layout Copying: Reuse layouts between jobs if file structures match
- Enhanced Layouts: Add positional metadata for robust track ordering

Job IDs are MD5 hashes of source file names, ensuring consistency across runs.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .persistence import LayoutPersistence
from .signature import EnhancedSignatureGenerator
from .validation import LayoutValidator

if TYPE_CHECKING:
    from collections.abc import Callable


class JobLayoutManager:
    """
    Main orchestrator for handling job layout persistence, copying, and validation.
    """

    def __init__(
        self, temp_root: str, log_callback: Callable[[str], None] | None = None
    ):
        self.log = log_callback or (lambda msg: print(msg))
        self.layouts_dir = Path(temp_root) / "job_layouts"

        self.signature_gen = EnhancedSignatureGenerator()
        self.persistence = LayoutPersistence(self.layouts_dir, self.log)
        self.validator = LayoutValidator()

    def generate_job_id(self, sources: dict[str, str]) -> str:
        """Generates a consistent and unique job ID from source file paths."""
        sorted_sources = sorted(sources.items())
        source_string = "|".join(
            f"{key}:{Path(path).name}" for key, path in sorted_sources if path
        )
        return hashlib.md5(source_string.encode()).hexdigest()[:16]

    def save_job_layout(
        self,
        job_id: str,
        layout: list[dict[str, Any]],
        attachment_sources: list[str],
        sources: dict[str, str],
        track_info: dict[str, list[dict]],
        source_settings: dict[str, dict[str, Any]] | None = None,
    ):
        """
        Saves a job layout, generating fresh signatures and enhancing the layout data.

        Args:
            source_settings: Per-source correlation settings, e.g.:
                {'Source 1': {'correlation_ref_track': 0}, 'Source 2': {'correlation_source_track': 1, 'use_source_separation': True}}
        """
        try:
            enhanced_layout = self._create_enhanced_layout(layout)
            track_sig = self.signature_gen.generate_track_signature(track_info)
            struct_sig = self.signature_gen.generate_structure_signature(track_info)

            layout_data = {
                "job_id": job_id,
                "sources": sources,
                "enhanced_layout": enhanced_layout,
                "attachment_sources": attachment_sources,
                "track_signature": track_sig,
                "structure_signature": struct_sig,
                "source_settings": source_settings or {},
            }

            if self.persistence.save_layout(job_id, layout_data):
                self.log(f"[LayoutManager] Saved layout for job {job_id}")
                return True
        except Exception as e:
            self.log(
                f"[LayoutManager] CRITICAL: Failed to save layout for {job_id}: {e}"
            )
        return False

    def load_job_layout(self, job_id: str) -> dict[str, Any] | None:
        """Loads and validates a job layout."""
        layout_data = self.persistence.load_layout(job_id)
        if layout_data:
            is_valid, reason = self.validator.validate(layout_data)
            if is_valid:
                return layout_data
            else:
                self.log(f"[LayoutManager] Validation failed for {job_id}: {reason}")
        return None

    def copy_layout_between_jobs(
        self,
        source_job_id: str,
        target_job_id: str,
        target_sources: dict[str, str],
        target_track_info: dict[str, list[dict]],
    ) -> bool:
        """Copies a layout if the source and target files are structurally compatible."""
        source_data = self.load_job_layout(source_job_id)
        if not source_data:
            self.log(
                f"[LayoutManager] Cannot copy: Source layout {source_job_id} not found."
            )
            return False

        source_struct_sig = source_data["structure_signature"]
        target_struct_sig = self.signature_gen.generate_structure_signature(
            target_track_info
        )

        if not self.signature_gen.structures_are_compatible(
            source_struct_sig, target_struct_sig
        ):
            self.log(
                f"[LayoutManager] Cannot copy: Incompatible track structures between {source_job_id} and {target_job_id}."
            )
            return False

        # Structures are compatible, create a new layout file for the target
        target_track_sig = self.signature_gen.generate_track_signature(
            target_track_info
        )

        target_layout_data = {
            "job_id": target_job_id,
            "sources": target_sources,
            "enhanced_layout": source_data[
                "enhanced_layout"
            ],  # The core data being copied
            "attachment_sources": source_data.get("attachment_sources", []),
            "source_settings": source_data.get(
                "source_settings", {}
            ),  # Copy per-source correlation settings
            "track_signature": target_track_sig,
            "structure_signature": target_struct_sig,
            "copied_from": source_job_id,
        }

        return self.persistence.save_layout(target_job_id, target_layout_data)

    def _create_enhanced_layout(
        self, layout: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Adds positional metadata to a layout for robust ordering."""
        enhanced = []
        source_type_positions = defaultdict(int)
        for user_index, track in enumerate(layout):
            enhanced_track = dict(track)
            source = track["source"]
            track_type = track["type"]
            source_type_key = f"{source}_{track_type}"

            enhanced_track.update(
                {
                    "user_order_index": user_index,
                    "position_in_source_type": source_type_positions[source_type_key],
                }
            )
            source_type_positions[source_type_key] += 1
            enhanced.append(enhanced_track)
        return enhanced

    def layout_exists(self, job_id: str) -> bool:
        return self.persistence.layout_exists(job_id)

    def delete_layout(self, job_id: str):
        return self.persistence.delete_layout(job_id)

    def cleanup_all(self):
        """Deletes all temporary layout files and releases cached video resources."""
        self.persistence.cleanup_all()

        # Clear VFR cache to release VideoTimestamps instances and prevent nanobind leaks
        try:
            from vsg_core.subtitles.frame_utils import clear_vfr_cache

            clear_vfr_cache()
        except ImportError:
            pass  # Module might not be loaded
