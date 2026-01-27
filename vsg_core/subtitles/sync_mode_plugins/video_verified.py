# vsg_core/subtitles/sync_mode_plugins/video_verified.py
# -*- coding: utf-8 -*-
"""
Video-Verified sync plugin for SubtitleData.

This mode addresses the case where audio correlation detects a small offset
(typically 1 frame ~42ms) but subtitles are actually timed to VIDEO.

Problem scenario:
- Audio may be slightly offset from video in the source file
- Subtitles are authored to VIDEO timing, not audio
- Audio correlation finds -46ms (audio-to-audio offset)
- But video-to-video is actually 0ms
- For subtitles, we need the VIDEO offset (0ms), not audio offset (-46ms)

Solution:
1. Take the audio correlation result as a starting point
2. Use frame matching to find the TRUE video-to-video offset
3. If the video offset differs from audio correlation, trust video
4. Specifically checks if "zero offset" is actually correct when correlation
   detects a small sub-frame or single-frame offset

All timing is float ms internally - rounding happens only at final save.

This module also exports `calculate_video_verified_offset()` which can be used
independently to get the frame-corrected delay for any subtitle format,
including bitmap subtitles (VobSub, PGS) that can't be loaded into SubtitleData.
"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, TYPE_CHECKING

from ..sync_modes import SyncPlugin, register_sync_plugin

if TYPE_CHECKING:
    from ..data import SubtitleData, OperationResult, OperationRecord, SyncEventData


def calculate_video_verified_offset(
    source_video: str,
    target_video: str,
    total_delay_ms: float,
    global_shift_ms: float,
    config: Optional[Dict] = None,
    runner=None,
    temp_dir: Optional[Path] = None,
    video_duration_ms: Optional[float] = None,
) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    Calculate the video-verified offset using frame matching.

    This function performs the core frame matching logic to find the TRUE
    video-to-video offset, independent of any subtitle format. It can be
    used for both text-based and bitmap subtitles (VobSub, PGS).

    Args:
        source_video: Path to source video file
        target_video: Path to target video file (Source 1)
        total_delay_ms: Total delay from audio correlation (with global shift)
        global_shift_ms: Global shift component of the delay
        config: Settings dict with video-verified parameters
        runner: CommandRunner for logging
        temp_dir: Temp directory for frame cache
        video_duration_ms: Optional video duration (auto-detected if not provided)

    Returns:
        Tuple of (final_offset_ms, details_dict)
        - final_offset_ms: The frame-corrected offset including global shift,
          or None if frame matching failed/wasn't needed
        - details_dict: Contains 'reason', 'audio_correlation_ms', 'video_offset_ms',
          'candidates', etc.
    """
    from ..frame_utils import detect_video_fps, detect_video_properties

    config = config or {}

    def log(msg: str):
        if runner:
            runner._log_message(msg)

    log(f"[VideoVerified] === Frame Matching for Delay Correction ===")

    if not source_video or not target_video:
        return None, {'reason': 'missing-videos', 'error': 'Both source and target videos required'}

    # Calculate pure correlation (correlation only, without global shift)
    pure_correlation_ms = total_delay_ms - global_shift_ms

    log(f"[VideoVerified] Source: {Path(source_video).name}")
    log(f"[VideoVerified] Target: {Path(target_video).name}")
    log(f"[VideoVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
    log(f"[VideoVerified] Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

    # Detect FPS
    fps = detect_video_fps(source_video, runner)
    if not fps:
        fps = 23.976
        log(f"[VideoVerified] FPS detection failed, using default: {fps}")

    frame_duration_ms = 1000.0 / fps
    log(f"[VideoVerified] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

    # Get config parameters
    zero_check_threshold_frames = config.get('video_verified_zero_check_frames', 3)
    zero_check_threshold_ms = zero_check_threshold_frames * frame_duration_ms
    min_quality_advantage = config.get('video_verified_min_quality_advantage', 0.1)
    num_checkpoints = config.get('video_verified_num_checkpoints', 5)
    search_range_frames = config.get('video_verified_search_range_frames', 3)
    hash_algorithm = config.get('frame_hash_algorithm', 'dhash')
    hash_size = int(config.get('frame_hash_size', 8))
    hash_threshold = int(config.get('frame_hash_threshold', 5))
    window_radius = int(config.get('frame_window_radius', 5))
    comparison_method = config.get('frame_comparison_method', 'hash')

    log(f"[VideoVerified] Zero-check threshold: ±{zero_check_threshold_ms:.1f}ms ({zero_check_threshold_frames} frames)")
    log(f"[VideoVerified] Checkpoints: {num_checkpoints}, Search: ±{search_range_frames} frames")
    log(f"[VideoVerified] Comparison method: {comparison_method}")

    # Determine if we need zero-check (correlation is small enough to be suspicious)
    needs_zero_check = abs(pure_correlation_ms) <= zero_check_threshold_ms

    if not needs_zero_check:
        log(f"[VideoVerified] Correlation {pure_correlation_ms:+.3f}ms exceeds zero-check threshold")
        log(f"[VideoVerified] Using correlation as-is (large offset unlikely to be zero)")
        return total_delay_ms, {
            'reason': 'correlation-large',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
        }

    log(f"[VideoVerified] Small correlation detected - verifying against video...")

    # Try to import frame utilities
    try:
        from ..frame_utils import VideoReader, compute_frame_hash, compute_hamming_distance
    except ImportError as e:
        log(f"[VideoVerified] Frame utilities unavailable: {e}")
        log(f"[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            'reason': 'fallback-no-frame-utils',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
            'error': str(e),
        }

    # Get video duration for checkpoint selection
    source_duration = video_duration_ms
    if not source_duration or source_duration <= 0:
        try:
            props = detect_video_properties(source_video, runner)
            source_duration = props.get('duration_ms', 0)
            if source_duration <= 0:
                raise ValueError("Could not detect video duration")
        except Exception:
            source_duration = 1200000  # Default 20 minutes
            log(f"[VideoVerified] Could not detect duration, using default: {source_duration/1000:.1f}s")

    log(f"[VideoVerified] Source duration: ~{source_duration/1000:.1f}s")

    # Generate candidate offsets to test
    candidates = _generate_candidates_static(
        pure_correlation_ms, frame_duration_ms, search_range_frames
    )
    log(f"[VideoVerified] Candidates to test: {[f'{c:+.1f}ms' for c in candidates]}")

    # Open video readers with deinterlace support
    try:
        deinterlace_mode = config.get('frame_deinterlace_mode', 'auto')
        source_reader = VideoReader(
            source_video, runner, temp_dir=temp_dir,
            deinterlace=deinterlace_mode, config=config
        )
        target_reader = VideoReader(
            target_video, runner, temp_dir=temp_dir,
            deinterlace=deinterlace_mode, config=config
        )
    except Exception as e:
        log(f"[VideoVerified] Failed to open videos: {e}")
        log(f"[VideoVerified] Falling back to correlation")
        return total_delay_ms, {
            'reason': 'fallback-video-open-failed',
            'audio_correlation_ms': pure_correlation_ms,
            'video_offset_ms': pure_correlation_ms,
            'final_offset_ms': total_delay_ms,
            'error': str(e),
        }

    # Select checkpoint times (distributed across video)
    checkpoint_times = _select_checkpoint_times_static(source_duration, num_checkpoints)
    log(f"[VideoVerified] Checkpoint times: {[f'{t/1000:.1f}s' for t in checkpoint_times]}")

    # Test each candidate
    candidate_results = []

    for candidate_offset in candidates:
        quality = _measure_candidate_quality_static(
            candidate_offset, checkpoint_times, source_reader, target_reader,
            fps, frame_duration_ms, window_radius, hash_algorithm, hash_size,
            hash_threshold, comparison_method, log
        )
        candidate_results.append({
            'offset_ms': candidate_offset,
            'quality': quality['score'],
            'matched_checkpoints': quality['matched'],
            'avg_distance': quality['avg_distance'],
        })
        log(f"[VideoVerified]   Candidate {candidate_offset:+.1f}ms: "
            f"score={quality['score']:.2f}, matched={quality['matched']}/{len(checkpoint_times)}, "
            f"avg_dist={quality['avg_distance']:.1f}")

    # Close readers
    try:
        source_reader.close()
        target_reader.close()
    except Exception:
        pass

    # Select best candidate
    best_result = max(candidate_results, key=lambda r: r['quality'])
    best_offset = best_result['offset_ms']

    # Check if zero is competitive (within quality margin)
    zero_result = next((r for r in candidate_results if abs(r['offset_ms']) < 0.5), None)

    log(f"[VideoVerified] ───────────────────────────────────────")
    log(f"[VideoVerified] Best candidate: {best_offset:+.1f}ms (score={best_result['quality']:.2f})")

    selected_offset = best_offset
    selection_reason = 'best-match'

    if zero_result and abs(best_offset) > 0.5:
        # Best isn't zero - check if zero is close enough
        quality_diff = best_result['quality'] - zero_result['quality']
        log(f"[VideoVerified] Zero offset score: {zero_result['quality']:.2f} "
            f"(diff from best: {quality_diff:.2f})")

        if quality_diff <= min_quality_advantage:
            # Zero is competitive - prefer it (simpler is better)
            selected_offset = 0.0
            selection_reason = 'zero-preferred'
            log(f"[VideoVerified] Zero offset is competitive (within {min_quality_advantage} margin)")
            log(f"[VideoVerified] Selecting 0ms (simpler offset preferred)")
        else:
            log(f"[VideoVerified] Best candidate is significantly better than zero")

    # Calculate final offset
    final_offset_ms = selected_offset + global_shift_ms

    log(f"[VideoVerified] ───────────────────────────────────────")
    log(f"[VideoVerified] Selection: {selection_reason}")
    log(f"[VideoVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")
    log(f"[VideoVerified] Video-verified offset: {selected_offset:+.3f}ms")
    log(f"[VideoVerified] + Global shift: {global_shift_ms:+.3f}ms")
    log(f"[VideoVerified] = Final offset: {final_offset_ms:+.3f}ms")

    if abs(selected_offset - pure_correlation_ms) > frame_duration_ms / 2:
        log(f"[VideoVerified] ⚠ VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")
        log(f"[VideoVerified] Audio said {pure_correlation_ms:+.1f}ms, "
            f"video shows {selected_offset:+.1f}ms")

    log(f"[VideoVerified] ───────────────────────────────────────")

    return final_offset_ms, {
        'reason': selection_reason,
        'audio_correlation_ms': pure_correlation_ms,
        'video_offset_ms': selected_offset,
        'final_offset_ms': final_offset_ms,
        'candidates': candidate_results,
        'checkpoints': len(checkpoint_times),
    }


def _generate_candidates_static(
    correlation_ms: float,
    frame_duration_ms: float,
    search_range_frames: int
) -> List[float]:
    """Generate candidate offsets to test (static version)."""
    candidates = set()

    # Always test zero
    candidates.add(0.0)

    # Always test correlation value
    candidates.add(round(correlation_ms, 1))

    # Test frame-quantized versions of correlation
    for frame_offset in range(-search_range_frames, search_range_frames + 1):
        candidate = round(frame_offset * frame_duration_ms, 1)
        candidates.add(candidate)

    # Also test the exact frame boundaries around correlation
    base_frame = int(round(correlation_ms / frame_duration_ms))
    for frame_delta in [-1, 0, 1]:
        candidate = round((base_frame + frame_delta) * frame_duration_ms, 1)
        candidates.add(candidate)

    return sorted(candidates)


def _select_checkpoint_times_static(
    duration_ms: float,
    num_checkpoints: int
) -> List[float]:
    """Select checkpoint times distributed across the video (static version)."""
    checkpoints = []

    # Use percentage-based positions (avoiding very start/end)
    positions = [15, 30, 50, 70, 85][:num_checkpoints]

    for pos in positions:
        time_ms = duration_ms * pos / 100
        checkpoints.append(time_ms)

    return checkpoints


def _measure_candidate_quality_static(
    offset_ms: float,
    checkpoint_times: List[float],
    source_reader,
    target_reader,
    fps: float,
    frame_duration_ms: float,
    window_radius: int,
    hash_algorithm: str,
    hash_size: int,
    hash_threshold: int,
    comparison_method: str,
    log
) -> Dict[str, Any]:
    """Measure quality of a candidate offset (static version)."""
    from ..frame_utils import compute_frame_hash, compute_hamming_distance

    total_score = 0.0
    matched_count = 0
    distances = []

    for checkpoint_ms in checkpoint_times:
        # Source frame at checkpoint time
        source_frame_idx = int(checkpoint_ms / frame_duration_ms)

        # Target frame at checkpoint + offset
        target_time_ms = checkpoint_ms + offset_ms
        target_frame_idx = int(target_time_ms / frame_duration_ms)

        try:
            source_frame = source_reader.get_frame(source_frame_idx)
            if source_frame is None:
                continue

            source_hash = compute_frame_hash(source_frame, hash_algorithm, hash_size)

            # Search window around expected target frame
            best_distance = float('inf')
            for delta in range(-window_radius, window_radius + 1):
                search_idx = target_frame_idx + delta
                if search_idx < 0:
                    continue

                target_frame = target_reader.get_frame(search_idx)
                if target_frame is None:
                    continue

                target_hash = compute_frame_hash(target_frame, hash_algorithm, hash_size)
                distance = compute_hamming_distance(source_hash, target_hash)

                if distance < best_distance:
                    best_distance = distance

            if best_distance < float('inf'):
                distances.append(best_distance)

                if best_distance <= hash_threshold:
                    matched_count += 1
                    # Score inversely proportional to distance
                    total_score += 1.0 - (best_distance / (hash_threshold * 2))
                else:
                    # Partial score for near-matches
                    total_score += max(0, 0.5 - (best_distance / (hash_threshold * 4)))

        except Exception as e:
            log(f"[VideoVerified] Checkpoint error: {e}")
            continue

    avg_distance = sum(distances) / len(distances) if distances else float('inf')

    return {
        'score': total_score,
        'matched': matched_count,
        'avg_distance': avg_distance,
    }


@register_sync_plugin
class VideoVerifiedSync(SyncPlugin):
    """
    Video-Verified sync mode.

    Uses audio correlation as starting point, then verifies with frame
    matching to determine the TRUE video-to-video offset for subtitle timing.

    Specifically designed to catch cases where:
    - Audio correlation detects small offsets (< 2 frames)
    - But actual video timing is 0ms (or different from audio)
    - Subtitles need video timing, not audio timing
    """

    name = 'video-verified'
    description = 'Audio correlation verified against video frame matching'

    def apply(
        self,
        subtitle_data: 'SubtitleData',
        total_delay_ms: float,
        global_shift_ms: float,
        target_fps: Optional[float] = None,
        source_video: Optional[str] = None,
        target_video: Optional[str] = None,
        runner=None,
        config: Optional[dict] = None,
        temp_dir: Optional[Path] = None,
        **kwargs
    ) -> 'OperationResult':
        """
        Apply video-verified sync to subtitle data.

        Algorithm:
        1. Calculate pure correlation offset (without global shift)
        2. Generate candidate offsets to test: 0ms, correlation, frame-quantized values
        3. For each candidate, measure frame match quality at multiple checkpoints
        4. Select the candidate with best video match quality
        5. Apply selected offset + global shift to all events

        Args:
            subtitle_data: SubtitleData to modify
            total_delay_ms: Total delay WITH global shift baked in
            global_shift_ms: Global shift that was added
            target_fps: Target video FPS
            source_video: Path to source video
            target_video: Path to target video
            runner: CommandRunner for logging
            config: Settings dict
            temp_dir: Temp directory for index files

        Returns:
            OperationResult with statistics
        """
        from ..data import OperationResult, OperationRecord, SyncEventData
        from ..frame_utils import detect_video_fps, detect_video_properties

        config = config or {}

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[VideoVerified] === Video-Verified Sync Mode ===")
        log(f"[VideoVerified] Events: {len(subtitle_data.events)}")

        if not source_video or not target_video:
            return OperationResult(
                success=False,
                operation='sync',
                error='Both source and target videos required for video-verified mode'
            )

        # Calculate pure correlation (correlation only, without global shift)
        pure_correlation_ms = total_delay_ms - global_shift_ms

        log(f"[VideoVerified] Source: {Path(source_video).name}")
        log(f"[VideoVerified] Target: {Path(target_video).name}")
        log(f"[VideoVerified] Total delay (with global): {total_delay_ms:+.3f}ms")
        log(f"[VideoVerified] Global shift: {global_shift_ms:+.3f}ms")
        log(f"[VideoVerified] Pure correlation (audio): {pure_correlation_ms:+.3f}ms")

        # Detect FPS
        fps = target_fps or detect_video_fps(source_video, runner)
        if not fps:
            fps = 23.976
            log(f"[VideoVerified] FPS detection failed, using default: {fps}")

        frame_duration_ms = 1000.0 / fps
        log(f"[VideoVerified] FPS: {fps:.3f} (frame: {frame_duration_ms:.3f}ms)")

        # Get config parameters
        zero_check_threshold_frames = config.get('video_verified_zero_check_frames', 3)
        zero_check_threshold_ms = zero_check_threshold_frames * frame_duration_ms
        min_quality_advantage = config.get('video_verified_min_quality_advantage', 0.1)
        num_checkpoints = config.get('video_verified_num_checkpoints', 5)
        search_range_frames = config.get('video_verified_search_range_frames', 3)
        hash_algorithm = config.get('frame_hash_algorithm', 'dhash')
        hash_size = int(config.get('frame_hash_size', 8))
        hash_threshold = int(config.get('frame_hash_threshold', 5))
        window_radius = int(config.get('frame_window_radius', 5))
        comparison_method = config.get('frame_comparison_method', 'hash')

        log(f"[VideoVerified] Zero-check threshold: ±{zero_check_threshold_ms:.1f}ms ({zero_check_threshold_frames} frames)")
        log(f"[VideoVerified] Checkpoints: {num_checkpoints}, Search: ±{search_range_frames} frames")
        log(f"[VideoVerified] Comparison method: {comparison_method}")

        # Determine if we need zero-check (correlation is small enough to be suspicious)
        needs_zero_check = abs(pure_correlation_ms) <= zero_check_threshold_ms

        if not needs_zero_check:
            log(f"[VideoVerified] Correlation {pure_correlation_ms:+.3f}ms exceeds zero-check threshold")
            log(f"[VideoVerified] Using correlation as-is (large offset unlikely to be zero)")
            return self._apply_offset(
                subtitle_data, total_delay_ms, global_shift_ms, pure_correlation_ms,
                pure_correlation_ms, 'correlation', {}, runner
            )

        log(f"[VideoVerified] Small correlation detected - verifying against video...")

        # Try to import frame utilities
        try:
            from ..frame_utils import VideoReader, compute_frame_hash, compute_hamming_distance
        except ImportError as e:
            log(f"[VideoVerified] Frame utilities unavailable: {e}")
            log(f"[VideoVerified] Falling back to correlation")
            return self._apply_offset(
                subtitle_data, total_delay_ms, global_shift_ms, pure_correlation_ms,
                pure_correlation_ms, 'fallback-no-frame-utils', {}, runner
            )

        # Get video duration for checkpoint selection
        try:
            props = detect_video_properties(source_video, runner)
            source_duration = props.get('duration_ms', 0)
            if source_duration <= 0:
                raise ValueError("Could not detect video duration")
        except Exception:
            if subtitle_data.events:
                source_duration = max(e.end_ms for e in subtitle_data.events) + 60000
            else:
                source_duration = 1200000

        log(f"[VideoVerified] Source duration: ~{source_duration/1000:.1f}s")

        # Generate candidate offsets to test
        candidates = self._generate_candidates(
            pure_correlation_ms, frame_duration_ms, search_range_frames
        )
        log(f"[VideoVerified] Candidates to test: {[f'{c:+.1f}ms' for c in candidates]}")

        # Open video readers with deinterlace support
        try:
            deinterlace_mode = config.get('frame_deinterlace_mode', 'auto')
            source_reader = VideoReader(
                source_video, runner, temp_dir=temp_dir,
                deinterlace=deinterlace_mode, config=config
            )
            target_reader = VideoReader(
                target_video, runner, temp_dir=temp_dir,
                deinterlace=deinterlace_mode, config=config
            )
        except Exception as e:
            log(f"[VideoVerified] Failed to open videos: {e}")
            log(f"[VideoVerified] Falling back to correlation")
            return self._apply_offset(
                subtitle_data, total_delay_ms, global_shift_ms, pure_correlation_ms,
                pure_correlation_ms, 'fallback-video-open-failed', {}, runner
            )

        # Select checkpoint times (distributed across video)
        checkpoint_times = self._select_checkpoint_times(
            source_duration, num_checkpoints, subtitle_data.events
        )
        log(f"[VideoVerified] Checkpoint times: {[f'{t/1000:.1f}s' for t in checkpoint_times]}")

        # Test each candidate
        candidate_results = []

        for candidate_offset in candidates:
            quality = self._measure_candidate_quality(
                candidate_offset, checkpoint_times, source_reader, target_reader,
                fps, frame_duration_ms, window_radius, hash_algorithm, hash_size,
                hash_threshold, comparison_method, log
            )
            candidate_results.append({
                'offset_ms': candidate_offset,
                'quality': quality['score'],
                'matched_checkpoints': quality['matched'],
                'avg_distance': quality['avg_distance'],
            })
            log(f"[VideoVerified]   Candidate {candidate_offset:+.1f}ms: "
                f"score={quality['score']:.2f}, matched={quality['matched']}/{len(checkpoint_times)}, "
                f"avg_dist={quality['avg_distance']:.1f}")

        # Close readers
        try:
            source_reader.close()
            target_reader.close()
        except Exception:
            pass

        # Select best candidate
        best_result = max(candidate_results, key=lambda r: r['quality'])
        best_offset = best_result['offset_ms']

        # Check if zero is competitive (within quality margin)
        zero_result = next((r for r in candidate_results if abs(r['offset_ms']) < 0.5), None)

        log(f"[VideoVerified] ───────────────────────────────────────")
        log(f"[VideoVerified] Best candidate: {best_offset:+.1f}ms (score={best_result['quality']:.2f})")

        selected_offset = best_offset
        selection_reason = 'best-match'

        if zero_result and abs(best_offset) > 0.5:
            # Best isn't zero - check if zero is close enough
            quality_diff = best_result['quality'] - zero_result['quality']
            log(f"[VideoVerified] Zero offset score: {zero_result['quality']:.2f} "
                f"(diff from best: {quality_diff:.2f})")

            if quality_diff <= min_quality_advantage:
                # Zero is competitive - prefer it (simpler is better)
                selected_offset = 0.0
                selection_reason = 'zero-preferred'
                log(f"[VideoVerified] Zero offset is competitive (within {min_quality_advantage} margin)")
                log(f"[VideoVerified] Selecting 0ms (simpler offset preferred)")
            else:
                log(f"[VideoVerified] Best candidate is significantly better than zero")

        # Calculate final offset
        final_offset_ms = selected_offset + global_shift_ms

        log(f"[VideoVerified] ───────────────────────────────────────")
        log(f"[VideoVerified] Selection: {selection_reason}")
        log(f"[VideoVerified] Audio correlation: {pure_correlation_ms:+.3f}ms")
        log(f"[VideoVerified] Video-verified offset: {selected_offset:+.3f}ms")
        log(f"[VideoVerified] + Global shift: {global_shift_ms:+.3f}ms")
        log(f"[VideoVerified] = Final offset: {final_offset_ms:+.3f}ms")

        if abs(selected_offset - pure_correlation_ms) > frame_duration_ms / 2:
            log(f"[VideoVerified] ⚠ VIDEO OFFSET DIFFERS FROM AUDIO CORRELATION")
            log(f"[VideoVerified] Audio said {pure_correlation_ms:+.1f}ms, "
                f"video shows {selected_offset:+.1f}ms")

        log(f"[VideoVerified] ───────────────────────────────────────")

        return self._apply_offset(
            subtitle_data, final_offset_ms, global_shift_ms, pure_correlation_ms,
            selected_offset, selection_reason, {
                'candidates': candidate_results,
                'checkpoints': len(checkpoint_times),
            }, runner
        )

    def _generate_candidates(
        self,
        correlation_ms: float,
        frame_duration_ms: float,
        search_range_frames: int
    ) -> List[float]:
        """
        Generate candidate offsets to test.

        Always includes:
        - 0ms (zero offset - maybe audio correlation is wrong)
        - correlation_ms (what audio correlation found)
        - Frame-quantized values around correlation

        Returns sorted unique list of candidates.
        """
        candidates = set()

        # Always test zero
        candidates.add(0.0)

        # Always test correlation value
        candidates.add(round(correlation_ms, 1))

        # Test frame-quantized versions of correlation
        correlation_frames = correlation_ms / frame_duration_ms
        for frame_offset in range(-search_range_frames, search_range_frames + 1):
            candidate = round(frame_offset * frame_duration_ms, 1)
            candidates.add(candidate)

        # Also test the exact frame boundaries around correlation
        base_frame = int(round(correlation_ms / frame_duration_ms))
        for frame_delta in [-1, 0, 1]:
            candidate = round((base_frame + frame_delta) * frame_duration_ms, 1)
            candidates.add(candidate)

        return sorted(candidates)

    def _select_checkpoint_times(
        self,
        duration_ms: float,
        num_checkpoints: int,
        events: List
    ) -> List[float]:
        """Select checkpoint times distributed across the video."""
        checkpoints = []

        # Use percentage-based positions (avoiding very start/end)
        positions = [15, 30, 50, 70, 85][:num_checkpoints]

        for pos in positions:
            time_ms = duration_ms * pos / 100
            checkpoints.append(time_ms)

        return checkpoints

    def _measure_candidate_quality(
        self,
        offset_ms: float,
        checkpoint_times: List[float],
        source_reader,
        target_reader,
        fps: float,
        frame_duration_ms: float,
        window_radius: int,
        hash_algorithm: str,
        hash_size: int,
        hash_threshold: int,
        comparison_method: str,
        log
    ) -> Dict[str, Any]:
        """
        Measure how well a candidate offset matches at checkpoints.

        Uses sliding window of frames around each checkpoint for robust matching.

        Args:
            comparison_method: 'hash', 'ssim', or 'mse'

        Returns dict with:
        - score: Overall quality score (higher = better)
        - matched: Number of checkpoints that matched well
        - avg_distance: Average distance across all frames
        """
        from ..frame_utils import compare_frames

        total_distance = 0
        total_frames = 0
        matched_checkpoints = 0

        # Thresholds for different methods
        if comparison_method == 'ssim':
            match_threshold = 10.0  # (1 - 0.90) * 100 = 10
            max_distance = 100.0
        elif comparison_method == 'mse':
            match_threshold = 5.0  # Normalized MSE
            max_distance = 100.0
        else:  # hash
            match_threshold = hash_threshold * 1.5
            max_distance = hash_size * hash_size

        for checkpoint_ms in checkpoint_times:
            # Get window of source frames around checkpoint
            checkpoint_distances = []

            for frame_offset in range(-window_radius, window_radius + 1):
                source_time_ms = checkpoint_ms + frame_offset * frame_duration_ms
                target_time_ms = source_time_ms + offset_ms

                source_frame = source_reader.get_frame_at_time(int(source_time_ms))
                target_frame = target_reader.get_frame_at_time(int(target_time_ms))

                if source_frame is not None and target_frame is not None:
                    distance, is_match = compare_frames(
                        source_frame, target_frame,
                        method=comparison_method,
                        hash_algorithm=hash_algorithm,
                        hash_size=hash_size
                    )
                    checkpoint_distances.append(distance)
                    total_distance += distance
                    total_frames += 1

            if checkpoint_distances:
                avg_checkpoint_dist = sum(checkpoint_distances) / len(checkpoint_distances)
                if avg_checkpoint_dist <= match_threshold:
                    matched_checkpoints += 1

        if total_frames == 0:
            return {'score': 0.0, 'matched': 0, 'avg_distance': 999.0}

        avg_distance = total_distance / total_frames

        # Score: prioritize low distance, bonus for matched checkpoints
        # Lower distance = higher score (invert)
        # More matches = higher score
        distance_score = max(0, 1 - (avg_distance / max_distance))
        match_ratio = matched_checkpoints / len(checkpoint_times)

        # Combined score (0-1 range)
        score = distance_score * 0.6 + match_ratio * 0.4

        return {
            'score': score,
            'matched': matched_checkpoints,
            'avg_distance': avg_distance,
        }

    def _apply_offset(
        self,
        subtitle_data: 'SubtitleData',
        final_offset_ms: float,
        global_shift_ms: float,
        audio_correlation_ms: float,
        video_offset_ms: float,
        selection_reason: str,
        details: Dict,
        runner
    ) -> 'OperationResult':
        """Apply the calculated offset to all events."""
        from ..data import OperationResult, OperationRecord, SyncEventData

        def log(msg: str):
            if runner:
                runner._log_message(msg)

        log(f"[VideoVerified] Applying {final_offset_ms:+.3f}ms to {len(subtitle_data.events)} events")

        events_synced = 0

        for event in subtitle_data.events:
            if event.is_comment:
                continue

            original_start = event.start_ms
            original_end = event.end_ms

            event.start_ms += final_offset_ms
            event.end_ms += final_offset_ms

            event.sync = SyncEventData(
                original_start_ms=original_start,
                original_end_ms=original_end,
                start_adjustment_ms=final_offset_ms,
                end_adjustment_ms=final_offset_ms,
                snapped_to_frame=False,
            )

            events_synced += 1

        # Build summary
        if abs(video_offset_ms - audio_correlation_ms) > 1.0:
            summary = (f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms "
                      f"(audio={audio_correlation_ms:+.0f}→video={video_offset_ms:+.0f})")
        else:
            summary = f"VideoVerified: {events_synced} events, {final_offset_ms:+.1f}ms"

        # Record operation
        record = OperationRecord(
            operation='sync',
            timestamp=datetime.now(),
            parameters={
                'mode': self.name,
                'final_offset_ms': final_offset_ms,
                'global_shift_ms': global_shift_ms,
                'audio_correlation_ms': audio_correlation_ms,
                'video_offset_ms': video_offset_ms,
                'selection_reason': selection_reason,
            },
            events_affected=events_synced,
            summary=summary
        )
        subtitle_data.operations.append(record)

        log(f"[VideoVerified] Sync complete: {events_synced} events")
        log(f"[VideoVerified] ===================================")

        return OperationResult(
            success=True,
            operation='sync',
            events_affected=events_synced,
            summary=summary,
            details={
                'audio_correlation_ms': audio_correlation_ms,
                'video_offset_ms': video_offset_ms,
                'final_offset_ms': final_offset_ms,
                'selection_reason': selection_reason,
                **details,
            }
        )
