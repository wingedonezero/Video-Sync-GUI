# vsg_core/subtitles/frame_utils/scene_detection.py
"""
Scene change detection using PySceneDetect.

Contains:
- Scene change detection for sync verification anchor points
"""

from __future__ import annotations

from pathlib import Path


def detect_scene_changes(
    video_path: str,
    start_frame: int,
    end_frame: int,
    runner,
    max_scenes: int = 10,
    threshold: float = 27.0,
) -> list[int]:
    """
    Detect scene changes in a video using PySceneDetect.

    Uses ContentDetector for fast and reliable scene change detection.
    Returns the frame BEFORE each scene change (last frame of previous scene)
    as a concrete anchor point for sync verification.

    Scene changes are ideal checkpoints because:
    - Adjacent frames are distinctly different (unambiguous for matching)
    - The frame before the cut is a stable reference point
    - Frame matching at cuts is highly reliable

    Args:
        video_path: Path to video file
        start_frame: Start frame to search from
        end_frame: End frame to search to
        runner: CommandRunner for logging
        max_scenes: Maximum number of scene changes to return
        threshold: Detection threshold (lower = more sensitive, default 27.0)

    Returns:
        List of frame numbers (the frame BEFORE each scene change)
    """
    try:
        from scenedetect import ContentDetector, detect, open_video

        runner._log_message(
            f"[SceneDetect] Detecting scene changes in {Path(video_path).name}"
        )
        runner._log_message(
            f"[SceneDetect] Using PySceneDetect (ContentDetector, threshold={threshold})"
        )
        runner._log_message(
            f"[SceneDetect] Searching frames {start_frame} to {end_frame}"
        )

        # Open video and get framerate
        video = open_video(str(video_path))
        fps = video.frame_rate
        # Close video handle to prevent resource leaks in batch processing
        del video

        # Convert frame range to time range for PySceneDetect
        start_time_sec = start_frame / fps
        end_time_sec = end_frame / fps

        runner._log_message(
            f"[SceneDetect] Time range: {start_time_sec:.2f}s - {end_time_sec:.2f}s (fps={fps:.3f})"
        )

        # Detect scenes using ContentDetector
        # Returns list of (start_timecode, end_timecode) tuples for each scene
        scene_list = detect(
            str(video_path),
            ContentDetector(threshold=threshold, min_scene_len=15),
            start_time=start_time_sec,
            end_time=end_time_sec,
            show_progress=False,
        )

        # Extract frame BEFORE each scene change (last frame of previous scene)
        # This is our concrete anchor point - the frame just before the cut
        scene_frames = []

        for i, (scene_start, scene_end) in enumerate(scene_list):
            if i == 0:
                # First scene - skip, no "before" frame exists for the first cut
                continue

            # scene_start is the first frame of the NEW scene (after the cut)
            # We want the frame BEFORE this (last frame of previous scene)
            cut_frame = scene_start.get_frames()
            anchor_frame = cut_frame - 1  # Frame before the scene change

            if anchor_frame >= start_frame and anchor_frame <= end_frame:
                scene_frames.append(anchor_frame)
                runner._log_message(
                    f"[SceneDetect] Scene change at frame {cut_frame} -> anchor frame {anchor_frame} "
                    f"(t={anchor_frame/fps:.3f}s)"
                )

                if len(scene_frames) >= max_scenes:
                    break

        runner._log_message(
            f"[SceneDetect] Found {len(scene_frames)} scene change anchor frames"
        )

        # If we didn't find enough scenes, try with lower threshold
        if len(scene_frames) < 2:
            runner._log_message(
                "[SceneDetect] Few scenes found, trying with lower threshold (15.0)"
            )

            scene_list = detect(
                str(video_path),
                ContentDetector(threshold=15.0, min_scene_len=10),
                start_time=start_time_sec,
                end_time=end_time_sec,
                show_progress=False,
            )

            scene_frames = []
            for i, (scene_start, scene_end) in enumerate(scene_list):
                if i == 0:
                    continue
                cut_frame = scene_start.get_frames()
                anchor_frame = cut_frame - 1

                if anchor_frame >= start_frame and anchor_frame <= end_frame:
                    scene_frames.append(anchor_frame)
                    if len(scene_frames) >= max_scenes:
                        break

            runner._log_message(
                f"[SceneDetect] Found {len(scene_frames)} scenes with lower threshold"
            )

        return scene_frames

    except ImportError as e:
        runner._log_message(f"[SceneDetect] WARNING: PySceneDetect not available: {e}")
        runner._log_message(
            "[SceneDetect] Install with: pip install scenedetect opencv-python"
        )
        return []
    except Exception as e:
        runner._log_message(f"[SceneDetect] ERROR: {e}")
        import traceback

        runner._log_message(f"[SceneDetect] Traceback: {traceback.format_exc()}")
        return []
