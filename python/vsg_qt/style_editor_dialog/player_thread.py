# vsg_qt/style_editor_dialog/player_thread.py
# -*- coding: utf-8 -*-
import time
from pathlib import Path
from threading import Lock
from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtGui import QImage

import av

class PlayerThread(QThread):
    new_frame = Signal(object, float)
    duration_changed = Signal(float)
    playback_finished = Signal()
    time_changed = Signal(int)

    def __init__(self, video_path: str, subtitle_path: str, widget_win_id, fonts_dir: str | None, parent=None):
        super().__init__(parent)
        self.video_path = video_path
        self.subtitle_path = subtitle_path
        self.fonts_dir = fonts_dir

        self._container = None
        self._video_stream = None
        self._graph = None

        self._is_running = True
        self._is_paused = False
        self._frame_delay = 0.0

        self._lock = Lock()
        self._seek_request_ms = -1
        self._reload_subs_requested = False

    def _setup_graph(self):
        self._graph = av.filter.Graph()
        buffer_in = self._graph.add_buffer(template=self._video_stream)
        buffer_out = self._graph.add('buffersink')
        escaped_path = Path(self.subtitle_path).as_posix().replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:').replace(',', '\\,')
        filter_args = f"filename='{escaped_path}'"
        if self.fonts_dir:
            escaped_fonts_dir = Path(self.fonts_dir).as_posix().replace('\\', '\\\\').replace("'", "\\'").replace(':', '\\:').replace(',', '\\,')
            filter_args += f":fontsdir='{escaped_fonts_dir}'"
        subtitles_filter = self._graph.add(filter='subtitles', args=filter_args)
        buffer_in.link_to(subtitles_filter)
        subtitles_filter.link_to(buffer_out)
        self._graph.configure()

    def run(self):
        try:
            self._container = av.open(self.video_path, 'r')
            self._video_stream = self._container.streams.video[0]
            self._video_stream.thread_type = "AUTO"
            if self._video_stream.average_rate: self._frame_delay = 1.0 / float(self._video_stream.average_rate)
            duration_sec = float(self._container.duration or 0) / av.time_base
            self.duration_changed.emit(duration_sec)
            self._setup_graph()
        except Exception as e:
            print(f"FATAL: Could not open media or build filter graph: {e}")
            self._is_running = False; return

        frame_generator = self._container.decode(self._video_stream)
        while self._is_running:
            try:
                # FIX: More robust state management for seeking while paused
                with self._lock:
                    should_seek = self._seek_request_ms >= 0
                    should_reload = self._reload_subs_requested
                    is_paused = self._is_paused

                if should_reload:
                    self._setup_graph()
                    with self._lock: self._reload_subs_requested = False

                if should_seek:
                    try:
                        seek_pts = int(self._seek_request_ms / 1000 / self._video_stream.time_base)
                        self._container.seek(seek_pts, stream=self._video_stream, backward=True)
                        frame_generator = self._container.decode(self._video_stream)
                        self._setup_graph() # A seek requires a full graph reset
                    except Exception as e:
                        print(f"Error during seek: {e}")
                    finally:
                        with self._lock: self._seek_request_ms = -1

                if is_paused and not should_seek:
                    time.sleep(0.05)
                    continue

                frame = next(frame_generator)
                timestamp_sec = frame.pts * frame.time_base
                self._graph.push(frame)
                filtered_frame = self._graph.pull()
                pillow_img = filtered_frame.to_image()
                rgb_img = pillow_img.convert('RGB')
                q_image = QImage(rgb_img.tobytes(), rgb_img.width, rgb_img.height, QImage.Format_RGB888)
                self.new_frame.emit(q_image, timestamp_sec)
                self.time_changed.emit(int(timestamp_sec * 1000))

            except (StopIteration, av.error.EOFError):
                self.playback_finished.emit(); break
            except av.error.EAGAIN:
                time.sleep(0.005); continue

            delay = self._frame_delay
            time.sleep(delay if delay > 0.001 else 0.001)

        if self._container: self._container.close()

    @Slot()
    def stop(self): self._is_running = False; self.wait()

    def toggle_pause(self):
        with self._lock: self._is_paused = not self._is_paused

    def seek(self, time_ms: int):
        with self._lock: self._seek_request_ms = time_ms

    def reload_subtitle_track(self):
        with self._lock:
            if self._graph: self._reload_subs_requested = True
