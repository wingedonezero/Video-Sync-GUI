# vsg_core/postprocess/auditors/subtitle_clamping.py
"""
Auditor for reporting subtitle tracks where negative timestamps were clamped to 0.

This occurs when a negative delay is applied (allow_negative mode) and subtitle
events would start before 0ms. Since ASS/SRT formats cannot represent negative
timestamps, these events are clamped to 0ms which may cause sync issues for
content in the first few seconds of the video.
"""

from pathlib import Path

from vsg_core.models.enums import TrackType

from .base import BaseAuditor


class SubtitleClampingAuditor(BaseAuditor):
    """
    Reports subtitle tracks where negative timestamps were clamped to 0.

    This is informational - it lets the user know that some subtitle events
    at the beginning of the video may be out of sync due to format limitations.
    """

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits subtitle clamping.
        Returns the number of tracks with clamped events.
        """
        issues = 0
        clamped_tracks = []

        # Check all subtitle items for clamping info
        for item in self.ctx.extracted_items:
            if item.track.type != TrackType.SUBTITLES:
                continue

            if not hasattr(item, "clamping_info") or not item.clamping_info:
                continue

            info = item.clamping_info
            track_name = item.track.props.name or f"Track {item.track.id}"
            source = item.track.source

            clamped_tracks.append({"name": track_name, "source": source, "info": info})

        if not clamped_tracks:
            self.log("[OK] No subtitle events were clamped to 0ms")
            return 0

        # Report each track with clamping
        for track in clamped_tracks:
            info = track["info"]
            self.log(f"[WARNING] {track['name']} ({track['source']}):")
            self.log(f"    {info['events_clamped']} event(s) clamped to 0ms")
            self.log(f"    Delay applied: {info['delay_ms']:+.1f}ms")
            self.log(
                f"    Negative range: {info['min_time_ms']:.0f}ms to {info['max_time_ms']:.0f}ms"
            )
            self.log(
                "    These events will appear at 0ms instead of their calculated times"
            )
            issues += 1

        # Summary
        if issues > 0:
            self.log(
                f"\n[INFO] {issues} subtitle track(s) had events clamped due to negative timestamps"
            )
            self.log(
                "       This is a format limitation (ASS/SRT cannot store negative times)"
            )
            self.log("       Early subtitle events may be slightly out of sync")

        return issues
