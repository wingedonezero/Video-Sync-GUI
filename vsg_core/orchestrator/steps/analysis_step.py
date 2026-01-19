# vsg_core/orchestrator/steps/analysis_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Dict, Any
from collections import Counter

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import Delays
from vsg_core.analysis.audio_corr import run_audio_correlation, run_multi_correlation
from vsg_core.analysis.drift_detection import diagnose_audio_issue
from vsg_core.analysis.sync_stability import analyze_sync_stability
from vsg_core.extraction.tracks import get_stream_info, get_stream_info_with_delays


def _format_track_details(track: Dict[str, Any], index: int) -> str:
    """
    Format audio track details for logging.

    Args:
        track: Track dictionary from mkvmerge JSON
        index: 0-based audio track index

    Returns:
        Formatted string like "Track 0: Japanese (jpn), FLAC 2.0, 'Commentary'"
    """
    props = track.get('properties', {})

    # Language
    lang = props.get('language', 'und')
    lang_name = props.get('language_ietf', '') or props.get('track_name', '')

    # Codec - extract readable name from codec_id
    codec_id = props.get('codec_id', 'unknown')
    # Common codec_id mappings
    codec_map = {
        'A_FLAC': 'FLAC',
        'A_AAC': 'AAC',
        'A_AC3': 'AC3',
        'A_EAC3': 'E-AC3',
        'A_DTS': 'DTS',
        'A_TRUEHD': 'TrueHD',
        'A_OPUS': 'Opus',
        'A_VORBIS': 'Vorbis',
        'A_PCM': 'PCM',
        'A_MP3': 'MP3',
    }
    # Try exact match first, then prefix match
    codec_name = codec_map.get(codec_id)
    if not codec_name:
        for prefix, name in codec_map.items():
            if codec_id.startswith(prefix):
                codec_name = name
                break
    if not codec_name:
        codec_name = codec_id.replace('A_', '')

    # Channels
    channels = props.get('audio_channels', 2)
    channel_str = {1: 'Mono', 2: '2.0', 6: '5.1', 8: '7.1'}.get(channels, f'{channels}ch')

    # Track name (if set)
    track_name = props.get('track_name', '')

    # Build the string
    parts = [f"Track {index}: {lang}"]
    parts.append(f"{codec_name} {channel_str}")
    if track_name:
        parts.append(f"'{track_name}'")

    return ", ".join(parts)


def _should_use_source_separated_mode(source_key: str, config: Dict, source_settings: Dict[str, Dict[str, Any]]) -> bool:
    """
    Check if this source should use source separation during correlation.

    Uses per-source settings from the job layout. Source separation is only applied
    when explicitly enabled for the specific source via use_source_separation flag.

    Args:
        source_key: The source being analyzed (e.g., "Source 2", "Source 3")
        config: Configuration dictionary (for separation mode/model settings)
        source_settings: Per-source correlation settings from job layout

    Returns:
        True if source separation should be applied to this comparison, False otherwise
    """
    # Check if source separation is configured at all (mode must be set)
    separation_mode = config.get('source_separation_mode', 'none')
    if separation_mode == 'none':
        return False

    # Check per-source setting - source separation must be explicitly enabled per-source
    per_source = source_settings.get(source_key, {})
    return per_source.get('use_source_separation', False)

def _find_first_stable_segment_delay(results: List[Dict[str, Any]], runner: CommandRunner, config: Dict, return_raw: bool = False) -> Optional[int | float]:
    """
    Find the delay from the first stable segment of chunks.

    This function identifies consecutive accepted chunks that share the same delay value
    and returns the delay from the first such stable group that meets stability criteria.

    Args:
        results: List of correlation results with 'delay', 'raw_delay', 'accepted', and 'start' keys
        runner: CommandRunner for logging
        config: Configuration dictionary with 'first_stable_min_chunks' and 'first_stable_skip_unstable'
        return_raw: If True, return the raw (unrounded) delay value

    Returns:
        The delay value from the first stable segment, or None if no stable segment found
    """
    min_chunks = int(config.get('first_stable_min_chunks', 3))
    skip_unstable = config.get('first_stable_skip_unstable', True)

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_chunks:
        return None

    # Group consecutive chunks with the same delay (within 1ms tolerance)
    # Track both rounded and raw delays for each segment
    segments = []
    current_segment = {
        'delay': accepted[0]['delay'],
        'raw_delays': [accepted[0].get('raw_delay', float(accepted[0]['delay']))],
        'count': 1,
        'start_time': accepted[0]['start']
    }

    for i in range(1, len(accepted)):
        if abs(accepted[i]['delay'] - current_segment['delay']) <= 1:
            # Same segment continues - accumulate raw delays for averaging
            current_segment['count'] += 1
            current_segment['raw_delays'].append(accepted[i].get('raw_delay', float(accepted[i]['delay'])))
        else:
            # New segment starts
            segments.append(current_segment)
            current_segment = {
                'delay': accepted[i]['delay'],
                'raw_delays': [accepted[i].get('raw_delay', float(accepted[i]['delay']))],
                'count': 1,
                'start_time': accepted[i]['start']
            }

    # Don't forget the last segment
    segments.append(current_segment)

    # Helper to get raw value from segment (average of all raw delays in segment)
    def get_segment_raw(segment):
        return sum(segment['raw_delays']) / len(segment['raw_delays'])

    # Find the first stable segment based on configuration
    if skip_unstable:
        # Skip segments that don't meet minimum chunk count
        for segment in segments:
            if segment['count'] >= min_chunks:
                raw_avg = get_segment_raw(segment)
                # CRITICAL: Round the raw average, don't use first chunk's delay!
                # segment['delay'] is just the first chunk's rounded value, which may differ
                # from the properly rounded average (e.g., raw avg -1001.825 should be -1002,
                # but first chunk might have been -1001)
                rounded_avg = round(raw_avg)
                runner._log_message(
                    f"[First Stable] Found stable segment: {segment['count']} chunks at {rounded_avg:+d}ms "
                    f"(raw avg: {raw_avg:.3f}ms, starting at {segment['start_time']:.1f}s)"
                )
                return raw_avg if return_raw else rounded_avg

        # No segment met the minimum chunk count
        runner._log_message(
            f"[First Stable] No segment found with minimum {min_chunks} chunks. "
            f"Largest segment: {max((s['count'] for s in segments), default=0)} chunks"
        )
        return None
    else:
        # Use the first segment regardless of chunk count
        if segments:
            first_segment = segments[0]
            raw_avg = get_segment_raw(first_segment)
            # CRITICAL: Round the raw average, don't use first chunk's delay!
            rounded_avg = round(raw_avg)
            if first_segment['count'] < min_chunks:
                runner._log_message(
                    f"[First Stable] Warning: First segment has only {first_segment['count']} chunks "
                    f"(minimum: {min_chunks}), but using it anyway (skip_unstable=False)"
                )
            runner._log_message(
                f"[First Stable] Using first segment: {first_segment['count']} chunks at {rounded_avg:+d}ms "
                f"(raw avg: {raw_avg:.3f}ms, starting at {first_segment['start_time']:.1f}s)"
            )
            return raw_avg if return_raw else rounded_avg

    return None

