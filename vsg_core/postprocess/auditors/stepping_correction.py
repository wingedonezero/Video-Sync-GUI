# vsg_core/postprocess/auditors/stepping_correction.py
"""
Auditor for verifying stepping corrections quality and flagging potential issues.
"""

from pathlib import Path

from .base import BaseAuditor


class SteppingCorrectionAuditor(BaseAuditor):
    """
    Verifies stepping corrections were applied correctly and audits quality metrics.
    Flags potential issues like:
    - Silence zone overflow (removal > available silence)
    - Low boundary scores (weak silence detection)
    - Speech or transient detection near boundaries
    - Large single corrections
    """

    def run(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        final_ffprobe_data: dict | None = None,
    ) -> int:
        """
        Audits stepping corrections.
        Returns the number of issues found.
        """
        issues = 0

        if not self.ctx.segment_flags:
            return 0

        self.log(
            f"⚠️  Stepping correction was applied to {len(self.ctx.stepping_sources)} source(s)"
        )
        self.log("    → Manual review recommended to verify sync quality")

        # Get configurable thresholds
        config = self.ctx.settings_dict
        min_boundary_score = config.get("stepping_audit_min_score", 12.0)
        overflow_tolerance_pct = config.get("stepping_audit_overflow_tolerance", 0.8)
        large_correction_threshold_s = config.get(
            "stepping_audit_large_correction_s", 3.0
        )

        # Track high-priority issues
        high_priority_issues = []

        for analysis_key, flag_info in self.ctx.segment_flags.items():
            source_key = analysis_key.split("_")[0]
            audit_metadata = flag_info.get("audit_metadata", [])

            if not audit_metadata:
                # No audit metadata means stepping was applied without smart boundary snapping
                # This is fine, just note it
                self.log(
                    f"  ℹ️  {source_key}: Stepping applied without smart boundary detection"
                )
                continue

            self.log(f"\n  → Analyzing stepping corrections for {source_key}...")
            source_issues = 0

            for idx, boundary in enumerate(audit_metadata, 1):
                target_time_s = boundary.get("target_time_s", 0)
                delay_change_ms = boundary.get("delay_change_ms", 0)
                zone_start = boundary.get("zone_start", 0)
                zone_end = boundary.get("zone_end", 0)
                zone_duration = zone_end - zone_start
                score = boundary.get("score", 0)
                overlaps_speech = boundary.get("overlaps_speech", False)
                near_transient = boundary.get("near_transient", False)
                avg_db = boundary.get("avg_db", 0)
                no_silence_found = boundary.get("no_silence_found", False)
                video_snap_skipped = boundary.get("video_snap_skipped", False)

                # Determine action type
                # When delay increases (positive): target is falling behind → INSERT silence
                # When delay decreases (negative): target is getting ahead → REMOVE audio
                if delay_change_ms > 0:
                    action = "ADD"
                    amount_s = abs(delay_change_ms) / 1000.0
                elif delay_change_ms < 0:
                    action = "REMOVE"
                    amount_s = abs(delay_change_ms) / 1000.0
                else:
                    continue  # No change, skip

                # Check 0: No silence zone found (highest priority)
                if no_silence_found:
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log("        Issue: No silence zone found in search window")
                    self.log(
                        "        → Correction applied at raw boundary without silence guarantee"
                    )
                    self.log("        → High risk of cutting dialogue/music")
                    high_priority_issues.append(
                        f"{source_key} at {target_time_s:.1f}s: No silence zone found"
                    )
                    self._add_quality_issue(
                        source_key,
                        "no_silence_found",
                        "high",
                        f"No silence zone found at {target_time_s:.1f}s",
                        {
                            "time_s": target_time_s,
                            "action": action,
                            "amount_s": amount_s,
                        },
                    )
                    issues += 1
                    source_issues += 1

                # Check 1: Silence overflow (only for removals)
                if (
                    action == "REMOVE"
                    and amount_s > zone_duration * overflow_tolerance_pct
                ):
                    overflow_s = amount_s - zone_duration
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(f"        Silence zone: {zone_duration:.3f}s available")
                    self.log(
                        f"        Issue: Removal exceeds silence by {overflow_s:.3f}s"
                    )
                    self.log("        → May cut into dialogue/music")
                    high_priority_issues.append(
                        f"{source_key} at {target_time_s:.1f}s: Silence overflow ({overflow_s:.3f}s)"
                    )
                    self._add_quality_issue(
                        source_key,
                        "silence_overflow",
                        "high",
                        f"Removal exceeds silence by {overflow_s:.3f}s at {target_time_s:.1f}s",
                        {
                            "time_s": target_time_s,
                            "overflow_s": overflow_s,
                            "zone_duration": zone_duration,
                        },
                    )
                    issues += 1
                    source_issues += 1

                # Check 2: Low boundary score
                elif score < min_boundary_score:
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(
                        f"        Boundary score: {score:.1f} (threshold: {min_boundary_score:.1f})"
                    )
                    self.log(
                        f"        Silence: [{zone_start:.1f}s - {zone_end:.1f}s, {avg_db:.1f}dB]"
                    )
                    self.log("        Issue: Low quality boundary (weak silence)")
                    high_priority_issues.append(
                        f"{source_key} at {target_time_s:.1f}s: Low boundary score ({score:.1f})"
                    )
                    self._add_quality_issue(
                        source_key,
                        "low_boundary_score",
                        "high",
                        f"Low boundary score ({score:.1f}) at {target_time_s:.1f}s",
                        {
                            "time_s": target_time_s,
                            "score": score,
                            "threshold": min_boundary_score,
                        },
                    )
                    issues += 1
                    source_issues += 1

                # Check 3: Speech detected
                elif overlaps_speech:
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log("        Issue: Speech detected near boundary")
                    self.log("        → May cut dialogue")
                    high_priority_issues.append(
                        f"{source_key} at {target_time_s:.1f}s: Speech detected"
                    )
                    self._add_quality_issue(
                        source_key,
                        "speech_detected",
                        "high",
                        f"Speech detected near boundary at {target_time_s:.1f}s",
                        {
                            "time_s": target_time_s,
                            "action": action,
                            "amount_s": amount_s,
                        },
                    )
                    issues += 1
                    source_issues += 1

                # Check 4: Transient detected (informational only, not counted as issue)
                elif near_transient:
                    self.log(f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log("        Note: Transient detected near boundary")
                    self.log("        → May cut musical beat")
                    # Not counted as an issue, just informational

                # Check 5: Large correction (informational)
                elif amount_s > large_correction_threshold_s:
                    self.log(f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(
                        f"        Action: {action} {amount_s:.3f}s (large correction)"
                    )
                    self.log("        Note: Unusually large correction")
                    self.log("        → Verify this is intentional")
                    # Not counted as an issue, just informational

                else:
                    # All checks passed
                    self.log(
                        f"    ✓ Boundary {idx} at {target_time_s:.1f}s: {action} {amount_s:.3f}s"
                    )
                    self.log(
                        f"      Silence: [{zone_start:.1f}s - {zone_end:.1f}s], Score: {score:.1f}"
                    )
                    if video_snap_skipped:
                        self.log(
                            "      Note: Video snap skipped to maintain silence guarantee"
                        )

            if source_issues == 0:
                self.log(f"  ✅ {source_key}: All quality checks passed")

        # Summary
        if high_priority_issues:
            self.log("\n⚠️  STEPPING QUALITY SUMMARY:")
            self.log(
                f"    Found {len(high_priority_issues)} potential issue(s) requiring review:"
            )
            for issue in high_priority_issues:
                self.log(f"    • {issue}")
            self.log(
                "\n    Recommendation: Manually review these timestamps in final output"
            )
        else:
            self.log("\n✅ STEPPING QUALITY SUMMARY: All quality checks passed")
            self.log(
                f"    {len(self.ctx.stepping_sources)} source(s) corrected with no detected issues"
            )

        return issues

    def _add_quality_issue(
        self, source: str, issue_type: str, severity: str, message: str, details: dict
    ) -> None:
        """Add a quality issue to the context for reporting."""
        self.ctx.stepping_quality_issues.append(
            {
                "source": source,
                "issue_type": issue_type,
                "severity": severity,
                "message": message,
                "details": details,
            }
        )
