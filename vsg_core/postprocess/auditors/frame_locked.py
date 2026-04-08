# vsg_core/postprocess/auditors/frame_locked.py
"""
Auditor for FrameLocked subtitle sync quality.

Reports whether subtitle events had unexpected duration changes or end-time
adjustments beyond the delay. Does not inspect the final file; relies entirely
on stats stashed on PlanItems by the FrameLocked sync path.
"""

from pathlib import Path

from .base import BaseAuditor


class FrameLockedAuditor(BaseAuditor):
    """Audits stats collected during FrameLocked subtitle sync."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """Check stored FrameLocked stats for issues.

        Returns the number of issues found.
        """
        extracted = self.ctx.extracted_items or []
        framelocked_items = [
            item for item in extracted if getattr(item, "framelocked_stats", None)
        ]

        if not framelocked_items:
            self.log("[INFO] No FrameLocked subtitles found - skipping audit")
            return 0

        for item in framelocked_items:
            stats = item.framelocked_stats or {}
            track_name = item.track.props.name or f"Track {item.track.id}"

            final_duration_changed = stats.get("final_duration_changed", 0)
            final_end_adjusted = stats.get("final_end_adjusted", 0)
            total_events = stats.get("total_events", 0)

            self.log(f"[FrameLocked] {track_name}:")
            self.log(f"  - Total Events: {total_events}")
            self.log(f"  - Final Duration Changed: {final_duration_changed}")
            self.log(f"  - Final End Adjusted: {final_end_adjusted}")

            if final_duration_changed > 0:
                self._report(
                    f"{track_name}: {final_duration_changed} subtitle(s) had "
                    "duration changes - may indicate timing issues or "
                    "intentional zero-duration effects becoming visible"
                )

            if final_end_adjusted > 0:
                self._report(
                    f"{track_name}: {final_end_adjusted} subtitle(s) had end "
                    "times adjusted beyond delay - may indicate duration "
                    "modifications for frame visibility"
                )

            if final_duration_changed == 0 and final_end_adjusted == 0:
                self.log(
                    "[OK] All durations preserved correctly (zero-duration "
                    "effects stayed zero-duration)"
                )

        return len(self.issues)
