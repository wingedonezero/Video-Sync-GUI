# vsg_core/postprocess/auditors/subtitle_duration.py
"""
Renders the text-subtitle end-time-vs-video audit in the final audit.

The check itself runs during subtitle processing (``SubtitlesStep`` →
``track_processor``): it compares each track's final ``SubtitleData`` event
end times against the reference video duration and stashes a
``SubtitleDurationAuditResult`` on ``ctx.subtitle_duration_audit_results``.
This auditor only renders those results — it does not re-probe or extract
anything (mirrors ``BitmapTimingAuditor``).

A subtitle ending past the last video frame lingers on a held/black frame
after the picture ends; this surfaces it as a batch-report warning so it can
be watched over time. **Read-only** — no clamping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path

    from vsg_core.subtitles.operations.duration_audit import (
        SubtitleDurationAuditResult,
    )


class SubtitleDurationAuditor(BaseAuditor):
    """Renders text-subtitle end-time-vs-video results (read-only)."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        results = self.ctx.subtitle_duration_audit_results
        if not results:
            self.log("[INFO] No text-subtitle duration results — skipping.")
            return 0

        for result in results.values():
            self._render(result)

        if not self.issues:
            self.log("  All subtitle tracks end within video duration.")

        return len(self.issues)

    def _render(self, result: SubtitleDurationAuditResult) -> None:
        label = result.track_label
        last_s = result.max_end_ms / 1000

        if not result.video_duration_known:
            self.log(
                f"  {label}: last subtitle ends at {last_s:.3f}s "
                "— video duration unknown, not compared."
            )
            return

        video_s = (result.video_duration_ms or 0.0) / 1000

        if result.events_overflow > 0:
            msg = (
                f"{label}: {result.events_overflow} subtitle line(s) end past "
                f"the video — last ends {last_s:.3f}s vs video {video_s:.3f}s "
                f"(+{result.overflow_ms:.0f}ms)"
            )
            if result.events_start_past_video > 0:
                msg += (
                    f"; {result.events_start_past_video} line(s) start entirely "
                    "after the video ends"
                )
            self._report(msg)
        else:
            self.log(
                f"  {label} last subtitle ends at {last_s:.3f}s — OK "
                f"(delta {result.overflow_ms / 1000:+.3f}s)"
            )
