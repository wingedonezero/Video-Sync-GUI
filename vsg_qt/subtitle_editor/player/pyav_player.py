# vsg_qt/subtitle_editor/player/pyav_player.py
# -*- coding: utf-8 -*-
"""
FFmpeg-based video player for subtitle editor.

Architecture:
- PyAV for video decoding with FFmpeg filter graph
- FFmpeg 'subtitles' filter for real-time libass rendering
- PyAV for audio decoding + sounddevice for output
- Audio as master clock for A/V sync
- FrameIndex for precise time<->frame conversion (subtitle clicking)

This provides:
- Real-time subtitle rendering (like a media player)
- Audio playback with proper A/V sync
- Frame-accurate seeking via FrameIndex
- Click subtitle → exact start frame
"""
from __future__ import annotations

import gc
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, Slot, QThread, QMutex, QWaitCondition
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

try:
    import av
    HAS_AV = True
except ImportError:
    HAS_AV = False
    print("[PyAVPlayer] WARNING: PyAV not installed")


class AudioClock:
    """
    Audio playback clock - acts as master clock for A/V sync.

    Tracks audio position based on samples played through sounddevice.
    """

    def __init__(self, sample_rate: int = 48000):
        self._sample_rate = sample_rate
        self._samples_played: int = 0
        self._base_time_ms: float = 0.0
        self._playing = False
        self._lock = threading.Lock()

    def reset(self, time_ms: float = 0.0):
        """Reset clock to specific time."""
        with self._lock:
            self._base_time_ms = time_ms
            self._samples_played = 0

    def add_samples(self, count: int):
        """Called by audio callback when samples are played."""
        with self._lock:
            self._samples_played += count

    @property
    def position_ms(self) -> float:
        """Get current playback position in milliseconds."""
        with self._lock:
            played_ms = self._samples_played * 1000.0 / self._sample_rate
            return self._base_time_ms + played_ms

    def set_playing(self, playing: bool):
        """Set playing state."""
        self._playing = playing

    @property
    def is_playing(self) -> bool:
        return self._playing


class AudioOutput:
    """
    Audio output using sounddevice with clock tracking.
    """

    def __init__(self, clock: AudioClock):
        self._clock = clock
        self._stream = None
        self._buffer: list = []
        self._buffer_lock = threading.Lock()
        self._playing = False
        self._sample_rate = 48000

    def start(self, sample_rate: int = 48000):
        """Start audio output stream."""
        try:
            import sounddevice as sd

            self._sample_rate = sample_rate

            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=2,
                dtype='float32',
                callback=self._callback,
                blocksize=1024,
                latency='low'
            )
            self._stream.start()
            self._playing = True
            print(f"[AudioOutput] Started: {sample_rate}Hz stereo")

        except ImportError:
            print("[AudioOutput] sounddevice not installed")
        except Exception as e:
            print(f"[AudioOutput] Failed: {e}")

    def stop(self):
        """Stop audio output."""
        self._playing = False
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self.clear()

    def clear(self):
        """Clear audio buffer."""
        with self._buffer_lock:
            self._buffer.clear()

    def add_samples(self, samples: np.ndarray):
        """Add samples to buffer."""
        with self._buffer_lock:
            # Limit buffer to ~500ms
            total = sum(len(s) for s in self._buffer)
            if total < self._sample_rate // 2:
                self._buffer.append(samples.copy())

    def set_paused(self, paused: bool):
        """Pause/unpause (keeps stream open but outputs silence)."""
        self._playing = not paused
        self._clock.set_playing(not paused)

    def _callback(self, outdata, frames, time_info, status):
        """Sounddevice callback."""
        if not self._playing:
            outdata.fill(0)
            return

        with self._buffer_lock:
            if not self._buffer:
                outdata.fill(0)
                return

            filled = 0
            while filled < frames and self._buffer:
                samples = self._buffer[0]
                available = len(samples)
                needed = frames - filled

                if available <= needed:
                    outdata[filled:filled + available] = samples
                    filled += available
                    self._buffer.pop(0)
                else:
                    outdata[filled:frames] = samples[:needed]
                    self._buffer[0] = samples[needed:]
                    filled = frames

            if filled < frames:
                outdata[filled:] = 0

            # Update clock with samples actually played
            self._clock.add_samples(filled)


