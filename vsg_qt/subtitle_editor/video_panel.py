# vsg_qt/subtitle_editor/video_panel.py
# -*- coding: utf-8 -*-
"""
Video panel widget for subtitle editor.

Contains:
- MPV-based video display with OpenGL rendering
- Playback controls (play/pause, seek slider)
- Time display
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)

from .utils import ms_to_ass_time
from .player.mpv_player import MpvWidget
from .player.frame_index import FrameIndex

if TYPE_CHECKING:
    from .state import EditorState


class VideoPanel(QWidget):
    """
    Video panel with MPV-based playback and controls.

    Uses MPV with OpenGL render API for native Wayland support
    and libass for accurate subtitle rendering.

    Signals:
        seek_requested: Emitted when user requests seek via slider
        playback_toggled: Emitted when play/pause is clicked
    """

    seek_requested = Signal(int)  # time in ms
    playback_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: Optional['EditorState'] = None
        self._duration_ms: int = 0
        self._is_seeking: bool = False
        self._frame_index: Optional[FrameIndex] = None

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        """Set up the video panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # MPV OpenGL video widget
        self._mpv_widget = MpvWidget()
        layout.addWidget(self._mpv_widget, 1)

        # Playback controls
        controls_layout = QHBoxLayout()
        controls_layout.setSpacing(8)

        # Play/Pause button
        self._play_btn = QPushButton("Play")
        self._play_btn.setFixedWidth(60)
        self._play_btn.clicked.connect(self._on_play_clicked)
        controls_layout.addWidget(self._play_btn)

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

        layout.addLayout(controls_layout)

    def _connect_signals(self):
        """Connect MPV widget signals."""
        self._mpv_widget.duration_changed.connect(self._on_duration_changed)
        self._mpv_widget.time_changed.connect(self._on_time_changed)
        self._mpv_widget.fps_detected.connect(self._on_fps_detected)
        self._mpv_widget.playback_finished.connect(self._on_playback_finished)

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
        print(f"[VideoPanel] Starting MPV player")
        print(f"[VideoPanel] Video: {video_path}")
        print(f"[VideoPanel] Subtitle: {subtitle_path}")
        print(f"[VideoPanel] Index dir: {index_dir}")
        if fonts_dir:
            print(f"[VideoPanel] Fonts dir: {fonts_dir}")

        # Load VS frame index for accurate frame-based seeking
        self._frame_index = FrameIndex(video_path, Path(index_dir))
        if self._frame_index.is_loaded:
            print(f"[VideoPanel] Frame index loaded: {self._frame_index.frame_count} frames @ {self._frame_index.fps:.3f} fps")

        self._mpv_widget.load_video(
            video_path=video_path,
            subtitle_path=subtitle_path,
            fonts_dir=fonts_dir
        )

    def stop_player(self):
        """Stop and clean up the player."""
        self._mpv_widget.stop()
        self._frame_index = None

    def seek_to(self, time_ms: int, precise: bool = True):
        """Seek to a specific time with frame accuracy.

        Uses VapourSynth index for accurate frame lookup, then seeks
        MPV to that exact frame number.

        Args:
            time_ms: Target time in milliseconds
            precise: Use frame-based seeking (default True for subtitle editing)
        """
        if precise and self._frame_index and self._frame_index.is_loaded:
            # Use VS index for frame-accurate seeking
            frame = self._frame_index.ms_to_frame(time_ms)
            self._mpv_widget.seek_frame(frame)
        else:
            # Fallback to time-based seeking
            self._mpv_widget.seek(time_ms, precise=precise)

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload the subtitle track."""
        self._mpv_widget.reload_subtitles(subtitle_path)

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
        self._mpv_widget.toggle_pause()
        is_paused = self._mpv_widget.is_paused
        self._play_btn.setText("Play" if is_paused else "Pause")
        self.playback_toggled.emit()

    def _on_slider_pressed(self):
        """Handle slider press (start seeking)."""
        self._is_seeking = True

    def _on_slider_released(self):
        """Handle slider release (complete seek)."""
        self._is_seeking = False
        self._mpv_widget.seek(self._seek_slider.value())

    def _on_slider_moved(self, value: int):
        """Handle slider movement during drag."""
        self._update_time_display(value)

    @property
    def mpv_widget(self) -> MpvWidget:
        """Get the MPV widget for direct access."""
        return self._mpv_widget
