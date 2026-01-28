# vsg_qt/subtitle_editor/player/pyav_player.py
# -*- coding: utf-8 -*-
"""
FFmpeg-based video player for subtitle editor.

Architecture:
- VapourSynth + L-SMASH/FFMS2 for frame-accurate video decoding
- VapourSynth SubText (libass) for subtitle rendering
- PyAV for audio decoding
- sounddevice for audio output

This provides:
- Frame-accurate seeking (VapourSynth index)
- True libass subtitle rendering
- Audio playback
- Precise time<->frame conversion via VideoTimestamps
"""
from __future__ import annotations

import gc
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import numpy as np
from PySide6.QtCore import Qt, Signal, QTimer, Slot, QThread, QMutex, QWaitCondition
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout

if TYPE_CHECKING:
    import vapoursynth as vs


class AudioOutput:
    """
    Audio playback using sounddevice.

    Provides callback-based audio output with position tracking
    for A/V sync.
    """

    def __init__(self):
        self._stream = None
        self._audio_buffer: list = []
        self._buffer_lock = threading.Lock()
        self._playing = False
        self._paused = False
        self._position_samples: int = 0
        self._sample_rate: int = 48000
        self._channels: int = 2

    def start(self, sample_rate: int = 48000, channels: int = 2):
        """Start audio output stream."""
        try:
            import sounddevice as sd

            self._sample_rate = sample_rate
            self._channels = channels
            self._position_samples = 0

            self._stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='float32',
                callback=self._audio_callback,
                blocksize=1024,
                latency='low'
            )
            self._stream.start()
            self._playing = True
            print(f"[AudioOutput] Started: {sample_rate}Hz, {channels}ch")

        except ImportError:
            print("[AudioOutput] sounddevice not installed, no audio")
            self._stream = None
        except Exception as e:
            print(f"[AudioOutput] Failed to start: {e}")
            self._stream = None

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
        with self._buffer_lock:
            self._audio_buffer.clear()
        print("[AudioOutput] Stopped")

    def set_paused(self, paused: bool):
        """Pause/unpause audio."""
        self._paused = paused

    def clear_buffer(self):
        """Clear audio buffer (for seeking)."""
        with self._buffer_lock:
            self._audio_buffer.clear()

    def add_samples(self, samples: np.ndarray):
        """Add audio samples to buffer."""
        with self._buffer_lock:
            # Limit buffer size to ~500ms
            max_samples = int(self._sample_rate * 0.5)
            total = sum(len(s) for s in self._audio_buffer)
            if total < max_samples:
                self._audio_buffer.append(samples.copy())

    def set_position(self, time_ms: float):
        """Set playback position (after seek)."""
        self._position_samples = int(time_ms * self._sample_rate / 1000.0)

    @property
    def position_ms(self) -> float:
        """Get current playback position in milliseconds."""
        return self._position_samples * 1000.0 / self._sample_rate

    @property
    def is_active(self) -> bool:
        return self._stream is not None

    def _audio_callback(self, outdata, frames, time_info, status):
        """Sounddevice callback - fill output buffer."""
        if not self._playing or self._paused:
            outdata.fill(0)
            return

        with self._buffer_lock:
            if not self._audio_buffer:
                outdata.fill(0)
                return

            # Fill from buffer
            filled = 0
            while filled < frames and self._audio_buffer:
                samples = self._audio_buffer[0]
                available = len(samples)
                needed = frames - filled

                if available <= needed:
                    outdata[filled:filled + available] = samples
                    filled += available
                    self._audio_buffer.pop(0)
                else:
                    outdata[filled:frames] = samples[:needed]
                    self._audio_buffer[0] = samples[needed:]
                    filled = frames

            # Zero-fill any remaining
            if filled < frames:
                outdata[filled:] = 0

            self._position_samples += frames


