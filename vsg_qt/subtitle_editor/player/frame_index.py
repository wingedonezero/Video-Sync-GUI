# vsg_qt/subtitle_editor/player/frame_index.py
# -*- coding: utf-8 -*-
"""
Lightweight VapourSynth index loader for frame-accurate timing.

Loads the VS index (creating if needed) to provide accurate frame<->time
conversion using VideoTimestamps library for precise NTSC rate handling.
"""
from __future__ import annotations

import gc
from fractions import Fraction
from pathlib import Path
from typing import Optional, Any


class FrameIndex:
    """
    Lightweight VS index for frame-accurate timing lookup.

    Uses VapourSynth with lsmas or ffms2 to load/create video index,
    extracts timing info (fps, frame_count), then releases the clip.

    Uses VideoTimestamps library for precise frame<->time conversion,
    properly handling NTSC fractional rates (24000/1001, etc).

    The index file persists on disk for fast subsequent loads.
    """

    def __init__(self, video_path: str, index_dir: Path):
        """
        Load or create VS index for the video.

        Args:
            video_path: Path to the video file
            index_dir: Directory for index cache files
        """
        self._video_path = video_path
        self._index_dir = Path(index_dir)
        self._fps: float = 23.976  # Default fallback
        self._fps_fraction: Optional[Fraction] = None
        self._frame_count: int = 0
        self._loaded: bool = False
        self._timestamps: Optional[Any] = None  # FPSTimestamps instance

        self._load_index()

    def _load_index(self):
        """Load or create the VapourSynth index."""
        try:
            import vapoursynth as vs

            core = vs.core
            clip = None

            # Ensure index directory exists
            self._index_dir.mkdir(parents=True, exist_ok=True)

            # Try L-SMASH first (more accurate for some formats)
            lwi_path = self._index_dir / "lwi_index.lwi"
            try:
                clip = core.lsmas.LWLibavSource(
                    str(self._video_path),
                    cachefile=str(lwi_path)
                )
                print(f"[FrameIndex] Loaded with L-SMASH: {lwi_path}")
            except AttributeError:
                print("[FrameIndex] L-SMASH plugin not available, trying ffms2")
            except Exception as e:
                print(f"[FrameIndex] L-SMASH failed: {e}, trying ffms2")

            # Fall back to ffms2
            if clip is None:
                ffindex_path = self._index_dir / "ffms2_index.ffindex"
                try:
                    if not ffindex_path.exists():
                        print(f"[FrameIndex] Creating new index at: {ffindex_path}")
                        print("[FrameIndex] This may take 1-2 minutes for first load...")
                    else:
                        print(f"[FrameIndex] Using cached index: {ffindex_path}")

                    clip = core.ffms2.Source(
                        source=str(self._video_path),
                        cachefile=str(ffindex_path)
                    )
                    print(f"[FrameIndex] Loaded with ffms2")
                except AttributeError:
                    print("[FrameIndex] ERROR: Neither L-SMASH nor ffms2 plugins available")
                    return
                except Exception as e:
                    print(f"[FrameIndex] ERROR: ffms2 failed: {e}")
                    return

            # Extract timing info - get exact fps fraction from VS
            self._fps = float(clip.fps)
            self._fps_fraction = Fraction(clip.fps.numerator, clip.fps.denominator)
            self._frame_count = len(clip)

            print(f"[FrameIndex] Video info: {self._frame_count} frames @ {self._fps:.3f} fps")
            print(f"[FrameIndex] Exact FPS fraction: {self._fps_fraction}")

            # Release clip - we only needed the timing info
            del clip
            del core
            gc.collect()

            # Initialize VideoTimestamps for precise frame/time conversion
            self._init_timestamps()

            self._loaded = True
            print("[FrameIndex] Index loaded, clip released")

        except ImportError:
            print("[FrameIndex] WARNING: VapourSynth not installed, using fallback")
        except Exception as e:
            print(f"[FrameIndex] ERROR: Failed to load index: {e}")

    def _init_timestamps(self):
        """Initialize VideoTimestamps for precise conversion."""
        try:
            from video_timestamps import FPSTimestamps, RoundingMethod

            # Use exact fps fraction from VapourSynth
            fps_frac = self._fps_fraction
            if fps_frac is None:
                # Fallback: convert float fps to proper NTSC fraction
                if abs(self._fps - 23.976) < 0.001:
                    fps_frac = Fraction(24000, 1001)
                elif abs(self._fps - 29.97) < 0.01:
                    fps_frac = Fraction(30000, 1001)
                elif abs(self._fps - 59.94) < 0.01:
                    fps_frac = Fraction(60000, 1001)
                else:
                    fps_frac = Fraction(int(self._fps * 1000), 1000).limit_denominator(10000)

            # Create FPSTimestamps with millisecond time scale
            time_scale = Fraction(1000)  # milliseconds
            self._timestamps = FPSTimestamps(RoundingMethod.ROUND, time_scale, fps_frac)

            print(f"[FrameIndex] VideoTimestamps initialized with fps={fps_frac}")

        except ImportError:
            print("[FrameIndex] WARNING: VideoTimestamps not installed, using simple math")
            self._timestamps = None
        except Exception as e:
            print(f"[FrameIndex] WARNING: VideoTimestamps init failed: {e}")
            self._timestamps = None

    @property
    def fps(self) -> float:
        """Get video frame rate."""
        return self._fps

    @property
    def frame_count(self) -> int:
        """Get total frame count."""
        return self._frame_count

    @property
    def is_loaded(self) -> bool:
        """Check if index was loaded successfully."""
        return self._loaded

    def ms_to_frame(self, time_ms: float) -> int:
        """
        Convert milliseconds to frame number using VideoTimestamps.

        Args:
            time_ms: Time in milliseconds

        Returns:
            Frame number (0-indexed)
        """
        if self._timestamps is not None:
            try:
                from video_timestamps import TimeType
                # Use EXACT for precise frame lookup
                frame = self._timestamps.time_to_frame(Fraction(int(time_ms), 1), TimeType.EXACT)
                return max(0, min(frame, self._frame_count - 1))
            except Exception as e:
                print(f"[FrameIndex] VideoTimestamps conversion failed: {e}")

        # Fallback to simple math
        if self._fps <= 0:
            return 0
        frame = int(time_ms * self._fps / 1000.0)
        return max(0, min(frame, self._frame_count - 1))

    def frame_to_ms(self, frame_num: int) -> float:
        """
        Convert frame number to milliseconds using VideoTimestamps.

        Args:
            frame_num: Frame number (0-indexed)

        Returns:
            Time in milliseconds
        """
        if self._timestamps is not None:
            try:
                from video_timestamps import TimeType
                # Use EXACT for precise timestamp
                time_ms = self._timestamps.frame_to_time(frame_num, TimeType.EXACT)
                return float(time_ms)
            except Exception as e:
                print(f"[FrameIndex] VideoTimestamps conversion failed: {e}")

        # Fallback to simple math
        if self._fps <= 0:
            return 0.0
        return frame_num * 1000.0 / self._fps

    @property
    def duration_ms(self) -> float:
        """Get total video duration in milliseconds."""
        return self.frame_to_ms(self._frame_count)
