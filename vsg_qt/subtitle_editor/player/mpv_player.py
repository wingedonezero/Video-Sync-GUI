# vsg_qt/subtitle_editor/player/mpv_player.py
# -*- coding: utf-8 -*-
"""
MPV-based video player for subtitle editor using OpenGL rendering.

Uses MPV's render API to draw directly into a Qt OpenGL widget.
This approach is more reliable than window ID embedding.
"""
import locale
from ctypes import c_void_p, cast, c_char_p
from typing import Optional

from PySide6.QtCore import Qt, Signal, QTimer, Slot
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout

import mpv


def get_process_address(ctx, name):
    """Get OpenGL proc address for MPV."""
    glctx = QOpenGLContext.currentContext()
    if glctx is None:
        return 0
    # name is bytes, need to decode for Qt
    return int(glctx.getProcAddress(name.decode('utf-8')))


class MpvOpenGLWidget(QOpenGLWidget):
    """
    OpenGL widget that renders MPV output.

    Uses MPV's render context API to draw video frames
    directly into Qt's OpenGL framebuffer.
    """

    time_changed = Signal(int)  # ms
    duration_changed = Signal(float)  # seconds
    fps_detected = Signal(float)
    playback_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Fix locale for MPV
        locale.setlocale(locale.LC_NUMERIC, 'C')

        self._mpv: Optional[mpv.MPV] = None
        self._mpv_gl = None
        self._duration_sec: float = 0
        self._fps: float = 23.976
        self._is_paused: bool = True
        self._subtitle_path: Optional[str] = None
        self._fonts_dir: Optional[str] = None

        # Pending load
        self._pending_video: Optional[str] = None
        self._pending_subtitle: Optional[str] = None
        self._pending_fonts_dir: Optional[str] = None

        # Time polling timer
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_time_position)
        self._poll_timer.setInterval(50)

        self.setMinimumSize(320, 180)

        # Create MPV instance
        self._create_mpv()

    def _create_mpv(self):
        """Create the MPV player instance."""
        self._mpv = mpv.MPV(
            # Seeking
            hr_seek='yes',
            hr_seek_framedrop='no',
            # Subtitles
            sub_auto='no',
            sub_ass='yes',
            # Playback
            pause=True,
            keep_open='yes',
            # Disable OSD
            osd_level=0,
            # Input
            input_default_bindings=False,
            input_vo_keyboard=False,
            # Logging
            log_handler=print,
            loglevel='warn'
        )

        # Register property observers
        @self._mpv.property_observer('duration')
        def on_duration(name, value):
            if value is not None:
                self._duration_sec = value
                self.duration_changed.emit(value)

        @self._mpv.property_observer('container-fps')
        def on_fps(name, value):
            if value is not None and value > 0:
                self._fps = value
                self.fps_detected.emit(value)

        @self._mpv.property_observer('eof-reached')
        def on_eof(name, value):
            if value:
                self.playback_finished.emit()

        @self._mpv.property_observer('pause')
        def on_pause(name, value):
            self._is_paused = value

        print("[MPV] Player instance created")

    def initializeGL(self):
        """Initialize OpenGL context for MPV rendering."""
        print("[MPV] Initializing OpenGL context...")

        # Create the OpenGL render context
        # MPV needs a callback to get OpenGL proc addresses
        def get_proc_addr_wrapper(ctx, name):
            return get_process_address(ctx, name)

        # Store reference to prevent garbage collection
        self._proc_addr_func = mpv.OpenGlCbGetProcAddrFn(get_proc_addr_wrapper)

        # Initialize MPV OpenGL
        self._mpv_gl = mpv.MpvRenderContext(
            self._mpv,
            'opengl',
            opengl_init_params={'get_proc_address': self._proc_addr_func}
        )

        # Set update callback - called when new frame is ready
        self._mpv_gl.update_cb = self._on_mpv_update

        print("[MPV] OpenGL context initialized")

        # Process pending load
        if self._pending_video:
            QTimer.singleShot(100, self._do_pending_load)

    def _do_pending_load(self):
        """Load pending video after GL init."""
        if self._pending_video:
            self._do_load_video(
                self._pending_video,
                self._pending_subtitle,
                self._pending_fonts_dir
            )
            self._pending_video = None
            self._pending_subtitle = None
            self._pending_fonts_dir = None

    def paintGL(self):
        """Render MPV frame to OpenGL framebuffer."""
        if self._mpv_gl is None:
            return

        # Get widget size with HiDPI scaling
        ratio = self.devicePixelRatio()
        w = int(self.width() * ratio)
        h = int(self.height() * ratio)

        # Render to default framebuffer
        fbo = self.defaultFramebufferObject()
        self._mpv_gl.render(
            flip_y=True,
            opengl_fbo={'w': w, 'h': h, 'fbo': fbo}
        )

    def _on_mpv_update(self, ctx=None):
        """Called by MPV when a new frame is ready."""
        # Schedule repaint on Qt thread
        QTimer.singleShot(0, self._maybe_update)

    @Slot()
    def _maybe_update(self):
        """Update the widget (thread-safe)."""
        if self.window().isMinimized():
            # Minimized - render directly
            self.makeCurrent()
            self.paintGL()
            self.context().swapBuffers(self.context().surface())
            self.doneCurrent()
        else:
            self.update()

    def load_video(self, video_path: str, subtitle_path: Optional[str] = None,
                   fonts_dir: Optional[str] = None):
        """Load a video file."""
        # If GL not initialized yet, store for later
        if self._mpv_gl is None:
            print(f"[MPV] GL not ready, storing pending load: {video_path}")
            self._pending_video = video_path
            self._pending_subtitle = subtitle_path
            self._pending_fonts_dir = fonts_dir
            return

        self._do_load_video(video_path, subtitle_path, fonts_dir)

    def _do_load_video(self, video_path: str, subtitle_path: Optional[str],
                       fonts_dir: Optional[str]):
        """Actually load the video."""
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

        print(f"[MPV] Loading video: {video_path}")
        if subtitle_path:
            print(f"[MPV] Subtitle: {subtitle_path}")
        if fonts_dir:
            print(f"[MPV] Fonts dir: {fonts_dir}")

        # Set fonts directory
        if fonts_dir:
            try:
                self._mpv['sub-fonts-dir'] = fonts_dir
            except Exception as e:
                print(f"[MPV] Warning setting fonts dir: {e}")

        # Load video
        self._mpv.loadfile(video_path)

        # File loaded callback
        @self._mpv.event_callback('file-loaded')
        def on_loaded(event):
            print("[MPV] File loaded")
            if subtitle_path:
                try:
                    self._mpv.sub_add(subtitle_path)
                    print(f"[MPV] Subtitle added")
                except Exception as e:
                    print(f"[MPV] Error adding subtitle: {e}")

            self._mpv.seek(0, 'absolute')
            self._poll_timer.start()

    def play(self):
        """Start playback."""
        if self._mpv:
            self._mpv.pause = False

    def pause(self):
        """Pause playback."""
        if self._mpv:
            self._mpv.pause = True

    def toggle_pause(self):
        """Toggle play/pause."""
        if self._mpv:
            self._mpv.pause = not self._mpv.pause

    def seek(self, time_ms: int):
        """Seek to time in milliseconds."""
        if self._mpv:
            self._mpv.seek(time_ms / 1000.0, 'absolute', 'exact')

    def seek_frame(self, frame_num: int):
        """Seek to frame number."""
        if self._mpv and self._fps > 0:
            self._mpv.seek(frame_num / self._fps, 'absolute', 'exact')

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload subtitles."""
        if not self._mpv:
            return

        if subtitle_path:
            self._subtitle_path = subtitle_path

        # Remove external subs
        try:
            for track in self._mpv.track_list:
                if track.get('type') == 'sub' and track.get('external'):
                    self._mpv.sub_remove(track.get('id'))
        except Exception:
            pass

        # Add new subtitle
        if self._subtitle_path:
            try:
                self._mpv.sub_add(self._subtitle_path)
                print(f"[MPV] Reloaded subtitle")
            except Exception as e:
                print(f"[MPV] Error reloading subtitle: {e}")

    def _poll_time_position(self):
        """Poll current playback time."""
        if self._mpv:
            try:
                pos = self._mpv.time_pos
                if pos is not None:
                    self.time_changed.emit(int(pos * 1000))
            except Exception:
                pass

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def fps(self) -> float:
        return self._fps

    @property
    def duration_ms(self) -> int:
        return int(self._duration_sec * 1000)

    def shutdown(self):
        """Shutdown render context."""
        if self._mpv_gl:
            self._mpv_gl.free()
            self._mpv_gl = None

    def stop(self):
        """Stop and cleanup."""
        self._poll_timer.stop()
        self.shutdown()
        if self._mpv:
            self._mpv.terminate()
            self._mpv = None

    def closeEvent(self, event):
        """Handle close."""
        self.stop()
        super().closeEvent(event)


# Alias for compatibility
MpvWidget = MpvOpenGLWidget
