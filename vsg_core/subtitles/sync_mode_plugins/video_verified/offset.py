# vsg_core/subtitles/sync_mode_plugins/video_verified/offset.py
"""
Sub-frame offset calculation and VFR frame lookup for video-verified sync.
"""

from __future__ import annotations

from typing import Any

# Cache for VFR VideoTimestamps instances (expensive to create)
_vfr_timestamps_cache: dict[str, Any] = {}
# Track which videos we've logged VFR usage for (avoid log spam)
_vfr_logged_videos: set[str] = set()


def get_vfr_frame_for_time(
    video_path: str, time_ms: float, is_soft_telecine: bool, log=None
) -> int | None:
    """
    Get frame number for a given time using VFR timestamps.

    For soft-telecine sources, uses VideoTimestamps.from_video_file() to get
    accurate frame numbers that account for VFR container timestamps.

    Args:
        video_path: Path to the video file
        time_ms: Timestamp in milliseconds
        is_soft_telecine: Whether this is a soft-telecine VFR source

    Returns:
        Frame number if VFR conversion successful, None otherwise (caller uses CFR)
    """
    if not is_soft_telecine:
        return None

    try:
        from pathlib import Path as PathLib

        from video_timestamps import TimeType, VideoTimestamps

        # Cache VideoTimestamps instance (expensive to create)
        if video_path not in _vfr_timestamps_cache:
            vts = VideoTimestamps.from_video_file(PathLib(video_path))
            _vfr_timestamps_cache[video_path] = vts
            # Log once per video
            if log and video_path not in _vfr_logged_videos:
                _vfr_logged_videos.add(video_path)
                log(
                    f"[VideoVerified] Using VFR timestamps for soft-telecine source: {PathLib(video_path).name}"
                )
        else:
            vts = _vfr_timestamps_cache[video_path]

        # Convert time to frame using EXACT (precise frame display window)
        # input_unit=3 means milliseconds
        frame_num = vts.time_to_frame(int(time_ms), TimeType.EXACT, input_unit=3)
        return frame_num

    except ImportError:
        # VideoTimestamps not installed, fall back to CFR
        return None
    except Exception:
        # Any error, fall back to CFR
        return None


def calculate_subframe_offset(
    frame_offset: int,
    match_details: list[dict],
    checkpoint_times: list[float],
    source_reader,
    target_reader,
    fps: float,
    frame_duration_ms: float,
    log,
    use_pts_precision: bool = False,
) -> float:
    """
    Calculate the final offset in milliseconds.

    By default, uses simple frame-based calculation:
        offset_ms = frame_offset * frame_duration_ms

    This is reliable when sequence verification confirms the frame offset is correct
    (10/10 frames matching means we KNOW the offset). Container PTS differences
    can introduce noise from muxing quirks, so frame-based is preferred.

    Optionally, can use PTS-based calculation for VFR content or when sub-frame
    precision is needed. Enable with use_pts_precision=True.

    Args:
        frame_offset: Best frame offset found (in frames)
        match_details: List of matched frame pairs from quality measurement
        checkpoint_times: Original checkpoint times
        source_reader: VideoReader for source
        target_reader: VideoReader for target
        fps: Video FPS
        frame_duration_ms: Frame duration in ms
        log: Logging function
        use_pts_precision: If True, use PTS for sub-frame precision (default False)

    Returns:
        Offset in milliseconds
    """
    # Default: simple frame-based calculation
    frame_based_offset = frame_offset * frame_duration_ms

    if not use_pts_precision:
        # Just use frame-based - simple and reliable
        log(
            f"[VideoVerified] Frame-based offset: {frame_offset:+d} frames = {frame_based_offset:+.3f}ms"
        )
        return frame_based_offset

    # PTS precision mode - use actual container timestamps
    log("[VideoVerified] Using PTS precision mode")

    # Prioritize sequence-verified matches (most reliable)
    sequence_verified_matches = [
        m for m in match_details if m.get("sequence_verified", False)
    ]

    # Fall back to single-frame matches if no sequence-verified
    if sequence_verified_matches:
        good_matches = sequence_verified_matches
        log(
            f"[VideoVerified] Using {len(good_matches)} sequence-verified checkpoints for PTS calculation"
        )
    else:
        good_matches = [m for m in match_details if m.get("is_match", False)]
        if good_matches:
            log(
                f"[VideoVerified] No sequence-verified matches, using {len(good_matches)} single-frame matches"
            )

    if not good_matches:
        # No good matches - fall back to frame-based calculation
        log(
            f"[VideoVerified] No good matches for PTS, using frame-based: {frame_based_offset:+.3f}ms"
        )
        return frame_based_offset

    # Calculate offset from each matched pair using PTS
    pts_offsets = []

    for match in good_matches:
        source_idx = match["source_frame"]
        target_idx = match["target_frame"]
        seq_info = ""
        if match.get("sequence_verified"):
            seq_info = f" [seq:{match.get('sequence_matched', '?')}/{match.get('sequence_length', '?')}]"

        try:
            source_pts = source_reader.get_frame_pts(source_idx)
            target_pts = target_reader.get_frame_pts(target_idx)

            if source_pts is not None and target_pts is not None:
                offset = target_pts - source_pts
                pts_offsets.append(offset)
                log(
                    f"[VideoVerified]   Frame {source_idx}→{target_idx}: "
                    f"PTS {source_pts:.3f}ms→{target_pts:.3f}ms = {offset:+.3f}ms{seq_info}"
                )

        except Exception as e:
            log(f"[VideoVerified] PTS lookup error: {e}")
            continue

    if not pts_offsets:
        # PTS lookup failed - fall back to frame-based
        log(
            f"[VideoVerified] PTS lookup failed, using frame-based: {frame_based_offset:+.3f}ms"
        )
        return frame_based_offset

    # Use median offset (robust to outliers)
    pts_offsets.sort()
    median_idx = len(pts_offsets) // 2
    if len(pts_offsets) % 2 == 0:
        sub_frame_offset = (pts_offsets[median_idx - 1] + pts_offsets[median_idx]) / 2
    else:
        sub_frame_offset = pts_offsets[median_idx]

    log(
        f"[VideoVerified] PTS-based offset from {len(pts_offsets)} pairs: {sub_frame_offset:+.3f}ms"
    )

    return sub_frame_offset
