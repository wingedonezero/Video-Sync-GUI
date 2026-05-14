"""
Auditor for bitmap-subtitle timing — surfaces what the in-app PGS
(and future VobSub) shifter found into the final audit report.

Reads ``ctx.bitmap_audit_results`` (populated by the shifter in
``SubtitlesStep``) and emits:

* Tier 1 (sanity) — events dropped, clamped, overflowing, duration
  anomalies, monotonicity. Always reported. Non-zero counts surface
  as warnings in the batch report.
* Tier 2 (frame alignment) — same model as text-sub frame_audit:
  ``F_actual == F_target`` per endpoint, where
  ``F_target = F_src + round(delay_ms / period)``. Includes counts of
  applied per-event corrections and any duration deltas that the
  corrections introduced.

Today's pipeline reports ``No frame audit results available -
skipping`` for bitmap subs because the text-only ``FrameAuditAuditor``
doesn't see them. This auditor fills that gap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import BaseAuditor

if TYPE_CHECKING:
    from pathlib import Path


class BitmapTimingAuditor(BaseAuditor):
    """Surface PGS / VobSub shifter audit results in the post-mux report."""

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        if not self.ctx.bitmap_audit_results:
            self.log("[INFO] No bitmap shifter results — skipping")
            return 0

        for audit_key, result in self.ctx.bitmap_audit_results.items():
            self._report_one(audit_key, result)

        return len(self.issues)

    # ------------------------------------------------------------------

    def _report_one(self, audit_key: str, result) -> None:
        t1 = result.tier1
        t2 = result.tier2

        kind_label = {
            "vv-frame": "video-verified (frame-derived)",
            "vv-correlation-fallback": "video-verified fallback (correlation)",
            "correlation": "audio correlation",
            "zero": "no shift (Source 1 / zero delay)",
        }.get(result.delay_source_kind, result.delay_source_kind)

        self.log(f"\n  ── {audit_key}: {result.track_label} ──")
        self.log(
            f"     Delay: {result.applied_delay_ms:+d} ms applied "
            f"(requested {result.requested_delay_ms:+.3f} ms, "
            f"source: {kind_label})"
        )

        # Tier 1: sanity
        self.log(
            f"     Tier 1 (sanity): {t1.events_total} events, "
            f"{t1.events_dropped_pre_shift} dropped (neg-shift), "
            f"{t1.events_clamped_start} clamped"
        )
        if t1.events_overflow_video > 0:
            self._report(
                f"{audit_key}: {t1.events_overflow_video} event(s) extend past "
                "video duration after shift"
            )
        if t1.events_negative_duration > 0:
            self._report(
                f"{audit_key}: {t1.events_negative_duration} event(s) with "
                "negative duration"
            )
        if t1.events_zero_duration > 0:
            self._report(
                f"{audit_key}: {t1.events_zero_duration} event(s) with zero duration"
            )
        if t1.events_excessive_duration > 0:
            self._report(
                f"{audit_key}: {t1.events_excessive_duration} event(s) with "
                "duration > 60 s (suspicious)"
            )
        if t1.events_below_min_duration > 0:
            self.log(
                f"     [info] {t1.events_below_min_duration} event(s) with "
                "duration < 100 ms (legal but short)"
            )
        if t1.monotonicity_violations > 0:
            self._report(
                f"{audit_key}: {t1.monotonicity_violations} event(s) violate "
                "chronological ordering (likely encoder bug, pre-existing)"
            )

        # Tier 2: frame alignment (text-sub-style)
        if t2 is None:
            if result.frame_align_enabled:
                self.log(
                    "     Tier 2 (frame alignment): skipped (shifter returned no result)"
                )
            else:
                self.log(
                    "     Tier 2 (frame alignment): skipped (target fps unavailable)"
                )
            return

        is_corrective = result.delay_source_kind == "vv-frame"
        tag = "corrective" if is_corrective else "informational"
        self.log(
            f"     Tier 2 (frame alignment, {tag}): "
            f"target {t2.target_fps:.3f} fps, "
            f"frame period {t2.frame_period_ms:.3f} ms, "
            f"frame_shift {t2.frame_shift:+d} frame(s)"
        )
        starts_pct = (
            100.0 * t2.starts_correct / t2.starts_total if t2.starts_total else 0.0
        )
        ends_pct = 100.0 * t2.ends_correct / t2.ends_total if t2.ends_total else 0.0
        self.log(
            f"       Starts on target frame: {t2.starts_correct}/{t2.starts_total} "
            f"({starts_pct:.1f}%) — {t2.corrections_start_applied} correction(s) "
            f"applied, max ±{t2.max_start_correction_ms} ms"
        )
        self.log(
            f"       Ends   on target frame: {t2.ends_correct}/{t2.ends_total} "
            f"({ends_pct:.1f}%) — {t2.corrections_end_applied} correction(s) "
            f"applied, max ±{t2.max_end_correction_ms} ms"
        )
        if t2.duration_changes_count > 0:
            self.log(
                f"       Duration changes from corrections: "
                f"{t2.duration_changes_count} event(s), "
                f"max ±{t2.max_duration_delta_ms} ms"
            )
        if t2.unfixable_count > 0:
            self._report(
                f"{audit_key}: {t2.unfixable_count} endpoint(s) couldn't be "
                "frame-aligned (impossible at this fps — should not happen)"
            )
