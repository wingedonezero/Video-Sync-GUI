# vsg_core/reporting/debug_manager.py
"""
Debug output lifecycle management.

Manages creation, organization, and archiving of debug outputs across single-file
and batch processing modes. Handles directory creation, job registration, and
post-batch cleanup (zipping debug folders).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

from .debug_paths import DebugOutputPaths, DebugPathResolver

if TYPE_CHECKING:
    from collections.abc import Callable

    from vsg_core.models.settings import AppSettings


class DebugOutputManager:
    """Manages debug output directories and archiving for processing jobs.

    Responsibilities:
    - Register jobs and create their debug directory structure
    - Track all registered job paths
    - Finalize batch processing by zipping debug folders
    - Clean up temporary debug files after archiving

    Usage:
        # At batch start (controller)
        manager = DebugOutputManager(output_dir, is_batch=True, settings)

        # For each job (pipeline)
        debug_paths = manager.register_job(job_name)
        # Pass debug_paths to Context and use throughout pipeline

        # After all jobs complete (controller)
        manager.finalize_batch(log_callback)
    """

    def __init__(self, output_dir: Path, is_batch: bool, settings: AppSettings):
        """Initialize the debug output manager.

        Args:
            output_dir: Root output directory where files and debug/ will live
            is_batch: True if processing multiple jobs (affects structure)
            settings: AppSettings to determine which features are enabled
        """
        self.output_dir = Path(output_dir)
        self.is_batch = is_batch
        self.settings = settings
        self.job_paths: dict[str, DebugOutputPaths] = {}

    def register_job(self, job_name: str) -> DebugOutputPaths:
        """Register a job and get its debug output paths.

        Creates the necessary directories if any debug features are enabled.
        Safe to call multiple times for the same job (idempotent).

        Args:
            job_name: Sanitized job name (usually source1 filename stem)

        Returns:
            DebugOutputPaths with resolved paths for this job
        """
        # Resolve paths based on settings
        paths = DebugPathResolver.resolve(
            output_dir=self.output_dir,
            job_name=job_name,
            is_batch=self.is_batch,
            settings=self.settings,
        )

        # Store for later reference
        self.job_paths[job_name] = paths

        # Create directories if any debug features are enabled
        if paths.should_create_debug_root():
            self._create_directories(paths)

        return paths

    def _create_directories(self, paths: DebugOutputPaths) -> None:
        """Create the directory structure for enabled debug features.

        Args:
            paths: DebugOutputPaths with resolved paths
        """
        # Create debug root
        paths.debug_root.mkdir(parents=True, exist_ok=True)

        # Create feature-specific directories
        if paths.ocr_debug_dir:
            paths.ocr_debug_dir.mkdir(parents=True, exist_ok=True)

        if paths.frame_audit_dir:
            paths.frame_audit_dir.mkdir(parents=True, exist_ok=True)

        if paths.visual_verify_dir:
            paths.visual_verify_dir.mkdir(parents=True, exist_ok=True)

    def finalize_batch(self, log: Callable[[str], None]) -> None:
        """Finalize batch processing by zipping debug folders.

        Called after all jobs complete in batch mode. Zips each debug feature
        folder individually and deletes the unzipped contents.

        Only runs in batch mode. In single-file mode, debug folders are left
        unzipped for easier access.

        Args:
            log: Logging callback for status messages
        """
        if not self.is_batch:
            return

        if not self.job_paths:
            return

        # Get debug root from any registered job (all share the same root)
        sample_paths = next(iter(self.job_paths.values()))
        debug_root = sample_paths.debug_root

        if not debug_root.exists():
            return

        log(f"[DebugManager] Archiving debug outputs in {debug_root}")

        # Determine which features were actually used
        enabled_features = sample_paths.get_enabled_features()

        for feature_name in enabled_features:
            self._zip_debug_feature(debug_root, feature_name, log)

        log("[DebugManager] Debug output archiving complete")

    def _zip_debug_feature(
        self, debug_root: Path, feature_name: str, log: Callable[[str], None]
    ) -> None:
        """Zip a single debug feature folder and delete originals.

        Args:
            debug_root: Root debug directory (output_dir/debug/)
            feature_name: Feature name (e.g., "ocr_debug", "frame_audit")
            log: Logging callback
        """
        feature_dir = debug_root / feature_name

        if not feature_dir.exists():
            return

        # Check if directory has any actual files (not just empty subdirectories)
        # In batch mode, job subdirectories are pre-created even if the feature
        # never runs (e.g., ocr_debug/ when no OCR tracks exist), so we need
        # to check for real file content.
        has_files = any(f.is_file() for f in feature_dir.rglob("*"))
        if not has_files:
            log(f"[DebugManager] {feature_name}/ has no files, skipping archive")
            shutil.rmtree(feature_dir)
            return

        zip_path = debug_root / f"{feature_name}.zip"

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                # Walk the directory and add all files
                for file_path in feature_dir.rglob("*"):
                    if file_path.is_file():
                        # Store with relative path from feature_dir
                        arcname = file_path.relative_to(feature_dir)
                        zipf.write(file_path, arcname=arcname)

            # Delete the original directory after successful zip
            shutil.rmtree(feature_dir)

            log(f"[DebugManager] Created archive: {zip_path.name}")

        except Exception as e:
            log(f"[DebugManager] ERROR: Failed to archive {feature_name}/: {e}")
            # Don't delete the directory if zipping failed

    def has_any_debug_enabled(self) -> bool:
        """Check if any debug features are enabled.

        Returns:
            True if at least one debug feature is enabled
        """
        return (
            self.settings.ocr_debug_output
            or self.settings.video_verified_frame_audit
            or self.settings.video_verified_visual_verify
        )

    def get_job_paths(self, job_name: str) -> DebugOutputPaths | None:
        """Get debug paths for a previously registered job.

        Args:
            job_name: Job name used during registration

        Returns:
            DebugOutputPaths if job was registered, None otherwise
        """
        return self.job_paths.get(job_name)
