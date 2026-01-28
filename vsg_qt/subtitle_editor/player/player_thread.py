# vsg_qt/subtitle_editor/player/player_thread.py
# -*- coding: utf-8 -*-
"""
Video player thread for subtitle editor.

Handles video decoding and subtitle overlay rendering using PyAV and libass.
Simple and reliable implementation.
"""
import gc
import time
from pathlib import Path
from threading import Lock
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QImage

import av


class PlayerThread(QThread):
    """
    Video playback thread with subtitle rendering.

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

    def __init__(self, video_path: str, subtitle_path: str, widget_win_id,
                 fonts_dir: str | None, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.fonts_dir = fonts_dir

        self._container = None
        self._video_stream = None
        self._graph = None

        self._is_running = True
        self._is_paused = True  # Start paused by default
        self._frame_delay = 0.0
        self._fps = 23.976  # Default, will be updated

        self._lock = Lock()
        self._seek_request_ms = -1
        self._reload_subs_requested = False
        self._force_render_frame = False

        # Current position tracking
        self._current_time_ms = 0

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

    def _setup_graph(self):
        """Set up the filter graph for subtitle rendering."""
        self._graph = av.filter.Graph()
        buffer_in = self._graph.add_buffer(template=self._video_stream)
        buffer_out = self._graph.add('buffersink')

        escaped_path = (Path(self.subtitle_path).as_posix()
                       .replace('\\', '\\\\')
                       .replace("'", "\\'")
                       .replace(':', '\\:')
                       .replace(',', '\\,'))

        filter_args = f"filename='{escaped_path}'"
        if self.fonts_dir:
            escaped_fonts_dir = (Path(self.fonts_dir).as_posix()
                                .replace('\\', '\\\\')
                                .replace("'", "\\'")
                                .replace(':', '\\:')
                                .replace(',', '\\,'))
            filter_args += f":fontsdir='{escaped_fonts_dir}'"

        subtitles_filter = self._graph.add(filter='subtitles', args=filter_args)
        buffer_in.link_to(subtitles_filter)
        subtitles_filter.link_to(buffer_out)
        self._graph.configure()

    def run(self):
        """Main thread loop."""
        try:
            self._container = av.open(self.video_path, 'r')
            self._video_stream = self._container.streams.video[0]
            self._video_stream.thread_type = "AUTO"

            if self._video_stream.average_rate:
                self._fps = float(self._video_stream.average_rate)
                self._frame_delay = 1.0 / self._fps
                self.fps_detected.emit(self._fps)

            duration_sec = float(self._container.duration or 0) / av.time_base
            self.duration_changed.emit(duration_sec)
            self._setup_graph()

        except Exception as e:
            print(f"FATAL: Could not open media or build filter graph: {e}")
            self._is_running = False
            return

        frame_generator = self._container.decode(self._video_stream)

        while self._is_running:
            try:
                with self._lock:
                    should_seek = self._seek_request_ms >= 0
                    should_reload = self._reload_subs_requested
                    is_paused = self._is_paused

                if should_reload:
                    self._setup_graph()
                    with self._lock:
                        self._reload_subs_requested = False
                        self._force_render_frame = True

                if should_seek:
                    target_ms = self._seek_request_ms
                    with self._lock:
                        self._seek_request_ms = -1

                    try:
                        # Seek to keyframe before target
                        seek_pts = int(target_ms / 1000 / self._video_stream.time_base)
                        self._container.seek(seek_pts, stream=self._video_stream, backward=True)
                        frame_generator = self._container.decode(self._video_stream)
                        self._setup_graph()

                        # Decode forward until we reach the frame containing target time
                        # Frame duration in ms
                        frame_duration_ms = 1000.0 / self._fps if self._fps > 0 else 41.7
                        target_frame = None
                        target_timestamp_sec = 0.0

                        for frame in frame_generator:
                            if frame.pts is None:
                                continue
                            timestamp_sec = float(frame.pts * frame.time_base)
                            frame_time_ms = timestamp_sec * 1000

                            # Push through subtitle filter to keep it in sync
                            self._graph.push(frame)
                            filtered_frame = self._graph.pull()

                            # Check if this frame contains or is past target time
                            # A frame "contains" a time if: frame_start <= time < frame_start + duration
                            if frame_time_ms + frame_duration_ms > target_ms:
                                target_frame = filtered_frame
                                target_timestamp_sec = timestamp_sec
                                break

                        if target_frame:
                            # Render the target frame
                            pillow_img = target_frame.to_image()
                            rgb_img = pillow_img.convert('RGB')
                            q_image = QImage(rgb_img.tobytes(), rgb_img.width, rgb_img.height,
                                            QImage.Format_RGB888)

                            self._current_time_ms = int(target_timestamp_sec * 1000)
                            self.new_frame.emit(q_image, target_timestamp_sec)
                            self.time_changed.emit(self._current_time_ms)

                        # Create fresh generator from current position for continued playback
                        frame_generator = self._container.decode(self._video_stream)

                    except Exception as e:
                        print(f"Error during seek: {e}")
                        import traceback
                        traceback.print_exc()

                    continue  # Skip normal frame processing after seek

                with self._lock:
                    force_render = self._force_render_frame
                    if force_render:
                        self._force_render_frame = False

                if is_paused and not force_render:
                    time.sleep(0.05)
                    continue

                frame = next(frame_generator)
                if frame.pts is None:
                    continue
                timestamp_sec = float(frame.pts * frame.time_base)
                self._current_time_ms = int(timestamp_sec * 1000)

                self._graph.push(frame)
                filtered_frame = self._graph.pull()
                pillow_img = filtered_frame.to_image()
                rgb_img = pillow_img.convert('RGB')
                q_image = QImage(rgb_img.tobytes(), rgb_img.width, rgb_img.height,
                                QImage.Format_RGB888)

                self.new_frame.emit(q_image, timestamp_sec)
                self.time_changed.emit(self._current_time_ms)

            except (StopIteration, av.error.EOFError):
                self.playback_finished.emit()
                break
            except av.error.EAGAIN:
                time.sleep(0.005)
                continue

            delay = self._frame_delay
            time.sleep(delay if delay > 0.001 else 0.001)

        self._cleanup_resources()

    def _cleanup_resources(self):
        """Explicitly free PyAV resources to prevent memory leaks."""
        if self._graph is not None:
            try:
                del self._graph
            except Exception:
                pass
            self._graph = None

        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None

        self._video_stream = None
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
        Seek to a specific time.

        Works both when playing and when paused.

        Args:
            time_ms: Target time in milliseconds
        """
        with self._lock:
            self._seek_request_ms = time_ms
            # Force a frame render after seeking while paused
            if self._is_paused:
                self._force_render_frame = True

    def reload_subtitle_track(self, subtitle_path: str | None = None):
        """
        Reload the subtitle track.

        Args:
            subtitle_path: Optional new path to subtitle file
        """
        with self._lock:
            if subtitle_path:
                self.subtitle_path = subtitle_path
            if self._graph:
                self._reload_subs_requested = True
