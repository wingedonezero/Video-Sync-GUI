# vsg_core/analysis/correlation/run.py
"""
Standalone audio correlation runner.

Provides run_audio_correlation() for modules that need to run a full
decode → filter → chunk → correlate pipeline without going through the
analysis step (e.g. stepping correction QA checks).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..types import ChunkResult
from .chunking import extract_chunks
from .decode import DEFAULT_SR, decode_audio, get_audio_stream_info, normalize_lang
from .filtering import apply_bandpass, apply_lowpass
from .methods.scc import Scc
from .registry import get_method

if TYPE_CHECKING:
    from collections.abc import Callable

    import numpy as np

    from ...io.runner import CommandRunner
    from ...models.settings import AppSettings


def _resolve_method(settings: AppSettings, *, source_separated: bool):
    """Resolve the correlation method to use based on settings."""
    method_name = (
        settings.correlation_method_source_separated
        if source_separated
        else settings.correlation_method
    )
    if "Standard Correlation" in method_name or "SCC" in method_name:
        return Scc(peak_fit=settings.audio_peak_fit)
    return get_method(method_name)


def _apply_filtering(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    log: Callable[[str], None],
) -> tuple[np.ndarray, np.ndarray]:
    """Apply configured audio filtering."""
    filtering_method = settings.filtering_method

    if filtering_method == "Dialogue Band-Pass Filter":
        log("Applying Dialogue Band-Pass filter...")
        lowcut = settings.filter_bandpass_lowcut_hz
        highcut = settings.filter_bandpass_highcut_hz
        order = settings.filter_bandpass_order
        ref_pcm = apply_bandpass(ref_pcm, sr, lowcut, highcut, order, log)
        tgt_pcm = apply_bandpass(tgt_pcm, sr, lowcut, highcut, order, log)
    elif filtering_method == "Low-Pass Filter":
        cutoff = settings.audio_bandlimit_hz
        if cutoff > 0:
            log(f"Applying Low-Pass filter at {cutoff} Hz...")
            taps = settings.filter_lowpass_taps
            ref_pcm = apply_lowpass(ref_pcm, sr, cutoff, taps, log)
            tgt_pcm = apply_lowpass(tgt_pcm, sr, cutoff, taps, log)

    return ref_pcm, tgt_pcm


def run_audio_correlation(
    ref_file: str,
    target_file: str,
    settings: AppSettings,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
    ref_lang: str | None = None,
    target_lang: str | None = None,
    role_tag: str = "Source 2",
    log: Callable[[str], None] | None = None,
) -> list[ChunkResult]:
    """
    Run a full audio correlation pipeline: decode → filter → chunk → correlate.

    This is a standalone function for use outside the analysis step,
    e.g. by stepping correction QA checks.

    Args:
        ref_file: Path to reference audio/video file.
        target_file: Path to target audio/video file.
        settings: App settings controlling correlation parameters.
        runner: CommandRunner for subprocess execution.
        tool_paths: Dict of tool paths (ffmpeg, mkvmerge, etc.).
        ref_lang: Language code to select reference audio track.
        target_lang: Language code to select target audio track.
        role_tag: Label for log messages (e.g. 'QA', 'Source 2').
        log: Optional logging callback.

    Returns:
        List of ChunkResult from correlation.
    """
    if log is None:
        log = runner._log_message

    # --- 1. Select audio streams ---
    ref_norm = normalize_lang(ref_lang)
    tgt_norm = normalize_lang(target_lang)

    idx_ref, _ = get_audio_stream_info(ref_file, ref_norm, runner, tool_paths)
    idx_tgt, _ = get_audio_stream_info(target_file, tgt_norm, runner, tool_paths)

    if idx_ref is None or idx_tgt is None:
        raise ValueError("Could not locate required audio streams for correlation.")

    # --- 2. Decode ---
    use_soxr = settings.use_soxr
    ref_pcm = decode_audio(ref_file, idx_ref, DEFAULT_SR, use_soxr, runner, tool_paths)
    tgt_pcm = decode_audio(
        target_file, idx_tgt, DEFAULT_SR, use_soxr, runner, tool_paths
    )

    # --- 3. Filtering ---
    ref_pcm, tgt_pcm = _apply_filtering(ref_pcm, tgt_pcm, DEFAULT_SR, settings, log)

    # --- 4. Extract chunks ---
    chunks = extract_chunks(
        ref_pcm=ref_pcm,
        tgt_pcm=tgt_pcm,
        sr=DEFAULT_SR,
        chunk_count=settings.scan_chunk_count,
        chunk_duration_s=float(settings.scan_chunk_duration),
        start_pct=settings.scan_start_percentage,
        end_pct=settings.scan_end_percentage,
    )

    # --- 5. Correlate ---
    min_match = float(settings.min_match_pct)
    method = _resolve_method(settings, source_separated=False)
    log(f"[{role_tag}] Using method: {method.name}")

    results: list[ChunkResult] = []
    chunk_count = len(chunks)

    for chunk in chunks:
        raw_ms, match = method.find_delay(chunk.ref, chunk.tgt, DEFAULT_SR)
        accepted = match >= min_match
        status_str = "ACCEPTED" if accepted else f"REJECTED (below {min_match:.1f})"
        log(
            f"  Chunk {chunk.index}/{chunk_count} (@{chunk.start_s:.1f}s): "
            f"delay = {int(round(raw_ms)):+d} ms "
            f"(raw={raw_ms:+.3f}, match={match:.2f}) "
            f"— {status_str}"
        )
        results.append(
            ChunkResult(
                delay_ms=int(round(raw_ms)),
                raw_delay_ms=raw_ms,
                match_pct=match,
                start_s=chunk.start_s,
                accepted=accepted,
            )
        )

    return results
