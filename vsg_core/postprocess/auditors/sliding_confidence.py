# vsg_core/postprocess/auditors/sliding_confidence.py
"""
Auditor for sliding-window video verification confidence.

When the sliding-window matcher is used for subtitle sync (any backend
— ISC, SSCD, pHash, dHash, SSIM), this auditor checks the confidence
level and flags LOW results so the user knows to verify manually. Also
surfaces PTS correction events and cross-check disagreements.
"""

from pathlib import Path

from .base import BaseAuditor

# The details["reason"] value the sliding matcher emits on success.
_SLIDING_REASONS = frozenset({"sliding-matched"})

# Reasons starting with this prefix mean sliding verification was REQUESTED
# but never ran (video open failed, torch missing, ...) and the sync fell
# back to the audio-only correlation value. These must be flagged loudly —
# filtering them out here is how a broken ffms2 once produced a clean
# final report while no video was ever compared.
_FALLBACK_PREFIX = "fallback"


class SlidingConfidenceAuditor(BaseAuditor):
    """
    Checks sliding-window verification confidence for each source.

    Confidence levels:
      HIGH   = 90%+ positions agree AND mean score >= 0.98
      MEDIUM = 70%+ positions agree AND mean score >= 0.95
      LOW    = anything else (flagged as warning)

    Additional surfaces (counted as issues):
      - PTS correction events (when source start_pts != target start_pts)
      - Cross-check disagreements (when a secondary backend disagrees
        with the primary by more than the tolerance)
    """

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits sliding-window verification confidence for all sources.
        Returns the total number of warnings (LOW confidence +
        PTS corrections + cross-check disagreements).
        """
        # Skip entirely if no video-verified sources exist
        if not self.ctx.video_verified_sources:
            return 0

        # Filter to sources that used the sliding matcher (any backend) —
        # including ones where it was requested but FELL BACK to audio-only.
        sliding_sources: list[tuple[str, dict]] = []
        fallback_sources: list[tuple[str, dict]] = []
        for source_key, vv_result in self.ctx.video_verified_sources.items():
            details = vv_result.get("details")
            if not details:
                continue
            reason = str(details.get("reason", ""))
            if reason in _SLIDING_REASONS:
                sliding_sources.append((source_key, details))
            elif reason.startswith(_FALLBACK_PREFIX):
                fallback_sources.append((source_key, details))

        # Skip if no sliding verification was used (classic mode or audio-only)
        if not sliding_sources and not fallback_sources:
            return 0

        # Verification never ran for these — the final timing is the raw
        # audio correlation, unverified. Always an issue.
        for source_key, details in fallback_sources:
            reason = details.get("reason", "")
            error = details.get("error", "")
            backend = details.get("backend", "unknown")
            audio_ms = details.get("audio_correlation_ms", 0.0)
            self.log(
                f"  ⚠ {source_key}: video verification FAILED ({backend}, {reason})"
            )
            if error:
                self.log(f"    Error: {error}")
            self.log(
                f"    Timing fell back to audio-only correlation "
                f"({audio_ms:+.1f}ms) — NOT video-verified; check the "
                "output manually"
            )
            self._track_issue(
                f"{source_key}: video verification FAILED ({backend}, "
                f"{reason}) - timing is audio-only and unverified, check "
                "the output manually"
            )

        for source_key, details in sliding_sources:
            confidence = details.get("confidence", "UNKNOWN")
            consensus_count = details.get("consensus_count", 0)
            num_positions = details.get("num_positions", 0)
            mean_score = details.get("mean_score", 0.0)
            video_offset_ms = details.get("video_offset_ms", 0.0)
            audio_ms = details.get("audio_correlation_ms", 0.0)
            backend_display = details.get(
                "backend_display_name", details.get("backend", "unknown")
            )

            positions_str = f"{consensus_count}/{num_positions} positions"

            if confidence == "LOW":
                self.log(
                    f"  \u26a0 {source_key}: LOW confidence "
                    f"({backend_display}, {positions_str}, score {mean_score:.4f})"
                )
                self.log(
                    f"    Video offset: {video_offset_ms:+.1f}ms, "
                    f"Audio correlation: {audio_ms:+.1f}ms"
                )
                self.log("    Subtitle timing may need manual verification")
                self._track_issue(
                    f"{source_key}: LOW confidence ({backend_display}, "
                    f"{positions_str}, score {mean_score:.4f}) - subtitle "
                    "timing may need manual verification"
                )
            else:
                self.log(
                    f"  \u2713 {source_key}: {confidence} confidence "
                    f"({backend_display}, {positions_str}, score {mean_score:.4f})"
                )

            # PTS correction flag — independent of confidence, always shown
            # when the sliding matcher had to compensate for a non-zero PTS
            # origin difference between source and target. Counts as an
            # issue so the job report surfaces it in the summary tally.
            if details.get("pts_correction_applied", False):
                src_pts = details.get("src_start_pts_s", 0.0)
                tgt_pts = details.get("tgt_start_pts_s", 0.0)
                delta_s = details.get("pts_delta_s", 0.0)
                delta_f = details.get("pts_delta_frames", 0)
                self.log(
                    f"  \u26a0 {source_key}: PTS correction applied "
                    f"({delta_f:+d}f / {delta_s * 1000:+.1f}ms)"
                )
                self.log(
                    f"    Source start_pts={src_pts:+.6f}s, "
                    f"Target start_pts={tgt_pts:+.6f}s"
                )
                self.log(
                    "    Source has a non-zero PTS origin — the matcher "
                    "compensated and returned a wall-clock offset."
                )
                self.log(
                    "    Rare edge case; please verify subs manually in "
                    "the output file."
                )
                self._track_issue(
                    f"{source_key}: PTS correction applied "
                    f"({delta_f:+d}f / {delta_s * 1000:+.1f}ms) - rare edge "
                    "case, please verify subs manually in the output file"
                )

            # Timeline integrity — frame-index ↔ wall-clock mapping of both
            # containers, and whether the matcher had to correct its answer
            # using real timestamps (dropped-frame-slot sources). A clean
            # "OK" is stated positively so a normal job is distinguishable
            # from a job where the check never ran.
            self._render_timeline(source_key, details)

            # Cross-check disagreement — when a secondary backend was
            # configured and its result differs from the primary beyond
            # the tolerance. Agreement is informational (no issue count).
            cross_check = details.get("cross_check")
            if cross_check:
                cross_backend = cross_check.get("backend", "unknown")
                cross_offset = cross_check.get("offset_ms")
                diff_frames = cross_check.get("diff_frames")
                tolerance = cross_check.get("tolerance_frames", 0)
                agreed = cross_check.get("agreed", False)
                if cross_check.get("failed", False):
                    failed_reason = cross_check.get("failed_reason", "")
                    self.log(
                        f"  ⚠ {source_key}: cross-check backend "
                        f"{cross_backend} FAILED ({failed_reason or 'no result'})"
                        " — primary result stands unconfirmed"
                    )
                    self._track_issue(
                        f"{source_key}: cross-check backend {cross_backend} "
                        f"failed ({failed_reason or 'no result'}) - primary "
                        "result unconfirmed"
                    )
                elif agreed:
                    self.log(
                        f"    \u2713 Cross-check agreed: {cross_backend} "
                        f"within {tolerance} frame(s)"
                    )
                else:
                    self.log(
                        f"  \u26a0 {source_key}: Cross-check disagreement "
                        f"(primary={video_offset_ms:+.1f}ms vs "
                        f"{cross_backend}={cross_offset}ms)"
                    )
                    if diff_frames is not None:
                        self.log(
                            f"    Diff: {diff_frames:.1f} frames "
                            f"(tolerance: {tolerance})"
                        )
                    self.log(
                        "    Two backends disagree — please verify subs "
                        "manually in the output file."
                    )
                    self._track_issue(
                        f"{source_key}: Cross-check disagreement "
                        f"(primary={video_offset_ms:+.1f}ms vs "
                        f"{cross_backend}={cross_offset}ms) - two backends "
                        "disagree, please verify subs manually"
                    )

        total = len(self.issues)
        if total == 0:
            self.log("\u2705 All sliding-window verification checks passed.")
        else:
            self.log(
                f"\u26a0\ufe0f  {total} sliding-window warning(s) — "
                "review sync quality for flagged sources"
            )

        return total

    def _render_timeline(self, source_key: str, details: dict) -> None:
        """Render timeline-integrity results for one source.

        Covers four states explicitly:
        1. Normal - both containers gapless, index and wall-clock agree.
        2. Gap correction - a container has dropped/extra frame slots and
           the matcher corrected its offset using real timestamps (issue).
        3. Timestamps unavailable - the check could not run (issue, because
           the offset then rests on the unverified gapless-CFR assumption).
        4. Inconsistent divergence - index-vs-timestamp disagreement varies
           across positions, suggesting a mid-file anomaly (issue).

        Older result payloads (pre-fix runs, e.g. replayed jobs) have none
        of these keys - stay silent rather than claim a check that never ran.
        """
        if "timeline_correction_applied" not in details:
            return

        src_ok = details.get("timeline_src_ok")
        tgt_ok = details.get("timeline_tgt_ok")
        corrected = details.get("timeline_correction_applied", False)
        correction_f = details.get("timeline_correction_frames", 0)
        inconsistent = details.get("timeline_divergence_inconsistent", False)
        num_positions = details.get("num_positions", 0)
        pts_based = details.get("positions_pts_based", 0)

        if corrected:
            index_f = details.get("index_consensus_frames", 0)
            final_f = details.get("frame_offset", 0)
            self.log(
                f"  ⚠ {source_key}: TIMELINE GAP CORRECTION "
                f"({index_f:+d}f frame-index -> {final_f:+d}f wall-clock, "
                f"{correction_f:+d}f)"
            )
            for label, ok, slots, gap_s in (
                (
                    "Source",
                    src_ok,
                    details.get("timeline_src_missing_slots", 0),
                    details.get("timeline_src_first_gap_s"),
                ),
                (
                    "Target",
                    tgt_ok,
                    details.get("timeline_tgt_missing_slots", 0),
                    details.get("timeline_tgt_first_gap_s"),
                ),
            ):
                if ok is False:
                    where = f" at ~{gap_s:.3f}s" if gap_s is not None else ""
                    self.log(
                        f"    {label}: {abs(slots)} "
                        f"{'missing' if slots > 0 else 'extra'} frame "
                        f"slot(s){where}"
                    )
            self.log(
                "    Offsets were computed from real container timestamps - "
                "the corrected value is authoritative. Spot-check the output "
                "once to confirm."
            )
            self._track_issue(
                f"{source_key}: timeline gap correction applied "
                f"({correction_f:+d}f) - a container has dropped/extra frame "
                "slots; offset taken from real timestamps, spot-check output"
            )
        elif src_ok is True and tgt_ok is True and pts_based == num_positions:
            self.log(
                f"    ✓ Timeline integrity OK (no pts gaps; frame-index "
                f"and wall-clock agree at all {num_positions} positions)"
            )
        else:
            self.log(
                f"  ⚠ {source_key}: timeline integrity UNVERIFIED "
                f"(timestamps unavailable for "
                f"{num_positions - pts_based}/{num_positions} position(s))"
            )
            self.log(
                "    Offset rests on the gapless-CFR assumption - verify "
                "subs manually if the source is a web encode."
            )
            self._track_issue(
                f"{source_key}: timeline integrity could not be verified "
                "(container timestamps unavailable) - verify subs manually"
            )

        if inconsistent:
            self.log(
                f"  ⚠ {source_key}: index-vs-timestamp divergence varies "
                "across positions - possible mid-file timestamp anomaly"
            )
            self._track_issue(
                f"{source_key}: inconsistent timeline divergence across "
                "positions - possible mid-file timestamp anomaly, verify "
                "subs manually"
            )
