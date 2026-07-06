# tests/test_correlation_subprocess.py
"""
Tests for the dense-correlation subprocess isolation.

Verifies:
1. ChunkResult / FrameRefinementResult JSON round-trips are exact.
2. The in-process runner recovers a known synthetic delay.
3. The subprocess path returns field-for-field identical results to the
   in-process path and forwards the dense log lines.
4. Launcher failures raise RuntimeError and still clean up the PCM files.
5. Multi-corr mode returns one result list per enabled method.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from vsg_core.analysis.correlation.dense_launcher import (  # noqa: E402
    chunk_result_from_dict,
    chunk_result_to_dict,
    run_dense_correlation_subprocess,
)
from vsg_core.analysis.types import ChunkResult  # noqa: E402
from vsg_core.correction.stepping.frame_refinement_subprocess import (  # noqa: E402
    frame_refinement_result_from_dict,
    frame_refinement_result_to_dict,
    payload_to_splice_point,
    splice_point_to_payload,
)
from vsg_core.correction.stepping.types import (  # noqa: E402
    FrameRefinementResult,
    SilenceZone,
    SplicePoint,
)
from vsg_core.models.settings import AppSettings  # noqa: E402

torch_available = importlib.util.find_spec("torch") is not None

needs_torch = pytest.mark.skipif(not torch_available, reason="torch not installed")

SR = 48_000
SHIFT_MS = 250.0


def _make_settings() -> AppSettings:
    """Fast dense-correlation settings for a 30 s synthetic file."""
    return AppSettings(
        correlation_method="Standard Correlation (SCC)",
        dense_window_s=1.0,
        dense_hop_s=0.5,
        min_match_pct=10.0,
        scan_start_percentage=0.0,
        scan_end_percentage=100.0,
    )


def _make_pcm_pair() -> tuple[np.ndarray, np.ndarray]:
    """Seeded band-limited noise, target delayed by exactly SHIFT_MS."""
    rng = np.random.default_rng(1234)
    duration_s = 30.0
    n = int(duration_s * SR)
    noise = rng.standard_normal(n).astype(np.float32)
    # Cheap band-limiting: moving average knocks out the highest frequencies
    kernel = np.ones(8, dtype=np.float32) / 8.0
    ref = np.convolve(noise, kernel, mode="same").astype(np.float32)

    shift_samples = int(SHIFT_MS / 1000.0 * SR)
    tgt = np.zeros_like(ref)
    tgt[shift_samples:] = ref[: n - shift_samples]
    return ref, tgt


def test_chunk_result_roundtrip_exact() -> None:
    original = ChunkResult(
        delay_ms=-1250,
        raw_delay_ms=-1250.0211838,
        match_pct=97.43,
        start_s=305.25,
        accepted=True,
    )
    rebuilt = chunk_result_from_dict(chunk_result_to_dict(original))
    assert rebuilt == original


def test_frame_refinement_roundtrip_exact() -> None:
    original = FrameRefinementResult(
        mode="refined",
        reason="",
        before_anchor_offset_frames=-3,
        after_anchor_offset_frames=5,
        before_anchor_score=0.913,
        after_anchor_score=0.887,
        audio_expected_jump_frames=8,
        measured_jump_frames=8,
        jump_confirmed=True,
        last_before_frame=1000,
        first_after_frame=1001,
        audio_src2_time_s=41.708,
        video_src2_time_s=41.75,
        frame_drift_ms=42.0,
        target_fps=23.976,
    )
    rebuilt = frame_refinement_result_from_dict(
        frame_refinement_result_to_dict(original)
    )
    assert rebuilt == original

    stamped = FrameRefinementResult(mode="skipped_gate", reason="bad fps")
    rebuilt_stamped = frame_refinement_result_from_dict(
        frame_refinement_result_to_dict(stamped)
    )
    assert rebuilt_stamped == stamped


def test_splice_payload_roundtrip() -> None:
    sp = SplicePoint(
        ref_time_s=120.5,
        src2_time_s=118.25,
        delay_before_ms=-100.0,
        delay_after_ms=-250.5,
        correction_ms=-150.5,
        silence_zone=SilenceZone(
            start_s=118.0,
            end_s=118.5,
            center_s=118.25,
            avg_db=-72.3,
            duration_ms=500.0,
            source="vad",
        ),
    )
    rebuilt = payload_to_splice_point(splice_point_to_payload(3, sp))
    assert rebuilt.ref_time_s == sp.ref_time_s
    assert rebuilt.src2_time_s == sp.src2_time_s
    assert rebuilt.delay_before_ms == sp.delay_before_ms
    assert rebuilt.delay_after_ms == sp.delay_after_ms
    assert rebuilt.correction_ms == sp.correction_ms
    assert rebuilt.silence_zone == sp.silence_zone

    bare = SplicePoint(
        ref_time_s=1.0,
        src2_time_s=1.0,
        delay_before_ms=0.0,
        delay_after_ms=42.0,
        correction_ms=42.0,
        silence_zone=None,
    )
    assert (
        payload_to_splice_point(splice_point_to_payload(0, bare)).silence_zone is None
    )


@needs_torch
def test_in_process_recovers_known_delay() -> None:
    from vsg_core.analysis.correlation.dense_runner import run_correlation_job

    ref, tgt = _make_pcm_pair()
    settings = _make_settings()
    result = run_correlation_job(
        ref,
        tgt,
        SR,
        settings,
        use_source_separated=False,
        multi_corr=False,
        min_match=10.0,
        start_pct=0.0,
        end_pct=100.0,
        log=lambda _msg: None,
    )
    accepted = [r for r in result.selected if r.accepted]
    assert len(accepted) > 20
    median = float(np.median([r.raw_delay_ms for r in accepted]))
    # Sign convention: a target that starts SHIFT_MS later than the
    # reference reports a NEGATIVE delay.
    assert median == pytest.approx(-SHIFT_MS, abs=2.0)


@needs_torch
def test_subprocess_matches_in_process(tmp_path: Path) -> None:
    from vsg_core.analysis.correlation.dense_runner import run_correlation_job

    ref, tgt = _make_pcm_pair()
    settings = _make_settings()

    truth = run_correlation_job(
        ref,
        tgt,
        SR,
        settings,
        use_source_separated=False,
        multi_corr=False,
        min_match=10.0,
        start_pct=0.0,
        end_pct=100.0,
        log=lambda _msg: None,
    ).selected

    lines: list[str] = []
    results = run_dense_correlation_subprocess(
        ref,
        tgt,
        SR,
        settings,
        use_source_separated=False,
        multi_corr=False,
        min_match=10.0,
        start_pct=0.0,
        end_pct=100.0,
        temp_dir=tmp_path,
        tag="test",
        log=lines.append,
    )

    assert results == truth  # exact: same code, same input, same device
    joined = "\n".join(lines)
    assert "[Dense Correlation]" in joined
    assert "CORRELATION SUMMARY" in joined
    # PCM temp files must be gone even on success
    assert not (tmp_path / "corr_ref_test.npy").exists()
    assert not (tmp_path / "corr_tgt_test.npy").exists()


def test_subprocess_failure_raises_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import vsg_core.analysis.correlation.dense_launcher as launcher_mod

    monkeypatch.setattr(
        launcher_mod.sys, "executable", str(tmp_path / "nonexistent-python")
    )

    ref = np.zeros(SR, dtype=np.float32)
    tgt = np.zeros(SR, dtype=np.float32)
    with pytest.raises(RuntimeError):
        run_dense_correlation_subprocess(
            ref,
            tgt,
            SR,
            _make_settings(),
            use_source_separated=False,
            multi_corr=False,
            min_match=10.0,
            start_pct=0.0,
            end_pct=100.0,
            temp_dir=tmp_path,
            tag="fail",
            log=lambda _msg: None,
        )
    assert not (tmp_path / "corr_ref_fail.npy").exists()
    assert not (tmp_path / "corr_tgt_fail.npy").exists()


@needs_torch
def test_multi_corr_runs_all_enabled_methods() -> None:
    from vsg_core.analysis.correlation.dense_runner import run_correlation_job

    ref, tgt = _make_pcm_pair()
    settings = _make_settings()
    settings.multi_correlation_enabled = True
    settings.multi_corr_scc = True
    settings.multi_corr_gcc_phat = True
    settings.multi_corr_onset = False
    settings.multi_corr_gcc_scot = False
    settings.multi_corr_gcc_whiten = False
    settings.multi_corr_spectrogram = False

    result = run_correlation_job(
        ref,
        tgt,
        SR,
        settings,
        use_source_separated=False,
        multi_corr=True,
        min_match=10.0,
        start_pct=0.0,
        end_pct=100.0,
        log=lambda _msg: None,
    )
    assert set(result.results_by_method) == {
        "Standard Correlation (SCC)",
        "Phase Correlation (GCC-PHAT)",
    }
    # First enabled method (registry order) is selected for delay calculation
    assert result.selected_method == "Standard Correlation (SCC)"
    assert result.selected is result.results_by_method["Standard Correlation (SCC)"]
