# vsg_qt/subtitle_editor/player/player_thread.py
# -*- coding: utf-8 -*-
"""
Video player thread for subtitle editor using VapourSynth.

Provides frame-accurate seeking with index caching for fast repeated access.
Uses lsmas for video loading and libass (via AssFile) for subtitle rendering.
"""
import gc
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QImage

import numpy as np
import vapoursynth as vs


class PlayerThread(QThread):
    """
    Video playback thread using VapourSynth.

    Features:
    - Frame-accurate seeking (no keyframe limitations)
    - Index caching for fast repeated access
    - Subtitle rendering with libass

    Signals:
        new_frame: Emitted with (QImage, timestamp_seconds) for each frame
        duration_changed: Emitted when video duration is known
        playback_finished: Emitted when video reaches end
        time_changed: Emitted with current time in milliseconds
        fps_detected: Emitted when FPS is detected
    """

    new_frame = Signal(object, float)
    duration_changed = Signal(float)
    playback_finished = Signal()
    time_changed = Signal(int)
    fps_detected = Signal(float)

    def __init__(self, video_path: str, subtitle_path: str, index_dir: str,
                 fonts_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.index_dir = Path(index_dir)
        self.fonts_dir = fonts_dir

        # VapourSynth core and clips
        self._core: Optional[vs.Core] = None
        self._base_clip: Optional[vs.VideoNode] = None  # Video without subs
        self._clip: Optional[vs.VideoNode] = None       # Video with subs
        self._rgb_clip: Optional[vs.VideoNode] = None   # Cached RGB output

        # Video properties
        self._fps: float = 23.976
        self._frame_count: int = 0
        self._duration_ms: int = 0
        self._width: int = 0
        self._height: int = 0

        # Playback state
        self._is_running = True
        self._is_paused = True  # Start paused
        self._current_frame: int = 0
        self._current_time_ms: int = 0

        # Thread synchronization
        self._lock = Lock()
        self._seek_request_frame: int = -1
        self._seek_request_ms: int = -1
        self._reload_subs_requested = False
        self._force_render_frame = False

    @property
    def fps(self) -> float:
        """Get the detected FPS."""
        return self._fps

    @property
    def current_time_ms(self) -> int:
        """Get the current playback position in milliseconds."""
        return self._current_time_ms

    @property
    def is_paused(self) -> bool:
        """Check if playback is paused."""
        with self._lock:
            return self._is_paused

    def _load_video(self):
        """Load video with VapourSynth using cached index."""
        self._core = vs.core

        # Index file path for lsmas
        index_file = self.index_dir / "lwi_index.lwi"

        # Load video with lsmas (creates/uses cached index)
        try:
            self._base_clip = self._core.lsmas.LWLibavSource(
                self.video_path,
                cachefile=str(index_file)
            )
        except AttributeError:
            # Fallback to ffms2 if lsmas not available
            self._base_clip = self._core.ffms2.Source(
                self.video_path,
                cachefile=str(self.index_dir / "ffms2_index")
            )

        # Get video properties
        self._fps = float(self._base_clip.fps)
        self._frame_count = len(self._base_clip)
        self._width = self._base_clip.width
        self._height = self._base_clip.height
        self._duration_ms = int(self._frame_count / self._fps * 1000)

        # Apply subtitles
        self._apply_subtitles()

    def _apply_subtitles(self):
        """Apply ASS subtitles to the base clip using libass."""
        if self._base_clip is None:
            return

        # Check if subtitle file exists
        sub_path = Path(self.subtitle_path)
        if not sub_path.exists():
            print(f"[VS Player] WARNING: Subtitle file not found: {self.subtitle_path}")
            self._clip = self._base_clip
            self._build_rgb_clip()
            return

        print(f"[VS Player] Applying subtitles from: {self.subtitle_path}")
        if self.fonts_dir:
            print(f"[VS Player] Using fonts directory: {self.fonts_dir}")

        try:
            if self.fonts_dir:
                self._clip = self._core.sub.AssFile(
                    self._base_clip,
                    self.subtitle_path,
                    fontdir=self.fonts_dir
                )
            else:
                self._clip = self._core.sub.AssFile(
                    self._base_clip,
                    self.subtitle_path
                )
            print(f"[VS Player] Subtitles applied successfully")
        except Exception as e:
            print(f"[VS Player] Failed to apply subtitles: {e}")
            # Fallback to video without subtitles
            self._clip = self._base_clip

        # Build cached RGB output clip
        self._build_rgb_clip()

    def _build_rgb_clip(self):
        """Build the cached RGB output clip from the current clip."""
        if self._clip is None:
            return

        try:
            # Convert to RGB24 for QImage output
            # Use matrix_in_s='709' for HD content (most common)
            self._rgb_clip = self._core.resize.Bicubic(
                self._clip,
                format=vs.RGB24,
                matrix_in_s='709'
            )
            print(f"[VS Player] RGB clip built: {self._rgb_clip.width}x{self._rgb_clip.height}")
        except Exception as e:
            print(f"[VS Player] Failed to build RGB clip: {e}")
            self._rgb_clip = None

    def _frame_to_ms(self, frame: int) -> int:
        """Convert frame number to milliseconds."""
        return int(frame / self._fps * 1000)

    def _ms_to_frame(self, ms: int) -> int:
        """Convert milliseconds to frame number."""
        return int(ms / 1000 * self._fps)

    def _get_frame_as_qimage(self, frame_num: int) -> Optional[QImage]:
        """
        Get a frame as QImage.

        Args:
            frame_num: Frame number to retrieve

        Returns:
            QImage of the frame, or None on error
        """
        if self._rgb_clip is None or frame_num < 0 or frame_num >= self._frame_count:
            return None

        try:
            # Get frame from cached RGB clip
            frame = self._rgb_clip.get_frame(frame_num)

            width = frame.width
            height = frame.height

            # Extract planes as numpy arrays (much faster than Python loops)
            r_plane = np.asarray(frame[0])
            g_plane = np.asarray(frame[1])
            b_plane = np.asarray(frame[2])

            # Stack and interleave RGB planes
            # Result shape: (height, width, 3)
            rgb_array = np.stack([r_plane, g_plane, b_plane], axis=-1)

            # Ensure contiguous array for QImage
            rgb_array = np.ascontiguousarray(rgb_array)

            # Create QImage from numpy array
            qimage = QImage(
                rgb_array.data,
                width,
                height,
                width * 3,
                QImage.Format_RGB888
            )

            # Make a copy since the numpy array will be invalidated
            return qimage.copy()

        except Exception as e:
            print(f"[VS Player] Error getting frame {frame_num}: {e}")
            return None

    def run(self):
        """Main thread loop."""
        try:
            print(f"[VS Player] Loading video: {self.video_path}")
            print(f"[VS Player] Index dir: {self.index_dir}")
            self._load_video()

            print(f"[VS Player] Video loaded: {self._width}x{self._height} @ {self._fps:.3f} fps, {self._frame_count} frames")

            # Emit video info
            self.fps_detected.emit(self._fps)
            self.duration_changed.emit(self._duration_ms / 1000)

            # Render first frame
            qimage = self._get_frame_as_qimage(0)
            if qimage:
                print(f"[VS Player] First frame rendered: {qimage.width()}x{qimage.height()}")
                self.new_frame.emit(qimage, 0.0)
                self.time_changed.emit(0)
            else:
                print(f"[VS Player] WARNING: Failed to render first frame!")

        except Exception as e:
            print(f"[VS Player] FATAL: Could not load video: {e}")
            import traceback
            traceback.print_exc()
            self._is_running = False
            return

        frame_delay = 1.0 / self._fps if self._fps > 0 else 0.04

        while self._is_running:
            try:
                with self._lock:
                    should_reload = self._reload_subs_requested
                    should_seek_ms = self._seek_request_ms
                    should_seek_frame = self._seek_request_frame
                    is_paused = self._is_paused
                    force_render = self._force_render_frame

                    if should_reload:
                        self._reload_subs_requested = False
                    if should_seek_ms >= 0:
                        self._seek_request_ms = -1
                    if should_seek_frame >= 0:
                        self._seek_request_frame = -1
                    if force_render:
                        self._force_render_frame = False

                # Handle subtitle reload
                if should_reload:
                    print(f"[VS Player] Reloading subtitles...")
                    self._apply_subtitles()
                    force_render = True

                # Handle seek by milliseconds
                if should_seek_ms >= 0:
                    target_frame = self._ms_to_frame(should_seek_ms)
                    target_frame = max(0, min(target_frame, self._frame_count - 1))
                    self._current_frame = target_frame
                    self._current_time_ms = self._frame_to_ms(target_frame)
                    force_render = True

                # Handle seek by frame number
                if should_seek_frame >= 0:
                    target_frame = max(0, min(should_seek_frame, self._frame_count - 1))
                    self._current_frame = target_frame
                    self._current_time_ms = self._frame_to_ms(target_frame)
                    force_render = True

                # Render frame if needed
                if force_render or not is_paused:
                    qimage = self._get_frame_as_qimage(self._current_frame)
                    if qimage:
                        timestamp_sec = self._current_time_ms / 1000
                        self.new_frame.emit(qimage, timestamp_sec)
                        self.time_changed.emit(self._current_time_ms)

                    # Advance frame if playing
                    if not is_paused:
                        self._current_frame += 1
                        self._current_time_ms = self._frame_to_ms(self._current_frame)

                        # Check for end of video
                        if self._current_frame >= self._frame_count:
                            self._current_frame = self._frame_count - 1
                            self.playback_finished.emit()
                            with self._lock:
                                self._is_paused = True

                # Sleep to maintain frame rate
                if is_paused and not force_render:
                    time.sleep(0.05)  # Sleep longer when paused
                else:
                    time.sleep(frame_delay)

            except Exception as e:
                print(f"[VS Player] Error in main loop: {e}")
                time.sleep(0.1)

        self._cleanup_resources()

    def _cleanup_resources(self):
        """Release VapourSynth resources (but keep index files)."""
        # Release clips
        self._rgb_clip = None
        self._clip = None
        self._base_clip = None
        self._core = None

        # Force garbage collection
        gc.collect()

    @Slot()
    def stop(self):
        """Stop the player thread."""
        self._is_running = False
        self.wait()
        self._cleanup_resources()

    def toggle_pause(self):
        """Toggle between paused and playing."""
        with self._lock:
            self._is_paused = not self._is_paused

    def set_paused(self, paused: bool):
        """Set the paused state."""
        with self._lock:
            self._is_paused = paused

    def seek(self, time_ms: int):
        """
        Seek to a specific time (frame-accurate).

        Args:
            time_ms: Target time in milliseconds
        """
        with self._lock:
            self._seek_request_ms = time_ms
            self._force_render_frame = True

    def seek_frame(self, frame_num: int):
        """
        Seek to a specific frame.

        Args:
            frame_num: Target frame number
        """
        with self._lock:
            self._seek_request_frame = frame_num
            self._force_render_frame = True

    def reload_subtitle_track(self, subtitle_path: Optional[str] = None):
        """
        Reload the subtitle track.

        Args:
            subtitle_path: Optional new path to subtitle file
        """
        with self._lock:
            if subtitle_path:
                self.subtitle_path = subtitle_path
            self._reload_subs_requested = True
            self._force_render_frame = True

    @property
    def frame_count(self) -> int:
        """Get total frame count."""
        return self._frame_count

    @property
    def duration_ms(self) -> int:
        """Get total duration in milliseconds."""
        return self._duration_ms
