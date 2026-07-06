# vsg_core/analysis/correlation/dense_runner.py
"""
Shared dense-correlation job runner.

Runs the single-method or multi-method dense sliding-window correlation
for one source pair. This is the code that used to live inside
``AnalysisStep`` — extracted so it can execute either in-process
(escape hatch) or inside ``dense_subprocess.py``, isolating the
torch/HIP runtime from the long-lived GUI process.

Torch-free at import time: torch is only pulled in when a method's
``find_delay()`` actually runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .dense import run_dense_correlation
from .methods.scc import Scc
from .registry import list_methods
from .run import _resolve_method

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from ...models.settings import AppSettings
    from ..types import ChunkResult
    from .registry import CorrelationMethod


@dataclass(frozen=True, slots=True)
class CorrelationJobResult:
    """Results of one dense-correlation job (single or multi-method)."""

    selected_method: str
    results_by_method: dict[str, list[ChunkResult]]

    @property
    def selected(self) -> list[ChunkResult]:
        """The results used for delay calculation downstream."""
        return self.results_by_method[self.selected_method]


def run_correlation_job(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    *,
    use_source_separated: bool,
    multi_corr: bool,
    min_match: float,
    start_pct: float,
    end_pct: float,
    log: Callable[[str], None],
) -> CorrelationJobResult:
    """
    Run dense correlation for one source pair.

    ``min_match`` / ``start_pct`` / ``end_pct`` are explicit (rather than
    read from settings) because the stepping QA caller uses different
    values than the analysis step.
    """
    if multi_corr:
        return _run_multi(
            ref_pcm,
            tgt_pcm,
            sr,
            settings,
            use_source_separated=use_source_separated,
            min_match=min_match,
            start_pct=start_pct,
            end_pct=end_pct,
            log=log,
        )

    method = _resolve_method(settings, source_separated=use_source_separated)
    results = _run_one(
        ref_pcm,
        tgt_pcm,
        sr,
        settings,
        method=method,
        min_match=min_match,
        start_pct=start_pct,
        end_pct=end_pct,
        log=log,
    )
    return CorrelationJobResult(
        selected_method=method.name,
        results_by_method={method.name: results},
    )


def _run_one(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    *,
    method: CorrelationMethod,
    min_match: float,
    start_pct: float,
    end_pct: float,
    log: Callable[[str], None],
) -> list[ChunkResult]:
    """One dense pass with the shared settings-derived parameters."""
    return run_dense_correlation(
        ref_pcm=ref_pcm,
        tgt_pcm=tgt_pcm,
        sr=sr,
        method=method,
        window_s=settings.dense_window_s,
        hop_s=settings.dense_hop_s,
        min_match=min_match,
        silence_threshold_db=settings.dense_silence_threshold_db,
        outlier_threshold_ms=settings.dense_outlier_threshold_ms,
        start_pct=start_pct,
        end_pct=end_pct,
        log=log,
        dbscan_epsilon_ms=settings.detection_dbscan_epsilon_ms,
        dbscan_min_samples_pct=settings.detection_dbscan_min_samples_pct,
    )


def _run_multi(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    *,
    use_source_separated: bool,
    min_match: float,
    start_pct: float,
    end_pct: float,
    log: Callable[[str], None],
) -> CorrelationJobResult:
    """
    Run multiple correlation methods using dense sliding window.

    Each enabled method gets its own dense correlation pass with
    full summary logging. The first method's results are selected
    for actual delay calculation.
    """
    # Find enabled methods
    enabled_methods: list[CorrelationMethod] = []
    for method in list_methods():
        if getattr(settings, method.config_key, False):
            if isinstance(method, Scc):
                method = Scc(peak_fit=settings.audio_peak_fit)
            enabled_methods.append(method)

    if not enabled_methods:
        log("[MULTI-CORRELATION] No methods enabled, falling back to single method")
        method = _resolve_method(settings, source_separated=use_source_separated)
        results = _run_one(
            ref_pcm,
            tgt_pcm,
            sr,
            settings,
            method=method,
            min_match=min_match,
            start_pct=start_pct,
            end_pct=end_pct,
            log=log,
        )
        return CorrelationJobResult(
            selected_method=method.name,
            results_by_method={method.name: results},
        )

    log(
        f"\n[MULTI-CORRELATION] Running {len(enabled_methods)} methods "
        f"(dense sliding window)"
    )

    all_results: dict[str, list[ChunkResult]] = {}

    for method in enabled_methods:
        log(f"\n{'=' * 70}")
        log(f"  MULTI-CORRELATION: {method.name}")
        log(f"{'=' * 70}")

        results = _run_one(
            ref_pcm,
            tgt_pcm,
            sr,
            settings,
            method=method,
            min_match=min_match,
            start_pct=start_pct,
            end_pct=end_pct,
            log=log,
        )
        all_results[method.name] = results

        # Free GPU memory between methods
        from .gpu_backend import cleanup_gpu

        cleanup_gpu()

    # Log comparison summary
    log(f"\n{'=' * 70}")
    log("  MULTI-CORRELATION SUMMARY (Dense)")
    log(f"{'=' * 70}")

    for method_name, method_results in all_results.items():
        accepted = [r for r in method_results if r.accepted]
        if accepted:
            import numpy as _np

            delays = _np.array([r.raw_delay_ms for r in accepted])
            median_d = float(_np.median(delays))
            std_d = float(_np.std(delays))
            avg_match = sum(r.match_pct for r in accepted) / len(accepted)
            outliers = int(_np.sum(_np.abs(delays - median_d) > 50.0))
            log(
                f"  {method_name}: {median_d:+.3f}ms median | "
                f"std={std_d:.3f}ms | "
                f"conf={avg_match:.1f}% | "
                f"accepted={len(accepted)}/{len(method_results)} | "
                f"outliers={outliers}"
            )
        else:
            log(f"  {method_name}: NO ACCEPTED WINDOWS")

    log(f"{'=' * 70}\n")

    # Use first method's results for actual processing
    first_method_name = next(iter(all_results.keys()))
    log(
        f"[MULTI-CORRELATION] Using '{first_method_name}' results for delay calculation"
    )
    return CorrelationJobResult(
        selected_method=first_method_name,
        results_by_method=all_results,
    )
