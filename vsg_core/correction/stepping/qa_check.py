# vsg_core/correction/stepping/qa_check.py
"""
Post-correction quality assurance.

Runs a fresh dense correlation between the corrected audio and the
reference to verify that the delay is now uniform at the anchor value.
"""

from __future__ import annotations

from dataclasses import replace
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

    Returns ``(passed, metadata_dict)``.
    """
    from ...analysis.correlation import run_audio_correlation

    log("  [QA] Running correlation on corrected audio...")

    qa_threshold = settings.segmented_qa_threshold
    qa_chunks = settings.segment_qa_chunk_count
    qa_min = settings.segment_qa_min_accepted_chunks

    # Override scan parameters for QA
    qa_settings = replace(
        settings,
        scan_chunk_count=qa_chunks,
        min_accepted_windows=qa_min,
        min_match_pct=qa_threshold,
    )

    try:
        ref_lang = settings.analysis_lang_source1
        results = run_audio_correlation(
            ref_file=ref_file_path,
            target_file=corrected_path,
            settings=qa_settings,
            runner=runner,
            tool_paths=tool_paths,
            ref_lang=ref_lang,
            target_lang=None,
            role_tag="QA",
        )

        accepted = [r for r in results if r.accepted]
        if len(accepted) < qa_min:
            log(
                f"  [QA] FAILED: Not enough confident windows "
                f"({len(accepted)}/{qa_min})"
            )
            return False, {"reason": "insufficient_accepted", "count": len(accepted)}

        delays = [r.delay_ms for r in accepted]
        median_delay = float(np.median(delays))
        std_dev = float(np.std(delays))

        # Median check
        tol = 100 if skip_mode else 20
        if abs(median_delay - base_delay_ms) > tol:
            log(
                f"  [QA] FAILED: Median delay {median_delay:.1f}ms "
                f"≠ base {base_delay_ms}ms"
            )
            return False, {
                "reason": "median_mismatch",
                "median": median_delay,
                "base": base_delay_ms,
            }

        # Stability check
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
