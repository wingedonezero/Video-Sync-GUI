# vsg_core/postprocess/auditors/neural_confidence.py
"""
Auditor for neural (ISC) video verification confidence.

When ISC sequence sliding is used for subtitle sync, this auditor checks
the confidence level and flags LOW results so the user knows to verify
manually. Only runs when neural verification was actually used.
"""

from pathlib import Path

from .base import BaseAuditor


class NeuralConfidenceAuditor(BaseAuditor):
    """
    Checks neural verification confidence for each source that used ISC matching.

    Confidence levels:
      HIGH   = 90%+ positions agree AND mean score >= 0.98
      MEDIUM = 70%+ positions agree AND mean score >= 0.95
      LOW    = anything else (flagged as warning)
    """

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits neural verification confidence for all sources.
        Returns the number of LOW confidence warnings.
        """
        issues = 0

        # Skip entirely if no video-verified sources exist
        if not self.ctx.video_verified_sources:
            return 0

        # Filter to only sources that used neural matching
        neural_sources: list[tuple[str, dict]] = []
        for source_key, vv_result in self.ctx.video_verified_sources.items():
            details = vv_result.get("details")
            if not details:
                continue
            reason = details.get("reason", "")
            if reason == "neural-matched":
                neural_sources.append((source_key, details))

        # Skip if no neural verification was used (classic mode or audio-only)
        if not neural_sources:
            return 0

        for source_key, details in neural_sources:
            confidence = details.get("confidence", "UNKNOWN")
            consensus_count = details.get("consensus_count", 0)
            num_positions = details.get("num_positions", 0)
            mean_score = details.get("mean_score", 0.0)
            video_offset_ms = details.get("video_offset_ms", 0.0)
            audio_ms = details.get("audio_correlation_ms", 0.0)

            positions_str = f"{consensus_count}/{num_positions} positions"

            if confidence == "LOW":
                self.log(
                    f"  \u26a0 {source_key}: LOW confidence "
                    f"({positions_str}, score {mean_score:.4f})"
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
                    f"({positions_str}, score {mean_score:.4f})"
                )

        if issues == 0:
            self.log("\u2705 All neural verification checks passed.")
        else:
            self.log(
                f"\u26a0\ufe0f  {issues} neural confidence warning(s) — "
                "review sync quality for flagged sources"
            )

        return issues