def _choose_final_delay(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Optional[int]:
    """
    Select final delay from correlation results using configured mode.
    Returns rounded integer for mkvmerge compatibility.
    """
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))
    delay_mode = config.get('delay_selection_mode', 'Mode (Most Common)')

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_accepted_chunks:
        runner._log_message(f"[ERROR] Analysis failed: Only {len(accepted)} chunks were accepted.")
        return None

    delays = [r['delay'] for r in accepted]
    raw_delays = [r.get('raw_delay', float(r['delay'])) for r in accepted]

    if delay_mode == 'First Stable':
        # Use proper stability detection to find first stable segment
        winner = _find_first_stable_segment_delay(results, runner, config, return_raw=False)
        if winner is None:
            # Fallback to mode if no stable segment found
            runner._log_message(f"[WARNING] No stable segment found, falling back to mode.")
            counts = Counter(delays)
            winner = counts.most_common(1)[0][0]
            method_label = "mode (fallback)"
        else:
            method_label = "first stable"
    elif delay_mode == 'Average':
        # Average the RAW float values, then round once at the end
        raw_avg = sum(raw_delays) / len(raw_delays)
        winner = round(raw_avg)
        runner._log_message(f"[Delay Selection] Average of {len(raw_delays)} raw values: {raw_avg:.3f}ms → rounded to {winner}ms")
        method_label = "average"
    elif delay_mode == 'Mode (Clustered)':
        # Find most common rounded delay, then include chunks within ±1ms tolerance
        counts = Counter(delays)
        mode_winner = counts.most_common(1)[0][0]

        # Collect raw values from chunks within ±1ms of the mode
        cluster_raw_values = []
        cluster_delays = []
        for r in accepted:
            if abs(r['delay'] - mode_winner) <= 1:
                cluster_raw_values.append(r.get('raw_delay', float(r['delay'])))
                cluster_delays.append(r['delay'])

        # Average the clustered raw values
        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            winner = round(raw_avg)
            cluster_counts = Counter(cluster_delays)
            runner._log_message(
                f"[Delay Selection] Mode (Clustered): most common = {mode_winner}ms, "
                f"cluster [{mode_winner-1} to {mode_winner+1}] contains {len(cluster_raw_values)}/{len(accepted)} chunks "
                f"(breakdown: {dict(cluster_counts)}), raw avg: {raw_avg:.3f}ms → rounded to {winner}ms"
            )
            method_label = "mode (clustered)"
        else:
            # Fallback to simple mode if clustering fails
            winner = mode_winner
            runner._log_message(f"[Delay Selection] Mode (Clustered): fallback to simple mode = {winner}ms")
            method_label = "mode (clustered fallback)"
    elif delay_mode == 'Mode (Early Cluster)':
        # Find clusters using ±1ms tolerance, prioritizing early stability
        early_window = int(config.get('early_cluster_window', 10))
        early_threshold = int(config.get('early_cluster_threshold', 5))

        # Build clusters: group delays within ±1ms of each other
        counts = Counter(delays)
        cluster_info = {}  # key: representative delay, value: {raw_values, early_count, first_chunk_idx}

        for delay_val in counts.keys():
            # Collect all chunks within ±1ms of this delay value
            cluster_raw_values = []
            early_count = 0
            first_chunk_idx = None

            for idx, r in enumerate(accepted):
                if abs(r['delay'] - delay_val) <= 1:
                    cluster_raw_values.append(r.get('raw_delay', float(r['delay'])))
                    if idx < early_window:
                        early_count += 1
                    if first_chunk_idx is None:
                        first_chunk_idx = idx

            cluster_info[delay_val] = {
                'raw_values': cluster_raw_values,
                'early_count': early_count,
                'first_chunk_idx': first_chunk_idx,
                'total_count': len(cluster_raw_values)
            }

        # Find early stable clusters (meet threshold in early window)
        early_stable_clusters = [
            (delay_val, info) for delay_val, info in cluster_info.items()
            if info['early_count'] >= early_threshold
        ]

        if early_stable_clusters:
            # Pick the cluster that appears earliest
            early_stable_clusters.sort(key=lambda x: x[1]['first_chunk_idx'])
            winner_delay, winner_info = early_stable_clusters[0]

            # Average the raw values in this cluster
            raw_avg = sum(winner_info['raw_values']) / len(winner_info['raw_values'])
            winner = round(raw_avg)

            runner._log_message(
                f"[Delay Selection] Mode (Early Cluster): found {len(early_stable_clusters)} early stable cluster(s), "
                f"selected cluster at {winner}ms with {winner_info['early_count']}/{early_window} early chunks, "
                f"total {winner_info['total_count']} chunks, first appears at chunk {winner_info['first_chunk_idx']+1}, "
                f"raw avg: {raw_avg:.3f}ms → rounded to {winner}ms"
            )
            method_label = "mode (early cluster)"
        else:
            # No cluster meets early threshold - fall back to Mode (Clustered)
            mode_winner = counts.most_common(1)[0][0]
            cluster_raw_values = [
                r.get('raw_delay', float(r['delay']))
                for r in accepted
                if abs(r['delay'] - mode_winner) <= 1
            ]

            if cluster_raw_values:
                raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
                winner = round(raw_avg)
                runner._log_message(
                    f"[Delay Selection] Mode (Early Cluster): no cluster met early threshold ({early_threshold} in first {early_window}), "
                    f"falling back to Mode (Clustered): {winner}ms (raw avg: {raw_avg:.3f}ms)"
                )
                method_label = "mode (early cluster - clustered fallback)"
            else:
                winner = mode_winner
                runner._log_message(
                    f"[Delay Selection] Mode (Early Cluster): fallback to simple mode = {winner}ms"
                )
                method_label = "mode (early cluster - simple fallback)"
    else:  # Mode (Most Common) - default
        counts = Counter(delays)
        winner = counts.most_common(1)[0][0]
        method_label = "mode"

    runner._log_message(f"{role_tag.capitalize()} delay determined: {winner:+d} ms ({method_label}).")
    return winner


