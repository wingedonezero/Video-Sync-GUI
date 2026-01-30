# vsg_core/analysis/correlation/_runner.py
"""
Correlation runner module.

Coordinates the full correlation workflow:
1. Decode audio from files
2. Apply source separation (if enabled)
3. Apply filtering
4. Extract chunks
5. Run correlation algorithm on each chunk
6. Return structured results

This is the main entry point for running correlation analysis.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vsg_core.models import ChunkResult

from ..preprocessing import (
    apply_filter,
    decode_to_memory,
    extract_chunks,
    get_audio_stream_info,
    get_chunk_config,
    normalize_lang,
)
from ..separation import apply_source_separation, is_separation_enabled
from . import get_algorithm_for_method

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner


def run_correlation(
    ref_file: str,
    target_file: str,
    config: dict[str, Any],
    runner: CommandRunner,
    tool_paths: dict[str, str],
    ref_track_index: int | None = None,
    target_track_index: int | None = None,
    ref_lang: str | None = None,
    target_lang: str | None = None,
    use_source_separation: bool = False,
    log: Callable[[str], None] | None = None,
    role_tag: str = "Source 2",
) -> list[ChunkResult]:
    """
    Run correlation analysis between reference and target files.

    This is the main entry point for single-method correlation.

    Args:
        ref_file: Path to reference video/audio file
        target_file: Path to target video/audio file
        config: Configuration dictionary
        runner: CommandRunner for external tools
        tool_paths: Paths to external tools
        ref_track_index: Optional specific reference track index (bypasses language matching)
        target_track_index: Optional specific target track index (bypasses language matching)
        ref_lang: Optional reference language code for track selection
        target_lang: Optional target language code for track selection
        use_source_separation: Whether to apply source separation
        log: Optional logging callback
        role_tag: Source identifier for logging

    Returns:
        List of ChunkResult dataclasses with correlation results
    """
    if log is None:
        log = lambda x: None

    sample_rate = int(config.get("sample_rate_hz", 48000))
    use_soxr = bool(config.get("use_soxr_resampler", False))
    method_name = config.get("correlation_method", "Standard Correlation (SCC)")
    acceptance_threshold = float(config.get("match_threshold_pct", 50.0))

    # Get reference track index
    if ref_track_index is not None:
        ref_idx = ref_track_index
        log(f"[AUDIO_CORR] Using explicit reference track index: {ref_idx}")
    else:
        ref_lang_norm = normalize_lang(ref_lang)
        ref_idx, _ = get_audio_stream_info(ref_file, ref_lang_norm, runner, tool_paths)
        ref_idx = ref_idx or 0

    # Get target track index
    if target_track_index is not None:
        tgt_idx = target_track_index
        tgt_lang = normalize_lang(target_lang)
        log(f"[AUDIO_CORR] Using explicit target track index: {tgt_idx}")
    else:
        tgt_lang = normalize_lang(target_lang)
        tgt_idx, _ = get_audio_stream_info(target_file, tgt_lang, runner, tool_paths)
        tgt_idx = tgt_idx or 0

    log(f"[AUDIO_CORR] Reference track index: {ref_idx}")
    log(
        f"[AUDIO_CORR] Target ({role_tag}) track index: {tgt_idx}, lang filter: {tgt_lang}"
    )

    # Decode audio
    log("Decoding reference audio...")
    ref_pcm = decode_to_memory(
        ref_file, ref_idx, sample_rate, use_soxr, runner, tool_paths
    )
    log("Decoding target audio...")
    tgt_pcm = decode_to_memory(
        target_file, tgt_idx, sample_rate, use_soxr, runner, tool_paths
    )

    log(
        f"[AUDIO_CORR] Reference: {len(ref_pcm)} samples, Target: {len(tgt_pcm)} samples"
    )

    # Apply source separation if enabled for this source
    if use_source_separation and is_separation_enabled(config):
        log(f"[AUDIO_CORR] Applying source separation for {role_tag}...")
        ref_pcm, tgt_pcm = apply_source_separation(
            ref_pcm, tgt_pcm, sample_rate, config, log, role_tag
        )

    # Apply filtering
    ref_pcm = apply_filter(ref_pcm, sample_rate, config, log)
    tgt_pcm = apply_filter(tgt_pcm, sample_rate, config, log)

    # Get correlation algorithm
    algorithm = get_algorithm_for_method(method_name)
    log(f"[AUDIO_CORR] Using correlation method: {algorithm.name}")

    # Extract chunks
    chunk_config = get_chunk_config(config)
    chunks = extract_chunks(ref_pcm, tgt_pcm, sample_rate, chunk_config)
    log(f"[AUDIO_CORR] Extracted {len(chunks)} chunks for analysis")

    # Run correlation on each chunk
    results: list[ChunkResult] = []
    for chunk in chunks:
        delay_ms, match = algorithm.find_delay(
            chunk.ref_audio, chunk.target_audio, sample_rate
        )

        accepted = match >= acceptance_threshold
        result = ChunkResult(
            chunk_index=chunk.index,
            start_time=chunk.start_time,
            delay_samples=0,  # Not tracked at this level
            delay_ms=round(delay_ms),
            raw_delay_ms=delay_ms,
            confidence=match,
            accepted=accepted,
        )
        results.append(result)

        status = "ACCEPTED" if accepted else "REJECTED"
        log(
            f"  Chunk {chunk.index}: delay={delay_ms:+.1f}ms, "
            f"match={match:.1f}% [{status}]"
        )

    accepted_count = sum(1 for r in results if r.accepted)
    log(f"[AUDIO_CORR] {accepted_count}/{len(results)} chunks accepted")

    return results


def run_multi_correlation(
    ref_file: str,
    target_file: str,
    config: dict[str, Any],
    runner: CommandRunner,
    tool_paths: dict[str, str],
    ref_track_index: int | None = None,
    target_track_index: int | None = None,
    ref_lang: str | None = None,
    target_lang: str | None = None,
    use_source_separation: bool = False,
    log: Callable[[str], None] | None = None,
    role_tag: str = "Source 2",
) -> dict[str, list[ChunkResult]]:
    """
    Run multiple correlation methods on the same decoded audio.

    Decodes audio once and runs all enabled methods to compare results.

    Args:
        ref_file: Path to reference video/audio file
        target_file: Path to target video/audio file
        config: Configuration dictionary with multi_corr_* settings
        runner: CommandRunner for external tools
        tool_paths: Paths to external tools
        ref_track_index: Optional specific reference track index (bypasses language matching)
        target_track_index: Optional specific target track index (bypasses language matching)
        ref_lang: Optional reference language code for track selection
        target_lang: Optional target language code for track selection
        use_source_separation: Whether to apply source separation
        log: Optional logging callback
        role_tag: Source identifier for logging

    Returns:
        Dictionary mapping method names to list of ChunkResult dataclasses
    """
    from . import MULTI_CORR_METHODS

    if log is None:
        log = lambda x: None

    sample_rate = int(config.get("sample_rate_hz", 48000))
    use_soxr = bool(config.get("use_soxr_resampler", False))
    acceptance_threshold = float(config.get("match_threshold_pct", 50.0))

    # Get reference track index
    if ref_track_index is not None:
        ref_idx = ref_track_index
        log(f"[MULTI_CORR] Using explicit reference track index: {ref_idx}")
    else:
        ref_lang_norm = normalize_lang(ref_lang)
        ref_idx, _ = get_audio_stream_info(ref_file, ref_lang_norm, runner, tool_paths)
        ref_idx = ref_idx or 0

    # Get target track index
    if target_track_index is not None:
        tgt_idx = target_track_index
        tgt_lang = normalize_lang(target_lang)
        log(f"[MULTI_CORR] Using explicit target track index: {tgt_idx}")
    else:
        tgt_lang = normalize_lang(target_lang)
        tgt_idx, _ = get_audio_stream_info(target_file, tgt_lang, runner, tool_paths)
        tgt_idx = tgt_idx or 0

    log(f"[MULTI_CORR] Reference track index: {ref_idx}")
    log(
        f"[MULTI_CORR] Target ({role_tag}) track index: {tgt_idx}, lang filter: {tgt_lang}"
    )

    # Decode audio once
    log("Decoding reference audio...")
    ref_pcm = decode_to_memory(
        ref_file, ref_idx, sample_rate, use_soxr, runner, tool_paths
    )
    log("Decoding target audio...")
    tgt_pcm = decode_to_memory(
        target_file, tgt_idx, sample_rate, use_soxr, runner, tool_paths
    )

    # Apply source separation if enabled
    if use_source_separation and is_separation_enabled(config):
        log(f"[MULTI_CORR] Applying source separation for {role_tag}...")
        ref_pcm, tgt_pcm = apply_source_separation(
            ref_pcm, tgt_pcm, sample_rate, config, log, role_tag
        )

    # Apply filtering
    ref_pcm = apply_filter(ref_pcm, sample_rate, config, log)
    tgt_pcm = apply_filter(tgt_pcm, sample_rate, config, log)

    # Extract chunks once
    chunk_config = get_chunk_config(config)
    chunks = extract_chunks(ref_pcm, tgt_pcm, sample_rate, chunk_config)
    log(f"[MULTI_CORR] Extracted {len(chunks)} chunks for analysis")

    # Determine which methods to run
    enabled_methods = []
    for method_name, config_key in MULTI_CORR_METHODS:
        if config.get(config_key, False):
            enabled_methods.append(method_name)

    if not enabled_methods:
        # Fallback to primary method only
        primary_method = config.get("correlation_method", "Standard Correlation (SCC)")
        enabled_methods = [primary_method]

    log(f"[MULTI_CORR] Running {len(enabled_methods)} method(s): {enabled_methods}")

    # Run each method
    all_results: dict[str, list[ChunkResult]] = {}

    for method_name in enabled_methods:
        algorithm = get_algorithm_for_method(method_name)
        log(f"[MULTI_CORR] Running {algorithm.name}...")

        method_results: list[ChunkResult] = []
        for chunk in chunks:
            delay_ms, match = algorithm.find_delay(
                chunk.ref_audio, chunk.target_audio, sample_rate
            )

            accepted = match >= acceptance_threshold
            result = ChunkResult(
                chunk_index=chunk.index,
                start_time=chunk.start_time,
                delay_samples=0,
                delay_ms=round(delay_ms),
                raw_delay_ms=delay_ms,
                confidence=match,
                accepted=accepted,
            )
            method_results.append(result)

        accepted_count = sum(1 for r in method_results if r.accepted)
        log(
            f"  {algorithm.name}: {accepted_count}/{len(method_results)} chunks accepted"
        )

        all_results[method_name] = method_results

    return all_results