class AudioDecoderThread(QThread):
    """
    Separate thread for decoding audio using PyAV.

    Runs independently from video to allow continuous audio buffering.
    """

    audio_ready = Signal(object)  # numpy array of samples
    audio_info = Signal(int, int)  # sample_rate, channels

    def __init__(self, parent=None):
        super().__init__(parent)
        self._video_path: Optional[str] = None
        self._running = False
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._seek_time_ms: float = -1
        self._playing = False

    def load(self, video_path: str):
        """Set video path to decode audio from."""
        self._video_path = video_path

    def set_playing(self, playing: bool):
        """Set playback state."""
        self._mutex.lock()
        self._playing = playing
        self._condition.wakeAll()
        self._mutex.unlock()

    def seek_to(self, time_ms: float):
        """Seek audio to time."""
        self._mutex.lock()
        self._seek_time_ms = time_ms
        self._condition.wakeAll()
        self._mutex.unlock()

    def stop_decoder(self):
        """Stop the decoder."""
        self._running = False
        self._mutex.lock()
        self._condition.wakeAll()
        self._mutex.unlock()
        self.wait(2000)

    def run(self):
        """Main audio decode loop."""
        self._running = True

        if not self._video_path:
            return

        try:
            import av

            container = av.open(self._video_path)

            if not container.streams.audio:
                print("[AudioDecoder] No audio stream found")
                container.close()
                return

            audio_stream = container.streams.audio[0]
            sample_rate = audio_stream.rate or 48000
            channels = audio_stream.channels or 2

            # Create resampler for consistent output
            resampler = av.AudioResampler(
                format='flt',
                layout='stereo',
                rate=48000
            )

            self.audio_info.emit(48000, 2)
            print(f"[AudioDecoder] Audio: {sample_rate}Hz → 48000Hz, {channels}ch → stereo")

            while self._running:
                self._mutex.lock()
                seek_ms = self._seek_time_ms
                playing = self._playing
                self._seek_time_ms = -1
                self._mutex.unlock()

                # Handle seek
                if seek_ms >= 0:
                    try:
                        target_pts = int(seek_ms / 1000.0 / audio_stream.time_base)
                        container.seek(target_pts, stream=audio_stream)
                    except Exception as e:
                        print(f"[AudioDecoder] Seek error: {e}")

                # Decode audio when playing
                if playing:
                    try:
                        for packet in container.demux(audio_stream):
                            if not self._running or not self._playing:
                                break

                            for frame in packet.decode():
                                resampled = resampler.resample(frame)
                                for out_frame in resampled:
                                    # Convert to numpy (samples, channels)
                                    arr = out_frame.to_ndarray()
                                    if arr.ndim == 1:
                                        arr = arr.reshape(-1, 1)
                                    if arr.shape[0] == 2:  # (channels, samples)
                                        arr = arr.T
                                    self.audio_ready.emit(arr)

                            # Check for new seek or pause
                            self._mutex.lock()
                            should_break = self._seek_time_ms >= 0 or not self._playing
                            self._mutex.unlock()
                            if should_break:
                                break

                    except av.EOFError:
                        pass
                    except Exception as e:
                        print(f"[AudioDecoder] Decode error: {e}")
                else:
                    # Paused - wait for signal
                    self._mutex.lock()
                    self._condition.wait(self._mutex, 100)
                    self._mutex.unlock()

            container.close()

        except ImportError:
            print("[AudioDecoder] PyAV not installed, no audio")
        except Exception as e:
            print(f"[AudioDecoder] Error: {e}")


