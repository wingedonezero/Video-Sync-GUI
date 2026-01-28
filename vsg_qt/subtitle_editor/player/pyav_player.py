# vsg_qt/subtitle_editor/player/pyav_player.py
# -*- coding: utf-8 -*-
"""
FFmpeg-based video player for subtitle editor.

Uses PyAV with FFmpeg filter graph for real-time libass subtitle rendering.
Based on the original working implementation from commit e1f0dbcc.

Features:
- Real-time subtitle rendering via FFmpeg 'subtitles' filter (libass)
- Frame-accurate seeking
- Optional audio playback via sounddevice
"""
from __future__ import annotations

import gc
import time
from pathlib import Path
from threading import Lock
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, Slot, QThread
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False
    print("[PyAVPlayer] WARNING: PyAV not installed")


class PlaybackThread(QThread):
    """
    Video playback thread using PyAV with FFmpeg filter graph for subtitles.

    Based on the original working implementation - simple and reliable.
    """

    new_frame = Signal(object, float)  # QImage, timestamp_sec
    duration_changed = Signal(float)   # seconds
    time_changed = Signal(int)         # ms
    fps_detected = Signal(float)
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, video_path: str, subtitle_path: str,
                 fonts_dir: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.fonts_dir = fonts_dir

        self._container = None
        self._video_stream = None
        self._graph = None

        self._is_running = True
        self._is_paused = True  # Start paused
        self._frame_delay = 0.04
        self._fps = 23.976

        self._lock = Lock()
        self._seek_request_ms = -1
        self._reload_subs_requested = False
        self._force_render_frame = False

        self._current_time_ms = 0
        self._current_frame = 0

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def current_time_ms(self) -> int:
        return self._current_time_ms

    @property
    def current_frame(self) -> int:
        return self._current_frame

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._is_paused

    def _setup_graph(self):
        """Set up the filter graph for subtitle rendering."""
        if self._video_stream is None:
            return

        self._graph = av.filter.Graph()
        buffer_in = self._graph.add_buffer(template=self._video_stream)
        buffer_out = self._graph.add('buffersink')

        # Check if subtitle file exists
        if self.subtitle_path and Path(self.subtitle_path).exists():
            # Escape path for FFmpeg filter syntax
            escaped_path = (Path(self.subtitle_path).as_posix()
                           .replace('\\', '\\\\')
                           .replace("'", "\\'")
                           .replace(':', '\\:')
                           .replace(',', '\\,'))

            filter_args = f"filename='{escaped_path}'"

            if self.fonts_dir and Path(self.fonts_dir).exists():
                escaped_fonts_dir = (Path(self.fonts_dir).as_posix()
                                    .replace('\\', '\\\\')
                                    .replace("'", "\\'")
                                    .replace(':', '\\:')
                                    .replace(',', '\\,'))
                filter_args += f":fontsdir='{escaped_fonts_dir}'"

            print(f"[Playback] Subtitle filter: {filter_args}")
            subtitles_filter = self._graph.add(filter='subtitles', args=filter_args)
            buffer_in.link_to(subtitles_filter)
            subtitles_filter.link_to(buffer_out)
        else:
            # No subtitles - direct passthrough
            buffer_in.link_to(buffer_out)

        self._graph.configure()
        print("[Playback] Filter graph configured")

    def run(self):
        """Main thread loop."""
        if not HAS_AV:
            self.error.emit("PyAV not installed")
            return

        try:
            self._container = av.open(self.video_path, 'r')
            self._video_stream = self._container.streams.video[0]
            self._video_stream.thread_type = "AUTO"

            # Get FPS
            if self._video_stream.average_rate:
                self._fps = float(self._video_stream.average_rate)
                self._frame_delay = 1.0 / self._fps
                self.fps_detected.emit(self._fps)

            # Get duration
            duration_sec = float(self._container.duration or 0) / av.time_base
            self.duration_changed.emit(duration_sec)

            print(f"[Playback] Video: {self._video_stream.width}x{self._video_stream.height} @ {self._fps:.3f}fps")
            print(f"[Playback] Duration: {duration_sec:.2f}s")

            # Set up filter graph
            self._setup_graph()

        except Exception as e:
            self.error.emit(f"Could not open video: {e}")
            import traceback
            traceback.print_exc()
            self._is_running = False
            return

        frame_generator = self._container.decode(self._video_stream)

        while self._is_running:
            try:
                with self._lock:
                    should_seek = self._seek_request_ms >= 0
                    should_reload = self._reload_subs_requested
                    is_paused = self._is_paused
                    seek_ms = self._seek_request_ms

                # Handle subtitle reload
                if should_reload:
                    self._setup_graph()
                    with self._lock:
                        self._reload_subs_requested = False
                        self._force_render_frame = True

                # Handle seek
                if should_seek:
                    try:
                        seek_pts = int(seek_ms / 1000 / self._video_stream.time_base)
                        self._container.seek(seek_pts, stream=self._video_stream, backward=True)
                        frame_generator = self._container.decode(self._video_stream)
                        self._setup_graph()
                        print(f"[Playback] Seeked to {seek_ms:.0f}ms")
                    except Exception as e:
                        print(f"[Playback] Seek error: {e}")
                    finally:
                        with self._lock:
                            self._seek_request_ms = -1

                with self._lock:
                    force_render = self._force_render_frame
                    if force_render:
                        self._force_render_frame = False

                # If paused and no seek/force render, just sleep
                if is_paused and not should_seek and not force_render:
                    time.sleep(0.05)
                    continue

                # Decode and render frame
                frame = next(frame_generator)

                # Get timestamp
                if frame.pts is not None:
                    timestamp_sec = float(frame.pts * frame.time_base)
                else:
                    timestamp_sec = self._current_frame / self._fps

                self._current_time_ms = int(timestamp_sec * 1000)
                self._current_frame = int(timestamp_sec * self._fps)

                # Apply filter graph (renders subtitles)
                if self._graph:
                    self._graph.push(frame)
                    filtered_frame = self._graph.pull()
                else:
                    filtered_frame = frame

                # Convert to QImage
                pil_img = filtered_frame.to_image()
                rgb_img = pil_img.convert('RGB')
                q_image = QImage(
                    rgb_img.tobytes(),
                    rgb_img.width,
                    rgb_img.height,
                    rgb_img.width * 3,
                    QImage.Format_RGB888
                )

                # Emit frame
                self.new_frame.emit(q_image.copy(), timestamp_sec)
                self.time_changed.emit(self._current_time_ms)

            except (StopIteration, av.error.EOFError):
                self.playback_finished.emit()
                with self._lock:
                    self._is_paused = True
                break
            except av.error.ExitError:
                # Filter graph needs rebuild after seek
                continue
            except Exception as e:
                print(f"[Playback] Error: {e}")
                time.sleep(0.01)
                continue

            # Frame timing
            delay = self._frame_delay if not is_paused else 0.001
            time.sleep(max(delay, 0.001))

        self._cleanup()

    def _cleanup(self):
        """Clean up resources."""
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
        print("[Playback] Cleaned up")

    @Slot()
    def stop(self):
        """Stop the player thread."""
        self._is_running = False
        self.wait(2000)
        self._cleanup()

    def toggle_pause(self):
        """Toggle pause state."""
        with self._lock:
            self._is_paused = not self._is_paused

    def set_paused(self, paused: bool):
        """Set pause state."""
        with self._lock:
            self._is_paused = paused

    def seek(self, time_ms: int):
        """Seek to time in milliseconds."""
        with self._lock:
            self._seek_request_ms = time_ms
            if self._is_paused:
                self._force_render_frame = True

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload subtitle track."""
        with self._lock:
            if subtitle_path:
                self.subtitle_path = subtitle_path
            if self._graph:
                self._reload_subs_requested = True


class PyAVPlayer(QWidget):
    """
    FFmpeg-based video player widget.

    Uses PyAV with FFmpeg filter graph for real-time libass subtitle rendering.
    Drop-in replacement for MpvWidget.

    Signals:
        time_changed: Current time in milliseconds
        duration_changed: Duration in seconds
        fps_detected: FPS detected
        playback_finished: Video ended
        frame_changed: Current frame number
    """

    time_changed = Signal(int)
    duration_changed = Signal(float)
    fps_detected = Signal(float)
    playback_finished = Signal()
    frame_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player: Optional[PlaybackThread] = None

        # State
        self._duration_sec: float = 0
        self._fps: float = 23.976
        self._is_paused: bool = True
        self._current_time_ms: int = 0
        self._current_frame: int = 0

        # Paths
        self._video_path: Optional[str] = None
        self._subtitle_path: Optional[str] = None
        self._fonts_dir: Optional[str] = None

        self._setup_ui()

    def _setup_ui(self):
        """Set up display."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._display = QLabel()
        self._display.setAlignment(Qt.AlignCenter)
        self._display.setStyleSheet("background-color: black;")
        self._display.setMinimumSize(320, 180)
        self._display.setScaledContents(False)
        layout.addWidget(self._display)

    def load_video(self, video_path: str, subtitle_path: Optional[str] = None,
                   fonts_dir: Optional[str] = None, index_dir: Optional[str] = None):
        """Load a video file."""
        self._video_path = video_path
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

        print(f"[PyAVPlayer] Loading: {video_path}")
        if subtitle_path:
            print(f"[PyAVPlayer] Subtitle: {subtitle_path}")

        # Stop existing
        self.stop()

        # Create player thread
        self._player = PlaybackThread(
            video_path=video_path,
            subtitle_path=subtitle_path,
            fonts_dir=fonts_dir,
            parent=self
        )
        self._player.new_frame.connect(self._on_new_frame)
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.time_changed.connect(self._on_time_changed)
        self._player.fps_detected.connect(self._on_fps_detected)
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.error.connect(self._on_error)
        self._player.start()

    @Slot(object, float)
    def _on_new_frame(self, qimage: QImage, timestamp_sec: float):
        """Handle frame from player."""
        self._current_time_ms = int(timestamp_sec * 1000)
        if self._player:
            self._current_frame = self._player.current_frame

        # Scale and display
        display_size = self._display.size()
        scaled = qimage.scaled(
            display_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._display.setPixmap(QPixmap.fromImage(scaled))

        # Emit frame changed
        self.frame_changed.emit(self._current_frame)

    @Slot(float)
    def _on_duration_changed(self, duration_sec: float):
        """Handle duration."""
        self._duration_sec = duration_sec
        self.duration_changed.emit(duration_sec)

    @Slot(int)
    def _on_time_changed(self, time_ms: int):
        """Handle time update."""
        self._current_time_ms = time_ms
        self.time_changed.emit(time_ms)

    @Slot(float)
    def _on_fps_detected(self, fps: float):
        """Handle FPS."""
        self._fps = fps
        self.fps_detected.emit(fps)

    @Slot()
    def _on_playback_finished(self):
        """Handle end of video."""
        self._is_paused = True
        self.playback_finished.emit()

    @Slot(str)
    def _on_error(self, error: str):
        """Handle error."""
        print(f"[PyAVPlayer] ERROR: {error}")

    def play(self):
        """Start playback."""
        self._is_paused = False
        if self._player:
            self._player.set_paused(False)

    def pause(self):
        """Pause playback."""
        self._is_paused = True
        if self._player:
            self._player.set_paused(True)

    def toggle_pause(self):
        """Toggle play/pause."""
        if self._player:
            self._player.toggle_pause()
            self._is_paused = self._player.is_paused

    def seek(self, time_ms: int, precise: bool = True):
        """Seek to time in milliseconds."""
        if self._player:
            self._player.seek(time_ms)

    def seek_frame(self, frame_num: int):
        """Seek to specific frame number."""
        if self._fps > 0:
            time_ms = int(frame_num * 1000.0 / self._fps)
            self.seek(time_ms)

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload subtitles."""
        if subtitle_path:
            self._subtitle_path = subtitle_path
        if self._player:
            self._player.reload_subtitles(self._subtitle_path)

    @property
    def is_paused(self) -> bool:
        if self._player:
            return self._player.is_paused
        return self._is_paused

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def duration_ms(self) -> int:
        return int(self._duration_sec * 1000)

    @property
    def current_frame(self) -> int:
        return self._current_frame

    def stop(self):
        """Stop and cleanup."""
        if self._player:
            print("[PyAVPlayer] Stopping...")
            self._player.stop()
            self._player = None
            self._display.clear()
            gc.collect()
            print("[PyAVPlayer] Stopped")

    def closeEvent(self, event):
        """Handle close."""
        self.stop()
        super().closeEvent(event)
