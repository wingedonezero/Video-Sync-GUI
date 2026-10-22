# vsg_core/postprocess/auditors/drift_correction.py
"""
Auditor for timing corrections: stepping corrections that were applied, and
PAL / linear drift that was detected but is not corrected (that correction is
disconnected, see docs/plans/drift-correction.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path


class DriftCorrectionAuditor(BaseAuditor):
    """Reports drift that stays uncorrected; verifies applied stepping."""

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
        flagged = (
            len(self.ctx.pal_drift_flags)
            + len(self.ctx.linear_drift_flags)
            + len(self.ctx.segment_flags)
        )
        if flagged == 0:
            self.log("✅ No drift corrections were flagged (none needed).")
            return 0

        self.log(f"  → Checking {flagged} flagged timing issue(s)...")
        self._report_uncorrected_drift(self.ctx.pal_drift_flags, "PAL drift")
        self._report_uncorrected_drift(self.ctx.linear_drift_flags, "Linear drift")
        self._verify_stepping()

        if not self.issues:
            self.log(f"✅ All {flagged} flagged timing issue(s) handled.")
        return len(self.issues)

    def _report_uncorrected_drift(self, flag_dict: dict, kind: str) -> None:
        """Drift is detected but never corrected: the track drifts by design."""
        for analysis_key, info in flag_dict.items():
            source_key = analysis_key.split("_")[0]
            self._report(
                f"{kind} detected in {source_key} ({info.get('rate', 0.0):+.2f} ms/s) "
                f"but not corrected: drift correction is disconnected for now, so "
                f"its audio keeps the analysis delay and drifts over the file"
            )

    def _verify_stepping(self) -> None:
        for analysis_key, flag_info in self.ctx.segment_flags.items():
            source_key = analysis_key.split("_")[0]
            if flag_info.get("subs_only", False):
                continue
            if source_key not in self.ctx.stepping_corrections:
                # No verified EDL (uniform after all, or QA failed — the latter
                # is reported by the stepping auditor): the tracks took the
                # normal route.
                self.log(
                    f"  Note: stepping flagged for {source_key} but no verified EDL; "
                    f"its audio was muxed with the analysis delay"
                )
                continue

            corrected_items = [
                item
                for item in (self.ctx.extracted_items or [])
                if (
                    item.track.source == source_key
                    and item.track.type == "audio"
                    and item.is_corrected
                    and not item.is_preserved
                )
            ]
            if not corrected_items:
                self._report(
                    f"Stepping EDL verified for {source_key} but no corrected track "
                    f"in the final file (see the Audio Processing log)"
                )
                continue

            for item in corrected_items:
                track_name = item.track.props.name or f"Track {item.track.id}"
                if item.track.props.codec_id != "FLAC":
                    self._report(
                        f"Stepping corrected track '{track_name}' ({source_key}) "
                        f"is not FLAC (got {item.track.props.codec_id})"
                    )
                else:
                    self.log(
                        f"  ✓ Stepping correction verified for '{track_name}' "
                        f"({source_key})"
                    )

            preserved = [
                p
                for p in (self.ctx.extracted_items or [])
                if (
                    p.track.source == source_key
                    and p.track.type == "audio"
                    and p.is_preserved
                )
            ]
            if not preserved:
                self._report(
                    f"No preserved original for the stepping-corrected audio of "
                    f"{source_key}"
                )
