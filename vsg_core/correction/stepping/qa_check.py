# vsg_core/correction/stepping/qa_check.py
"""
Post-correction quality assurance.

Runs a fresh dense correlation between the corrected audio and the
reference to verify that the delay is now uniform at the anchor value.

Uses the same dense sliding-window methodology as the main analysis
step for consistency — NOT the old chunk-based pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable

    from ...io.runner import CommandRunner
    from ...models.settings import AppSettings


def verify_correction(
    corrected_path: str,
    ref_file_path: str,
    base_delay_ms: int,
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    log: Callable[[str], None],
    skip_mode: bool = False,
) -> tuple[bool, dict[str, object]]:
    """Verify corrected audio matches reference at *base_delay_ms*.

    Uses dense sliding-window correlation (same as the main analysis)
    to produce hundreds of delay estimates, then checks that the median
    is near base_delay_ms and the variance is low.

    Returns ``(passed, metadata_dict)``.
    """
    from ...analysis.correlation import (
        DEFAULT_SR,
        decode_audio,
        get_audio_stream_info,
        normalize_lang,
    )
    from ...analysis.correlation.dense import run_dense_correlation
    from ...analysis.correlation.filtering import apply_bandpass, apply_lowpass
    from ...analysis.correlation.run import _resolve_method

    log("  [QA] Running dense correlation on corrected audio...")

    qa_threshold = settings.stepping_qa_threshold
    qa_min_pct = settings.stepping_qa_min_accepted_pct

    try:
        # --- 1. Select audio streams ---
        ref_lang = normalize_lang(settings.analysis_lang_source1)

        idx_ref, _ = get_audio_stream_info(
            ref_file_path, ref_lang, runner, tool_paths
        )
        idx_tgt, _ = get_audio_stream_info(
            corrected_path, None, runner, tool_paths
        )

        if idx_ref is None or idx_tgt is None:
            log("  [QA] FAILED: Could not locate audio streams")
            return False, {"reason": "no_audio_streams"}

        # --- 2. Decode ---
        use_soxr = settings.use_soxr
        ref_pcm = decode_audio(
            ref_file_path, idx_ref, DEFAULT_SR, use_soxr, runner, tool_paths
        )
        tgt_pcm = decode_audio(
            corrected_path, idx_tgt, DEFAULT_SR, use_soxr, runner, tool_paths
        )

        # --- 3. Apply filtering (same as main analysis) ---
        filtering_method = settings.filtering_method
        if filtering_method == "Dialogue Band-Pass Filter":
            ref_pcm = apply_bandpass(
                ref_pcm,
                DEFAULT_SR,
                settings.filter_bandpass_lowcut_hz,
                settings.filter_bandpass_highcut_hz,
                settings.filter_bandpass_order,
                log,
            )
            tgt_pcm = apply_bandpass(
                tgt_pcm,
                DEFAULT_SR,
                settings.filter_bandpass_lowcut_hz,
                settings.filter_bandpass_highcut_hz,
                settings.filter_bandpass_order,
                log,
            )
        elif filtering_method == "Low-Pass Filter":
            cutoff = settings.audio_bandlimit_hz
            if cutoff > 0:
                taps = settings.filter_lowpass_taps
                ref_pcm = apply_lowpass(ref_pcm, DEFAULT_SR, cutoff, taps, log)
                tgt_pcm = apply_lowpass(tgt_pcm, DEFAULT_SR, cutoff, taps, log)

        # --- 4. Run dense correlation ---
        method = _resolve_method(settings, source_separated=False)

        results = run_dense_correlation(
            ref_pcm=ref_pcm,
            tgt_pcm=tgt_pcm,
            sr=DEFAULT_SR,
            method=method,
            window_s=settings.dense_window_s,
            hop_s=settings.dense_hop_s,
            min_match=qa_threshold,
            silence_threshold_db=settings.dense_silence_threshold_db,
            outlier_threshold_ms=settings.dense_outlier_threshold_ms,
            log=log,
            dbscan_epsilon_ms=settings.detection_dbscan_epsilon_ms,
            dbscan_min_samples_pct=settings.detection_dbscan_min_samples_pct,
        )

        # Release GPU resources
        from ...analysis.correlation.gpu_backend import cleanup_gpu

        cleanup_gpu()

        # --- 5. Evaluate results ---
        accepted = [r for r in results if r.accepted]
        total_windows = len(results)
        # Calculate minimum from percentage (floor of 10 for very short files)
        qa_min = max(10, int(total_windows * qa_min_pct / 100.0))
        if len(accepted) < qa_min:
            actual_pct = len(accepted) / total_windows * 100 if total_windows else 0
            log(
                f"  [QA] FAILED: Not enough confident windows "
                f"({len(accepted)}/{total_windows} = {actual_pct:.1f}%, "
                f"need {qa_min_pct:.0f}%)"
            )
            return False, {
                "reason": "insufficient_accepted",
                "count": len(accepted),
                "total": total_windows,
                "pct": actual_pct,
                "required_pct": qa_min_pct,
            }

        delays = np.array([r.delay_ms for r in accepted])
        median_delay = float(np.median(delays))
        std_dev = float(np.std(delays))

        # Median check — corrected audio should have uniform delay at base value
        tol = 100 if skip_mode else 20
        if abs(median_delay - base_delay_ms) > tol:
            log(
                f"  [QA] FAILED: Median delay {median_delay:.1f}ms "
                f"≠ base {base_delay_ms}ms (tolerance ±{tol}ms)"
            )
            return False, {
                "reason": "median_mismatch",
                "median": median_delay,
                "base": base_delay_ms,
            }

        # Stability check — delay should be uniform (low variance)
        std_limit = 500 if skip_mode else 15
        if std_dev > std_limit:
            log(f"  [QA] FAILED: Unstable (std = {std_dev:.1f}ms)")
            return False, {"reason": "unstable", "std_dev": std_dev}

        log(
            f"  [QA] PASSED - median={median_delay:.1f}ms, "
            f"std={std_dev:.1f}ms, {len(accepted)} windows"
        )
        return True, {
            "median_delay": median_delay,
            "std_dev": std_dev,
            "accepted_count": len(accepted),
        }

    except Exception as exc:
        log(f"  [QA] FAILED with exception: {exc}")
        return False, {"reason": "exception", "error": str(exc)}
