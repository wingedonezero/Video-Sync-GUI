# vsg_qt/subtitle_editor/player/mpv_player.py
# -*- coding: utf-8 -*-
"""
MPV-based video player for subtitle editor.

Uses MPV for video playback and subtitle rendering (libass built-in).
"""
import locale
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame

import mpv


class MpvWidget(QWidget):
    """
    Qt widget that embeds an MPV player.

    Uses native window embedding - the video frame widget must be
    realized (shown) before MPV can attach to it.

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

        # Pending load request (stored until widget is shown)
        self._pending_video: Optional[str] = None
        self._pending_subtitle: Optional[str] = None
        self._pending_fonts_dir: Optional[str] = None
        self._widget_shown: bool = False

        # Timer for polling time position
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_time_position)
        self._poll_timer.setInterval(50)  # 50ms = 20 updates/sec

        self._setup_ui()

    def _setup_ui(self):
        """Set up the widget UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Container frame for MPV - MUST have native window attributes
        self._video_frame = QFrame()
        self._video_frame.setStyleSheet("background-color: black;")
        self._video_frame.setMinimumSize(320, 180)

        # Critical: Tell Qt to create a native window for embedding
        self._video_frame.setAttribute(Qt.WA_DontCreateNativeAncestors)
        self._video_frame.setAttribute(Qt.WA_NativeWindow)

        layout.addWidget(self._video_frame)

    def showEvent(self, event):
        """Handle widget show - now safe to create MPV player."""
        super().showEvent(event)

        if not self._widget_shown:
            self._widget_shown = True
            print("[MPV] Widget shown, creating player...")

            # Use single-shot timer to ensure window is fully realized
            QTimer.singleShot(100, self._on_widget_ready)

    def _on_widget_ready(self):
        """Called when widget is ready for MPV embedding."""
        if self._player is None:
            self._create_player()

        # Process any pending load request
        if self._pending_video:
            self._do_load_video(
                self._pending_video,
                self._pending_subtitle,
                self._pending_fonts_dir
            )
            self._pending_video = None
            self._pending_subtitle = None
            self._pending_fonts_dir = None

    def _create_player(self):
        """Create and configure the MPV player instance."""
        # Fix locale for MPV (required on some systems)
        locale.setlocale(locale.LC_NUMERIC, 'C')

        # Get window ID for embedding - widget must be shown first
        wid = int(self._video_frame.winId())
        print(f"[MPV] Creating player with wid={wid}")

        # Create MPV instance with embedding
        self._player = mpv.MPV(
            wid=wid,
            # Video output
            vo='x11',  # Use X11 for Linux - more reliable embedding
            # Seeking settings for accuracy
            hr_seek='yes',
            hr_seek_framedrop='no',
            # Subtitle settings
            sub_auto='no',  # We'll add subtitles manually
            sub_ass='yes',
            # Keep video paused on load
            pause=True,
            keep_open='yes',
            # Disable OSD
            osd_level=0,
            # Input
            input_default_bindings=False,
            input_vo_keyboard=False,
            # Log level
            log_handler=print,
            loglevel='warn'
        )

        print("[MPV] Player created successfully")

        # Register property observers
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
        # If widget not shown yet, store request for later
        if not self._widget_shown or self._player is None:
            print(f"[MPV] Storing pending load: {video_path}")
            self._pending_video = video_path
            self._pending_subtitle = subtitle_path
            self._pending_fonts_dir = fonts_dir
            return

        self._do_load_video(video_path, subtitle_path, fonts_dir)

    def _do_load_video(self, video_path: str, subtitle_path: Optional[str],
                       fonts_dir: Optional[str]):
        """Actually load the video (called when player is ready)."""
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

        print(f"[MPV] Loading video: {video_path}")
        if subtitle_path:
            print(f"[MPV] Subtitle: {subtitle_path}")
        if fonts_dir:
            print(f"[MPV] Fonts dir: {fonts_dir}")

        # Set fonts directory for ASS rendering
        if fonts_dir:
            try:
                self._player['sub-fonts-dir'] = fonts_dir
            except Exception as e:
                print(f"[MPV] Warning: Could not set fonts dir: {e}")

        # Load video file
        self._player.loadfile(video_path)

        # Register file-loaded callback
        @self._player.event_callback('file-loaded')
        def on_file_loaded(event):
            print("[MPV] File loaded")
            # Add subtitle if provided
            if subtitle_path:
                try:
                    self._player.sub_add(subtitle_path)
                    print(f"[MPV] Subtitle added: {subtitle_path}")
                except Exception as e:
                    print(f"[MPV] Error adding subtitle: {e}")

            # Seek to start
            self._player.seek(0, 'absolute')
            # Start time polling
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
        if not self._player:
            return

        if subtitle_path:
            self._subtitle_path = subtitle_path

        # Remove existing external subtitle tracks
        try:
            track_list = self._player.track_list
            for track in track_list:
                if track.get('type') == 'sub' and track.get('external'):
                    track_id = track.get('id')
                    if track_id:
                        self._player.sub_remove(track_id)
        except Exception as e:
            print(f"[MPV] Error removing subtitles: {e}")

        # Add new subtitle
        if self._subtitle_path:
            try:
                self._player.sub_add(self._subtitle_path)
                print(f"[MPV] Reloaded subtitle: {self._subtitle_path}")
            except Exception as e:
                print(f"[MPV] Error adding subtitle: {e}")

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
            try:
                self._player.terminate()
            except Exception:
                pass
            self._player = None

    def closeEvent(self, event):
        """Handle widget close."""
        self.stop()
        super().closeEvent(event)
