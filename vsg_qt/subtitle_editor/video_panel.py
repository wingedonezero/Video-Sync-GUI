# vsg_qt/subtitle_editor/video_panel.py
# -*- coding: utf-8 -*-
"""
Video panel widget for subtitle editor.

Contains:
- Video display area
- Playback controls (play/pause, seek slider)
- Time display
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel
)

from .utils import ms_to_ass_time
from .player import PlayerThread

if TYPE_CHECKING:
    from .state import EditorState


class VideoWidget(QWidget):
    """Widget that displays video frames, scaling to fit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self.setMinimumSize(320, 180)

    def set_pixmap(self, pixmap: QPixmap):
        """Set the pixmap to display."""
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        """Paint the video frame scaled to fit."""
        super().paintEvent(event)
        if self._pixmap is None:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # Scale pixmap to fit widget while maintaining aspect ratio
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )

        # Center the scaled pixmap
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class VideoPanel(QWidget):
    """
    Video panel with playback controls.

    Signals:
        seek_requested: Emitted when user requests seek via slider
        playback_toggled: Emitted when play/pause is clicked
    """

    seek_requested = Signal(int)  # time in ms
    playback_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: Optional['EditorState'] = None
        self._player: Optional[PlayerThread] = None
        self._duration_ms: int = 0
        self._is_seeking: bool = False

        self._setup_ui()

    def _setup_ui(self):
        """Set up the video panel UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Video display
        self._video_widget = VideoWidget()
        layout.addWidget(self._video_widget, 1)

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

    def set_state(self, state: 'EditorState'):
        """Set the editor state."""
        self._state = state

    def start_player(self, video_path: str, subtitle_path: str, fonts_dir: Optional[str] = None):
        """
        Start the video player.

        Args:
            video_path: Path to video file
            subtitle_path: Path to subtitle file for overlay
            fonts_dir: Optional path to fonts directory
        """
        # Stop existing player if any
        self.stop_player()

        self._player = PlayerThread(
            video_path=video_path,
            subtitle_path=subtitle_path,
            widget_win_id=self._video_widget.winId(),
            fonts_dir=fonts_dir,
            parent=self
        )

        # Connect signals
        self._player.new_frame.connect(self._on_new_frame)
        self._player.duration_changed.connect(self._on_duration_changed)
        self._player.time_changed.connect(self._on_time_changed)
        self._player.fps_detected.connect(self._on_fps_detected)

        # Start player (starts paused)
        self._player.start()

    def stop_player(self):
        """Stop and clean up the player."""
        if self._player:
            self._player.stop()
            self._player = None

    def seek_to(self, time_ms: int):
        """
        Seek to a specific time.

        Args:
            time_ms: Target time in milliseconds
        """
        if self._player:
            self._player.seek(time_ms)

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """
        Reload the subtitle track.

        Args:
            subtitle_path: Optional new path to subtitle file
        """
        if self._player:
            self._player.reload_subtitle_track(subtitle_path)

    def _on_new_frame(self, image: QImage, timestamp: float):
        """Handle new video frame."""
        pixmap = QPixmap.fromImage(image)
        self._video_widget.set_pixmap(pixmap)

    def _on_duration_changed(self, duration_sec: float):
        """Handle duration change."""
        self._duration_ms = int(duration_sec * 1000)
        self._seek_slider.setRange(0, self._duration_ms)
        self._update_time_display(0)

    def _on_time_changed(self, time_ms: int):
        """Handle playback time change."""
        if not self._is_seeking:
            self._seek_slider.setValue(time_ms)
        self._update_time_display(time_ms)

    def _on_fps_detected(self, fps: float):
        """Handle FPS detection."""
        if self._state:
            self._state.set_video_fps(fps)

    def _update_time_display(self, current_ms: int):
        """Update the time display label."""
        current = ms_to_ass_time(current_ms)
        total = ms_to_ass_time(self._duration_ms)
        self._time_label.setText(f"{current} / {total}")

    def _on_play_clicked(self):
        """Handle play/pause button click."""
        if self._player:
            self._player.toggle_pause()
            is_paused = self._player.is_paused
            self._play_btn.setText("Play" if is_paused else "Pause")
            self.playback_toggled.emit()

    def _on_slider_pressed(self):
        """Handle slider press (start seeking)."""
        self._is_seeking = True

    def _on_slider_released(self):
        """Handle slider release (complete seek)."""
        self._is_seeking = False
        if self._player:
            self._player.seek(self._seek_slider.value())

    def _on_slider_moved(self, value: int):
        """Handle slider movement during drag."""
        self._update_time_display(value)

    @property
    def video_widget(self) -> VideoWidget:
        """Get the video widget for embedding."""
        return self._video_widget