class VideoThread(QThread):
    """
    Video playback thread using VapourSynth for frame-accurate decoding
    and libass subtitle rendering via SubText plugin.
    """

    frame_ready = Signal(object, float, int)  # QImage, time_ms, frame_num
    duration_ready = Signal(float)  # seconds
    fps_ready = Signal(float, object)  # fps, fps_fraction
    playback_finished = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._video_path: Optional[str] = None
        self._subtitle_path: Optional[str] = None
        self._index_dir: Optional[Path] = None
        self._fonts_dir: Optional[str] = None

        # VapourSynth objects
        self._core: Optional['vs.Core'] = None
        self._base_clip: Optional['vs.VideoNode'] = None
        self._clip_with_subs: Optional['vs.VideoNode'] = None
        self._rgb_clip: Optional['vs.VideoNode'] = None

        # Video properties
        self._fps: float = 23.976
        self._fps_fraction: Optional[Fraction] = None
        self._frame_count: int = 0
        self._duration_ms: float = 0
        self._width: int = 0
        self._height: int = 0

        # Playback state
        self._running = False
        self._playing = False
        self._current_frame: int = 0
        self._current_time_ms: float = 0

        # Thread sync
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._seek_frame: int = -1
        self._reload_subs: bool = False
        self._force_render: bool = False

    def load(self, video_path: str, subtitle_path: Optional[str],
             index_dir: Path, fonts_dir: Optional[str] = None):
        """Set paths for loading."""
        self._video_path = video_path
        self._subtitle_path = subtitle_path
        self._index_dir = index_dir
        self._fonts_dir = fonts_dir

    def set_playing(self, playing: bool):
        """Set playback state."""
        self._mutex.lock()
        self._playing = playing
        self._condition.wakeAll()
        self._mutex.unlock()

    def seek_to_frame(self, frame_num: int):
        """Seek to specific frame."""
        self._mutex.lock()
        self._seek_frame = frame_num
        self._force_render = True
        self._condition.wakeAll()
        self._mutex.unlock()

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Request subtitle reload."""
        self._mutex.lock()
        if subtitle_path:
            self._subtitle_path = subtitle_path
        self._reload_subs = True
        self._force_render = True
        self._condition.wakeAll()
        self._mutex.unlock()

    def request_frame(self):
        """Request current frame render (when paused)."""
        self._mutex.lock()
        self._force_render = True
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
        """Main video playback loop."""
        self._running = True

        try:
            self._load_video()
        except Exception as e:
            self.error.emit(f"Failed to load video: {e}")
            import traceback
            traceback.print_exc()
            return

        # Emit video info
        self.fps_ready.emit(self._fps, self._fps_fraction)
        self.duration_ready.emit(self._duration_ms / 1000.0)

        # Render first frame
        self._render_and_emit_frame(0)

        frame_duration = 1.0 / self._fps if self._fps > 0 else 0.04

        while self._running:
            self._mutex.lock()
            playing = self._playing
            seek_frame = self._seek_frame
            reload_subs = self._reload_subs
            force_render = self._force_render

            self._seek_frame = -1
            self._reload_subs = False
            self._force_render = False
            self._mutex.unlock()

            # Handle subtitle reload
            if reload_subs:
                self._apply_subtitles()
                force_render = True

            # Handle seek
            if seek_frame >= 0:
                self._current_frame = max(0, min(seek_frame, self._frame_count - 1))
                self._current_time_ms = self._frame_to_ms(self._current_frame)
                force_render = True

            # Render frame
            if force_render or playing:
                self._render_and_emit_frame(self._current_frame)

                if playing:
                    self._current_frame += 1
                    self._current_time_ms = self._frame_to_ms(self._current_frame)

                    if self._current_frame >= self._frame_count:
                        self._current_frame = self._frame_count - 1
                        self._playing = False
                        self.playback_finished.emit()

            # Timing
            if playing:
                time.sleep(frame_duration * 0.95)
            else:
                self._mutex.lock()
                self._condition.wait(self._mutex, 100)
                self._mutex.unlock()

        self._cleanup()

    def _load_video(self):
        """Load video with VapourSynth."""
        import vapoursynth as vs

        self._core = vs.core

        # Ensure index directory exists
        self._index_dir.mkdir(parents=True, exist_ok=True)

        # Try L-SMASH first
        lwi_path = self._index_dir / "lwi_index.lwi"
        try:
            self._base_clip = self._core.lsmas.LWLibavSource(
                str(self._video_path),
                cachefile=str(lwi_path)
            )
            print(f"[VideoThread] Loaded with L-SMASH")
        except AttributeError:
            # Fall back to ffms2
            ffindex_path = self._index_dir / "ffms2_index.ffindex"
            self._base_clip = self._core.ffms2.Source(
                source=str(self._video_path),
                cachefile=str(ffindex_path)
            )
            print(f"[VideoThread] Loaded with ffms2")

        # Extract properties
        self._fps = float(self._base_clip.fps)
        self._fps_fraction = Fraction(
            self._base_clip.fps.numerator,
            self._base_clip.fps.denominator
        )
        self._frame_count = len(self._base_clip)
        self._width = self._base_clip.width
        self._height = self._base_clip.height
        self._duration_ms = self._frame_count / self._fps * 1000.0

        print(f"[VideoThread] Video: {self._width}x{self._height} @ {self._fps:.3f}fps")
        print(f"[VideoThread] Frames: {self._frame_count}, Duration: {self._duration_ms:.0f}ms")

        # Apply subtitles
        self._apply_subtitles()

    def _apply_subtitles(self):
        """Apply ASS subtitles using VapourSynth SubText (libass)."""
        if self._base_clip is None:
            return

        # Check if subtitle file exists
        if not self._subtitle_path or not Path(self._subtitle_path).exists():
            print(f"[VideoThread] No subtitles to apply")
            self._clip_with_subs = self._base_clip
            self._build_rgb_clip()
            return

        # Check for SubText plugin
        if not hasattr(self._core, 'sub'):
            print("[VideoThread] WARNING: SubText plugin not available!")
            print("[VideoThread] Subtitles will not be rendered")
            self._clip_with_subs = self._base_clip
            self._build_rgb_clip()
            return

        try:
            print(f"[VideoThread] Applying subtitles: {self._subtitle_path}")

            if self._fonts_dir and Path(self._fonts_dir).exists():
                self._clip_with_subs = self._core.sub.AssFile(
                    self._base_clip,
                    str(self._subtitle_path),
                    fontdir=self._fonts_dir
                )
            else:
                self._clip_with_subs = self._core.sub.AssFile(
                    self._base_clip,
                    str(self._subtitle_path)
                )

            print("[VideoThread] Subtitles applied successfully")

        except Exception as e:
            print(f"[VideoThread] Failed to apply subtitles: {e}")
            self._clip_with_subs = self._base_clip

        self._build_rgb_clip()

    def _build_rgb_clip(self):
        """Build RGB output clip."""
        if self._clip_with_subs is None:
            return

        try:
            self._rgb_clip = self._core.resize.Bicubic(
                self._clip_with_subs,
                format=self._core.query_video_format(vs.RGB, 8, 0, 0).id,
                matrix_in_s='709'
            )
            print(f"[VideoThread] RGB clip ready")
        except Exception as e:
            print(f"[VideoThread] Failed to build RGB clip: {e}")
            # Fallback - try with explicit format
            import vapoursynth as vs
            self._rgb_clip = self._core.resize.Bicubic(
                self._clip_with_subs,
                format=vs.RGB24,
                matrix_in_s='709'
            )

    def _frame_to_ms(self, frame: int) -> float:
        """Convert frame number to milliseconds."""
        if self._fps_fraction:
            return float(frame * 1000 * self._fps_fraction.denominator / self._fps_fraction.numerator)
        return frame * 1000.0 / self._fps

    def _render_and_emit_frame(self, frame_num: int):
        """Render frame and emit signal."""
        if self._rgb_clip is None or frame_num < 0 or frame_num >= self._frame_count:
            return

        try:
            frame = self._rgb_clip.get_frame(frame_num)

            # Extract RGB planes
            r = np.asarray(frame[0])
            g = np.asarray(frame[1])
            b = np.asarray(frame[2])

            # Stack to RGB array
            rgb = np.stack([r, g, b], axis=-1)
            rgb = np.ascontiguousarray(rgb)

            # Create QImage
            height, width = r.shape
            qimage = QImage(
                rgb.data,
                width,
                height,
                width * 3,
                QImage.Format_RGB888
            )

            # Copy since numpy array will be invalidated
            qimage = qimage.copy()

            time_ms = self._frame_to_ms(frame_num)
            self.frame_ready.emit(qimage, time_ms, frame_num)

        except Exception as e:
            print(f"[VideoThread] Error rendering frame {frame_num}: {e}")

    def _cleanup(self):
        """Release VapourSynth resources."""
        self._rgb_clip = None
        self._clip_with_subs = None
        self._base_clip = None
        self._core = None
        gc.collect()
        print("[VideoThread] Cleaned up")


class PyAVPlayer(QWidget):
    """
    FFmpeg-based video player widget.

    Uses VapourSynth for frame-accurate video with libass subtitles,
    and PyAV for audio decoding with sounddevice output.

    Drop-in replacement for MpvWidget.

    Signals:
        time_changed: Current time in milliseconds
        duration_changed: Duration in seconds
        fps_detected: FPS detected
        playback_finished: Video ended
        frame_changed: Current frame number (for subtitle editor)
    """

    time_changed = Signal(int)       # ms
    duration_changed = Signal(float)  # seconds
    fps_detected = Signal(float)
    playback_finished = Signal()
    frame_changed = Signal(int)      # frame number

    def __init__(self, parent=None):
        super().__init__(parent)

        self._video_thread: Optional[VideoThread] = None
        self._audio_thread: Optional[AudioDecoderThread] = None
        self._audio_output: Optional[AudioOutput] = None

        # State
        self._duration_sec: float = 0
        self._fps: float = 23.976
        self._fps_fraction: Optional[Fraction] = None
        self._is_paused: bool = True
        self._current_time_ms: int = 0
        self._current_frame: int = 0

        # Paths
        self._video_path: Optional[str] = None
        self._subtitle_path: Optional[str] = None
        self._fonts_dir: Optional[str] = None
        self._index_dir: Optional[Path] = None

        # Time polling
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_time)
        self._poll_timer.setInterval(50)

        self._setup_ui()

    def _setup_ui(self):
        """Set up the display widget."""
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
        """
        Load a video file.

        Args:
            video_path: Path to video file
            subtitle_path: Path to ASS subtitle file
            fonts_dir: Directory containing fonts
            index_dir: Directory for VapourSynth index cache
        """
        self._video_path = video_path
        self._subtitle_path = subtitle_path
        self._fonts_dir = fonts_dir

        # Use provided index_dir or create one next to video
        if index_dir:
            self._index_dir = Path(index_dir)
        else:
            self._index_dir = Path(video_path).parent / ".vs_index"

        print(f"[PyAVPlayer] Loading: {video_path}")
        if subtitle_path:
            print(f"[PyAVPlayer] Subtitle: {subtitle_path}")
        print(f"[PyAVPlayer] Index dir: {self._index_dir}")

        # Stop existing playback
        self.stop()

        # Create and start video thread
        self._video_thread = VideoThread(self)
        self._video_thread.load(video_path, subtitle_path, self._index_dir, fonts_dir)
        self._video_thread.frame_ready.connect(self._on_frame_ready)
        self._video_thread.duration_ready.connect(self._on_duration_ready)
        self._video_thread.fps_ready.connect(self._on_fps_ready)
        self._video_thread.playback_finished.connect(self._on_playback_finished)
        self._video_thread.error.connect(self._on_error)
        self._video_thread.start()

        # Create and start audio thread
        self._audio_output = AudioOutput()
        self._audio_thread = AudioDecoderThread(self)
        self._audio_thread.load(video_path)
        self._audio_thread.audio_ready.connect(self._on_audio_ready)
        self._audio_thread.audio_info.connect(self._on_audio_info)
        self._audio_thread.start()

        # Start time polling
        self._poll_timer.start()

    @Slot(object, float, int)
    def _on_frame_ready(self, qimage: QImage, time_ms: float, frame_num: int):
        """Handle decoded frame from video thread."""
        self._current_time_ms = int(time_ms)
        self._current_frame = frame_num

        # Scale to display
        display_size = self._display.size()
        scaled = qimage.scaled(
            display_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self._display.setPixmap(QPixmap.fromImage(scaled))

    @Slot(float)
    def _on_duration_ready(self, duration_sec: float):
        """Handle duration detection."""
        self._duration_sec = duration_sec
        self.duration_changed.emit(duration_sec)

    @Slot(float, object)
    def _on_fps_ready(self, fps: float, fps_fraction: Optional[Fraction]):
        """Handle FPS detection."""
        self._fps = fps
        self._fps_fraction = fps_fraction
        self.fps_detected.emit(fps)

        # Start audio output
        if self._audio_output:
            self._audio_output.start(48000, 2)

    @Slot()
    def _on_playback_finished(self):
        """Handle end of playback."""
        self._is_paused = True
        if self._audio_output:
            self._audio_output.set_paused(True)
        self.playback_finished.emit()

    @Slot(str)
    def _on_error(self, error: str):
        """Handle error."""
        print(f"[PyAVPlayer] ERROR: {error}")

    @Slot(object)
    def _on_audio_ready(self, samples: np.ndarray):
        """Handle decoded audio samples."""
        if self._audio_output and not self._is_paused:
            self._audio_output.add_samples(samples)

    @Slot(int, int)
    def _on_audio_info(self, sample_rate: int, channels: int):
        """Handle audio info."""
        print(f"[PyAVPlayer] Audio ready: {sample_rate}Hz, {channels}ch")

    def _poll_time(self):
        """Poll and emit current time."""
        self.time_changed.emit(self._current_time_ms)
        self.frame_changed.emit(self._current_frame)

    def play(self):
        """Start playback."""
        self._is_paused = False
        if self._video_thread:
            self._video_thread.set_playing(True)
        if self._audio_thread:
            self._audio_thread.set_playing(True)
        if self._audio_output:
            self._audio_output.set_paused(False)

    def pause(self):
        """Pause playback."""
        self._is_paused = True
        if self._video_thread:
            self._video_thread.set_playing(False)
        if self._audio_thread:
            self._audio_thread.set_playing(False)
        if self._audio_output:
            self._audio_output.set_paused(True)
            self._audio_output.clear_buffer()

    def toggle_pause(self):
        """Toggle play/pause."""
        if self._is_paused:
            self.play()
        else:
            self.pause()

    def seek(self, time_ms: int, precise: bool = True):
        """
        Seek to time in milliseconds.

        Converts to frame number for frame-accurate seeking.
        """
        if self._fps > 0:
            frame = int(time_ms * self._fps / 1000.0)
            self.seek_frame(frame)

    def seek_frame(self, frame_num: int):
        """
        Seek to specific frame number (frame-accurate).

        This is the primary seek method - guarantees landing on exact frame.
        """
        if self._video_thread:
            self._video_thread.seek_to_frame(frame_num)

        # Sync audio
        if self._audio_thread and self._fps > 0:
            time_ms = frame_num * 1000.0 / self._fps
            self._audio_thread.seek_to(time_ms)
        if self._audio_output:
            self._audio_output.clear_buffer()

    def reload_subtitles(self, subtitle_path: Optional[str] = None):
        """Reload subtitles."""
        if subtitle_path:
            self._subtitle_path = subtitle_path
        if self._video_thread:
            self._video_thread.reload_subtitles(self._subtitle_path)

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

        # Stop threads
        if self._audio_thread:
            self._audio_thread.stop_decoder()
            self._audio_thread = None

        if self._video_thread:
            self._video_thread.stop_thread()
            self._video_thread = None

        # Stop audio output
        if self._audio_output:
            self._audio_output.stop()
            self._audio_output = None

        # Clear display
        self._display.clear()

        gc.collect()
        print("[PyAVPlayer] Stopped")

    def closeEvent(self, event):
        """Handle close."""
        self.stop()
        super().closeEvent(event)
