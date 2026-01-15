# vsg_core/analysis/audio_corr.py
# -*- coding: utf-8 -*-
"""
In-memory audio cross-correlation for delay detection.
Implements a decode-once strategy for improved accuracy and consistency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import correlate, butter, lfilter, firwin

from ..io.runner import CommandRunner

# --- Language Normalization ---
_LANG2TO3 = {
    'en': 'eng', 'ja': 'jpn', 'jp': 'jpn', 'zh': 'zho', 'cn': 'zho', 'es': 'spa', 'de': 'deu', 'fr': 'fra',
    'it': 'ita', 'pt': 'por', 'ru': 'rus', 'ko': 'kor', 'ar': 'ara', 'tr': 'tur', 'pl': 'pol', 'nl': 'nld',
    'sv': 'swe', 'no': 'nor', 'fi': 'fin', 'da': 'dan', 'cs': 'ces', 'sk': 'slk', 'sl': 'slv', 'hu': 'hun',
    'el': 'ell', 'he': 'heb', 'id': 'ind', 'vi': 'vie', 'th': 'tha', 'hi': 'hin', 'ur': 'urd', 'fa': 'fas',
    'uk': 'ukr', 'ro': 'ron', 'bg': 'bul', 'sr': 'srp', 'hr': 'hrv', 'ms': 'msa', 'bn': 'ben', 'ta': 'tam',
    'te': 'tel'
}
def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    if not lang: return None
    s = lang.strip().lower()
    if not s or s == 'und': return None
    return _LANG2TO3.get(s, s) if len(s) == 2 else s


# --- DSP & IO Helpers ---
def get_audio_stream_info(mkv_path: str, lang: Optional[str], runner: CommandRunner, tool_paths: dict) -> Tuple[Optional[int], Optional[int]]:
    """
    Finds the best audio stream and returns its 0-based index and mkvmerge track ID.
    Returns: A tuple of (stream_index, track_id) or (None, None).
    """
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str): return None, None
    try:
        info = json.loads(out)
        audio_tracks = [t for t in info.get('tracks', []) if t.get('type') == 'audio']
        if not audio_tracks: return None, None
        if lang:
            for i, t in enumerate(audio_tracks):
                props = t.get('properties', {})
                if (props.get('language') or '').strip().lower() == lang:
                    return i, t.get('id')
        # Fallback to the first audio track
        first_track = audio_tracks[0]
        return 0, first_track.get('id')
    except (json.JSONDecodeError, IndexError):
        return None, None

def _decode_to_memory(file_path: str, a_index: int, out_sr: int, use_soxr: bool, runner: CommandRunner, tool_paths: dict) -> np.ndarray:
    """Decodes one audio stream to a mono float32 NumPy array."""
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error',
        '-i', str(file_path), '-map', f'0:a:{a_index}']

    if use_soxr:
        cmd.extend(['-resampler', 'soxr'])

    cmd.extend(['-ac', '1', '-ar', str(out_sr), '-f', 'f32le', '-'])

    pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
    if not pcm_bytes or not isinstance(pcm_bytes, bytes):
        raise RuntimeError(f'ffmpeg decode failed for {Path(file_path).name}')

    # Ensure buffer size is a multiple of element size (4 bytes for float32)
    # This fixes issues with Opus and other codecs that may produce unaligned output
    element_size = np.dtype(np.float32).itemsize
    aligned_size = (len(pcm_bytes) // element_size) * element_size
    if aligned_size != len(pcm_bytes):
        trimmed_bytes = len(pcm_bytes) - aligned_size
        if hasattr(runner, '_log_message'):
            runner._log_message(f"[BUFFER ALIGNMENT] Trimmed {trimmed_bytes} bytes from {Path(file_path).name} (likely Opus/other codec)")
        pcm_bytes = pcm_bytes[:aligned_size]

    return np.frombuffer(pcm_bytes, dtype=np.float32)

def _apply_bandpass(waveform: np.ndarray, sr: int, lowcut: float, highcut: float, order: int) -> np.ndarray:
    """Applies a Butterworth band-pass filter to isolate dialogue frequencies."""
    try:
        nyquist = 0.5 * sr
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return lfilter(b, a, waveform).astype(np.float32)
    except Exception:
        return waveform

def _apply_lowpass(waveform: np.ndarray, sr: int, cutoff_hz: int, num_taps: int) -> np.ndarray:
    """Applies a simple FIR low-pass filter."""
    if cutoff_hz <= 0: return waveform
    try:
        nyquist = sr / 2
        hz = min(cutoff_hz, nyquist - 1)
        h = firwin(num_taps, hz / nyquist)
        return lfilter(h, 1.0, waveform).astype(np.float32)
    except Exception:
        return waveform

def _normalize_peak_confidence(correlation_array: np.ndarray, peak_idx: int) -> float:
    """
    Normalizes peak confidence by comparing to noise floor and second-best peak.

    This provides robust confidence estimation that's comparable across different
    videos with varying noise floors and signal characteristics.

    Uses three normalization strategies:
    1. peak / median (prominence over noise floor)
    2. peak / second_best (uniqueness of the match)
    3. peak / local_stddev (signal-to-noise ratio)

    Args:
        correlation_array: The correlation result array
        peak_idx: Index of the peak in the array

    Returns:
        Normalized confidence score (0-100)
    """
    abs_corr = np.abs(correlation_array)
    peak_value = abs_corr[peak_idx]

    # Metric 1: Noise floor using median (more robust than mean)
    noise_floor_median = np.median(abs_corr)
    prominence_ratio = peak_value / (noise_floor_median + 1e-9)

    # Metric 2: Find second-best peak (excluding immediate neighbors)
    # Create a mask to exclude the peak and its neighbors to avoid sidelobes
    mask = np.ones(len(abs_corr), dtype=bool)
    neighbor_range = max(1, len(abs_corr) // 100)  # Exclude 1% around peak
    start_mask = max(0, peak_idx - neighbor_range)
    end_mask = min(len(abs_corr), peak_idx + neighbor_range + 1)
    mask[start_mask:end_mask] = False

    second_best = np.max(abs_corr[mask]) if np.any(mask) else noise_floor_median
    uniqueness_ratio = peak_value / (second_best + 1e-9)

    # Metric 3: SNR using robust background estimation
    # Use standard deviation of lower 90% of values
    threshold_90 = np.percentile(abs_corr, 90)
    background = abs_corr[abs_corr < threshold_90]
    bg_stddev = np.std(background) if len(background) > 10 else 1e-9
    snr_ratio = peak_value / (bg_stddev + 1e-9)

    # Combine metrics with empirically tuned weights and scales
    # Prominence: scaled by 5 (typical good match: 10-30 → 50-150)
    # Uniqueness: scaled by 8 (typical good match: 2-5 → 16-40)
    # SNR: scaled by 1.5 (typical good match: 15-50 → 22-75)
    # Combined typical range: 88-265 for good matches
    confidence = (prominence_ratio * 5.0) + (uniqueness_ratio * 8.0) + (snr_ratio * 1.5)

    # Scale to 0-100 range: divide by 3 to bring typical good matches to ~30-90 range
    confidence = confidence / 3.0

    return min(100.0, max(0.0, confidence))

def _find_delay_gcc_phat(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """Calculates delay using Generalized Cross-Correlation with Phase Transform."""
    n = len(ref_chunk) + len(tgt_chunk) - 1
    R = np.fft.fft(ref_chunk, n)
    T = np.fft.fft(tgt_chunk, n)
    G = R * np.conj(T)
    G_phat = G / (np.abs(G) + 1e-9)
    r_phat = np.fft.ifft(G_phat)
    k = np.argmax(np.abs(r_phat))
    lag_samples = k - n if k > n / 2 else k
    delay_ms = (lag_samples / float(sr)) * 1000.0
    match_confidence = _normalize_peak_confidence(r_phat, k)
    return delay_ms, match_confidence

def _find_delay_scc(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int, peak_fit: bool) -> Tuple[float, float]:
    """Calculates delay and match percentage using standard cross-correlation."""
    r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
    t = (tgt_chunk - np.mean(tgt_chunk)) / (np.std(tgt_chunk) + 1e-9)
    c = correlate(r, t, mode='full', method='fft')
    k = np.argmax(np.abs(c))
    lag_samples = float(k - (len(t) - 1))
    if peak_fit and 0 < k < len(c) - 1:
        y1, y2, y3 = np.abs(c[k-1:k+2])
        delta = 0.5 * (y1 - y3) / (y1 - 2*y2 + y3)
        if -1 < delta < 1:
            lag_samples += delta
    raw_delay_s = lag_samples / float(sr)
    match_pct = (np.abs(c[k]) / (np.sqrt(np.sum(r**2) * np.sum(t**2)) + 1e-9)) * 100.0
    return raw_delay_s * 1000.0, match_pct


def _find_delay_onset(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Calculates delay using onset detection envelope correlation.

    Computes onset strength envelopes (detecting transients like hits, speech onsets,
    music attacks) and correlates those rather than raw waveforms. More robust to
    different audio mixes since it matches *when things happen* not exact waveform shape.

    Uses GCC-PHAT on the onset envelopes for the actual correlation.
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("Onset Detection requires librosa. Install with: pip install librosa")

    # Onset detection parameters
    # hop_length=512 at 48kHz gives ~10.7ms resolution per frame
    hop_length = 512

    # Compute onset strength envelopes
    # This detects transients (attacks, hits, speech onsets) and creates
    # a 1D envelope showing "onset-ness" over time
    ref_env = librosa.onset.onset_strength(y=ref_chunk, sr=sr, hop_length=hop_length)
    tgt_env = librosa.onset.onset_strength(y=tgt_chunk, sr=sr, hop_length=hop_length)

    # Normalize envelopes
    ref_env = (ref_env - np.mean(ref_env)) / (np.std(ref_env) + 1e-9)
    tgt_env = (tgt_env - np.mean(tgt_env)) / (np.std(tgt_env) + 1e-9)

    # Cross-correlate envelopes using GCC-PHAT for robustness
    # The envelope sample rate is sr / hop_length
    envelope_sr = sr / hop_length  # ~93.75 Hz at 48kHz with hop=512

    n = len(ref_env) + len(tgt_env) - 1
    R = np.fft.fft(ref_env, n)
    T = np.fft.fft(tgt_env, n)
    G = R * np.conj(T)
    G_phat = G / (np.abs(G) + 1e-9)
    r_phat = np.fft.ifft(G_phat)

    k = np.argmax(np.abs(r_phat))
    lag_frames = k - n if k > n / 2 else k

    # Convert frame lag to milliseconds
    delay_ms = (lag_frames / envelope_sr) * 1000.0
    match_confidence = _normalize_peak_confidence(r_phat, k)

    return delay_ms, match_confidence


def _find_delay_gcc_scot(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Calculates delay using GCC-SCOT (Smoothed Coherence Transform).

    Similar to GCC-PHAT but weights by signal coherence instead of just phase.
    Better than PHAT when one signal has more noise than the other, as it
    accounts for the reliability of each frequency bin.
    """
    n = len(ref_chunk) + len(tgt_chunk) - 1
    R = np.fft.fft(ref_chunk, n)
    T = np.fft.fft(tgt_chunk, n)

    # Cross-power spectrum
    G = R * np.conj(T)

    # SCOT weighting: normalize by geometric mean of auto-spectra
    # This gives more weight to frequencies where both signals are strong
    R_power = np.abs(R) ** 2
    T_power = np.abs(T) ** 2
    scot_weight = np.sqrt(R_power * T_power) + 1e-9

    G_scot = G / scot_weight
    r_scot = np.fft.ifft(G_scot)

    k = np.argmax(np.abs(r_scot))
    lag_samples = k - n if k > n / 2 else k
    delay_ms = (lag_samples / float(sr)) * 1000.0

    # Match confidence based on peak prominence
    match_confidence = np.abs(r_scot[k]) / (np.mean(np.abs(r_scot)) + 1e-9) * 10
    match_confidence = min(100.0, match_confidence)

    return delay_ms, match_confidence


