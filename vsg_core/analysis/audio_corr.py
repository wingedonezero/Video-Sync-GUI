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
    return np.frombuffer(pcm_bytes, dtype=np.float32)

def _apply_bandpass(waveform: np.ndarray, sr: int, lowcut=300.0, highcut=3400.0, order=5) -> np.ndarray:
    """Applies a Butterworth band-pass filter to isolate dialogue frequencies."""
    try:
        nyquist = 0.5 * sr
        low = lowcut / nyquist
        high = highcut / nyquist
        b, a = butter(order, [low, high], btype='band')
        return lfilter(b, a, waveform).astype(np.float32)
    except Exception:
        return waveform

def _apply_lowpass(waveform: np.ndarray, sr: int, cutoff_hz: int) -> np.ndarray:
    """Applies a simple FIR low-pass filter."""
    if cutoff_hz <= 0: return waveform
    try:
        nyquist = sr / 2
        num_taps = 101
        hz = min(cutoff_hz, nyquist - 1)
        h = firwin(num_taps, hz / nyquist)
        return lfilter(h, 1.0, waveform).astype(np.float32)
    except Exception:
        return waveform

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
    match_confidence = np.abs(r_phat[k]) * 100
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
    Runs the full analysis and returns a list of chunk result dictionaries.
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

    # --- 3. Pre-processing (Filtering) ---
    filtering_method = config.get('filtering_method', 'None')
    if filtering_method == 'Dialogue Band-Pass Filter':
        log("Applying Dialogue Band-Pass filter...")
        ref_pcm = _apply_bandpass(ref_pcm, DEFAULT_SR)
        tgt_pcm = _apply_bandpass(tgt_pcm, DEFAULT_SR)
    elif filtering_method == 'Low-Pass Filter':
        cutoff = int(config.get('audio_bandlimit_hz', 0))
        if cutoff > 0:
            log(f"Applying Low-Pass filter at {cutoff} Hz...")
            ref_pcm = _apply_lowpass(ref_pcm, DEFAULT_SR, cutoff)
            tgt_pcm = _apply_lowpass(tgt_pcm, DEFAULT_SR, cutoff)

    # --- 4. Per-Chunk Correlation ---
    duration_s = len(ref_pcm) / float(DEFAULT_SR)
    chunk_count = int(config.get('scan_chunk_count', 10))
    chunk_dur = float(config.get('scan_chunk_duration', 15.0))
    scan_range = max(0.0, duration_s - chunk_dur)
    start_offset = 0
    if scan_range > 0:
        scan_range = duration_s * 0.9
        start_offset = duration_s * 0.05

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
        else:
            raw_ms, match = _find_delay_scc(ref_chunk, tgt_chunk, DEFAULT_SR, peak_fit)

        accepted = match >= min_match
        status_str = "ACCEPTED" if accepted else f"REJECTED (below {min_match:.1f})"
        log(f"  Chunk {i}/{chunk_count} (@{t0:.1f}s): delay = {int(round(raw_ms)):+d} ms (raw={raw_ms:+.3f}, match={match:.2f}) — {status_str}")
        results.append({
            'delay': int(round(raw_ms)), 'raw_delay': raw_ms,
            'match': match, 'start': t0, 'accepted': accepted
        })
    return results
