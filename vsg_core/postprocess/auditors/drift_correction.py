# vsg_core/postprocess/auditors/drift_correction.py
"""
Auditor for verifying drift corrections were applied correctly.
"""
from pathlib import Path

from vsg_core.models.enums import TrackType

from .base import BaseAuditor


class DriftCorrectionAuditor(BaseAuditor):
    """Verifies drift corrections were applied correctly."""

    def run(self, final_mkv_path: Path, final_mkvmerge_data: dict,
            final_ffprobe_data: dict | None = None) -> int:
        """
        Audits drift corrections.
        Returns the number of issues found.
        """
        issues = 0

        total_corrections = (
            len(self.ctx.pal_drift_flags) +
            len(self.ctx.linear_drift_flags) +
            len(self.ctx.segment_flags)
        )

        if total_corrections == 0:
            self.log("✅ No drift corrections were flagged (none needed).")
            return 0

        self.log(f"  → Verifying {total_corrections} drift correction(s)...")

        issues += self._verify_correction_type(
            self.ctx.pal_drift_flags,
            "PAL Drift"
        )

        issues += self._verify_correction_type(
            self.ctx.linear_drift_flags,
            "Linear Drift"
        )

        issues += self._verify_correction_type(
            self.ctx.segment_flags,
            "Stepping"
        )

        if issues == 0:
            self.log(f"✅ All {total_corrections} drift correction(s) verified successfully.")

        return issues

    def _verify_correction_type(self, flag_dict: dict, correction_name: str) -> int:
        """
        Verify corrections for a specific correction type.
        Returns number of issues found.
        """
        issues = 0

        for analysis_key in flag_dict:
            source_key = analysis_key.split('_')[0]

            corrected_items = [
                item for item in self.ctx.extracted_items
                if (item.track.source == source_key and
                    item.track.type == TrackType.AUDIO and
                    item.is_corrected and
                    not item.is_preserved)
            ]

            if not corrected_items:
                self.log(f"[WARNING] {correction_name} correction was flagged for "
                        f"{source_key} but no corrected track found in final file!")
                self.log("          This indicates the correction step failed silently.")
                issues += 1
                continue

            for item in corrected_items:
                track_name = item.track.props.name or f"Track {item.track.id}"

                if item.track.props.codec_id != "FLAC":
                    self.log(f"[WARNING] {correction_name} corrected track '{track_name}' "
                            f"({source_key}) is not FLAC!")
                    self.log("          Expected: FLAC")
                    self.log(f"          Actual:   {item.track.props.codec_id}")
                    self.log("          → Correction may not have been applied correctly.")
                    issues += 1
                else:
                    self.log(f"  ✓ {correction_name} correction verified for "
                            f"'{track_name}' ({source_key})")

                preserved_items = [
                    p for p in self.ctx.extracted_items
                    if (p.track.source == source_key and
                        p.track.type == TrackType.AUDIO and
                        p.is_preserved)
                ]

                if not preserved_items:
                    self.log(f"[WARNING] No preserved original found for corrected track "
                            f"'{track_name}' ({source_key})")
                    self.log("          Original audio was not preserved for comparison.")
                    issues += 1

        return issues