def _find_delay_gcc_whiten(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Calculates delay using GCC with Spectral Whitening (Whitened Cross-Correlation).

    Whitening equalizes the magnitude spectrum of both signals before correlation,
    making it robust to spectral differences caused by processing (like source
    separation), different recording conditions, or frequency-dependent effects.

    This is particularly useful when comparing audio that has been processed
    differently (e.g., separated instrumental vs. original mix) as it focuses
    on timing/phase alignment rather than spectral content matching.

    The whitening process:
    1. Transform both signals to frequency domain
    2. Normalize the magnitude spectrum (keeping phase intact)
    3. Compute cross-correlation in whitened space
    4. Find peak delay from the correlation result
    """
    n = len(ref_chunk) + len(tgt_chunk) - 1
    R = np.fft.fft(ref_chunk, n)
    T = np.fft.fft(tgt_chunk, n)

    # Whiten both signals: normalize magnitude while preserving phase
    # This makes the method robust to spectral differences
    R_whitened = R / (np.abs(R) + 1e-9)
    T_whitened = T / (np.abs(T) + 1e-9)

    # Cross-correlation in whitened space
    G_whitened = R_whitened * np.conj(T_whitened)
    r_whitened = np.fft.ifft(G_whitened)

    k = np.argmax(np.abs(r_whitened))
    lag_samples = k - n if k > n / 2 else k
    delay_ms = (lag_samples / float(sr)) * 1000.0

    # Match confidence based on peak sharpness
    # Whitening tends to produce sharper peaks for aligned signals
    match_confidence = _normalize_peak_confidence(r_whitened, k)

    return delay_ms, match_confidence


def _find_delay_dtw(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Calculates delay using Dynamic Time Warping on MFCC features.

    DTW finds the optimal alignment between two sequences, handling tempo
    variations and non-linear time differences. Uses MFCC features which
    are robust to amplitude and timbral differences.

    Returns the median offset from the warping path as the delay estimate.
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("DTW requires librosa. Install with: pip install librosa")

    # Downsample for DTW efficiency (DTW is O(n*m) complexity)
    # Use a lower sample rate for feature extraction
    hop_length = 512

    # Extract MFCC features - robust to amplitude/timbre differences
    ref_mfcc = librosa.feature.mfcc(y=ref_chunk, sr=sr, n_mfcc=13, hop_length=hop_length)
    tgt_mfcc = librosa.feature.mfcc(y=tgt_chunk, sr=sr, n_mfcc=13, hop_length=hop_length)

    # Compute DTW alignment
    # D is the accumulated cost matrix, wp is the warping path
    D, wp = librosa.sequence.dtw(X=ref_mfcc, Y=tgt_mfcc, metric='euclidean')

    # wp is array of (ref_frame, tgt_frame) pairs along optimal path
    # Calculate the offset at each point in the path
    offsets_frames = wp[:, 1] - wp[:, 0]  # tgt - ref frame indices

    # Use median offset (robust to outliers at boundaries)
    median_offset_frames = np.median(offsets_frames)

    # Convert frame offset to milliseconds
    frame_duration_ms = (hop_length / sr) * 1000.0
    delay_ms = median_offset_frames * frame_duration_ms

    # Match confidence based on normalized DTW distance
    # Lower distance = better match
    path_length = len(wp)
    avg_cost = D[wp[-1, 0], wp[-1, 1]] / path_length if path_length > 0 else float('inf')

    # Convert to 0-100 scale (lower cost = higher confidence)
    # Empirically, good matches have avg_cost < 50, poor matches > 200
    match_confidence = max(0, min(100, 100 - avg_cost * 0.5))

    return delay_ms, match_confidence


def _find_delay_spectrogram(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int) -> Tuple[float, float]:
    """
    Calculates delay using spectrogram cross-correlation.

    Computes mel spectrograms of both signals and correlates them along the
    time axis. Captures both frequency and time structure, making it robust
    to some types of audio differences while maintaining time precision.
    """
    try:
        import librosa
    except ImportError:
        raise ImportError("Spectrogram correlation requires librosa. Install with: pip install librosa")

    hop_length = 512
    n_mels = 64  # Number of mel bands

    # Compute mel spectrograms (log-scaled for better dynamic range)
    ref_mel = librosa.feature.melspectrogram(y=ref_chunk, sr=sr, hop_length=hop_length, n_mels=n_mels)
    tgt_mel = librosa.feature.melspectrogram(y=tgt_chunk, sr=sr, hop_length=hop_length, n_mels=n_mels)

    # Convert to log scale (dB)
    ref_mel_db = librosa.power_to_db(ref_mel, ref=np.max)
    tgt_mel_db = librosa.power_to_db(tgt_mel, ref=np.max)

    # Flatten spectrograms along frequency axis to get time-series of spectral features
    # Then correlate these feature vectors
    ref_flat = ref_mel_db.mean(axis=0)  # Average across mel bands
    tgt_flat = tgt_mel_db.mean(axis=0)

    # Normalize
    ref_norm = (ref_flat - np.mean(ref_flat)) / (np.std(ref_flat) + 1e-9)
    tgt_norm = (tgt_flat - np.mean(tgt_flat)) / (np.std(tgt_flat) + 1e-9)

    # Cross-correlate using GCC-PHAT for robustness
    n = len(ref_norm) + len(tgt_norm) - 1
    R = np.fft.fft(ref_norm, n)
    T = np.fft.fft(tgt_norm, n)
    G = R * np.conj(T)
    G_phat = G / (np.abs(G) + 1e-9)
    r_phat = np.fft.ifft(G_phat)

    k = np.argmax(np.abs(r_phat))
    lag_frames = k - n if k > n / 2 else k

    # Convert frame lag to milliseconds
    frame_duration_ms = (hop_length / sr) * 1000.0
    delay_ms = lag_frames * frame_duration_ms

    match_confidence = _normalize_peak_confidence(r_phat, k)

    return delay_ms, match_confidence


# --- Public API ---
def run_audio_correlation(
    ref_file: str,
    target_file: str,
    config: Dict,
    runner: CommandRunner,
    tool_paths: Dict[str, str],
    ref_lang: Optional[str],
    target_lang: Optional[str],
    role_tag: str
) -> List[Dict]:
    """
    Runs audio correlation analysis between reference and target files.

    Decodes audio streams, applies optional filtering (dialogue band-pass or low-pass),
    then analyzes multiple chunks across the file to detect delay and match quality.

    Args:
        ref_file: Path to reference video file (Source 1)
        target_file: Path to target video file to analyze
        config: Configuration dictionary with analysis settings
        runner: CommandRunner for executing ffmpeg/ffprobe commands
        tool_paths: Paths to external tools (ffmpeg, ffprobe, etc.)
        ref_lang: Optional language code to select reference audio stream
        target_lang: Optional language code to select target audio stream
        role_tag: Source identifier for logging (e.g., "Source 2", "Source 3")

    Returns:
        List of chunk result dictionaries, each containing:
            - delay (int): Rounded delay in milliseconds
            - raw_delay (float): Unrounded delay value
            - match (float): Match quality/confidence score (0-100)
            - start (float): Start time of chunk in seconds
            - accepted (bool): True if match >= min_match_pct threshold
    """
    log = runner._log_message

    # --- 1. Select streams ---
    ref_norm, tgt_norm = _normalize_lang(ref_lang), _normalize_lang(target_lang)
    idx_ref, _ = get_audio_stream_info(ref_file, ref_norm, runner, tool_paths)
    idx_tgt, id_tgt = get_audio_stream_info(target_file, tgt_norm, runner, tool_paths)

    if idx_ref is None or idx_tgt is None:
        raise ValueError("Could not locate required audio streams for correlation.")
    log(f"Selected streams: REF (lang='{ref_norm or 'first'}', index={idx_ref}), "
        f"{role_tag.upper()} (lang='{tgt_norm or 'first'}', index={idx_tgt}, track_id={id_tgt})")

    # --- 2. Decode ---
    DEFAULT_SR = 48000
    use_soxr = config.get('use_soxr', False)
    ref_pcm = _decode_to_memory(ref_file, idx_ref, DEFAULT_SR, use_soxr, runner, tool_paths)
    tgt_pcm = _decode_to_memory(target_file, idx_tgt, DEFAULT_SR, use_soxr, runner, tool_paths)

    # --- 2b. Source Separation (Optional) ---
    separation_mode = config.get('source_separation_mode', 'none')
    if separation_mode and separation_mode != 'none':
        try:
            from .source_separation import apply_source_separation
            ref_pcm, tgt_pcm = apply_source_separation(
                ref_pcm, tgt_pcm, DEFAULT_SR, config, log
            )
        except ImportError as e:
            log(f"[SOURCE SEPARATION] Dependencies not available: {e}")
        except Exception as e:
            log(f"[SOURCE SEPARATION] Error during separation: {e}")

    # --- 3. Pre-processing (Filtering) ---
    filtering_method = config.get('filtering_method', 'None')
    if filtering_method == 'Dialogue Band-Pass Filter':
        log("Applying Dialogue Band-Pass filter...")
        lowcut = config.get('filter_bandpass_lowcut_hz', 300.0)
        highcut = config.get('filter_bandpass_highcut_hz', 3400.0)
        order = config.get('filter_bandpass_order', 5)
        ref_pcm = _apply_bandpass(ref_pcm, DEFAULT_SR, lowcut, highcut, order)
        tgt_pcm = _apply_bandpass(tgt_pcm, DEFAULT_SR, lowcut, highcut, order)
    elif filtering_method == 'Low-Pass Filter':
        cutoff = int(config.get('audio_bandlimit_hz', 0))
        if cutoff > 0:
            log(f"Applying Low-Pass filter at {cutoff} Hz...")
            taps = config.get('filter_lowpass_taps', 101)
            ref_pcm = _apply_lowpass(ref_pcm, DEFAULT_SR, cutoff, taps)
            tgt_pcm = _apply_lowpass(tgt_pcm, DEFAULT_SR, cutoff, taps)

    # --- 4. Per-Chunk Correlation ---
    duration_s = len(ref_pcm) / float(DEFAULT_SR)
    chunk_count = int(config.get('scan_chunk_count', 10))
    chunk_dur = float(config.get('scan_chunk_duration', 15.0))

    start_pct = config.get('scan_start_percentage', 5.0)
    end_pct = config.get('scan_end_percentage', 95.0)
    if not 0.0 <= start_pct < end_pct <= 100.0: # Sanity check
        start_pct, end_pct = 5.0, 95.0

    scan_start_s = duration_s * (start_pct / 100.0)
    scan_end_s = duration_s * (end_pct / 100.0)

    # Total duration of the scannable area, accounting for the final chunk's length
    scan_range = max(0.0, (scan_end_s - scan_start_s) - chunk_dur)
    start_offset = scan_start_s

    starts = [start_offset + (scan_range / max(1, chunk_count - 1) * i) for i in range(chunk_count)]
    results = []
    chunk_samples = int(round(chunk_dur * DEFAULT_SR))

    correlation_method = config.get('correlation_method', 'Standard Correlation (SCC)')
    peak_fit = config.get('audio_peak_fit', False)
    min_match = float(config.get('min_match_pct', 5.0))

    for i, t0 in enumerate(starts, 1):
        start_sample = int(round(t0 * DEFAULT_SR))
        end_sample = start_sample + chunk_samples
        if end_sample > len(ref_pcm) or end_sample > len(tgt_pcm):
            continue

        ref_chunk = ref_pcm[start_sample:end_sample]
        tgt_chunk = tgt_pcm[start_sample:end_sample]

        if 'Phase Correlation (GCC-PHAT)' in correlation_method:
            raw_ms, match = _find_delay_gcc_phat(ref_chunk, tgt_chunk, DEFAULT_SR)
        elif 'Onset Detection' in correlation_method:
            raw_ms, match = _find_delay_onset(ref_chunk, tgt_chunk, DEFAULT_SR)
        elif 'GCC-SCOT' in correlation_method:
            raw_ms, match = _find_delay_gcc_scot(ref_chunk, tgt_chunk, DEFAULT_SR)
        elif 'DTW' in correlation_method:
            raw_ms, match = _find_delay_dtw(ref_chunk, tgt_chunk, DEFAULT_SR)
        elif 'Spectrogram' in correlation_method:
            raw_ms, match = _find_delay_spectrogram(ref_chunk, tgt_chunk, DEFAULT_SR)
        else:
            raw_ms, match = _find_delay_scc(ref_chunk, tgt_chunk, DEFAULT_SR, peak_fit)

        accepted = match >= min_match
        status_str = "ACCEPTED" if accepted else f"REJECTED (below {min_match:.1f})"
        log(f"  Chunk {i}/{chunk_count} (@{t0:.1f}s): delay = {int(round(raw_ms)):+d} ms (raw={raw_ms:+.3f}, match={match:.2f}) — {status_str}")
        results.append({
            'delay': int(round(raw_ms)), 'raw_delay': raw_ms,
            'match': match, 'start': t0, 'accepted': accepted
        })

    # Release audio arrays immediately after correlation completes
    ref_pcm = None
    tgt_pcm = None
    import gc
    gc.collect()

    return results


# --- Method name to config key mapping ---
MULTI_CORR_METHODS = [
    ('Standard Correlation (SCC)', 'multi_corr_scc'),
    ('Phase Correlation (GCC-PHAT)', 'multi_corr_gcc_phat'),
    ('Onset Detection', 'multi_corr_onset'),
    ('GCC-SCOT', 'multi_corr_gcc_scot'),
    ('Whitened Cross-Correlation', 'multi_corr_gcc_whiten'),
    ('DTW (Dynamic Time Warping)', 'multi_corr_dtw'),
    ('Spectrogram Correlation', 'multi_corr_spectrogram'),
]


def _run_method_on_chunks(
    method_name: str,
    chunks: List[Tuple[int, float, np.ndarray, np.ndarray]],
    sr: int,
    min_match: float,
    peak_fit: bool,
    log: Callable
) -> List[Dict]:
    """
    Runs a specific correlation method on pre-extracted chunks.

    Args:
        method_name: Name of the correlation method
        chunks: List of (chunk_index, start_time, ref_chunk, tgt_chunk) tuples
        sr: Sample rate
        min_match: Minimum match percentage threshold
        peak_fit: Whether to use peak fitting (SCC only)
        log: Logging function

    Returns:
        List of chunk results
    """
    results = []
    chunk_count = len(chunks)

    for i, t0, ref_chunk, tgt_chunk in chunks:
        if 'Phase Correlation (GCC-PHAT)' in method_name:
            raw_ms, match = _find_delay_gcc_phat(ref_chunk, tgt_chunk, sr)
        elif 'Onset Detection' in method_name:
            raw_ms, match = _find_delay_onset(ref_chunk, tgt_chunk, sr)
        elif 'GCC-SCOT' in method_name:
            raw_ms, match = _find_delay_gcc_scot(ref_chunk, tgt_chunk, sr)
        elif 'Whitened Cross-Correlation' in method_name:
            raw_ms, match = _find_delay_gcc_whiten(ref_chunk, tgt_chunk, sr)
        elif 'DTW' in method_name:
            raw_ms, match = _find_delay_dtw(ref_chunk, tgt_chunk, sr)
        elif 'Spectrogram' in method_name:
            raw_ms, match = _find_delay_spectrogram(ref_chunk, tgt_chunk, sr)
        else:
            raw_ms, match = _find_delay_scc(ref_chunk, tgt_chunk, sr, peak_fit)

        accepted = match >= min_match
        status_str = "ACCEPTED" if accepted else f"REJECTED (below {min_match:.1f})"
        log(f"  Chunk {i}/{chunk_count} (@{t0:.1f}s): delay = {int(round(raw_ms)):+d} ms (raw={raw_ms:+.3f}, match={match:.2f}) — {status_str}")
        results.append({
            'delay': int(round(raw_ms)), 'raw_delay': raw_ms,
            'match': match, 'start': t0, 'accepted': accepted
        })

    return results


def run_multi_correlation(
    ref_file: str,
    target_file: str,
    config: Dict,
    runner: CommandRunner,
    tool_paths: Dict[str, str],
    ref_lang: Optional[str],
    target_lang: Optional[str],
    role_tag: str
) -> Dict[str, List[Dict]]:
    """
    Runs multiple correlation methods on the same audio chunks for comparison.

    Decodes audio once, extracts chunks once, then runs each enabled correlation
    method on the same data. Used for Analyze Only mode when multi-correlation
    comparison is enabled.

    Args:
        ref_file: Path to reference video file (Source 1)
        target_file: Path to target video file to analyze
        config: Configuration dictionary with analysis settings
        runner: CommandRunner for executing ffmpeg/ffprobe commands
        tool_paths: Paths to external tools
        ref_lang: Optional language code for reference audio
        target_lang: Optional language code for target audio
        role_tag: Source identifier for logging

    Returns:
        Dict mapping method names to their chunk result lists
    """
    log = runner._log_message

    # Safety check: if multi-correlation is disabled, fall back to single method immediately
    if not config.get('multi_correlation_enabled', False):
        log("[MULTI-CORRELATION] Feature disabled, using single correlation method")
        return {config.get('correlation_method', 'Standard Correlation (SCC)'):
                run_audio_correlation(ref_file, target_file, config, runner, tool_paths, ref_lang, target_lang, role_tag)}

    # Get enabled methods
    enabled_methods = []
    for method_name, config_key in MULTI_CORR_METHODS:
        if config.get(config_key, False):
            enabled_methods.append(method_name)

    if not enabled_methods:
        log("[MULTI-CORRELATION] No methods enabled, falling back to single method")
        return {config.get('correlation_method', 'Standard Correlation (SCC)'):
                run_audio_correlation(ref_file, target_file, config, runner, tool_paths, ref_lang, target_lang, role_tag)}

    # --- 1. Select streams ---
    ref_norm, tgt_norm = _normalize_lang(ref_lang), _normalize_lang(target_lang)
    idx_ref, _ = get_audio_stream_info(ref_file, ref_norm, runner, tool_paths)
    idx_tgt, id_tgt = get_audio_stream_info(target_file, tgt_norm, runner, tool_paths)

    if idx_ref is None or idx_tgt is None:
        raise ValueError("Could not locate required audio streams for correlation.")
    log(f"Selected streams: REF (lang='{ref_norm or 'first'}', index={idx_ref}), "
        f"{role_tag.upper()} (lang='{tgt_norm or 'first'}', index={idx_tgt}, track_id={id_tgt})")

    # --- 2. Decode ---
    DEFAULT_SR = 48000
    use_soxr = config.get('use_soxr', False)
    ref_pcm = _decode_to_memory(ref_file, idx_ref, DEFAULT_SR, use_soxr, runner, tool_paths)
    tgt_pcm = _decode_to_memory(target_file, idx_tgt, DEFAULT_SR, use_soxr, runner, tool_paths)

    # --- 2b. Source Separation (Optional) ---
    separation_mode = config.get('source_separation_mode', 'none')
    if separation_mode and separation_mode != 'none':
        try:
            from .source_separation import apply_source_separation
            ref_pcm, tgt_pcm = apply_source_separation(
                ref_pcm, tgt_pcm, DEFAULT_SR, config, log
            )
        except ImportError as e:
            log(f"[SOURCE SEPARATION] Dependencies not available: {e}")
        except Exception as e:
            log(f"[SOURCE SEPARATION] Error during separation: {e}")

    # --- 3. Pre-processing (Filtering) ---
    filtering_method = config.get('filtering_method', 'None')
    if filtering_method == 'Dialogue Band-Pass Filter':
        log("Applying Dialogue Band-Pass filter...")
        lowcut = config.get('filter_bandpass_lowcut_hz', 300.0)
        highcut = config.get('filter_bandpass_highcut_hz', 3400.0)
        order = config.get('filter_bandpass_order', 5)
        ref_pcm = _apply_bandpass(ref_pcm, DEFAULT_SR, lowcut, highcut, order)
        tgt_pcm = _apply_bandpass(tgt_pcm, DEFAULT_SR, lowcut, highcut, order)
    elif filtering_method == 'Low-Pass Filter':
        cutoff = int(config.get('audio_bandlimit_hz', 0))
        if cutoff > 0:
            log(f"Applying Low-Pass filter at {cutoff} Hz...")
            taps = config.get('filter_lowpass_taps', 101)
            ref_pcm = _apply_lowpass(ref_pcm, DEFAULT_SR, cutoff, taps)
            tgt_pcm = _apply_lowpass(tgt_pcm, DEFAULT_SR, cutoff, taps)

    # --- 4. Extract chunks ONCE ---
    duration_s = len(ref_pcm) / float(DEFAULT_SR)
    chunk_count = int(config.get('scan_chunk_count', 10))
    chunk_dur = float(config.get('scan_chunk_duration', 15.0))

    start_pct = config.get('scan_start_percentage', 5.0)
    end_pct = config.get('scan_end_percentage', 95.0)
    if not 0.0 <= start_pct < end_pct <= 100.0:
        start_pct, end_pct = 5.0, 95.0

    scan_start_s = duration_s * (start_pct / 100.0)
    scan_end_s = duration_s * (end_pct / 100.0)
    scan_range = max(0.0, (scan_end_s - scan_start_s) - chunk_dur)
    start_offset = scan_start_s
    starts = [start_offset + (scan_range / max(1, chunk_count - 1) * i) for i in range(chunk_count)]
    chunk_samples = int(round(chunk_dur * DEFAULT_SR))

    # Extract all chunks
    chunks = []
    for i, t0 in enumerate(starts, 1):
        start_sample = int(round(t0 * DEFAULT_SR))
        end_sample = start_sample + chunk_samples
        if end_sample > len(ref_pcm) or end_sample > len(tgt_pcm):
            continue
        ref_chunk = ref_pcm[start_sample:end_sample]
        tgt_chunk = tgt_pcm[start_sample:end_sample]
        chunks.append((i, t0, ref_chunk, tgt_chunk))

    log(f"\n[MULTI-CORRELATION] Running {len(enabled_methods)} methods on {len(chunks)} chunks")

    # --- 5. Run each method on the same chunks ---
    peak_fit = config.get('audio_peak_fit', False)
    min_match = float(config.get('min_match_pct', 5.0))
    all_results = {}

    for method_name in enabled_methods:
        log(f"\n{'═' * 70}")
        log(f"  MULTI-CORRELATION: {method_name}")
        log(f"{'═' * 70}")

        results = _run_method_on_chunks(method_name, chunks, DEFAULT_SR, min_match, peak_fit, log)
        all_results[method_name] = results

    return all_results
