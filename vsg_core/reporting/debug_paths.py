# vsg_core/reporting/debug_paths.py
"""
Debug output path resolution.

Provides pure path logic for organizing debug outputs (OCR debug, frame audit,
visual verify) in single-file and batch modes. No I/O operations - just path
resolution based on settings and job context.

Path Structure:
    Single File Mode:
        output_folder/
          ├── output.mkv
          └── debug/
              ├── ocr_debug/
              ├── frame_audit/
              └── visual_verify/

    Batch Mode:
        output_folder/batch_name/
          ├── file1.mkv
          ├── file2.mkv
          ├── batch_name.zip (logs)
          └── debug/
              ├── ocr_debug/
              │   ├── file1_job/
              │   └── file2_job/
              ├── frame_audit/
              └── visual_verify/
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.models.settings import AppSettings


@dataclass(frozen=True, slots=True)
class DebugOutputPaths:
    """Resolved paths for all debug outputs for a single job.

    All paths are resolved at job start based on settings. Paths are None
    if the corresponding debug feature is disabled.
    """

    # Root paths
    output_dir: Path  # Where the final .mkv goes
    job_name: str  # Sanitized source1 filename stem
    is_batch: bool  # True if processing multiple jobs

    # Debug root (parent of all debug outputs)
    debug_root: Path  # output_dir/debug/

    # Feature-specific paths
    ocr_debug_dir: Path | None  # debug/ocr_debug/{job_name}/ (batch) or debug/ocr_debug/ (single)
    frame_audit_dir: Path | None  # debug/frame_audit/
    visual_verify_dir: Path | None  # debug/visual_verify/

    def should_create_debug_root(self) -> bool:
        """Check if any debug feature is enabled."""
        return any([self.ocr_debug_dir, self.frame_audit_dir, self.visual_verify_dir])

    def get_enabled_features(self) -> list[str]:
        """Get list of enabled debug feature names."""
        features = []
        if self.ocr_debug_dir:
            features.append("ocr_debug")
        if self.frame_audit_dir:
            features.append("frame_audit")
        if self.visual_verify_dir:
            features.append("visual_verify")
        return features


class DebugPathResolver:
    """Resolves debug output paths based on mode and settings.

    Pure path logic - no filesystem operations. All path resolution is
    deterministic based on inputs.
    """

    @staticmethod
    def resolve(
        output_dir: Path,
        job_name: str,
        is_batch: bool,
        settings: AppSettings,
    ) -> DebugOutputPaths:
        """Create path structure based on enabled features.

        Args:
            output_dir: Directory where output .mkv will be written
            job_name: Sanitized job name (source1 filename stem)
            is_batch: True if processing multiple jobs
            settings: AppSettings to check which features are enabled

        Returns:
            DebugOutputPaths with resolved paths
        """
        debug_root = output_dir / "debug"

        # Determine which features are enabled
        ocr_enabled = settings.ocr_debug_output
        frame_audit_enabled = settings.video_verified_frame_audit
        visual_verify_enabled = settings.video_verified_visual_verify

        # Resolve OCR debug path
        ocr_debug_dir = None
        if ocr_enabled:
            if is_batch:
                # Batch: debug/ocr_debug/{job_name}/
                ocr_debug_dir = debug_root / "ocr_debug" / job_name
            else:
                # Single: debug/ocr_debug/
                ocr_debug_dir = debug_root / "ocr_debug"

        # Resolve frame audit path
        frame_audit_dir = None
        if frame_audit_enabled:
            # Same structure for single and batch - files are named uniquely
            frame_audit_dir = debug_root / "frame_audit"

        # Resolve visual verify path
        visual_verify_dir = None
        if visual_verify_enabled:
            # Same structure for single and batch - files are named uniquely
            visual_verify_dir = debug_root / "visual_verify"

        return DebugOutputPaths(
            output_dir=output_dir,
            job_name=job_name,
            is_batch=is_batch,
            debug_root=debug_root,
            ocr_debug_dir=ocr_debug_dir,
            frame_audit_dir=frame_audit_dir,
            visual_verify_dir=visual_verify_dir,
        )

    @staticmethod
    def sanitize_job_name(source1_path: str) -> str:
        """Sanitize source1 filename to use as job name.

        Removes problematic characters that could cause filesystem issues.

        Args:
            source1_path: Full path to source1 file

        Returns:
            Sanitized filename stem safe for use in paths
        """
        stem = Path(source1_path).stem
        # Replace problematic characters with underscores
        safe_chars = []
        for char in stem:
            if char.isalnum() or char in "._- ":
                safe_chars.append(char)
            else:
                safe_chars.append("_")
        return "".join(safe_chars).strip("_")
