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
        issues = 0

        # Skip entirely if no video-verified sources exist
        if not self.ctx.video_verified_sources:
            return 0

        # Filter to only sources that used the sliding matcher (any backend).
        sliding_sources: list[tuple[str, dict]] = []
        for source_key, vv_result in self.ctx.video_verified_sources.items():
            details = vv_result.get("details")
            if not details:
                continue
            reason = details.get("reason", "")
            if reason in _SLIDING_REASONS:
                sliding_sources.append((source_key, details))

        # Skip if no sliding verification was used (classic mode or audio-only)
        if not sliding_sources:
            return 0

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
                issues += 1
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
                issues += 1

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
                if agreed:
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
                    issues += 1

        if issues == 0:
            self.log("\u2705 All sliding-window verification checks passed.")
        else:
            self.log(
                f"\u26a0\ufe0f  {issues} sliding-window warning(s) — "
                "review sync quality for flagged sources"
            )

        return issues
