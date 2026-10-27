# vsg_core/postprocess/auditors/frame_audit.py
"""
Auditor for reporting frame alignment audit results.

Reads FrameAuditResult objects stored on ctx during subtitle sync and
reports issue counts per track. The detailed summary is already logged
at sync time; this auditor surfaces the results to the final audit
pass/fail so they appear in the batch report.
"""

from pathlib import Path

from .base import BaseAuditor


class FrameAuditAuditor(BaseAuditor):
    """Reports frame alignment audit results from video-verified sync."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Check stored frame audit results for issues.

        Returns the number of tracks with frame drift issues, plus Source 1
        frame-timeline warnings (holes in the stream, formula disagreement).
        """
        for note in self.ctx.frame_grid_notes:
            if note.severity == "warning":
                self._report(f"Source 1 frame grid: {note.message}")
            else:
                self.log(f"[INFO] Source 1 frame grid: {note.message}")

        if not self.ctx.frame_audit_results:
            self.log("[INFO] No frame audit results available - skipping")
            return len(self.issues)

        for track_key, result in self.ctx.frame_audit_results.items():
            start_issues = result.start_early + result.start_late
            end_issues = result.end_early + result.end_late
            span_issues = result.span_changed

            # Duration deltas: for OCR-origin tracks the <=10ms bucket is
            # forced by ASS centisecond storage (bitmap timing sits at
            # arbitrary whole ms) and provably cannot move an event across a
            # frame — report it, don't count it. Native ASS/SRT deltas stay
            # counted: their timestamps are already grid-aligned, so any
            # delta there is rare and worth eyes on. >10ms buckets always
            # count — big enough to be a canary regardless of origin.
            quantization_deltas = 0
            duration_issues = (
                result.duration_delta_10ms
                + result.duration_delta_20ms
                + result.duration_delta_large
            )
            if getattr(result, "ocr_origin", False):
                quantization_deltas = result.duration_delta_10ms
                duration_issues = (
                    result.duration_delta_20ms + result.duration_delta_large
                )

            quant_note = (
                f"; {quantization_deltas} duration delta(s) ≤10ms "
                f"(OCR-origin timing → ASS centisecond storage, "
                f"frame span unchanged)"
                if quantization_deltas > 0
                else ""
            )
            # Deltas from storing an exact frame-snap time in centiseconds:
            # every frame of those events is checked unchanged, so not counted.
            snapped = getattr(result, "duration_delta_frame_time", 0)
            if snapped:
                quant_note += (
                    f"; {snapped} duration delta(s) ≤10ms from frame-snapped "
                    "times (centisecond storage, frames unchanged)"
                )

            has_any = start_issues + end_issues + span_issues + duration_issues > 0

            if has_any and result.correction_applied:
                # Issues were detected but corrected by surgical rounding
                self.log(
                    f"  ✓ {track_key}: {start_issues} start, {end_issues} end "
                    f"issues CORRECTED ({result.corrected_timing_points} timing "
                    f"points fixed via frame-aware rounding){quant_note}"
                )
                # Don't count as issues since they were corrected
            elif has_any:
                self._report(
                    f"{track_key}: {start_issues} start, {end_issues} end, "
                    f"{span_issues} span, {duration_issues} duration issues"
                    f"{quant_note}"
                )
            else:
                self.log(
                    f"  ✓ {track_key}: 0 start, 0 end, 0 span, "
                    f"{duration_issues} duration issues{quant_note}"
                )

        if not self.issues:
            self.log("✅ All frame audits passed - no frame drift detected")

        return len(self.issues)