def _choose_final_delay_raw(results: List[Dict[str, Any]], config: Dict, runner: CommandRunner, role_tag: str) -> Optional[float]:
    """
    Select final delay from correlation results, returning raw float value.
    Used for subtitle sync modes that need precision (defers rounding to final application).

    For each mode:
    - First Stable: Returns average of raw delays in the stable segment
    - Average: Returns true average of all raw delays (no intermediate rounding)
    - Mode: Returns raw delay from the first chunk matching the most common rounded value
    """
    min_accepted_chunks = int(config.get('min_accepted_chunks', 3))
    delay_mode = config.get('delay_selection_mode', 'Mode (Most Common)')

    accepted = [r for r in results if r.get('accepted', False)]
    if len(accepted) < min_accepted_chunks:
        return None

    delays = [r['delay'] for r in accepted]
    raw_delays = [r.get('raw_delay', float(r['delay'])) for r in accepted]

    if delay_mode == 'First Stable':
        # Get raw average from first stable segment
        winner_raw = _find_first_stable_segment_delay(results, runner, config, return_raw=True)
        if winner_raw is None:
            # Fallback to mode - find raw value for most common rounded delay
            counts = Counter(delays)
            winner_rounded = counts.most_common(1)[0][0]
            for r in accepted:
                if r.get('delay') == winner_rounded:
                    return r.get('raw_delay', float(winner_rounded))
            return float(winner_rounded)
        return winner_raw

    elif delay_mode == 'Average':
        # True average of raw floats - NO intermediate rounding!
        raw_avg = sum(raw_delays) / len(raw_delays)
        runner._log_message(f"[Delay Selection Raw] True average of {len(raw_delays)} raw values: {raw_avg:.3f}ms")
        return raw_avg

    elif delay_mode == 'Mode (Clustered)':
        # Find most common rounded delay, then include chunks within ±1ms tolerance
        counts = Counter(delays)
        mode_winner = counts.most_common(1)[0][0]

        # Collect raw values from chunks within ±1ms of the mode
        cluster_raw_values = [
            r.get('raw_delay', float(r['delay']))
            for r in accepted
            if abs(r['delay'] - mode_winner) <= 1
        ]

        # Average the clustered raw values
        if cluster_raw_values:
            raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
            runner._log_message(f"[Delay Selection Raw] Mode (Clustered): {len(cluster_raw_values)} chunks in cluster, raw avg: {raw_avg:.3f}ms")
            return raw_avg
        else:
            # Fallback to simple mode
            return float(mode_winner)

    elif delay_mode == 'Mode (Early Cluster)':
        # Find clusters using ±1ms tolerance, prioritizing early stability
        early_window = int(config.get('early_cluster_window', 10))
        early_threshold = int(config.get('early_cluster_threshold', 5))

        # Build clusters: group delays within ±1ms of each other
        counts = Counter(delays)
        cluster_info = {}  # key: representative delay, value: {raw_values, early_count, first_chunk_idx}

        for delay_val in counts.keys():
            # Collect all chunks within ±1ms of this delay value
            cluster_raw_values = []
            early_count = 0
            first_chunk_idx = None

            for idx, r in enumerate(accepted):
                if abs(r['delay'] - delay_val) <= 1:
                    cluster_raw_values.append(r.get('raw_delay', float(r['delay'])))
                    if idx < early_window:
                        early_count += 1
                    if first_chunk_idx is None:
                        first_chunk_idx = idx

            cluster_info[delay_val] = {
                'raw_values': cluster_raw_values,
                'early_count': early_count,
                'first_chunk_idx': first_chunk_idx,
                'total_count': len(cluster_raw_values)
            }

        # Find early stable clusters (meet threshold in early window)
        early_stable_clusters = [
            (delay_val, info) for delay_val, info in cluster_info.items()
            if info['early_count'] >= early_threshold
        ]

        if early_stable_clusters:
            # Pick the cluster that appears earliest
            early_stable_clusters.sort(key=lambda x: x[1]['first_chunk_idx'])
            winner_delay, winner_info = early_stable_clusters[0]

            # Average the raw values in this cluster
            raw_avg = sum(winner_info['raw_values']) / len(winner_info['raw_values'])

            runner._log_message(
                f"[Delay Selection Raw] Mode (Early Cluster): selected cluster with {winner_info['early_count']}/{early_window} early chunks, "
                f"total {winner_info['total_count']} chunks, raw avg: {raw_avg:.3f}ms"
            )
            return raw_avg
        else:
            # No cluster meets early threshold - fall back to Mode (Clustered)
            mode_winner = counts.most_common(1)[0][0]
            cluster_raw_values = [
                r.get('raw_delay', float(r['delay']))
                for r in accepted
                if abs(r['delay'] - mode_winner) <= 1
            ]

            if cluster_raw_values:
                raw_avg = sum(cluster_raw_values) / len(cluster_raw_values)
                runner._log_message(
                    f"[Delay Selection Raw] Mode (Early Cluster): no cluster met early threshold, "
                    f"falling back to Mode (Clustered): {len(cluster_raw_values)} chunks, raw avg: {raw_avg:.3f}ms"
                )
                return raw_avg
            else:
                runner._log_message(f"[Delay Selection Raw] Mode (Early Cluster): fallback to simple mode")
                return float(mode_winner)

    else:  # Mode (Most Common) - default
        # Average raw values from all chunks matching the most common rounded delay
        counts = Counter(delays)
        winner_rounded = counts.most_common(1)[0][0]
        matching_raw_values = [
            r.get('raw_delay', float(winner_rounded))
            for r in accepted
            if r.get('delay') == winner_rounded
        ]
        if matching_raw_values:
            return sum(matching_raw_values) / len(matching_raw_values)
        return float(winner_rounded)


class AnalysisStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for analysis.")

        # --- Part 1: Determine if a global shift is required ---
        config = ctx.settings_dict
        sync_mode = config.get('sync_mode', 'positive_only')

        # Check if there are audio tracks from secondary sources
        has_secondary_audio = any(
            t.get('type') == 'audio' and t.get('source') != 'Source 1'
            for t in ctx.manual_layout
        )

        # Store sync mode in context for auditor
        ctx.sync_mode = sync_mode

        # Determine if global shift should be applied based on sync mode
        runner._log_message("=" * 60)
        runner._log_message(f"=== TIMING SYNC MODE: {sync_mode.upper()} ===")
        runner._log_message("=" * 60)

        if sync_mode == 'allow_negative':
            # Mode 2: Force allow negatives even with secondary audio
            ctx.global_shift_is_required = False
            runner._log_message(f"[SYNC MODE] Negative delays are ALLOWED (no global shift).")
            runner._log_message(f"[SYNC MODE] Source 1 remains reference (delay = 0).")
            runner._log_message(f"[SYNC MODE] Secondary sources can have negative delays.")
        elif sync_mode == 'positive_only':
            # Mode 1: Default behavior - only apply global shift if secondary audio exists
            ctx.global_shift_is_required = has_secondary_audio
            if ctx.global_shift_is_required:
                runner._log_message(f"[SYNC MODE] Positive-only mode - global shift will eliminate negative delays.")
                runner._log_message(f"[SYNC MODE] All tracks will be shifted to be non-negative.")
            else:
                runner._log_message(f"[SYNC MODE] Positive-only mode (but no secondary audio detected).")
                runner._log_message(f"[SYNC MODE] Global shift will not be applied (subtitle-only exception).")
        else:
            # Unknown mode - fallback to default (positive_only)
            runner._log_message(f"[WARNING] Unknown sync_mode '{sync_mode}', falling back to 'positive_only'.")
            ctx.global_shift_is_required = has_secondary_audio

        # NEW: Skip analysis if only Source 1 (remux-only mode)
        if len(ctx.sources) == 1:
            runner._log_message("--- Analysis Phase: Skipped (Remux-only mode - no sync sources) ---")
            ctx.delays = Delays(source_delays_ms={}, raw_source_delays_ms={}, global_shift_ms=0, raw_global_shift_ms=0.0)
            return ctx

        source_delays: Dict[str, int] = {}
        raw_source_delays: Dict[str, float] = {}  # Unrounded delays for VideoTimestamps precision

        # --- Step 1: Get Source 1's container delays for chain calculation ---
        runner._log_message("--- Getting Source 1 Container Delays for Analysis ---")
        source1_info = get_stream_info_with_delays(source1_file, runner, ctx.tool_paths)
        source1_container_delays = {}

        if source1_info:
            for track in source1_info.get('tracks', []):
                tid = track.get('id')
                delay_ms = track.get('container_delay_ms', 0)
                source1_container_delays[tid] = delay_ms

                track_type = track.get('type')
                if delay_ms != 0 and track_type in ['video', 'audio']:
                    runner._log_message(f"[Container Delay] Source 1 {track_type} track {tid} has container delay: {delay_ms:+.1f}ms")

        # Find which audio track from Source 1 will be used for correlation
        source1_audio_track_id = None
        source1_audio_container_delay = 0
        source1_video_container_delay = 0

        ref_lang = config.get('analysis_lang_source1')
        if source1_info:
            # Get video track delay first
            video_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'video']
            if video_tracks:
                video_track_id = video_tracks[0].get('id')
                source1_video_container_delay = source1_container_delays.get(video_track_id, 0)

            # CRITICAL FIX: Convert ALL Source 1 audio tracks to relative delays
            # This ensures they're stored correctly for later use in extraction/mux
            for track in source1_info.get('tracks', []):
                if track.get('type') == 'audio':
                    tid = track.get('id')
                    absolute_delay = source1_container_delays.get(tid, 0)
                    relative_delay = absolute_delay - source1_video_container_delay
                    source1_container_delays[tid] = relative_delay  # Update with relative delay

            audio_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'audio']

            # Log Source 1 track selection for clarity
            source1_selected_index = None
            if ref_lang:
                for idx, track in enumerate(audio_tracks):
                    if (track.get('properties', {}).get('language', '') or '').strip().lower() == ref_lang:
                        source1_audio_track_id = track.get('id')
                        source1_selected_index = idx
                        runner._log_message(f"[Source 1] Selected (lang={ref_lang}): {_format_track_details(track, idx)}")
                        break

            if source1_audio_track_id is None and audio_tracks:
                source1_audio_track_id = audio_tracks[0].get('id')
                source1_selected_index = 0
                runner._log_message(f"[Source 1] Selected (first track): {_format_track_details(audio_tracks[0], 0)}")

            if source1_audio_track_id is not None:
                # Now get the relative delay (already corrected in the dict)
                source1_audio_container_delay = source1_container_delays.get(source1_audio_track_id, 0)
                ctx.source1_audio_container_delay_ms = source1_audio_container_delay

                if source1_audio_container_delay != 0:
                    runner._log_message(
                        f"[Container Delay] Audio track {source1_audio_track_id} relative delay (audio relative to video): "
                        f"{source1_audio_container_delay:+.1f}ms. "
                        f"This will be added to all correlation results."
                    )

        # --- Step 2: Run correlation for other sources ---
        runner._log_message("\n--- Running Audio Correlation Analysis ---")

        # Track which sources have stepping for final report
        stepping_sources = []

        for source_key, source_file in sorted(ctx.sources.items()):
            if source_key == "Source 1":
                continue

            runner._log_message(f"\n[Analyzing {source_key}]")

            # Get per-source settings for this source
            per_source_settings = ctx.source_settings.get(source_key, {})

            # Get explicit track index for this source (Source 2/3)
            correlation_source_track = per_source_settings.get('correlation_source_track')  # Which Source 2/3 track to use

            # Determine target language
            if correlation_source_track is not None:
                tgt_lang = None  # Bypassed by explicit track index
            else:
                # Fall back to global language setting for target
                tgt_lang = config.get('analysis_lang_others')

            # Get Source 1 track selection (can be per-job or global)
            # Check if Source 1 has per-job track selection configured
            source1_settings = ctx.source_settings.get('Source 1', {})
            correlation_ref_track = source1_settings.get('correlation_ref_track')  # Which Source 1 track to use
            if correlation_ref_track is not None and source1_info:
                source1_audio_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'audio']
                if 0 <= correlation_ref_track < len(source1_audio_tracks):
                    ref_track = source1_audio_tracks[correlation_ref_track]
                    runner._log_message(f"[Source 1] Selected (explicit): {_format_track_details(ref_track, correlation_ref_track)}")
                else:
                    runner._log_message(f"[Source 1] WARNING: Invalid track index {correlation_ref_track}, using previously selected track")

            # ===================================================================
            # CRITICAL DECISION POINT: Determine if source separation was applied
            # This decision affects correlation method and delay selection mode
            # Make this decision ONCE and create appropriate config for this source
            # ===================================================================
            use_source_separated_settings = _should_use_source_separated_mode(source_key, config, ctx.source_settings)

            if use_source_separated_settings:
                # Create config with source-separated overrides
                # Use dict spread to create new dict without modifying original
                source_config = {
                    **config,
                    'correlation_method': config.get('correlation_method_source_separated', 'Phase Correlation (GCC-PHAT)'),
                    'delay_selection_mode': config.get('delay_selection_mode_source_separated', 'Mode (Clustered)')
                }
                runner._log_message(f"[Analysis Config] Source separation enabled - using:")
                runner._log_message(f"  Correlation: {source_config['correlation_method']}")
                runner._log_message(f"  Delay Mode: {source_config['delay_selection_mode']}")
            else:
                # Use original config as-is (no source separation)
                source_config = config
                runner._log_message(f"[Analysis Config] Standard mode - using:")
                runner._log_message(f"  Correlation: {source_config.get('correlation_method', 'SCC (Sliding Cross-Correlation)')}")
                runner._log_message(f"  Delay Mode: {source_config.get('delay_selection_mode', 'Mode (Most Common)')}")

            stream_info = get_stream_info(source_file, runner, ctx.tool_paths)
            if not stream_info:
                runner._log_message(f"[WARN] Could not get stream info for {source_key}. Skipping.")
                continue

            audio_tracks = [t for t in stream_info.get('tracks', []) if t.get('type') == 'audio']
            target_track_obj = None
            if not audio_tracks:
                runner._log_message(f"[WARN] No audio tracks found in {source_key}. Skipping.")
                continue

            # Priority 1: Explicit track index from per-source settings
            if correlation_source_track is not None:
                if 0 <= correlation_source_track < len(audio_tracks):
                    target_track_obj = audio_tracks[correlation_source_track]
                    runner._log_message(f"[{source_key}] Selected (explicit): {_format_track_details(target_track_obj, correlation_source_track)}")
                else:
                    runner._log_message(f"[WARN] Invalid track index {correlation_source_track}, falling back to first track")
                    target_track_obj = audio_tracks[0]
                    # CRITICAL FIX: Also update correlation_source_track to match the fallback!
                    # Otherwise run_audio_correlation would receive the invalid index
                    correlation_source_track = 0
                    runner._log_message(f"[{source_key}] Selected (fallback): {_format_track_details(target_track_obj, 0)}")
            # Priority 2: Language matching
            elif tgt_lang:
                for idx, track in enumerate(audio_tracks):
                    if (track.get('properties', {}).get('language', '') or '').strip().lower() == tgt_lang:
                        target_track_obj = track
                        runner._log_message(f"[{source_key}] Selected (lang={tgt_lang}): {_format_track_details(track, idx)}")
                        break

            # Fallback: First track
            if not target_track_obj:
                target_track_obj = audio_tracks[0]
                runner._log_message(f"[{source_key}] Selected (first track): {_format_track_details(target_track_obj, 0)}")

            target_track_id = target_track_obj.get('id')
            target_codec_id = target_track_obj.get('properties', {}).get('codec_id', 'unknown')

            if target_track_id is None:
                runner._log_message(f"[WARN] No suitable audio track found in {source_key} for analysis. Skipping.")
                continue

            # Check if multi-correlation comparison is enabled (Analyze Only mode only)
            multi_corr_enabled = bool(source_config.get('multi_correlation_enabled', False)) and (not ctx.and_merge)

            if multi_corr_enabled:
                # Run multiple correlation methods for comparison
                # Returns dict mapping method names to their results
                # Note: Multi-correlation uses its own method selection (checkboxes), ignores correlation_method setting
                all_method_results = run_multi_correlation(
                    str(source1_file), str(source_file), source_config, runner, ctx.tool_paths,
                    ref_lang=source_config.get('analysis_lang_source1'),
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,  # Use per-job setting if configured
                    target_track_index=correlation_source_track,
                    use_source_separation=use_source_separated_settings
                )

                # Log summary for each method
                runner._log_message(f"\n{'═' * 70}")
                runner._log_message("  MULTI-CORRELATION SUMMARY")
                runner._log_message(f"{'═' * 70}")

                for method_name, method_results in all_method_results.items():
                    accepted = [r for r in method_results if r.get('accepted', False)]
                    if accepted:
                        delays = [r['delay'] for r in accepted]
                        raw_delays = [r['raw_delay'] for r in accepted]
                        mode_delay = Counter(delays).most_common(1)[0][0]
                        avg_match = sum(r['match'] for r in accepted) / len(accepted)
                        avg_raw = sum(raw_delays) / len(raw_delays)
                        runner._log_message(
                            f"  {method_name}: {mode_delay:+d}ms (raw avg: {avg_raw:+.3f}ms) | "
                            f"match: {avg_match:.1f}% | accepted: {len(accepted)}/{len(method_results)}"
                        )
                    else:
                        runner._log_message(f"  {method_name}: NO ACCEPTED CHUNKS")

                runner._log_message(f"{'═' * 70}\n")

                # Use the first method's results for actual processing
                # (or the dropdown method if we want to be smarter about this)
                first_method = list(all_method_results.keys())[0]
                results = all_method_results[first_method]
                runner._log_message(f"[MULTI-CORRELATION] Using '{first_method}' results for delay calculation")
            else:
                # Normal single-method correlation
                # Use source_config which already has the right correlation_method set
                results = run_audio_correlation(
                    str(source1_file), str(source_file), source_config, runner, ctx.tool_paths,
                    ref_lang=source_config.get('analysis_lang_source1'),
                    target_lang=tgt_lang,
                    role_tag=source_key,
                    ref_track_index=correlation_ref_track,  # Use per-job setting if configured
                    target_track_index=correlation_source_track,
                    use_source_separation=use_source_separated_settings
                )

            # --- CRITICAL FIX: Detect stepping BEFORE calculating mode delay ---
            diagnosis = None
            details = {}
            stepping_override_delay = None
            stepping_override_delay_raw = None
            stepping_enabled = source_config.get('segmented_enabled', False)

            # ALWAYS run diagnosis to detect stepping (even if correction is disabled)
            diagnosis, details = diagnose_audio_issue(
                video_path=source1_file,
                chunks=results,
                config=source_config,
                runner=runner,
                tool_paths=ctx.tool_paths,
                codec_id=target_codec_id
            )

            # If stepping detected, handle based on whether correction is enabled
            if diagnosis == "STEPPING":
                # CRITICAL: Stepping correction doesn't work on source-separated audio
                # Separated stems have fundamentally different waveform characteristics
                if stepping_enabled and not use_source_separated_settings:
                    # Stepping correction is ENABLED - proceed with correction logic
                    stepping_sources.append(source_key)  # Track for final report

                    # Check if any audio tracks from this source are being merged
                    has_audio_from_source = any(
                        t.get('type') == 'audio' and t.get('source') == source_key
                        for t in ctx.manual_layout
                    )

                    if has_audio_from_source:
                        # Stepping correction will run, so use first segment delay
                        # Use stepping-specific stability criteria (separate from First Stable delay selection mode)
                        stepping_config = {
                            'first_stable_min_chunks': source_config.get('stepping_first_stable_min_chunks', 3),
                            'first_stable_skip_unstable': source_config.get('stepping_first_stable_skip_unstable', True)
                        }
                        # Get both rounded (for mkvmerge) and raw (for subtitle precision)
                        first_segment_delay = _find_first_stable_segment_delay(results, runner, stepping_config, return_raw=False)
                        first_segment_delay_raw = _find_first_stable_segment_delay(results, runner, stepping_config, return_raw=True)
                        if first_segment_delay is not None:
                            stepping_override_delay = first_segment_delay
                            stepping_override_delay_raw = first_segment_delay_raw
                            runner._log_message(f"[Stepping Detected] Found stepping in {source_key}")
                            runner._log_message(f"[Stepping Override] Using first segment's delay: {stepping_override_delay:+d}ms (raw: {stepping_override_delay_raw:.3f}ms)")
                            runner._log_message(f"[Stepping Override] This delay will be used for ALL tracks (audio + subtitles) from {source_key}")
                            runner._log_message(f"[Stepping Override] Stepping correction will be applied to audio tracks during processing")
                    else:
                        # No audio tracks from this source - stepping correction won't run
                        # Use normal delay selection mode instead
                        delay_mode = source_config.get('delay_selection_mode', 'Mode (Most Common)')
                        runner._log_message(f"[Stepping Detected] Found stepping in {source_key}")
                        runner._log_message(f"[Stepping] No audio tracks from this source are being merged")
                        runner._log_message(f"[Stepping] Using delay_selection_mode='{delay_mode}' instead of first segment (stepping correction won't run)")
                        # Don't set stepping_override_delay - let normal flow handle it
                elif use_source_separated_settings:
                    # Source separation blocks stepping correction (unreliable on separated stems)
                    # Track for audit warning - user should manually review this file
                    ctx.stepping_detected_separated.append(source_key)
                    delay_mode = source_config.get('delay_selection_mode', 'Mode (Clustered)')
                    runner._log_message(f"[Stepping Detected] Found stepping in {source_key}")
                    runner._log_message(f"[Stepping Disabled] Source separation is enabled - stepping correction is unreliable on separated stems")
                    runner._log_message(f"[Stepping Disabled] Separated stems have different waveform characteristics that break stepping detection")
                    runner._log_message(f"[Stepping Disabled] Using delay_selection_mode='{delay_mode}' instead")
                    # Don't set stepping_override_delay - let normal flow handle it with source-separated delay mode
                else:
                    # Stepping correction is DISABLED globally - just warn the user
                    ctx.stepping_detected_disabled.append(source_key)  # Track for warning
                    runner._log_message(f"⚠️  [Stepping Detected] Found stepping in {source_key}")
                    runner._log_message(f"⚠️  [Stepping Disabled] Stepping correction is disabled - timing may be inconsistent")
                    runner._log_message(f"⚠️  [Recommendation] Enable 'Stepping Correction' in settings if you want automatic correction")
                    runner._log_message(f"⚠️  [Manual Review] You should manually review this file's sync quality")
                    # Use normal delay selection mode
                    # Don't set stepping_override_delay - let normal flow handle it

            # Use stepping override if available, otherwise calculate using configured mode
            # Get both rounded (for mkvmerge/audio) and raw (for subtitle sync precision)
            if stepping_override_delay is not None:
                correlation_delay_ms = stepping_override_delay
                correlation_delay_raw = stepping_override_delay_raw  # Use true raw, not float(int)
                runner._log_message(f"{source_key.capitalize()} delay determined: {correlation_delay_ms:+d} ms (first segment, stepping corrected).")
            else:
                # Use source_config which already has the right delay_selection_mode set
                correlation_delay_ms = _choose_final_delay(results, source_config, runner, source_key)
                correlation_delay_raw = _choose_final_delay_raw(results, source_config, runner, source_key)

                if correlation_delay_ms is None:
                    # ENHANCED ERROR MESSAGE
                    accepted_count = len([r for r in results if r.get('accepted', False)])
                    min_required = source_config.get('min_accepted_chunks', 3)
                    total_chunks = len(results)

                    raise RuntimeError(
                        f'Analysis failed for {source_key}: Could not determine a reliable delay.\n'
                        f'  - Accepted chunks: {accepted_count}\n'
                        f'  - Minimum required: {min_required}\n'
                        f'  - Total chunks scanned: {total_chunks}\n'
                        f'  - Match threshold: {source_config.get("min_match_pct", 5.0)}%\n'
                        f'\n'
                        f'Possible causes:\n'
                        f'  - Audio quality is too poor for reliable correlation\n'
                        f'  - Audio tracks are not from the same source material\n'
                        f'  - Excessive noise or compression artifacts\n'
                        f'  - Wrong language tracks selected for analysis\n'
                        f'\n'
                        f'Solutions:\n'
                        f'  - Try lowering the "Minimum Match %" threshold in settings\n'
                        f'  - Increase "Chunk Count" for more sample points\n'
                        f'  - Try selecting different audio tracks (check language settings)\n'
                        f'  - Use VideoDiff mode instead of Audio Correlation\n'
                        f'  - Check that both files are from the same video source'
                    )

            # --- Sync Stability Analysis ---
            # Check for variance in correlation results that may indicate sync issues
            # Pass stepping cluster info if available to avoid false positives
            stepping_clusters = None
            if diagnosis == "STEPPING" and details:
                stepping_clusters = details.get('cluster_info', [])

            stability_result = analyze_sync_stability(
                chunk_results=results,
                source_key=source_key,
                config=source_config,
                log=runner._log_message,
                stepping_clusters=stepping_clusters
            )

            if stability_result and stability_result.get('variance_detected'):
                ctx.sync_stability_issues.append(stability_result)

            # Calculate final delay including container delay chain correction
            # CRITICAL: Use the container delay from the ACTUAL Source 1 track used for correlation
            actual_container_delay = source1_audio_container_delay

            # Try to determine which Source 1 track was actually used for correlation
            # This is needed when Source 1 has multiple audio tracks with different container delays
            if source1_info:
                source1_audio_tracks = [t for t in source1_info.get('tracks', []) if t.get('type') == 'audio']

                # Priority 1: Explicit per-job track selection
                if correlation_ref_track is not None and 0 <= correlation_ref_track < len(source1_audio_tracks):
                    ref_track_id = source1_audio_tracks[correlation_ref_track].get('id')
                    track_container_delay = source1_container_delays.get(ref_track_id, 0)
                    if track_container_delay != source1_audio_container_delay:
                        actual_container_delay = track_container_delay
                        runner._log_message(
                            f"[Container Delay Override] Using Source 1 audio index {correlation_ref_track} (track ID {ref_track_id}) delay: "
                            f"{actual_container_delay:+.3f}ms (global reference was {source1_audio_container_delay:+.3f}ms)"
                        )
                # Priority 2: Language matching fallback
                elif source_config.get('analysis_lang_source1'):
                    ref_lang = source_config.get('analysis_lang_source1')
                    for i, track in enumerate(source1_audio_tracks):
                        track_lang = (track.get('properties', {}).get('language', '') or '').strip().lower()
                        if track_lang == ref_lang.strip().lower():
                            ref_track_id = track.get('id')
                            track_container_delay = source1_container_delays.get(ref_track_id, 0)
                            if track_container_delay != source1_audio_container_delay:
                                actual_container_delay = track_container_delay
                                runner._log_message(
                                    f"[Container Delay Override] Using Source 1 audio index {i} (track ID {ref_track_id}, lang={ref_lang}) delay: "
                                    f"{actual_container_delay:+.3f}ms (global reference was {source1_audio_container_delay:+.3f}ms)"
                                )
                            break

            # Store both rounded (for mkvmerge) and raw (for subtitle sync precision)
            final_delay_ms = round(correlation_delay_ms + actual_container_delay)
            final_delay_raw = correlation_delay_raw + actual_container_delay

            # Log the delay calculation chain for transparency
            runner._log_message(f"[Delay Calculation] {source_key} delay chain:")
            runner._log_message(f"[Delay Calculation]   Correlation delay: {correlation_delay_raw:+.3f}ms (raw) → {correlation_delay_ms:+d}ms (rounded)")
            if actual_container_delay != 0:
                runner._log_message(f"[Delay Calculation]   + Container delay:  {actual_container_delay:+.3f}ms")
                runner._log_message(f"[Delay Calculation]   = Final delay:      {final_delay_raw:+.3f}ms (raw) → {final_delay_ms:+d}ms (rounded)")

            source_delays[source_key] = final_delay_ms
            raw_source_delays[source_key] = final_delay_raw

            # --- Handle drift detection flags ---
            # CRITICAL: Drift/stepping corrections are NOT compatible with source separation
            # The separated stems have different waveform characteristics that make
            # precise timing corrections unreliable
            if diagnosis:
                analysis_track_key = f"{source_key}_{target_track_id}"

                if diagnosis == "PAL_DRIFT":
                    # Block PAL drift correction when source separation is enabled
                    if use_source_separated_settings:
                        runner._log_message(
                            f"[PAL Drift Detected] PAL drift detected in {source_key}, but source separation "
                            f"is enabled. PAL correction is unreliable on separated stems - skipping."
                        )
                    else:
                        source_has_audio_in_layout = any(
                            item.get('source') == source_key and item.get('type') == 'audio'
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            ctx.pal_drift_flags[analysis_track_key] = details
                        else:
                            runner._log_message(
                                f"[PAL Drift Detected] PAL drift detected in {source_key}, but no audio tracks "
                                f"from this source are being used. Skipping PAL correction for {source_key}."
                            )

                elif diagnosis == "LINEAR_DRIFT":
                    # Block linear drift correction when source separation is enabled
                    if use_source_separated_settings:
                        runner._log_message(
                            f"[Linear Drift Detected] Linear drift detected in {source_key}, but source separation "
                            f"is enabled. Linear drift correction is unreliable on separated stems - skipping."
                        )
                    else:
                        source_has_audio_in_layout = any(
                            item.get('source') == source_key and item.get('type') == 'audio'
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            ctx.linear_drift_flags[analysis_track_key] = details
                        else:
                            runner._log_message(
                                f"[Linear Drift Detected] Linear drift detected in {source_key}, but no audio tracks "
                                f"from this source are being used. Skipping linear drift correction for {source_key}."
                            )

                elif diagnosis == "STEPPING":
                    # Block stepping correction when source separation is enabled
                    # (Already handled earlier in the stepping detection block, but also skip flag storage)
                    if use_source_separated_settings:
                        # Already logged above, just skip storing flags
                        pass
                    else:
                        source_has_audio_in_layout = any(
                            item.get('source') == source_key and item.get('type') == 'audio'
                            for item in ctx.manual_layout
                        )
                        source_has_subs_in_layout = any(
                            item.get('source') == source_key and item.get('type') == 'subtitles'
                            for item in ctx.manual_layout
                        )

                        if source_has_audio_in_layout:
                            # Store stepping correction info with the corrected delay and cluster diagnostics
                            ctx.segment_flags[analysis_track_key] = {
                                'base_delay': final_delay_ms,
                                'cluster_details': details.get('cluster_details', []),
                                'valid_clusters': details.get('valid_clusters', {}),
                                'invalid_clusters': details.get('invalid_clusters', {}),
                                'validation_results': details.get('validation_results', {}),
                                'correction_mode': details.get('correction_mode', 'full'),
                                'fallback_mode': details.get('fallback_mode', 'nearest'),
                                'subs_only': False
                            }
                            runner._log_message(
                                f"[Stepping] Stepping correction will be applied to audio tracks from {source_key}."
                            )
                        elif source_has_subs_in_layout and config.get('stepping_adjust_subtitles_no_audio', True):
                            # No audio but subs exist - run full stepping correction to get verified EDL
                            runner._log_message(
                                f"[Stepping Detected] Stepping detected in {source_key}. No audio tracks "
                                f"from this source, but subtitles will use verified stepping EDL."
                            )
                            # Set segment_flags so stepping correction step runs full analysis
                            ctx.segment_flags[analysis_track_key] = {
                                'base_delay': final_delay_ms,
                                'cluster_details': details.get('cluster_details', []),
                                'valid_clusters': details.get('valid_clusters', {}),
                                'invalid_clusters': details.get('invalid_clusters', {}),
                                'validation_results': details.get('validation_results', {}),
                                'correction_mode': details.get('correction_mode', 'full'),
                                'fallback_mode': details.get('fallback_mode', 'nearest'),
                                'subs_only': True  # Flag to indicate no audio application needed
                            }
                            runner._log_message(
                                f"[Stepping] Full stepping analysis will run for verified subtitle EDL."
                            )
                        else:
                            # No audio and no subs (or setting disabled)
                            runner._log_message(
                                f"[Stepping Detected] Stepping detected in {source_key}, but no audio or subtitle tracks "
                                f"from this source are being used. Skipping stepping correction."
                            )

        # Store stepping sources in context for final report
        ctx.stepping_sources = stepping_sources

        # Initialize Source 1 with 0ms base delay so it gets the global shift
        source_delays["Source 1"] = 0
        raw_source_delays["Source 1"] = 0.0

        # --- Step 3: Calculate Global Shift to Handle Negative Delays ---
        runner._log_message("\n--- Calculating Global Shift ---")

        delays_to_consider = []
        raw_delays_to_consider = []  # For VideoTimestamps precision
        if ctx.global_shift_is_required:
            runner._log_message("[Global Shift] Identifying delays from sources contributing audio tracks...")
            for item in ctx.manual_layout:
                item_source = item.get('source')
                item_type = item.get('type')
                if item_type == 'audio':
                    if item_source in source_delays and source_delays[item_source] not in delays_to_consider:
                        delays_to_consider.append(source_delays[item_source])
                        raw_delays_to_consider.append(raw_source_delays[item_source])
                        runner._log_message(f"  - Considering delay from {item_source}: {source_delays[item_source]}ms")

            if source1_container_delays and source1_info:
                audio_container_delays = []
                for track in source1_info.get('tracks', []):
                    if track.get('type') == 'audio':
                        tid = track.get('id')
                        delay = source1_container_delays.get(tid, 0)
                        if delay != 0:
                            audio_container_delays.append(delay)

                if audio_container_delays:
                    delays_to_consider.extend(audio_container_delays)
                    runner._log_message("  - Considering Source 1 audio container delays (video delays ignored).")

        most_negative = min(delays_to_consider) if delays_to_consider else 0
        most_negative_raw = min(raw_delays_to_consider) if raw_delays_to_consider else 0.0
        global_shift_ms = 0
        raw_global_shift_ms = 0.0

        if most_negative < 0:
            # Rounded global shift for mkvmerge/audio sync (existing behavior)
            global_shift_ms = abs(most_negative)
            # Raw global shift for VideoTimestamps precision (prevents triple rounding)
            raw_global_shift_ms = abs(most_negative_raw)

            runner._log_message(f"[Delay] Most negative relevant delay: {most_negative}ms (rounded), {most_negative_raw:.3f}ms (raw)")
            runner._log_message(f"[Delay] Applying lossless global shift: +{global_shift_ms}ms (rounded), +{raw_global_shift_ms:.3f}ms (raw)")
            runner._log_message(f"[Delay] Adjusted delays after global shift:")
            for source_key in sorted(source_delays.keys()):
                original_delay = source_delays[source_key]
                original_raw_delay = raw_source_delays[source_key]
                source_delays[source_key] += global_shift_ms
                raw_source_delays[source_key] += raw_global_shift_ms
                runner._log_message(f"  - {source_key}: {original_delay:+.1f}ms → {source_delays[source_key]:+.1f}ms (rounded: {original_raw_delay:+.3f}ms → {raw_source_delays[source_key]:+.3f}ms raw)")

            if source1_container_delays:
                runner._log_message(f"[Delay] Source 1 container delays (will have +{global_shift_ms}ms added during mux):")
                for track in source1_info.get('tracks', []):
                    if track.get('type') in ['audio', 'video']:
                        tid = track.get('id')
                        delay = source1_container_delays.get(tid, 0)
                        final_delay = delay + global_shift_ms
                        track_type = track.get('type')

                        note = " (will be ignored - video defines timeline)" if track_type == 'video' else ""
                        runner._log_message(f"  - Track {tid} ({track_type}): {delay:+.1f}ms → {final_delay:+.1f}ms{note}")
        else:
            runner._log_message(f"[Delay] All relevant delays are non-negative. No global shift needed.")

        # Store the calculated delays with global shift
        ctx.delays = Delays(
            source_delays_ms=source_delays,
            raw_source_delays_ms=raw_source_delays,
            global_shift_ms=global_shift_ms,
            raw_global_shift_ms=raw_global_shift_ms
        )

        # Final summary
        runner._log_message(f"\n[Delay] === FINAL DELAYS (Sync Mode: {sync_mode.upper()}, Global Shift: +{global_shift_ms}ms) ===")
        for source_key, delay_ms in sorted(source_delays.items()):
            runner._log_message(f"  - {source_key}: {delay_ms:+d}ms")

        if sync_mode == 'allow_negative' and global_shift_ms == 0:
            runner._log_message(f"\n[INFO] Negative delays retained (allow_negative mode). Secondary sources may have negative delays.")
        elif global_shift_ms > 0:
            runner._log_message(f"\n[INFO] All delays shifted by +{global_shift_ms}ms to eliminate negatives.")

        return ctx
