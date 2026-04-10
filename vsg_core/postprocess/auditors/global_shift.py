# vsg_core/postprocess/auditors/global_shift.py
"""
Auditor for verifying global shift was applied correctly.
"""

from pathlib import Path

from .base import BaseAuditor


class GlobalShiftAuditor(BaseAuditor):
    """Verifies global shift was applied correctly to all tracks."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits global shift application.
        Returns the number of issues found.
        """
        if not self.ctx.delays:
            self.log("✅ No delays calculated (analysis skipped or single source).")
            return 0

        global_shift = self.ctx.delays.global_shift_ms

        if global_shift == 0:
            self.log("✅ No global shift was required (all delays were non-negative).")
            return 0

        self.log(
            f"  → Verifying global shift of +{global_shift}ms was applied correctly..."
        )

        audio_items = [
            item for item in (self.ctx.extracted_items or []) if item.track.type == "audio"
        ]

        for item in audio_items:
            expected_delay = self._calculate_expected_delay(item)

            if expected_delay < 0:
                track_name = item.track.props.name or f"Track {item.track.id}"
                self._report(
                    f"Audio track '{track_name}' ({item.track.source}) has "
                    f"negative delay after global shift (expected delay "
                    f"{expected_delay}ms, global shift +{global_shift}ms) - "
                    "global shift calculation may be incorrect"
                )

        if not self.issues:
            self.log(
                f"✅ Global shift of +{global_shift}ms verified (no negative delays)."
            )

        return len(self.issues)
