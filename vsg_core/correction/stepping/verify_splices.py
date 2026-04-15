# vsg_core/correction/stepping/verify_splices.py
"""
Per-transition before/after match verification.

After the boundary refiner picks splice points, this module checks — for
each transition — that Source 1 and Source 2 actually line up at the
expected delay on each side of the edit.  Short 1-second cross-correlation
windows are taken at ``edit_s ± {5, 3, 1}`` seconds:

  * BEFORE the edit, Source 2 at time ``t`` should match Source 1 at
    time ``t + delay_before_ms / 1000``.
  * AFTER the edit, the same for ``delay_after_ms``.

Each window returns a (lag, confidence) pair; we flag the transition if
any window shows ``abs(lag) > lag_tolerance_ms`` with decent confidence.

This is the app-side equivalent of Stage 3 in the research test script
(``test_combined_final.py``).  It catches cases where a splice point was
placed a bit early/late, or where the cluster-detected delay doesn't
actually match the content on one side.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from scipy.signal import correlate

if TYPE_CHECKING:
    from collections.abc import Callable

    from .types import SplicePoint


# Per-window result tuple: (check_time_s, lag_ms, confidence_pct, passed)
_CheckResult = tuple[float, float, float, bool]


def _xcorr_lag(
    w1: np.ndarray,
    w2: np.ndarray,
    sample_rate: int,
    search_radius_s: float = 0.05,
) -> tuple[float, float]:
    """Return ``(lag_ms, confidence_pct)`` for two equal-length windows.

    Positive lag = w2 leads w1 (needs to be shifted right to align).
    Confidence is the normalised cross-correlation peak as a percentage
    (100% = identical signals).

    Search is restricted to ``±search_radius_s`` around the center to
    avoid spurious peaks from periodic content.
    """
    if len(w1) == 0 or len(w2) == 0:
        return 0.0, 0.0
    search = int(search_radius_s * sample_rate)
    corr = correlate(w1.astype(np.float64), w2.astype(np.float64), mode="full")
    center = len(w2) - 1
    ss = max(0, center - search)
    se = min(len(corr), center + search)
    if ss >= se:
        return 0.0, 0.0
    peak = ss + int(np.argmax(np.abs(corr[ss:se])))
    lag_ms = (peak - center) / sample_rate * 1000.0
    w1_energy = float(np.sum(w1.astype(np.float64) ** 2))
    w2_energy = float(np.sum(w2.astype(np.float64) ** 2))
    conf_pct = abs(corr[peak]) / (np.sqrt(w1_energy * w2_energy) + 1e-10) * 100.0
    return lag_ms, conf_pct


def _check_window(
    ref_pcm: np.ndarray,
    src2_pcm: np.ndarray,
    sample_rate: int,
    src2_time_s: float,
    offset_ms: float,
    window_s: float,
    lag_tolerance_ms: float,
    conf_threshold: float,
) -> _CheckResult | None:
    """Run a single 1-second cross-correlation check.

    Returns None if the requested slice doesn't fit in both PCMs.
    Returns (src2_time, lag_ms, conf_pct, passed) otherwise.
    """
    win = int(window_s * sample_rate)
    s1 = int((src2_time_s + offset_ms / 1000.0) * sample_rate)
    s2 = int(src2_time_s * sample_rate)
    if s1 < 0 or s1 + win > len(ref_pcm):
        return None
    if s2 < 0 or s2 + win > len(src2_pcm):
        return None

    lag, conf = _xcorr_lag(ref_pcm[s1 : s1 + win], src2_pcm[s2 : s2 + win], sample_rate)
    passed = abs(lag) < lag_tolerance_ms and conf > conf_threshold
    return (src2_time_s, lag, conf, passed)


def _format_mark(
    lag_ms: float, conf_pct: float, lag_tolerance_ms: float, conf_threshold: float
) -> str:
    """Return the trailing marker shown after each window's line."""
    if abs(lag_ms) < lag_tolerance_ms and conf_pct > conf_threshold:
        return "✓"
    if conf_pct > 10.0:
        return f"✗ {lag_ms:+.0f}ms"
    return "~ low conf"


