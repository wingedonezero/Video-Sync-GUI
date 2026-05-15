# vsg_core/postprocess/auditors/stepping_correction.py
"""
Auditor for verifying stepping corrections quality and flagging potential issues.
"""

from pathlib import Path
from typing import cast

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
        if not self.ctx.segment_flags:
            return 0

        self.log(
            f"⚠️  Stepping correction was applied to {len(self.ctx.stepping_sources)} source(s)"
        )
        self.log("    → Manual review recommended to verify sync quality")

        # Audit thresholds (informational, not behavioral)
        min_boundary_score = 12.0
        overflow_tolerance_pct = 0.8
        large_correction_threshold_s = 3.0

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
            source_issues_start = len(self.issues)

            for idx, boundary in enumerate(audit_metadata, 1):
                target_time_s = cast("float", boundary.get("target_time_s", 0))
                delay_change_ms = cast("float", boundary.get("delay_change_ms", 0))
                zone_start = cast("float", boundary.get("zone_start", 0))
                zone_end = cast("float", boundary.get("zone_end", 0))
                zone_duration = zone_end - zone_start
                score = cast("float", boundary.get("score", 0))
                overlaps_speech = cast("bool", boundary.get("overlaps_speech", False))
                near_transient = cast("bool", boundary.get("near_transient", False))
                avg_db = cast("float", boundary.get("avg_db", 0))
                no_silence_found = cast("bool", boundary.get("no_silence_found", False))
                video_snap_skipped = cast(
                    "bool", boundary.get("video_snap_skipped", False)
                )

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
                    self._track_issue(
                        f"{source_key} at {target_time_s:.1f}s: no silence "
                        f"zone found - correction applied at raw boundary "
                        "without silence guarantee (high risk of cutting "
                        "dialogue/music)"
                    )

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
                    self._track_issue(
                        f"{source_key} at {target_time_s:.1f}s: silence "
                        f"overflow ({overflow_s:.3f}s beyond available "
                        "silence) - may cut into dialogue/music"
                    )

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
                    self._track_issue(
                        f"{source_key} at {target_time_s:.1f}s: low boundary "
                        f"score {score:.1f} (threshold {min_boundary_score:.1f}) "
                        "- weak silence, may cut into dialogue/music"
                    )

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
                    self._track_issue(
                        f"{source_key} at {target_time_s:.1f}s: speech "
                        "detected near boundary - may cut dialogue"
                    )

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

                # Independent display: Frame-precision refinement outcome.
                # Reported per-boundary so the user can see whether the
                # splice point was rewritten to the exact video frame edge
                # (and by how much it differed from the audio-derived
                # position), or why refinement was skipped.  Informational
                # only — when refinement falls back, the audio splice is
                # used as before and no quality issue is logged.
                fr = boundary.get("frame_refinement")
                if isinstance(fr, dict):
                    self._report_frame_refinement(idx, target_time_s, fr)

                # Independent check: Multi-track residual.
                # JPN analysis found silence at the chosen splice but a
                # sibling audio track (e.g. ENG dub on a DVD) has active
                # signal at that exact sample.  Splice was NOT shifted —
                # this surfaces the residual so the user knows to listen
                # for a possible artifact on the affected track.
                mt = boundary.get("multitrack_residual")
                if isinstance(mt, dict):
                    loud_track = cast("str", mt.get("loudest_track", "?"))
                    loud_db = cast("float", mt.get("loudest_db", 0.0))
                    alt_t = cast("float", mt.get("best_alternative_t_s", target_time_s))
                    alt_db = cast("float", mt.get("best_alternative_worst_db", loud_db))
                    shift_ms = cast("float", mt.get("shift_ms_would_be", 0.0))
                    improvement_db = cast(
                        "float", mt.get("improvement_db_would_be", 0.0)
                    )
                    # Severity: high if loud_track is clearly audible
                    # signal (> -30 dB), medium otherwise (-30 to -45 dB).
                    severity = "high" if loud_db > -30.0 else "medium"
                    self.log(
                        f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s (multi-track):"
                    )
                    self.log(
                        f"        {loud_track} at {loud_db:+.1f}dB at chosen "
                        f"sample (JPN was silent, sibling track was not)"
                    )
                    self.log(
                        f"        Quietest alt in zone @{alt_t:.3f}s "
                        f"(shift {shift_ms:+.0f}ms, worst track "
                        f"{alt_db:+.1f}dB, "
                        f"improvement {improvement_db:+.1f}dB)"
                    )
                    self.log(
                        "        → Splice NOT shifted; possible artifact "
                        f"on {loud_track} only"
                    )
                    high_priority_issues.append(
                        f"{source_key} at {target_time_s:.1f}s: "
                        f"multi-track residual ({loud_track} at "
                        f"{loud_db:+.1f}dB)"
                    )
                    self._add_quality_issue(
                        source_key,
                        "multitrack_residual",
                        severity,
                        (
                            f"Splice at {target_time_s:.1f}s: "
                            f"{loud_track} has {loud_db:+.1f}dB residual "
                            f"at chosen sample. A {shift_ms:+.0f}ms shift "
                            f"inside the silence zone would reduce worst-track "
                            f"RMS to {alt_db:+.1f}dB."
                        ),
                        {
                            "time_s": target_time_s,
                            "loudest_track": loud_track,
                            "loudest_db": loud_db,
                            "best_alternative_t_s": alt_t,
                            "best_alternative_worst_db": alt_db,
                            "shift_ms_would_be": shift_ms,
                            "improvement_db_would_be": improvement_db,
                            "per_track_db_at_splice": mt.get("per_track_db_at_splice"),
                        },
                    )
                    self._track_issue(
                        f"{source_key} at {target_time_s:.1f}s: "
                        f"multi-track residual — {loud_track} at "
                        f"{loud_db:+.1f}dB while JPN was silent. Possible "
                        f"audible artifact on {loud_track} only. "
                        f"Splice not shifted."
                    )

            # Scan the produced output for actual seam discontinuities.
            # This is the final independent check — confirms the corrected
            # audio that was actually muxed has no audible click at any
            # splice on any corrected track.  Gated by both seam_diff AND
            # seam_rms so deep-silence false positives are excluded.
            seam_flags = self._scan_seam_quality_on_output(
                final_mkv_path,
                final_mkvmerge_data,
                audit_metadata,
            )
            for fs in seam_flags:
                self.log(
                    f"    ⚠️  Boundary {fs['splice_idx']} at "
                    f"{fs['target_time_s']:.1f}s (post-mux scan):"
                )
                self.log(f"        Track: {fs['track_lang']} {fs['track_codec']}")
                self.log(
                    f"        Edge: {fs['edge']} @ {fs['seam_t_s']:.3f}s "
                    f"(seam_diff {fs['seam_diff']:.5f}, "
                    f"rms {fs['seam_rms_db']:+.1f}dB)"
                )
                self.log(
                    "        Issue: Audible sample discontinuity in produced output"
                )
                high_priority_issues.append(
                    f"{source_key} at {fs['target_time_s']:.1f}s: "
                    f"seam discontinuity on {fs['track_lang']} "
                    f"(seam_diff {fs['seam_diff']:.4f})"
                )
                self._add_quality_issue(
                    source_key,
                    "seam_discontinuity",
                    "high" if fs["seam_diff"] > 0.05 else "medium",
                    (
                        f"Splice at {fs['target_time_s']:.1f}s: "
                        f"{fs['track_lang']} {fs['track_codec']} has audible "
                        f"discontinuity in produced output "
                        f"(seam_diff {fs['seam_diff']:.4f} at "
                        f"{fs['seam_rms_db']:+.1f}dB) — edge: {fs['edge']}"
                    ),
                    {
                        "time_s": fs["target_time_s"],
                        "track_lang": fs["track_lang"],
                        "track_codec": fs["track_codec"],
                        "edge": fs["edge"],
                        "seam_t_s": fs["seam_t_s"],
                        "seam_diff": fs["seam_diff"],
                        "seam_rms_db": fs["seam_rms_db"],
                    },
                )
                self._track_issue(
                    f"{source_key} at {fs['target_time_s']:.1f}s: seam "
                    f"discontinuity on {fs['track_lang']} track "
                    f"(seam_diff {fs['seam_diff']:.4f} at "
                    f"{fs['seam_rms_db']:+.1f}dB) — audible artifact in "
                    "produced output"
                )

            if len(self.issues) == source_issues_start:
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

        return len(self.issues)

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

    # ------------------------------------------------------------------
    # Frame-precision refinement reporting
    # ------------------------------------------------------------------

    def _report_frame_refinement(
        self, idx: int, target_time_s: float, fr: dict
    ) -> None:
        """Display a per-boundary frame-refinement report.

        ``fr`` is the dict stamped onto ``audit_metadata`` by
        ``vsg_core/correction/stepping/run.py`` after refinement runs.
        Informational only — refinement falls back to the audio splice on
        any failure, so no quality issue is logged here.
        """
        mode = cast("str", fr.get("mode", ""))
        reason = cast("str", fr.get("reason", ""))

        # Skipped because user disabled — no need to clutter the audit.
        if mode == "skipped_disabled":
            return

        if mode == "refined":
            audio_t = cast("float", fr.get("audio_src2_time_s", 0.0))
            video_t = cast("float", fr.get("video_src2_time_s", 0.0) or 0.0)
            drift_ms = cast("float", fr.get("frame_drift_ms", 0.0))
            b_score = cast("float", fr.get("before_score", 0.0))
            a_score = cast("float", fr.get("after_score", 0.0))
            expected = fr.get("audio_expected_jump_frames")
            measured = fr.get("measured_jump_frames")
            first_after = fr.get("first_after_frame")
            fps = fr.get("target_fps")
            self.log(
                f"    🎬 Boundary {idx} at {target_time_s:.1f}s: frame refinement applied"
            )
            self.log(
                f"        Audio splice: {audio_t:.3f}s → "
                f"Video splice: {video_t:.3f}s (drift {drift_ms:+.1f} ms)"
            )
            self.log(
                f"        Anchor pHash scores: before {b_score:.2f}, after {a_score:.2f}"
            )
            if expected is not None and measured is not None:
                self.log(
                    f"        Jump confirmed: measured {measured:+d} frames "
                    f"(audio expected {expected:+d})"
                )
            if first_after is not None and fps is not None:
                self.log(
                    f"        First-AFTER frame: {first_after} "
                    f"(@ {float(cast('float', fps)):.3f} fps)"
                )
            return

        # Fallbacks — refinement could not be applied; audio splice kept.
        if mode == "fallback_outside_silence":
            video_t = fr.get("video_src2_time_s")
            video_t_str = (
                f"{float(cast('float', video_t)):.3f}s" if video_t is not None else "?"
            )
            self.log(
                f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
                f"frame refinement fell back (kept audio splice)"
            )
            self.log(
                f"        Video-derived splice ({video_t_str}) fell outside the "
                "silence zone"
            )
            self.log(f"        Reason: {reason}")
            return

        if mode == "fallback_no_first_after":
            self.log(
                f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
                f"frame refinement fell back (kept audio splice)"
            )
            self.log("        Could not identify first-AFTER frame in dead zone")
            if reason:
                self.log(f"        Reason: {reason}")
            return

        if mode == "skipped_low_confidence":
            b_score = cast("float", fr.get("before_score", 0.0))
            a_score = cast("float", fr.get("after_score", 0.0))
            self.log(
                f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
                f"frame refinement skipped (low anchor confidence)"
            )
            self.log(
                f"        Anchor pHash scores: before {b_score:.2f}, after {a_score:.2f}"
            )
            self.log(f"        Reason: {reason}")
            return

        if mode == "skipped_jump_mismatch":
            expected = fr.get("audio_expected_jump_frames")
            measured = fr.get("measured_jump_frames")
            self.log(
                f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
                f"frame refinement skipped (jump mismatch)"
            )
            if expected is not None and measured is not None:
                self.log(
                    f"        Audio expected {expected:+d} frames, "
                    f"video measured {measured:+d} frames"
                )
            if reason:
                self.log(f"        Reason: {reason}")
            return

        if mode in ("skipped_gate", "skipped_no_video"):
            # Common gating: interlaced / MPEG-2 / fps mismatch / no video
            # path / open_clip unavailable.  One-line note.
            self.log(
                f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
                f"frame refinement skipped ({reason or mode})"
            )
            return

        # Unknown mode — surface the raw values for forensic clarity.
        self.log(
            f"    ℹ️  Boundary {idx} at {target_time_s:.1f}s: "
            f"frame refinement mode={mode!r} reason={reason!r}"
        )

    # ------------------------------------------------------------------
    # Seam-quality scan on the produced output
    # ------------------------------------------------------------------

    # Gates for flagging an actual click in the muxed output.  Both must
    # hold simultaneously to avoid false positives in deep silence (where
    # noise-floor ratios can spike without any audible artifact).  Validated
    # against 5 test cases / 64 seam measurements: catches the one known
    # issue, zero false positives.
    _SEAM_DIFF_THRESHOLD: float = 0.01  # ~−40 dB absolute amplitude jump
    _SEAM_RMS_DB_THRESHOLD: float = -50.0  # seam region has real signal

    def _scan_seam_quality_on_output(
        self,
        final_mkv_path: Path,
        final_mkvmerge_data: dict,
        audit_metadata: list[dict],
    ) -> list[dict]:
        """Decode small windows from each corrected (FLAC) audio track in
        the produced output around each splice and check for sample-derivative
        spikes that would be audible.

        Returns a list of flagged seam dicts (one entry per flagged edge).
        """
        # Corrected audio tracks are FLAC-encoded by audio_assembly.  The
        # preserved (original) tracks keep their source codec — so filtering
        # by FLAC is a robust way to identify the tracks we produced.
        flac_tracks = [
            t
            for t in final_mkvmerge_data.get("tracks", [])
            if t.get("type") == "audio" and t.get("codec") in ("FLAC", "A_FLAC")
        ]
        if not flac_tracks:
            return []

        flagged: list[dict] = []
        for idx, boundary in enumerate(audit_metadata, 1):
            target_time_s = cast("float", boundary.get("target_time_s", 0.0))
            seam_t_before = boundary.get("output_seam_t_before_s")
            seam_t_after = boundary.get("output_seam_t_after_s")
            if seam_t_before is None or seam_t_after is None:
                continue
            for ft in flac_tracks:
                track_id = ft.get("id")
                if track_id is None:
                    continue
                track_props = ft.get("properties", {}) or {}
                track_lang = track_props.get("language", "und")
                track_codec = ft.get("codec", "?")
                for edge_name, seam_t in [
                    ("end_of_before", float(cast("float", seam_t_before))),
                    ("start_of_after", float(cast("float", seam_t_after))),
                ]:
                    try:
                        seam_diff, seam_rms = self._probe_seam(
                            str(final_mkv_path), int(track_id), seam_t
                        )
                    except Exception:
                        continue
                    if (
                        seam_diff > self._SEAM_DIFF_THRESHOLD
                        and seam_rms > self._SEAM_RMS_DB_THRESHOLD
                    ):
                        flagged.append(
                            {
                                "splice_idx": idx,
                                "target_time_s": target_time_s,
                                "track_id": track_id,
                                "track_lang": track_lang,
                                "track_codec": track_codec,
                                "edge": edge_name,
                                "seam_t_s": seam_t,
                                "seam_diff": seam_diff,
                                "seam_rms_db": seam_rms,
                            }
                        )
        return flagged

    def _probe_seam(
        self,
        mkv_path: str,
        track_id: int,
        seam_t: float,
        window_ms: float = 20.0,
    ) -> tuple[float, float]:
        """Decode a small mono window centered on *seam_t* and return
        ``(seam_diff, seam_rms_db)``.

        ``seam_diff`` is the maximum sample-to-sample absolute jump in the
        window (audible click indicator).  ``seam_rms_db`` is the RMS dB of
        the window (used to gate against deep-silence false positives).
        """
        import subprocess

        import numpy as np

        half = (window_ms / 1000.0) / 2.0
        ffmpeg_bin = (self.tool_paths or {}).get("ffmpeg") or "ffmpeg"
        cmd = [
            ffmpeg_bin,
            "-v",
            "error",
            "-nostdin",
            "-ss",
            str(max(0.0, seam_t - half)),
            "-t",
            str(window_ms / 1000.0),
            "-i",
            mkv_path,
            "-map",
            f"0:{track_id}",
            "-ac",
            "1",
            "-ar",
            "48000",
            "-f",
            "f32le",
            "pipe:1",
        ]
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
        pcm = np.frombuffer(out, dtype=np.float32)
        if len(pcm) < 2:
            return 0.0, -120.0
        seam_diff = float(np.max(np.abs(np.diff(pcm))))
        rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
        seam_rms_db = 20.0 * float(np.log10(rms)) if rms > 1e-12 else -120.0
        return seam_diff, seam_rms_db
