# vsg_qt/subtitle_editor/video_panel.py
# -*- coding: utf-8 -*-
"""
Video panel widget for subtitle editor.

Contains:
- FFmpeg/VapourSynth-based video display with libass subtitle rendering
- Audio playback via PyAV + sounddevice
- Frame-accurate seeking with precise time<->frame conversion
- Playback controls (play/pause, seek slider)
- Time and frame display
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)

from .utils import ms_to_ass_time
from .player.pyav_player import PyAVPlayer
from .player.frame_index import FrameIndex

if TYPE_CHECKING:
    from .state import EditorState


class VideoPanel(QWidget):
    """
    Video panel with FFmpeg-based playback and controls.

    Uses VapourSynth for frame-accurate video with libass subtitles,
    and PyAV for audio playback.

    Key feature: Click subtitle → seek to exact start frame.

    Signals:
        seek_requested: Emitted when user requests seek via slider
        playback_toggled: Emitted when play/pause is clicked
        frame_changed: Emitted when current frame changes
    """

    seek_requested = Signal(int)  # time in ms
    playback_toggled = Signal()
    frame_changed = Signal(int)   # frame number

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: Optional['EditorState'] = None
        self._duration_ms: int = 0
        self._is_seeking: bool = False
        self._frame_index: Optional[FrameIndex] = None
        self._current_frame: int = 0

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the video panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Video display widget (PyAV/VapourSynth based)
        self._player = PyAVPlayer()
        layout.addWidget(self._player, 1)

        # Playback controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        # Play/Pause button
        self._play_btn = QPushButton("Play")
        self._play_btn.setFixedWidth(60)
        self._play_btn.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self._play_btn)

        # Frame step buttons
        self._prev_frame_btn = QPushButton("◀")
        self._prev_frame_btn.setFixedWidth(30)
        self._prev_frame_btn.setToolTip("Previous frame")
        self._prev_frame_btn.clicked.connect(self._on_prev_frame)
        controls_layout.addWidget(self._prev_frame_btn)

        self._next_frame_btn = QPushButton("▶")
        self._next_frame_btn.setFixedWidth(30)
        self._next_frame_btn.setToolTip("Next frame")
        self._next_frame_btn.clicked.connect(self._on_next_frame)
        controls_layout.addWidget(self._next_frame_btn)

        # Seek slider
        self._seek_slider = QSlider(Qt.Horizontal)
        self._seek_slider.setRange(0, 1000)
        self._seek_slider.sliderPressed.connect(self._on_slider_pressed)
        self._seek_slider.sliderReleased.connect(self._on_slider_released)
        self._seek_slider.sliderMoved.connect(self._on_slider_moved)
        controls_layout.addWidget(self._seek_slider, 1)

        # Time display
        self._time_label = QLabel("0:00:00.00 / 0:00:00.00")
        self._time_label.setStyleSheet("font-family: monospace;")
        controls_layout.addWidget(self._time_label)

        # Frame display
        self._frame_label = QLabel("F: 0")
        self._frame_label.setStyleSheet("font-family: monospace; color: #888;")
        self._frame_label.setFixedWidth(80)
        controls_layout.addWidget(self._frame_label)

        layout.addLayout(controls_layout)

    def _connect_signals(self):
        """Connect player signals."""
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.time_changed.connect(self._on_time_changed)
        self._player.fps_detected.connect(self._on_fps_detected)
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.frame_changed.connect(self._on_frame_changed)

    def set_state(self, state: 'EditorState'):
        """Set the editor state."""
        self._state = state

    def start_player(self, video_path: str, subtitle_path: str,
                     index_dir: str, fonts_dir: Optional[str] = None):
        """
        Start the video player.

        Args:
            video_path: Path to video file
            subtitle_path: Path to subtitle file for overlay
            index_dir: Directory for VS index cache (used for frame-accurate seeking)
            fonts_dir: Optional path to fonts directory
        """
        print(f"[VideoPanel] Starting player")
        print(f"[VideoPanel] Video: {video_path}")
        print(f"[VideoPanel] Subtitle: {subtitle_path}")
        print(f"[VideoPanel] Index dir: {index_dir}")
        if fonts_dir:
            print(f"[VideoPanel] Fonts dir: {fonts_dir}")

        # Load frame index for precise time<->frame conversion
        self._frame_index = FrameIndex(video_path, Path(index_dir))
        if self._frame_index.is_loaded:
            print(f"[VideoPanel] Frame index loaded: {self._frame_index.frame_count} frames @ {self._frame_index.fps:.3f} fps")

        # Start the player
        self._player.load_video(
            video_path=video_path,
            subtitle_path=subtitle_path,
            fonts_dir=fonts_dir,
            index_dir=index_dir
        )

    def stop_player(self):
        """Stop and clean up the player."""
        self._player.stop()
        self._frame_index = None

    def seek_to_time(self, time_ms: float, use_frame_index: bool = True):
        """
        Seek to a specific time in milliseconds.

        Uses FrameIndex for precise time→frame conversion to ensure
        we land on the exact frame containing this timestamp.

        Args:
            time_ms: Target time in milliseconds
            use_frame_index: Use FrameIndex for precise frame lookup (default True)
        """
        if use_frame_index and self._frame_index and self._frame_index.is_loaded:
            # Use VideoTimestamps for precise frame lookup
            frame = self._frame_index.ms_to_frame(time_ms)
            print(f"[VideoPanel] Seek to {time_ms:.2f}ms → frame {frame}")
            self._player.seek_frame(frame)
        else:
            # Fallback to time-based seek
            self._player.seek(int(time_ms))

    def seek_to_frame(self, frame_num: int):
        """
        Seek to a specific frame number (frame-accurate).

        This is the most precise seek method - use this when
        clicking subtitles to get the exact start frame.

        Args:
            frame_num: Target frame number (0-indexed)
        """
        print(f"[VideoPanel] Seek to frame {frame_num}")
        self._player.seek_frame(frame_num)

    def seek_to(self, time_ms: int, precise: bool = True):
        """
        Seek to a specific time (backwards compatible API).

        Args:
            time_ms: Target time in milliseconds
            precise: Use frame-accurate seeking (default True)
        """
        self.seek_to_time(float(time_ms), use_frame_index=precise)

    def get_frame_for_time(self, time_ms: float) -> int:
        """
        Get the frame number that contains the given time.

        Useful for determining which frame a subtitle starts on,
        even when the subtitle time is in the middle of a frame.

        Args:
            time_ms: Time in milliseconds

        Returns:
            Frame number (0-indexed)
        """
        if self._frame_index and self._frame_index.is_loaded:
            return self._frame_index.ms_to_frame(time_ms)
        elif self._player.fps > 0:
            return int(time_ms * self._player.fps / 1000.0)
        return 0

    def get_time_for_frame(self, frame_num: int) -> float:
        """
        Get the start time of a specific frame.

        Args:
            frame_num: Frame number (0-indexed)

        Returns:
            Time in milliseconds
        """
        if self._frame_index and self._frame_index.is_loaded:
            return self._frame_index.frame_to_ms(frame_num)
        elif self._player.fps > 0:
            return frame_num * 1000.0 / self._player.fps
        return 0.0

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload the subtitle track."""
        self._player.reload_subtitles(subtitle_path)

    def _on_duration_changed(self, duration_sec: float):
        """Handle duration change."""
        self._duration_ms = int(duration_sec * 1000)
        self._seek_slider.setRange(0, self._duration_ms)
        self._update_time_display(0)
        print(f"[VideoPanel] Duration: {duration_sec:.2f}s")

    def _on_time_changed(self, time_ms: int):
        """Handle playback time change."""
        if not self._is_seeking:
            self._seek_slider.setValue(time_ms)
        self._update_time_display(time_ms)

    def _on_frame_changed(self, frame_num: int):
        """Handle frame number change."""
        self._current_frame = frame_num
        self._frame_label.setText(f"F: {frame_num}")
        self.frame_changed.emit(frame_num)

    def _on_fps_detected(self, fps: float):
        """Handle FPS detection."""
        print(f"[VideoPanel] FPS detected: {fps:.3f}")
        if self._state:
            self._state.set_video_fps(fps)

    def _on_playback_finished(self):
        """Handle end of playback."""
        self._play_btn.setText("Play")

    def _update_time_display(self, current_ms: int):
        """Update the time display label."""
        current = ms_to_ass_time(current_ms)
        total = ms_to_ass_time(self._duration_ms)
        self._time_label.setText(f"{current} / {total}")

    def _on_play_clicked(self):
        """Handle play/pause button click."""
        self._player.toggle_pause()
        is_paused = self._player.is_paused
        self._play_btn.setText("Play" if is_paused else "Pause")
        self.playback_toggled.emit()

    def _on_prev_frame(self):
        """Go to previous frame."""
        if self._current_frame > 0:
            self._player.seek_frame(self._current_frame - 1)

    def _on_next_frame(self):
        """Go to next frame."""
        self._player.seek_frame(self._current_frame + 1)

    def _on_slider_pressed(self):
        """Handle slider press (start seeking)."""
        self._is_seeking = True

    def _on_slider_released(self):
        """Handle slider release (complete seek)."""
        self._is_seeking = False
        self.seek_to_time(float(self._seek_slider.value()))

    def _on_slider_moved(self, value: int):
        """Handle slider movement during drag."""
        self._update_time_display(value)

    @property
    def player(self) -> PyAVPlayer:
        """Get the player widget for direct access."""
        return self._player

    @property
    def current_frame(self) -> int:
        """Get current frame number."""
        return self._current_frame

    @property
    def frame_index(self) -> Optional[FrameIndex]:
        """Get the frame index for external use."""
        return self._frame_index
