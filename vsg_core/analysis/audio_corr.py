# vsg_core/analysis/audio_corr.py

# -*- coding: utf-8 -*-
"""
In-memory audio cross-correlation for delay detection.
Implements a decode-once strategy for improved accuracy and consistency.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from scipy.signal import correlate, firwin, lfilter, resample_poly

from ..io.runner import CommandRunner

# --- Language Normalization (from original file) ---
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
def _get_audio_stream_index(mkv_path: str, lang: Optional[str], runner: CommandRunner, tool_paths: dict) -> Optional[int]:
    """Return 0-based audio stream index for ffmpeg -map 0:a:{idx}."""
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str): return None
    try:
        info = json.loads(out)
        audio_tracks = [t for t in info.get('tracks', []) if t.get('type') == 'audio']
        if not audio_tracks: return None
        if lang:
            for i, t in enumerate(audio_tracks):
                props = t.get('properties', {})
                if (props.get('language') or '').strip().lower() == lang:
                    return i
        return 0 # Default to the first audio track
    except (json.JSONDecodeError, IndexError):
        return None

def _probe_stream_sr(file_path: str, a_index: int, runner: CommandRunner, tool_paths: dict) -> int:
    """Probes the native sample rate of a specific audio stream."""
    out = runner.run([
        'ffprobe', '-v', 'error', '-select_streams', f'a:{a_index}',
        '-show_entries', 'stream=sample_rate', '-of', 'csv=p=0', str(file_path)
    ], tool_paths)
    try:
        return int(str(out).strip())
    except (ValueError, TypeError):
        return 48000 # Fallback

def _decode_to_memory(file_path: str, a_index: int, out_sr: int, runner: CommandRunner, tool_paths: dict) -> np.ndarray:
    """Decodes one audio stream to a mono float32 NumPy array."""
    cmd = [
        'ffmpeg', '-nostdin', '-v', 'error',
        '-i', str(file_path), '-map', f'0:a:{a_index}',
        '-ac', '1', '-ar', str(out_sr), '-f', 'f32le', '-'
    ]
    pcm_bytes = runner.run(cmd, tool_paths, is_binary=True)
    if not pcm_bytes or not isinstance(pcm_bytes, bytes):
        raise RuntimeError(f'ffmpeg decode failed for {Path(file_path).name}')
    return np.frombuffer(pcm_bytes, dtype=np.float32)

def _apply_lowpass(waveform: np.ndarray, sr: int, cutoff_hz: int) -> np.ndarray:
    """Applies a simple FIR low-pass filter."""
    if cutoff_hz <= 0: return waveform
    try:
        nyquist = sr / 2
        num_taps = 101 # Simple FIR filter
        hz = min(cutoff_hz, nyquist - 1)
        h = firwin(num_taps, hz / nyquist)
        return lfilter(h, 1.0, waveform).astype(np.float32)
    except Exception:
        return waveform # Return original on filter error

def _find_delay(ref_chunk: np.ndarray, tgt_chunk: np.ndarray, sr: int, peak_fit: bool) -> Tuple[float, float]:
    """Calculates delay and match percentage between two normalized chunks."""
    r = (ref_chunk - np.mean(ref_chunk)) / (np.std(ref_chunk) + 1e-9)
    # --- The fix is on the next line ---
    t = (tgt_chunk - np.mean(tgt_chunk)) / (np.std(tgt_chunk) + 1e-9)
    # ----------------------------------
    c = correlate(r, t, mode='full', method='fft')

    k = np.argmax(np.abs(c))
    lag_samples = float(k - (len(t) - 1))

    # Parabolic peak interpolation for sub-sample accuracy
    if peak_fit and 0 < k < len(c) - 1:
        y1, y2, y3 = c[k-1], c[k], c[k+1]
        delta = 0.5 * (y1 - y3) / (y1 - 2*y2 + y3)
        if -1 < delta < 1: # Ensure delta is reasonable
            lag_samples += delta

    raw_delay_s = lag_samples / float(sr)
    match_pct = (np.abs(c[k]) / (np.sqrt(np.sum(r**2) * np.sum(t**2)) + 1e-9)) * 100.0
    return raw_delay_s * 1000.0, match_pct


# --- Public API ---
def run_audio_correlation(
    ref_file: str,
    target_file: str,
    temp_dir_unused: Path,
    config: Dict,
    runner: CommandRunner,
    tool_paths: Dict[str, str],
    ref_lang: Optional[str],
    target_lang: Optional[str],
    role_tag: str
) -> List[Dict]:
    """
    Performs in-memory audio correlation and returns a list of per-chunk results.
    The caller is responsible for choosing the final delay from this data.
    """
    log = runner._log_message

    # --- 1. Parse Config ---
    cfg = {
        'chunks': int(config.get('scan_chunk_count', 10)),
        'chunk_dur': float(config.get('scan_chunk_duration', 15.0)),
        'min_match': float(config.get('min_match_pct', 5.0)),
        'decode_native': bool(config.get('audio_decode_native', False)),
        'peak_fit': bool(config.get('audio_peak_fit', False)),
        'bandlimit': int(config.get('audio_bandlimit_hz', 0)),
    }
    bandlimit_str = f"{cfg['bandlimit']} Hz" if cfg['bandlimit'] > 0 else "Off"
    log(f"Config: chunks={cfg['chunks']}, chunk_dur={cfg['chunk_dur']}s, min_match_pct={cfg['min_match']:.1f}, "
        f"decode_native={cfg['decode_native']}, peak_fit={cfg['peak_fit']}, bandlimit={bandlimit_str}")

    # --- 2. Stream Selection ---
    ref_norm, tgt_norm = _normalize_lang(ref_lang), _normalize_lang(target_lang)
    idx_ref = _get_audio_stream_index(ref_file, ref_norm, runner, tool_paths)
    idx_tgt = _get_audio_stream_index(target_file, tgt_norm, runner, tool_paths)
    if idx_ref is None or idx_tgt is None:
        raise ValueError("Could not locate required audio streams for correlation.")
    log(f"Selected streams: REF (lang='{ref_norm or 'first'}', index={idx_ref}), "
        f"{role_tag.upper()} (lang='{tgt_norm or 'first'}', index={idx_tgt})")

    # --- 3. Decode and Resample ---
    DEFAULT_SR = 48000
    if cfg['decode_native']:
        sr_ref = _probe_stream_sr(ref_file, idx_ref, runner, tool_paths)
        sr_tgt = _probe_stream_sr(target_file, idx_tgt, runner, tool_paths)
    else:
        sr_ref = sr_tgt = DEFAULT_SR

    ref_pcm = _decode_to_memory(ref_file, idx_ref, sr_ref, runner, tool_paths)
    tgt_pcm = _decode_to_memory(target_file, idx_tgt, sr_tgt, runner, tool_paths)

    if sr_ref != sr_tgt:
        log(f"Resampling target audio from {sr_tgt} Hz to {sr_ref} Hz...")
        up = sr_ref // math.gcd(sr_ref, sr_tgt)
        down = sr_tgt // math.gcd(sr_ref, sr_tgt)
        tgt_pcm = resample_poly(tgt_pcm, up, down).astype(np.float32)

    # --- 4. Pre-processing ---
    ref_pcm = _apply_lowpass(ref_pcm, sr_ref, cfg['bandlimit'])
    tgt_pcm = _apply_lowpass(tgt_pcm, sr_ref, cfg['bandlimit']) # Use sr_ref as final rate

    duration_s = len(ref_pcm) / float(sr_ref)
    log(f"Reference decoded: {duration_s:.2f} s @ {sr_ref} Hz, mono")
    log(f"Processing {cfg['chunks']} chunks of {cfg['chunk_dur']:.1f} seconds each (scan window ≈ 10% → 90%)")

    # --- 5. Per-Chunk Correlation ---
    scan_range = max(0.0, duration_s * 0.8)
    start_offset = duration_s * 0.1
    starts = [start_offset + (scan_range / max(1, cfg['chunks'] - 1) * i) for i in range(cfg['chunks'])]

    results = []
    chunk_samples = int(round(cfg['chunk_dur'] * sr_ref))

    for i, t0 in enumerate(starts, 1):
        start_sample = int(round(t0 * sr_ref))
        end_sample = start_sample + chunk_samples
        if end_sample > len(ref_pcm) or end_sample > len(tgt_pcm):
            continue

        ref_chunk = ref_pcm[start_sample:end_sample]
        tgt_chunk = tgt_pcm[start_sample:end_sample]

        raw_ms, match = _find_delay(ref_chunk, tgt_chunk, sr_ref, cfg['peak_fit'])
        accepted = match >= cfg['min_match']

        status_str = "ACCEPTED" if accepted else f"REJECTED (below {cfg['min_match']:.1f}%)"
        log(f"  Chunk {i}/{cfg['chunks']} (@{t0:.1f}s): delay = {int(round(raw_ms)):+d} ms  "
            f"(raw = {raw_ms:+.3f} ms, match={match:.2f}%) — {status_str}")

        results.append({
            'delay': int(round(raw_ms)),
            'raw_delay': raw_ms,
            'match': match,
            'start': t0,
            'accepted': accepted
        })

    return results