def verify_splice_points(
    ref_pcm: np.ndarray,
    src2_pcm: np.ndarray,
    sample_rate: int,
    splice_points: list[SplicePoint],
    log: Callable[[str], None],
    check_offsets_s: tuple[float, ...] = (-5.0, -3.0, -1.0, 1.0, 3.0, 5.0),
    window_s: float = 1.0,
    lag_tolerance_ms: float = 3.0,
    conf_threshold: float = 30.0,
) -> list[dict[str, object]]:
    """Verify every splice point against Source 1.

    Parameters
    ----------
    ref_pcm : np.ndarray
        Source 1 mono PCM (int32 or float32).
    src2_pcm : np.ndarray
        Source 2 mono PCM (same sample rate as ref_pcm).
    splice_points : list[SplicePoint]
        Output of ``refine_boundaries``.
    check_offsets_s
        Offsets relative to each splice_point.src2_time_s at which to
        take 1-second verification windows.  Negative = before the
        edit at delay_before; positive = after the edit at delay_after.
    window_s
        Length of each verification window.
    lag_tolerance_ms
        Maximum absolute lag that counts as "matched".
    conf_threshold
        Minimum confidence (%) for a window to be considered reliable.

    Returns
    -------
    list[dict]
        Non-empty list = at least one transition failed verification.
        Each dict has keys: ``transition_index``, ``src2_time_s``,
        ``before_failures`` (count), ``after_failures`` (count),
        ``details`` (list of failed window descriptions).
    """
    issues: list[dict[str, object]] = []

    for idx, sp in enumerate(splice_points):
        edit_s = sp.src2_time_s
        log(f"  [Verify] Transition {idx + 1} @ {edit_s:.3f}s:")

        # BEFORE: pre-edit delay
        log(f"    BEFORE edit (offset {sp.delay_before_ms:+.0f}ms):")
        before_failures: list[tuple[float, float, float]] = []
        for dt in sorted(check_offsets_s):
            if dt >= 0:
                continue
            result = _check_window(
                ref_pcm,
                src2_pcm,
                sample_rate,
                edit_s + dt,
                sp.delay_before_ms,
                window_s,
                lag_tolerance_ms,
                conf_threshold,
            )
            if result is None:
                continue
            check_time, lag, conf, passed = result
            mark = _format_mark(lag, conf, lag_tolerance_ms, conf_threshold)
            log(
                f"      {check_time:.1f}s: lag={lag:>+6.1f}ms conf={conf:>4.0f}% {mark}"
            )
            if not passed and conf > 10.0:
                before_failures.append((check_time, lag, conf))

        # AFTER: post-edit delay
        log(f"    AFTER edit (offset {sp.delay_after_ms:+.0f}ms):")
        after_failures: list[tuple[float, float, float]] = []
        for dt in sorted(check_offsets_s):
            if dt <= 0:
                continue
            result = _check_window(
                ref_pcm,
                src2_pcm,
                sample_rate,
                edit_s + dt,
                sp.delay_after_ms,
                window_s,
                lag_tolerance_ms,
                conf_threshold,
            )
            if result is None:
                continue
            check_time, lag, conf, passed = result
            mark = _format_mark(lag, conf, lag_tolerance_ms, conf_threshold)
            log(
                f"      {check_time:.1f}s: lag={lag:>+6.1f}ms conf={conf:>4.0f}% {mark}"
            )
            if not passed and conf > 10.0:
                after_failures.append((check_time, lag, conf))

        if before_failures or after_failures:
            issue: dict[str, object] = {
                "transition_index": idx + 1,
                "src2_time_s": edit_s,
                "before_failures": len(before_failures),
                "after_failures": len(after_failures),
                "details": [
                    f"BEFORE {t:.1f}s: lag {lag:+.0f}ms (conf {conf:.0f}%)"
                    for (t, lag, conf) in before_failures
                ]
                + [
                    f"AFTER {t:.1f}s: lag {lag:+.0f}ms (conf {conf:.0f}%)"
                    for (t, lag, conf) in after_failures
                ],
            }
            issues.append(issue)

    return issues
