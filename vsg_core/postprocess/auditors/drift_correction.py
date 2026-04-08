# vsg_core/postprocess/auditors/drift_correction.py
"""
Auditor for verifying drift corrections were applied correctly.
"""

from pathlib import Path

from .base import BaseAuditor


class DriftCorrectionAuditor(BaseAuditor):
    """Verifies drift corrections were applied correctly."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits drift corrections.
        Returns the number of issues found.
        """
        total_corrections = (
            len(self.ctx.pal_drift_flags)
            + len(self.ctx.linear_drift_flags)
            + len(self.ctx.segment_flags)
        )

        if total_corrections == 0:
            self.log("✅ No drift corrections were flagged (none needed).")
            return 0

        self.log(f"  → Verifying {total_corrections} drift correction(s)...")

        self._verify_correction_type(self.ctx.pal_drift_flags, "PAL Drift")
        self._verify_correction_type(self.ctx.linear_drift_flags, "Linear Drift")
        self._verify_correction_type(self.ctx.segment_flags, "Stepping")

        if not self.issues:
            self.log(
                f"✅ All {total_corrections} drift correction(s) verified successfully."
            )

        return len(self.issues)

    def _verify_correction_type(self, flag_dict: dict, correction_name: str) -> None:
        """Verify corrections for a specific correction type."""
        for analysis_key in flag_dict:
            source_key = analysis_key.split("_")[0]

            corrected_items = [
                item
                for item in self.ctx.extracted_items
                if (
                    item.track.source == source_key
                    and item.track.type == "audio"
                    and item.is_corrected
                    and not item.is_preserved
                )
            ]

            if not corrected_items:
                self._report(
                    f"{correction_name} correction was flagged for "
                    f"{source_key} but no corrected track found in final "
                    "file - correction step failed silently"
                )
                continue

            for item in corrected_items:
                track_name = item.track.props.name or f"Track {item.track.id}"

                if item.track.props.codec_id != "FLAC":
                    self._report(
                        f"{correction_name} corrected track '{track_name}' "
                        f"({source_key}) is not FLAC - expected FLAC, got "
                        f"{item.track.props.codec_id}; correction may not "
                        "have been applied correctly"
                    )
                else:
                    self.log(
                        f"  ✓ {correction_name} correction verified for "
                        f"'{track_name}' ({source_key})"
                    )

                preserved_items = [
                    p
                    for p in self.ctx.extracted_items
                    if (
                        p.track.source == source_key
                        and p.track.type == "audio"
                        and p.is_preserved
                    )
                ]

                if not preserved_items:
                    self._report(
                        f"No preserved original found for corrected track "
                        f"'{track_name}' ({source_key}) - original audio "
                        "was not preserved for comparison"
                    )