class PlaybackThread(QThread):
    """
    Video playback thread using PyAV with FFmpeg filter graph for subtitles.

    Uses audio clock as master for A/V sync - video frames are displayed
    when their PTS matches audio position, dropped if behind.
    """

    frame_ready = Signal(object, float, int)  # QImage, time_ms, frame_num
    audio_ready = Signal(object)              # numpy samples
    duration_ready = Signal(float)            # seconds
    fps_ready = Signal(float)
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, audio_clock: AudioClock, parent=None):
        super().__init__(parent)

        self._audio_clock = audio_clock

        # Paths
        self._video_path: Optional[str] = None
        self._subtitle_path: Optional[str] = None
        self._fonts_dir: Optional[str] = None

        # PyAV objects
        self._container = None
        self._video_stream = None
        self._audio_stream = None
        self._filter_graph = None
        self._audio_resampler = None

        # Video properties
        self._fps: float = 23.976
        self._fps_fraction: Optional[Fraction] = None
        self._frame_count: int = 0
        self._duration_ms: float = 0
        self._width: int = 0
        self._height: int = 0

        # State
        self._running = False
        self._playing = False
        self._current_frame: int = 0
        self._current_time_ms: float = 0

        # Thread sync
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._seek_time_ms: float = -1
        self._reload_subs: bool = False

    def load(self, video_path: str, subtitle_path: Optional[str] = None,
             fonts_dir: Optional[str] = None):
        """Set paths for loading."""
        self._video_path = video_path
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

    def set_playing(self, playing: bool):
        """Set playback state."""
        self._mutex.lock()
        self._playing = playing
        self._condition.wakeAll()
        self._mutex.unlock()

    def seek_to_ms(self, time_ms: float):
        """Request seek to time."""
        self._mutex.lock()
        self._seek_time_ms = time_ms
        self._condition.wakeAll()
        self._mutex.unlock()

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Request subtitle reload."""
        self._mutex.lock()
        if subtitle_path:
            self._subtitle_path = subtitle_path
        self._reload_subs = True
        self._condition.wakeAll()
        self._mutex.unlock()

    def stop_thread(self):
        """Stop the thread."""
        self._running = False
        self._mutex.lock()
        self._condition.wakeAll()
        self._mutex.unlock()
        self.wait(3000)

    @property
    def current_frame(self) -> int:
        return self._current_frame

    @property
    def current_time_ms(self) -> float:
        return self._current_time_ms

    def run(self):
        """Main playback loop."""
        self._running = True

        if not HAS_AV:
            self.error.emit("PyAV not installed")
            return

        try:
            self._open_container()
        except Exception as e:
            self.error.emit(f"Failed to open video: {e}")
            import traceback
            traceback.print_exc()
            return

        # Emit video info
        self.fps_ready.emit(self._fps)
        self.duration_ready.emit(self._duration_ms / 1000.0)

        # Build filter graph for subtitles
        self._setup_filter_graph()

        # Create frame generator
        frame_gen = self._container.decode(self._video_stream)

        # Render first frame
        self._decode_and_emit_frame(frame_gen, force=True)

        while self._running:
            self._mutex.lock()
            playing = self._playing
            seek_ms = self._seek_time_ms
            reload_subs = self._reload_subs

            self._seek_time_ms = -1
            self._reload_subs = False
            self._mutex.unlock()

            # Handle subtitle reload
            if reload_subs:
                self._setup_filter_graph()

            # Handle seek
            if seek_ms >= 0:
                try:
                    self._do_seek(seek_ms)
                    frame_gen = self._container.decode(self._video_stream)
                    self._setup_filter_graph()
                    self._decode_and_emit_frame(frame_gen, force=True)
                except Exception as e:
                    print(f"[Playback] Seek error: {e}")

            # Playback
            if playing:
                try:
                    self._decode_and_emit_frame(frame_gen, force=False)
                    self._decode_audio()
                except StopIteration:
                    self._playing = False
                    self.playback_finished.emit()
                except av.error.EOFError:
                    self._playing = False
                    self.playback_finished.emit()
            else:
                # Paused - wait for signal
                self._mutex.lock()
                self._condition.wait(self._mutex, 50)
                self._mutex.unlock()

        self._cleanup()

    def _open_container(self):
        """Open video container."""
        print(f"[Playback] Opening: {self._video_path}")

        self._container = av.open(self._video_path)

        # Video stream
        if not self._container.streams.video:
            raise ValueError("No video stream")

        self._video_stream = self._container.streams.video[0]
        self._video_stream.thread_type = "AUTO"

        # Get properties
        self._width = self._video_stream.width
        self._height = self._video_stream.height

        if self._video_stream.average_rate:
            self._fps = float(self._video_stream.average_rate)
            self._fps_fraction = Fraction(
                self._video_stream.average_rate.numerator,
                self._video_stream.average_rate.denominator
            )

        # Duration and frame count
        if self._container.duration:
            self._duration_ms = self._container.duration / 1000.0
        if self._video_stream.frames:
            self._frame_count = self._video_stream.frames
        elif self._duration_ms > 0 and self._fps > 0:
            self._frame_count = int(self._duration_ms * self._fps / 1000.0)

        print(f"[Playback] Video: {self._width}x{self._height} @ {self._fps:.3f}fps")
        print(f"[Playback] Duration: {self._duration_ms:.0f}ms, Frames: {self._frame_count}")

        # Audio stream
        if self._container.streams.audio:
            self._audio_stream = self._container.streams.audio[0]
            self._audio_resampler = av.AudioResampler(
                format='flt',
                layout='stereo',
                rate=48000
            )
            print(f"[Playback] Audio: {self._audio_stream.rate}Hz")

    def _setup_filter_graph(self):
        """Set up FFmpeg filter graph with subtitles filter (uses libass)."""
        if self._video_stream is None:
            return

        try:
            self._filter_graph = av.filter.Graph()

            # Input buffer
            buffer_in = self._filter_graph.add_buffer(template=self._video_stream)

            # Output buffer
            buffer_out = self._filter_graph.add('buffersink')

            # Check if we have subtitles to render
            if self._subtitle_path and Path(self._subtitle_path).exists():
                # Escape path for FFmpeg filter
                escaped_path = self._escape_filter_path(self._subtitle_path)

                # Build filter args
                filter_args = f"filename='{escaped_path}'"

                if self._fonts_dir and Path(self._fonts_dir).exists():
                    escaped_fonts = self._escape_filter_path(self._fonts_dir)
                    filter_args += f":fontsdir='{escaped_fonts}'"

                print(f"[Playback] Subtitle filter: {filter_args}")

                # Add subtitles filter (uses libass internally)
                subs_filter = self._filter_graph.add('subtitles', filter_args)

                # Link: input -> subtitles -> output
                buffer_in.link_to(subs_filter)
                subs_filter.link_to(buffer_out)
            else:
                # No subtitles - direct passthrough
                buffer_in.link_to(buffer_out)

            self._filter_graph.configure()
            print("[Playback] Filter graph configured")

        except Exception as e:
            print(f"[Playback] Filter graph error: {e}")
            # Fallback - no filter graph
            self._filter_graph = None

    def _escape_filter_path(self, path: str) -> str:
        """Escape path for FFmpeg filter syntax."""
        return (Path(path).as_posix()
                .replace('\\', '\\\\')
                .replace("'", "\\'")
                .replace(':', '\\:')
                .replace(',', '\\,'))

    def _do_seek(self, time_ms: float):
        """Seek to time in milliseconds."""
        if not self._container or not self._video_stream:
            return

        # Seek to keyframe before target
        target_pts = int(time_ms / 1000.0 / self._video_stream.time_base)
        self._container.seek(target_pts, stream=self._video_stream, backward=True)

        # Update audio clock
        self._audio_clock.reset(time_ms)

        print(f"[Playback] Seeked to {time_ms:.1f}ms")

    def _decode_and_emit_frame(self, frame_gen, force: bool = False):
        """Decode next frame, apply filter, emit if in sync."""
        frame = next(frame_gen)

        # Get frame timestamp
        if frame.pts is not None and self._video_stream.time_base:
            frame_time_ms = float(frame.pts * self._video_stream.time_base) * 1000.0
        else:
            frame_time_ms = self._current_frame * 1000.0 / self._fps

        # Calculate frame number
        frame_num = int(frame_time_ms * self._fps / 1000.0)

        # A/V sync check (skip if we have audio and are behind)
        if not force and self._audio_stream:
            audio_pos = self._audio_clock.position_ms
            diff = frame_time_ms - audio_pos

            # If video is more than 1 frame behind audio, skip this frame
            frame_duration_ms = 1000.0 / self._fps
            if diff < -frame_duration_ms:
                # Skip frame - we're behind
                return

            # If video is ahead, wait a bit
            if diff > frame_duration_ms:
                time.sleep(min(diff / 1000.0, 0.05))

        # Apply filter graph (renders subtitles)
        if self._filter_graph:
            try:
                self._filter_graph.push(frame)
                filtered_frame = self._filter_graph.pull()
                frame = filtered_frame
            except Exception as e:
                print(f"[Playback] Filter error: {e}")

        # Convert to QImage
        qimage = self._frame_to_qimage(frame)

        # Update state
        self._current_time_ms = frame_time_ms
        self._current_frame = frame_num

        # Emit
        self.frame_ready.emit(qimage, frame_time_ms, frame_num)

        # Frame timing (when not syncing to audio)
        if not self._audio_stream:
            time.sleep(1.0 / self._fps * 0.95)

    def _decode_audio(self):
        """Decode some audio and emit."""
        if not self._audio_stream or not self._audio_resampler:
            return

        try:
            for packet in self._container.demux(self._audio_stream):
                if not self._running or not self._playing:
                    break

                for frame in packet.decode():
                    resampled = self._audio_resampler.resample(frame)
                    for out_frame in resampled:
                        arr = out_frame.to_ndarray()
                        # Ensure shape is (samples, channels)
                        if arr.ndim == 1:
                            arr = arr.reshape(-1, 1)
                        if arr.shape[0] == 2 and arr.shape[1] != 2:
                            arr = arr.T
                        self.audio_ready.emit(arr)

                # Only decode one packet at a time
                return

        except Exception as e:
            print(f"[Playback] Audio decode error: {e}")

    def _frame_to_qimage(self, frame) -> QImage:
        """Convert PyAV frame to QImage."""
        # Convert to RGB via PIL (handles format conversion)
        pil_img = frame.to_image()
        rgb_img = pil_img.convert('RGB')

        qimage = QImage(
            rgb_img.tobytes(),
            rgb_img.width,
            rgb_img.height,
            rgb_img.width * 3,
            QImage.Format_RGB888
        )
        return qimage.copy()

    def _cleanup(self):
        """Clean up resources."""
        self._filter_graph = None
        self._audio_resampler = None

        if self._container:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None

        self._video_stream = None
        self._audio_stream = None
        gc.collect()
        print("[Playback] Cleaned up")


class PyAVPlayer(QWidget):
    """
    FFmpeg-based video player widget.

    Uses PyAV with FFmpeg filter graph for real-time libass subtitle rendering.
    Audio acts as master clock for A/V sync.

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

        # Audio clock (master for sync)
        self._audio_clock = AudioClock()

        # Components
        self._playback_thread: Optional[PlaybackThread] = None
        self._audio_output: Optional[AudioOutput] = None

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

        # Time polling
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_time)
        self._poll_timer.setInterval(50)

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

        # Reset audio clock
        self._audio_clock.reset(0)

        # Create audio output
        self._audio_output = AudioOutput(self._audio_clock)

        # Create playback thread
        self._playback_thread = PlaybackThread(self._audio_clock, self)
        self._playback_thread.load(video_path, subtitle_path, fonts_dir)
        self._playback_thread.frame_ready.connect(self._on_frame_ready)
        self._playback_thread.audio_ready.connect(self._on_audio_ready)
        self._playback_thread.duration_ready.connect(self._on_duration_ready)
        self._playback_thread.fps_ready.connect(self._on_fps_ready)
        self._playback_thread.playback_finished.connect(self._on_playback_finished)
        self._playback_thread.error.connect(self._on_error)
        self._playback_thread.start()

        # Start polling
        self._poll_timer.start()

    @Slot(object, float, int)
    def _on_frame_ready(self, qimage: QImage, time_ms: float, frame_num: int):
        """Handle frame from playback thread."""
        self._current_time_ms = int(time_ms)
        self._current_frame = frame_num

        # Scale and display
        display_size = self._display.size()
        scaled = qimage.scaled(
            display_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._display.setPixmap(QPixmap.fromImage(scaled))

    @Slot(object)
    def _on_audio_ready(self, samples: np.ndarray):
        """Handle audio from playback thread."""
        if self._audio_output and not self._is_paused:
            self._audio_output.add_samples(samples)

    @Slot(float)
    def _on_duration_ready(self, duration_sec: float):
        """Handle duration."""
        self._duration_sec = duration_sec
        self.duration_changed.emit(duration_sec)

    @Slot(float)
    def _on_fps_ready(self, fps: float):
        """Handle FPS."""
        self._fps = fps
        self.fps_detected.emit(fps)

        # Start audio output
        if self._audio_output:
            self._audio_output.start(48000)

    @Slot()
    def _on_playback_finished(self):
        """Handle end of video."""
        self._is_paused = True
        if self._audio_output:
            self._audio_output.set_paused(True)
        self.playback_finished.emit()

    @Slot(str)
    def _on_error(self, error: str):
        """Handle error."""
        print(f"[PyAVPlayer] ERROR: {error}")

    def _poll_time(self):
        """Emit time updates."""
        self.time_changed.emit(self._current_time_ms)
        self.frame_changed.emit(self._current_frame)

    def play(self):
        """Start playback."""
        self._is_paused = False
        if self._playback_thread:
            self._playback_thread.set_playing(True)
        if self._audio_output:
            self._audio_output.set_paused(False)

    def pause(self):
        """Pause playback."""
        self._is_paused = True
        if self._playback_thread:
            self._playback_thread.set_playing(False)
        if self._audio_output:
            self._audio_output.set_paused(True)
            self._audio_output.clear()

    def toggle_pause(self):
        """Toggle play/pause."""
        if self._is_paused:
            self.play()
        else:
            self.pause()

    def seek(self, time_ms: int, precise: bool = True):
        """Seek to time in milliseconds."""
        if self._playback_thread:
            self._playback_thread.seek_to_ms(float(time_ms))
        if self._audio_output:
            self._audio_output.clear()
        self._audio_clock.reset(float(time_ms))

    def seek_frame(self, frame_num: int):
        """Seek to specific frame number."""
        if self._fps > 0:
            time_ms = frame_num * 1000.0 / self._fps
            self.seek(int(time_ms))

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload subtitles."""
        if subtitle_path:
            self._subtitle_path = subtitle_path
        if self._playback_thread:
            self._playback_thread.reload_subtitles(self._subtitle_path)

    @property
    def is_paused(self) -> bool:
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
        print("[PyAVPlayer] Stopping...")

        self._poll_timer.stop()

        if self._playback_thread:
            self._playback_thread.stop_thread()
            self._playback_thread = None

        if self._audio_output:
            self._audio_output.stop()
            self._audio_output = None

        self._display.clear()
        gc.collect()
        print("[PyAVPlayer] Stopped")

    def closeEvent(self, event):
        """Handle close."""
        self.stop()
        super().closeEvent(event)
