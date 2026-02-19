# vsg_core/analysis/correlation/dense.py
"""
Dense sliding window correlation on GPU.

Replaces the old chunk-based approach (30 fixed chunks) with a dense
sliding window that processes the entire file at high resolution.
Produces hundreds of delay estimates instead of ~30, enabling:
  - Precise stepping transition detection (within hop_s precision)
  - Robust outlier rejection (configurable threshold from median)
  - Detailed confidence and cluster statistics

All GPU work happens here. Results are returned as list[ChunkResult]
for backward compatibility with the existing pipeline (stepping
detection, delay selection, audit trail).
"""

from __future__ import annotations

import time
from collections import Counter
from typing import TYPE_CHECKING

import numpy as np

from ..types import ChunkResult

if TYPE_CHECKING:
    from collections.abc import Callable

    from .registry import CorrelationMethod


# ── Silence Detection ─────────────────────────────────────────────────────


def _rms_db(samples: np.ndarray) -> float:
    """RMS energy in dB for a numpy chunk."""
    rms = np.sqrt(np.mean(samples * samples))
    if rms < 1e-12:
        return -120.0
    return 20.0 * np.log10(rms)


# ── Dense Correlation Runner ──────────────────────────────────────────────


def run_dense_correlation(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    method: CorrelationMethod,
    window_s: float,
    hop_s: float,
    min_match: float,
    silence_threshold_db: float = -60.0,
    outlier_threshold_ms: float = 50.0,
    start_pct: float = 5.0,
    end_pct: float = 95.0,
    log: Callable[[str], None] | None = None,
) -> list[ChunkResult]:
    """
    Run dense sliding window correlation over the full file.

    Args:
        ref_pcm: Reference audio (mono float32, full file).
        tgt_pcm: Target audio (mono float32, full file).
        sr: Sample rate in Hz.
        method: Correlation method plugin to use.
        window_s: Window duration in seconds.
        hop_s: Hop (step) between windows in seconds.
        min_match: Minimum confidence threshold for acceptance (0-100).
        silence_threshold_db: RMS threshold below which a window is silence.
        outlier_threshold_ms: Distance from median (ms) beyond which a window
            is considered an outlier. Used in summary logging.
        start_pct: Start of scan range as percentage of duration (0-100).
        end_pct: End of scan range as percentage of duration (0-100).
        log: Logging callback.

    Returns:
        list[ChunkResult] — one per non-silence window, compatible with
        the existing delay selection and stepping detection pipeline.
    """
    if log is None:

        def log(msg: str) -> None:
            pass

    window_samples = int(round(window_s * sr))
    hop_samples = int(round(hop_s * sr))
    min_len = min(len(ref_pcm), len(tgt_pcm))
    duration_s = min_len / sr

    # Apply scan range
    scan_start = int(round(duration_s * (start_pct / 100.0) * sr))
    scan_end = int(round(duration_s * (end_pct / 100.0) * sr))
    scan_end = min(scan_end, min_len)

    # Calculate total window positions
    total_positions = max(0, (scan_end - scan_start - window_samples) // hop_samples + 1)

    log(
        f"[Dense Correlation] {method.name}"
    )
    log(
        f"  Window: {window_s}s, Hop: {hop_s}s, "
        f"Range: {start_pct:.0f}%-{end_pct:.0f}% "
        f"({scan_start / sr:.1f}s - {scan_end / sr:.1f}s)"
    )
    log(f"  Total windows: {total_positions}")

    results: list[ChunkResult] = []
    silence_count = 0

    t0 = time.perf_counter()
    last_report = t0

    pos = scan_start
    window_idx = 0

    while pos + window_samples <= scan_end:
        center_s = (pos + window_samples / 2) / sr

        ref_win = ref_pcm[pos : pos + window_samples]
        tgt_win = tgt_pcm[pos : pos + window_samples]

        ref_db = _rms_db(ref_win)
        tgt_db = _rms_db(tgt_win)

        if ref_db < silence_threshold_db or tgt_db < silence_threshold_db:
            silence_count += 1
        else:
            # Run correlation method (handles numpy→torch→numpy internally)
            raw_ms, confidence = method.find_delay(ref_win, tgt_win, sr)
            accepted = confidence >= min_match

            results.append(
                ChunkResult(
                    delay_ms=int(round(raw_ms)),
                    raw_delay_ms=raw_ms,
                    match_pct=confidence,
                    start_s=center_s,
                    accepted=accepted,
                )
            )

        pos += hop_samples
        window_idx += 1

        # Progress reporting every 5 seconds
        now = time.perf_counter()
        if now - last_report > 5.0:
            done = window_idx
            pct = done / total_positions * 100 if total_positions > 0 else 100
            elapsed = now - t0
            rate = done / elapsed if elapsed > 0 else 0
            eta = (total_positions - done) / rate if rate > 0 else 0
            log(f"  [{pct:5.1f}%] {done}/{total_positions} ({rate:.0f}/s, ETA {eta:.0f}s)")
            last_report = now

    elapsed = time.perf_counter() - t0
    active_count = len(results)

    log(
        f"  Done: {active_count} active + {silence_count} silence = "
        f"{active_count + silence_count} windows in {elapsed:.1f}s "
        f"({(active_count + silence_count) / max(elapsed, 0.001):.0f} windows/s)"
    )

    # ── Summary ──
    _log_dense_summary(results, silence_count, method.name, outlier_threshold_ms,
                       duration_s, scan_start / sr, scan_end / sr, log)

    return results


# ── Helpers ───────────────────────────────────────────────────────────────


def _fmt_time(seconds: float) -> str:
    """Format seconds as M:SS or H:MM:SS."""
    s = int(round(seconds))
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


# ── Summary Logging ───────────────────────────────────────────────────────


def _log_dense_summary(
    results: list[ChunkResult],
    silence_count: int,
    method_name: str,
    outlier_threshold_ms: float,
    file_duration_s: float,
    scan_start_s: float,
    scan_end_s: float,
    log: Callable[[str], None],
) -> None:
    """
    Log a detailed summary of the dense correlation results.

    Shows: classification, coverage, delay statistics, agreement,
    outlier analysis, confidence tiers, delay distribution, and
    cluster analysis with transitions if stepping is detected.
    """
    accepted = [r for r in results if r.accepted]
    rejected = [r for r in results if not r.accepted]
    total = len(results)

    if not accepted:
        log(f"\n  [Summary] {method_name}: NO ACCEPTED WINDOWS (all {total} rejected)")
        return

    delays = np.array([r.raw_delay_ms for r in accepted])
    confs = np.array([r.match_pct for r in accepted])
    rounded_delays = np.array([r.delay_ms for r in accepted])
    times = np.array([r.start_s for r in accepted])

    median_delay = float(np.median(delays))
    mean_delay = float(np.mean(delays))
    std_delay = float(np.std(delays))
    min_delay = float(np.min(delays))
    max_delay = float(np.max(delays))

    # Outlier detection
    outlier_mask = np.abs(delays - median_delay) > outlier_threshold_ms
    outlier_count = int(np.sum(outlier_mask))
    outlier_pct = outlier_count / len(accepted) * 100

    # Inlier statistics (without outliers)
    inlier_delays = delays[~outlier_mask]
    inlier_median = float(np.median(inlier_delays)) if len(inlier_delays) > 0 else median_delay
    inlier_std = float(np.std(inlier_delays)) if len(inlier_delays) > 1 else 0.0

    # Agreement: what % of windows agree on the top rounded delay
    delay_counts = Counter(rounded_delays.tolist())
    most_common = delay_counts.most_common()
    top_delay, top_count = most_common[0]
    agreement_pct = top_count / len(accepted) * 100

    # Classification
    classification = _classify_result(
        std_delay, outlier_pct, agreement_pct, len(accepted), inlier_std,
    )

    # Coverage
    time_span_s = float(times[-1] - times[0]) if len(times) > 1 else 0.0
    coverage_pct = (time_span_s / file_duration_s * 100) if file_duration_s > 0 else 0.0

    log(f"\n{'─' * 70}")
    log(f"  CORRELATION SUMMARY — {method_name}")
    log(f"{'─' * 70}")

    # Classification line (scan-at-a-glance)
    log(f"  Result:      {classification}")

    # File coverage
    log(
        f"  Coverage:    {_fmt_time(scan_start_s)} - {_fmt_time(scan_end_s)} "
        f"({_fmt_time(time_span_s)} analyzed, "
        f"{coverage_pct:.0f}% of {_fmt_time(file_duration_s)})"
    )

    # Window counts
    log(
        f"  Windows:     {len(accepted)} accepted, "
        f"{len(rejected)} rejected, "
        f"{silence_count} silence "
        f"({total + silence_count} total)"
    )

    # Agreement
    log(
        f"  Agreement:   {agreement_pct:.1f}% at {int(top_delay):+d}ms "
        f"({top_count}/{len(accepted)} windows)"
    )

    # Delay statistics
    log(f"  Delay:       {median_delay:+.3f}ms median, "
        f"{mean_delay:+.3f}ms mean, {std_delay:.3f}ms std")
    log(f"               [{min_delay:+.3f}, {max_delay:+.3f}]ms range")

    # Inlier statistics
    if outlier_count > 0:
        log(
            f"  Inliers:     {inlier_median:+.3f}ms median, "
            f"{inlier_std:.3f}ms std "
            f"({len(inlier_delays)} windows, excluding {outlier_count} outliers)"
        )

    # Outlier analysis
    log(
        f"  Outliers:    {outlier_count}/{len(accepted)} "
        f"({outlier_pct:.1f}%) >{outlier_threshold_ms:.0f}ms from median"
    )

    # Confidence tiers
    n = len(confs)
    t90 = int(np.sum(confs >= 90))
    t70 = int(np.sum((confs >= 70) & (confs < 90)))
    t50 = int(np.sum((confs >= 50) & (confs < 70)))
    tlow = int(np.sum(confs < 50))
    log(
        f"  Confidence:  "
        f"≥90%: {t90} ({t90/n*100:.0f}%) | "
        f"70-89%: {t70} ({t70/n*100:.0f}%) | "
        f"50-69%: {t50} ({t50/n*100:.0f}%) | "
        f"<50%: {tlow} ({tlow/n*100:.0f}%)"
    )
    log(
        f"               mean={np.mean(confs):.1f}%, "
        f"min={np.min(confs):.1f}%, max={np.max(confs):.1f}%"
    )

    # Delay distribution (top values with bar chart)
    top_n = min(6, len(most_common))
    log(f"  Delay distribution (top {top_n}):")
    for delay_val, count in most_common[:top_n]:
        pct = count / len(accepted) * 100
        bar = "█" * min(50, int(pct / 2))
        log(f"    {int(delay_val):+6d}ms: {count:5d} ({pct:5.1f}%) {bar}")

    # Cluster analysis for stepping detection
    _log_cluster_analysis(accepted, delays, log)

    log(f"{'─' * 70}")


def _classify_result(
    std_delay: float,
    outlier_pct: float,
    agreement_pct: float,
    n_accepted: int,
    inlier_std: float,
) -> str:
    """
    Produce a one-line classification of the correlation result.

    Returns something like:
      UNIFORM (+145ms, 99.8% agreement, high confidence)
      STEPPING (3 delay groups detected)
      NOISY (high variance, only 45% agreement)
      LOW DATA (only 12 accepted windows)
    """
    if n_accepted < 20:
        return f"⚠ LOW DATA (only {n_accepted} accepted windows)"

    # Uniform: high agreement, low inlier std
    if agreement_pct >= 90 and inlier_std < 5.0:
        return f"UNIFORM ({agreement_pct:.1f}% agreement, std={inlier_std:.3f}ms)"

    # Uniform but slightly noisy
    if agreement_pct >= 70 and inlier_std < 10.0:
        return f"UNIFORM ({agreement_pct:.1f}% agreement, std={inlier_std:.3f}ms, minor noise)"

    # Stepping: low agreement but low std within groups suggests distinct levels
    if agreement_pct < 70 and std_delay > 50 and outlier_pct > 10:
        return f"STEPPING (std={std_delay:.0f}ms, {agreement_pct:.0f}% top agreement — see clusters)"

    # Noisy
    if outlier_pct > 30:
        return f"⚠ NOISY ({outlier_pct:.0f}% outliers, {agreement_pct:.0f}% agreement)"

    # Moderate
    return f"MODERATE ({agreement_pct:.0f}% agreement, std={std_delay:.1f}ms)"


def _log_cluster_analysis(
    accepted: list[ChunkResult],
    delays: np.ndarray,
    log: Callable[[str], None],
) -> None:
    """
    Analyze and log delay clusters for stepping detection.

    Uses DBSCAN clustering to identify distinct delay groups and
    their time ranges. This is informational — the actual stepping
    decision is made by diagnose_audio_issue().
    """
    from sklearn.cluster import DBSCAN

    # Only analyze if there's enough data
    if len(accepted) < 10:
        return

    # Quick check: if std is very small, uniform — no cluster analysis needed
    if np.std(delays) < 10.0:
        return

    # DBSCAN clustering
    db = DBSCAN(eps=30.0, min_samples=5).fit(delays.reshape(-1, 1))
    labels = db.labels_
    unique_labels = sorted(set(labels) - {-1})

    if len(unique_labels) < 2:
        return

    noise_count = int(np.sum(labels == -1))

    log(f"\n  Cluster Analysis ({len(unique_labels)} groups, {noise_count} noise points):")

    cluster_info = []
    for label in unique_labels:
        mask = labels == label
        cluster_delays = delays[mask]
        cluster_chunks = [accepted[i] for i in range(len(accepted)) if mask[i]]
        cluster_times = [c.start_s for c in cluster_chunks]
        cluster_confs = [c.match_pct for c in cluster_chunks]

        mean_d = float(np.mean(cluster_delays))
        std_d = float(np.std(cluster_delays))
        count = int(np.sum(mask))
        pct = count / len(accepted) * 100
        t_start = min(cluster_times)
        t_end = max(cluster_times)
        span_s = t_end - t_start
        mean_conf = float(np.mean(cluster_confs))

        cluster_info.append({
            "label": label,
            "mean_delay": mean_d,
            "std_delay": std_d,
            "count": count,
            "pct": pct,
            "t_start": t_start,
            "t_end": t_end,
            "span_s": span_s,
            "mean_conf": mean_conf,
        })

    # Sort by time of first appearance
    cluster_info.sort(key=lambda c: c["t_start"])

    for i, c in enumerate(cluster_info):
        jump_str = ""
        if i > 0:
            jump = c["mean_delay"] - cluster_info[i - 1]["mean_delay"]
            direction = "+" if jump > 0 else ""
            jump_str = f"  [jump: {direction}{jump:.0f}ms]"

        log(
            f"    Cluster {i + 1}: {c['mean_delay']:+.1f}ms "
            f"(std={c['std_delay']:.1f}ms, n={c['count']}, {c['pct']:.1f}%) "
            f"@ {_fmt_time(c['t_start'])} - {_fmt_time(c['t_end'])} "
            f"({_fmt_time(c['span_s'])}) "
            f"conf={c['mean_conf']:.1f}%"
            f"{jump_str}"
        )

    # Transition point detection — only log real transitions
    # (skip noise-to-cluster or cluster-to-noise bouncing)
    if len(cluster_info) >= 2:
        log(f"\n  Transitions:")
        sorted_results = sorted(accepted, key=lambda r: r.start_s)
        sorted_delays_arr = np.array([r.raw_delay_ms for r in sorted_results])
        sorted_labels = np.array([
            labels[accepted.index(r)] for r in sorted_results
        ])

        # Track the last real (non-noise) cluster label
        prev_real_label = -1
        for i in range(len(sorted_labels)):
            if sorted_labels[i] != -1:
                prev_real_label = sorted_labels[i]
                break

        transitions = []
        for i in range(1, len(sorted_labels)):
            cur = sorted_labels[i]
            if cur == -1:
                continue  # skip noise
            if cur != prev_real_label and prev_real_label != -1:
                # Find last non-noise point before this
                t_before = None
                d_before = None
                for j in range(i - 1, -1, -1):
                    if sorted_labels[j] == prev_real_label:
                        t_before = sorted_results[j].start_s
                        d_before = sorted_delays_arr[j]
                        break
                if t_before is not None:
                    t_after = sorted_results[i].start_s
                    d_after = sorted_delays_arr[i]
                    transitions.append((d_before, d_after, t_before, t_after))
                prev_real_label = cur
            elif cur != -1:
                prev_real_label = cur

        if transitions:
            for d_before, d_after, t_before, t_after in transitions:
                log(
                    f"    {d_before:+.1f}ms → {d_after:+.1f}ms "
                    f"between {_fmt_time(t_before)} and {_fmt_time(t_after)}"
                )
        else:
            log("    (no clean transitions detected)")
