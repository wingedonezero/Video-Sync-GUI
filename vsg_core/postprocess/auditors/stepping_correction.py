# vsg_core/postprocess/auditors/stepping_correction.py
# -*- coding: utf-8 -*-
"""
Auditor for verifying stepping corrections quality and flagging potential issues.
"""
from typing import Dict, Optional
from pathlib import Path

from vsg_core.models.enums import TrackType
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

    def run(self, final_mkv_path: Path, final_mkvmerge_data: Dict,
            final_ffprobe_data: Optional[Dict] = None) -> int:
        """
        Audits stepping corrections.
        Returns the number of issues found.
        """
        issues = 0

        if not self.ctx.segment_flags:
            return 0

        self.log(f"⚠️  Stepping correction was applied to {len(self.ctx.stepping_sources)} source(s)")
        self.log("    → Manual review recommended to verify sync quality")

        # Get configurable thresholds
        config = self.ctx.settings_dict
        min_boundary_score = config.get('stepping_audit_min_score', 12.0)
        overflow_tolerance_pct = config.get('stepping_audit_overflow_tolerance', 0.8)
        large_correction_threshold_s = config.get('stepping_audit_large_correction_s', 3.0)

        # Track high-priority issues
        high_priority_issues = []

        for analysis_key, flag_info in self.ctx.segment_flags.items():
            source_key = analysis_key.split('_')[0]
            audit_metadata = flag_info.get('audit_metadata', [])

            if not audit_metadata:
                # No audit metadata means stepping was applied without smart boundary snapping
                # This is fine, just note it
                self.log(f"  ℹ️  {source_key}: Stepping applied without smart boundary detection")
                continue

            self.log(f"\n  → Analyzing stepping corrections for {source_key}...")
            source_issues = 0

            for idx, boundary in enumerate(audit_metadata, 1):
                target_time_s = boundary.get('target_time_s', 0)
                delay_change_ms = boundary.get('delay_change_ms', 0)
                zone_start = boundary.get('zone_start', 0)
                zone_end = boundary.get('zone_end', 0)
                zone_duration = zone_end - zone_start
                score = boundary.get('score', 0)
                overlaps_speech = boundary.get('overlaps_speech', False)
                near_transient = boundary.get('near_transient', False)
                avg_db = boundary.get('avg_db', 0)

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

                # Check 1: Silence overflow (only for removals)
                if action == "REMOVE" and amount_s > zone_duration * overflow_tolerance_pct:
                    overflow_s = amount_s - zone_duration
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(f"        Silence zone: {zone_duration:.3f}s available")
                    self.log(f"        Issue: Removal exceeds silence by {overflow_s:.3f}s")
                    self.log(f"        → May cut into dialogue/music")
                    high_priority_issues.append(f"{source_key} at {target_time_s:.1f}s: Silence overflow ({overflow_s:.3f}s)")
                    issues += 1
                    source_issues += 1

                # Check 2: Low boundary score
                elif score < min_boundary_score:
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(f"        Boundary score: {score:.1f} (threshold: {min_boundary_score:.1f})")
                    self.log(f"        Silence: [{zone_start:.1f}s - {zone_end:.1f}s, {avg_db:.1f}dB]")
                    self.log(f"        Issue: Low quality boundary (weak silence)")
                    high_priority_issues.append(f"{source_key} at {target_time_s:.1f}s: Low boundary score ({score:.1f})")
                    issues += 1
                    source_issues += 1

                # Check 3: Speech detected
                elif overlaps_speech:
                    self.log(f"    ⚠️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(f"        Issue: Speech detected near boundary")
                    self.log(f"        → May cut dialogue")
                    high_priority_issues.append(f"{source_key} at {target_time_s:.1f}s: Speech detected")
                    issues += 1
                    source_issues += 1

                # Check 4: Transient detected (informational only, not counted as issue)
                elif near_transient:
                    self.log(f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s")
                    self.log(f"        Note: Transient detected near boundary")
                    self.log(f"        → May cut musical beat")
                    # Not counted as an issue, just informational

                # Check 5: Large correction (informational)
                elif amount_s > large_correction_threshold_s:
                    self.log(f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s:")
                    self.log(f"        Action: {action} {amount_s:.3f}s (large correction)")
                    self.log(f"        Note: Unusually large correction")
                    self.log(f"        → Verify this is intentional")
                    # Not counted as an issue, just informational

                else:
                    # All checks passed
                    self.log(f"    ✓ Boundary {idx} at {target_time_s:.1f}s: {action} {amount_s:.3f}s")
                    self.log(f"      Silence: [{zone_start:.1f}s - {zone_end:.1f}s], Score: {score:.1f}")

            if source_issues == 0:
                self.log(f"  ✅ {source_key}: All quality checks passed")

        # Summary
        if high_priority_issues:
            self.log(f"\n⚠️  STEPPING QUALITY SUMMARY:")
            self.log(f"    Found {len(high_priority_issues)} potential issue(s) requiring review:")
            for issue in high_priority_issues:
                self.log(f"    • {issue}")
            self.log(f"\n    Recommendation: Manually review these timestamps in final output")
        else:
            self.log(f"\n✅ STEPPING QUALITY SUMMARY: All quality checks passed")
            self.log(f"    {len(self.ctx.stepping_sources)} source(s) corrected with no detected issues")

        return issues
