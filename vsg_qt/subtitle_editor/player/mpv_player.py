# vsg_qt/subtitle_editor/player/mpv_player.py
# -*- coding: utf-8 -*-
"""
MPV-based video player for subtitle editor.

Uses MPV for video playback and subtitle rendering (libass built-in).
Optionally uses VapourSynth index for frame-accurate time mapping.
"""
import locale
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import Qt, Signal, QTimer, QObject
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame

import mpv


class MpvEventHandler(QObject):
    """
    Handles MPV events and emits Qt signals.
    """
    time_changed = Signal(float)  # Current time in seconds
    duration_changed = Signal(float)  # Duration in seconds
    fps_detected = Signal(float)  # Video FPS
    eof_reached = Signal()  # End of file
    file_loaded = Signal()  # File loaded successfully

    def __init__(self, parent=None):
        super().__init__(parent)


class MpvWidget(QWidget):
    """
    Qt widget that embeds an MPV player.

    Signals:
        time_changed: Emitted with current time in milliseconds
        duration_changed: Emitted with duration in seconds
        fps_detected: Emitted when FPS is detected
        playback_finished: Emitted when video ends
    """

    time_changed = Signal(int)  # ms
    duration_changed = Signal(float)  # seconds
    fps_detected = Signal(float)
    playback_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._player: Optional[mpv.MPV] = None
        self._duration_sec: float = 0
        self._fps: float = 23.976
        self._is_paused: bool = True
        self._subtitle_path: Optional[str] = None
        self._fonts_dir: Optional[str] = None

        # Timer for polling time position
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_time_position)
        self._poll_timer.setInterval(50)  # 50ms = 20 updates/sec

        self._setup_ui()

    def _setup_ui(self):
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Container frame for MPV
        self._video_frame = QFrame()
        self._video_frame.setStyleSheet("background-color: black;")
        self._video_frame.setMinimumSize(320, 180)
        layout.addWidget(self._video_frame)

    def _create_player(self):
        """Create and configure the MPV player instance."""
        # Fix locale for MPV
        locale.setlocale(locale.LC_NUMERIC, 'C')

        # Get window ID for embedding
        wid = int(self._video_frame.winId())

        # Create MPV instance with embedding
        self._player = mpv.MPV(
            wid=wid,
            # Video settings
            vo='gpu',  # Use GPU rendering
            hwdec='auto',  # Hardware decoding
            # Seeking settings for accuracy
            hr_seek='yes',  # High-resolution seeking
            hr_seek_framedrop='no',  # Don't drop frames when seeking
            # Subtitle settings
            sub_auto='fuzzy',  # Auto-load subtitles
            sub_ass=True,  # Enable ASS rendering
            # Keep video paused on load
            pause=True,
            keep_open=True,  # Keep player open at EOF
            # Disable OSD for cleaner look
            osd_level=0,
            # Log level
            log_handler=print,
            loglevel='warn'
        )

        # Set fonts directory if provided
        if self._fonts_dir:
            self._player['sub-fonts-dir'] = self._fonts_dir

        # Register event observers
        @self._player.property_observer('duration')
        def on_duration(name, value):
            if value is not None:
                self._duration_sec = value
                self.duration_changed.emit(value)

        @self._player.property_observer('container-fps')
        def on_fps(name, value):
            if value is not None and value > 0:
                self._fps = value
                self.fps_detected.emit(value)

        @self._player.property_observer('eof-reached')
        def on_eof(name, value):
            if value:
                self.playback_finished.emit()

        @self._player.property_observer('pause')
        def on_pause(name, value):
            self._is_paused = value

    def load_video(self, video_path: str, subtitle_path: Optional[str] = None,
                   fonts_dir: Optional[str] = None):
        """
        Load a video file with optional subtitle overlay.

        Args:
            video_path: Path to video file
            subtitle_path: Optional path to subtitle file
            fonts_dir: Optional path to fonts directory for ASS rendering
        """
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

        # Create player if needed
        if self._player is None:
            self._create_player()

        # Set fonts directory
        if fonts_dir:
            self._player['sub-fonts-dir'] = fonts_dir

        # Load video
        self._player.loadfile(video_path)

        # Wait for file to load, then add subtitle
        @self._player.event_callback('file-loaded')
        def on_file_loaded(event):
            if subtitle_path:
                self._player.sub_add(subtitle_path)
            # Seek to start and render first frame
            self._player.seek(0, 'absolute')
            # Start polling timer
            self._poll_timer.start()

    def play(self):
        """Start playback."""
        if self._player:
            self._player.pause = False

    def pause(self):
        """Pause playback."""
        if self._player:
            self._player.pause = True

    def toggle_pause(self):
        """Toggle between play and pause."""
        if self._player:
            self._player.pause = not self._player.pause

    def seek(self, time_ms: int):
        """
        Seek to a specific time.

        Args:
            time_ms: Target time in milliseconds
        """
        if self._player:
            time_sec = time_ms / 1000.0
            self._player.seek(time_sec, 'absolute', 'exact')

    def seek_frame(self, frame_num: int):
        """
        Seek to a specific frame.

        Args:
            frame_num: Target frame number
        """
        if self._player and self._fps > 0:
            time_sec = frame_num / self._fps
            self._player.seek(time_sec, 'absolute', 'exact')

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """
        Reload the subtitle track.

        Args:
            subtitle_path: Optional new path to subtitle file
        """
        if self._player:
            if subtitle_path:
                self._subtitle_path = subtitle_path

            # Remove existing subtitle tracks
            try:
                # Get current sub track count
                track_count = self._player.track_list
                for track in track_count:
                    if track.get('type') == 'sub' and track.get('external'):
                        self._player.sub_remove(track.get('id'))
            except Exception:
                pass

            # Add new subtitle
            if self._subtitle_path:
                self._player.sub_add(self._subtitle_path)

    def _poll_time_position(self):
        """Poll current time position and emit signal."""
        if self._player:
            try:
                time_pos = self._player.time_pos
                if time_pos is not None:
                    self.time_changed.emit(int(time_pos * 1000))
            except Exception:
                pass

    @property
    def is_paused(self) -> bool:
        """Check if playback is paused."""
        return self._is_paused

    @property
    def fps(self) -> float:
        """Get video FPS."""
        return self._fps

    @property
    def duration_ms(self) -> int:
        """Get duration in milliseconds."""
        return int(self._duration_sec * 1000)

    def stop(self):
        """Stop playback and release resources."""
        self._poll_timer.stop()
        if self._player:
            self._player.terminate()
            self._player = None

    def closeEvent(self, event):
        """Handle widget close."""
        self.stop()
        super().closeEvent(event)
