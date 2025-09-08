# -*- coding: utf-8 -*-
"""
Audio cross-correlation utilities (decode-once, in-memory).
- No Qt/GUI.
- Same stream-pick + sign convention as your original.
- Decodes each file once to 48 kHz mono PCM, slices chunks in memory,
  and logs per-chunk delay with both rounded and high-precision values.
"""

from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import scipy.signal  # same backend as before

# ---------------------------------------------------------------------------
# Language normalization (unchanged behavior)
# ---------------------------------------------------------------------------

_LANG2TO3 = {
    'en': 'eng','ja': 'jpn','jp': 'jpn','zh': 'zho','cn': 'zho','es': 'spa','de': 'deu',
    'fr': 'fra','it': 'ita','pt': 'por','ru': 'rus','ko': 'kor','ar': 'ara','tr': 'tur',
    'pl': 'pol','nl': 'nld','sv': 'swe','no': 'nor','fi': 'fin','da': 'dan','cs': 'ces',
    'sk': 'slk','sl': 'slv','hu': 'hun','el': 'ell','he': 'heb','id': 'ind','vi': 'vie',
    'th': 'tha','hi': 'hin','ur': 'urd','fa': 'fas','uk': 'ukr','ro': 'ron','bg': 'bul',
    'sr': 'srp','hr': 'hrv','ms': 'msa','bn': 'ben','ta': 'tam','te': 'tel'
}

def _normalize_lang(lang: Optional[str]) -> Optional[str]:
    if not lang:
        return None
    s = lang.strip().lower()
    if not s or s == 'und':
        return None
    if len(s) == 2 and s in _LANG2TO3:
        return _LANG2TO3[s]
    return s

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _bin(tool_paths: Dict[str, str], name: str) -> str:
    p = (tool_paths or {}).get(name)
    return p or name

def _get_audio_stream_index(
    mkv_path: str,
    language: Optional[str],
    log: Callable[[str], None],
    tool_paths: Dict[str, str] | None = None,
) -> Optional[int]:
    """
    Return the 0-based audio-stream index (for -map 0:a:<idx>).
    Prefer `language` (3-letter) if provided, else first audio stream.
    """
    desired = _normalize_lang(language)
    cmd = [_bin(tool_paths, 'mkvmerge'), '-J', str(mkv_path)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True)
        info = json.loads(out.stdout)
    except Exception as e:
        log(f"[mkvmerge] probe failed: {e}")
        return None

    idx = -1
    first_found = None
    for t in info.get('tracks', []):
        if t.get('type') == 'audio':
            idx += 1
            if first_found is None:
                first_found = idx
            if desired:
                lang = ((t.get('properties') or {}).get('language') or '').strip().lower()
                if lang == desired:
                    return idx
    return first_found

def _decode_audio_to_array(
    source_file: str,
    stream_index: int,
    sr_out: int,
    mono: bool,
    log: Callable[[str], None],
    tool_paths: Dict[str, str] | None = None,
) -> Tuple[np.ndarray, int]:
    """
    Decode one stream to PCM (s16le) via ffmpeg piping.
    Returns (float32 mono array in [-1,1], sr_out).
    """
    cmd = [
        _bin(tool_paths, 'ffmpeg'), '-v', 'error', '-nostdin',
        '-i', str(source_file),
        '-map', f'0:a:{stream_index}',
        '-ac', '1' if mono else '2',
        '-ar', str(sr_out),
        '-f', 's16le', '-'  # raw PCM to stdout
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        tail = (e.stderr or b'')[-400:].decode('utf-8', errors='ignore')
        log(f"[ffmpeg] decode failed (exit {e.returncode}). stderr tail:\n{tail}")
        raise

    pcm = np.frombuffer(proc.stdout, dtype=np.int16)
    if pcm.size == 0:
        raise RuntimeError("ffmpeg produced no PCM data.")
    y = pcm.astype(np.float32) / 32768.0
    return y, sr_out

def _slice_by_time(y: np.ndarray, sr: int, start_s: float, dur_s: float) -> np.ndarray:
    start = int(round(start_s * sr))
    length = int(round(dur_s * sr))
    if start < 0:
        start = 0
    end = min(start + length, y.shape[0])
    if end <= start:
        return np.zeros((0,), dtype=np.float32)
    return y[start:end].copy()

def _find_audio_delay(
    ref_sig: np.ndarray,
    sec_sig: np.ndarray,
    sr: int,
) -> Tuple[Optional[int], float, Optional[float]]:
    """
    Same math/sign as your original:
      lag_samples = argmax(corr) - (len(sec) - 1)
      delay_ms    = round(lag_samples / sr * 1000)
      match %     = peak / (||ref||*||sec||)
    """
    try:
        if ref_sig.size == 0 or sec_sig.size == 0:
            return None, 0.0, None

        ref = ref_sig.astype(np.float32)
        sec = sec_sig.astype(np.float32)
        ref = (ref - ref.mean()) / (ref.std() + 1e-9)
        sec = (sec - sec.mean()) / (sec.std() + 1e-9)

        corr = scipy.signal.correlate(ref, sec, mode='full', method='auto')
        peak_idx = int(np.argmax(corr))
        lag_samples = peak_idx - (len(sec) - 1)
        raw_delay_s = lag_samples / float(sr)

        norm_factor = math.sqrt(float((ref**2).sum()) * float((sec**2).sum()))
        match_pct = (float(np.max(np.abs(corr))) / (norm_factor + 1e-9)) * 100.0

        return int(round(raw_delay_s * 1000.0)), match_pct, raw_delay_s
    except Exception:
        return None, 0.0, None

# ---------------------------------------------------------------------------
# Public: decode once, slice many, correlate (with per-chunk logging)
# ---------------------------------------------------------------------------

def run_audio_correlation(
    ref_file: str,
    target_file: str,
    temp_dir_unused: Path,    # kept for signature compatibility
    config: Dict,             # expects scan_chunk_count, scan_chunk_duration; optional 'chunk_starts'
    runner,                   # object with ._log_message(str)
    tool_paths: Dict[str, str],
    ref_lang: Optional[str],
    target_lang: Optional[str],
    role_tag: str,
    *,
    sr_out: int = 48000,
    mono: bool = True,
    full_span_like_cli: bool = False,  # True: chunk starts from 0s..(end-chunk)
    log_chunks: bool = True,           # per-chunk verbose logging
) -> List[Dict[str, float]]:
    log = getattr(runner, "_log_message", print)

    # Stream selection
    ref_norm = _normalize_lang(ref_lang)
    tgt_norm = _normalize_lang(target_lang)

    idx_ref = _get_audio_stream_index(ref_file, ref_norm, log, tool_paths)
    idx_tgt = _get_audio_stream_index(target_file, tgt_norm, log, tool_paths)

    log(
        f"Selected streams: REF (lang='{ref_norm or 'first'}', index={idx_ref}), "
        f"{role_tag.upper()} (lang='{tgt_norm or 'first'}', index={idx_tgt})"
    )
    if idx_ref is None or idx_tgt is None:
        raise ValueError("Could not locate required audio streams for correlation.")

    # Decode once
    y_ref, sr_ref = _decode_audio_to_array(ref_file, idx_ref, sr_out, mono, log, tool_paths)
    y_tgt, sr_tgt = _decode_audio_to_array(target_file, idx_tgt, sr_out, mono, log, tool_paths)
    if sr_ref != sr_tgt:
        raise RuntimeError(f"Sample rate mismatch: ref={sr_ref}, tgt={sr_tgt}")

    duration_s = len(y_ref) / float(sr_ref)
    chunks = int(max(1, int(config.get('scan_chunk_count', 10))))
    chunk_dur = float(config.get('scan_chunk_duration', 15.0))

    explicit_starts: Optional[List[float]] = config.get('chunk_starts')
    if explicit_starts:
        starts = [max(0.0, min(duration_s, float(s))) for s in explicit_starts]
    else:
        if full_span_like_cli:
            if chunks == 1:
                starts = [0.0]
            else:
                step = (max(0.0, duration_s - chunk_dur)) / (chunks - 1)
                starts = [i * step for i in range(chunks)]
        else:
            scan_range = max(0.0, duration_s * 0.8)
            start_offset = duration_s * 0.1
            starts = [start_offset + (scan_range / max(1, chunks - 1) * i) for i in range(chunks)]

    if log_chunks:
        log(f"Reference decoded: {duration_s:.2f} s @ {sr_ref} Hz, mono")
        log(f"Processing {chunks} chunks of {chunk_dur:.1f} seconds each")

    results: List[Dict[str, float]] = []
    for i, s in enumerate(starts, 1):
        ref_chunk = _slice_by_time(y_ref, sr_ref, s, chunk_dur)
        tgt_chunk = _slice_by_time(y_tgt, sr_tgt, s, chunk_dur)

        n = min(ref_chunk.shape[0], tgt_chunk.shape[0])
        if n <= 100:
            continue
        if ref_chunk.shape[0] != n:
            ref_chunk = ref_chunk[:n]
        if tgt_chunk.shape[0] != n:
            tgt_chunk = tgt_chunk[:n]

        delay_ms, match_pct, raw_delay_s = _find_audio_delay(ref_chunk, tgt_chunk, sr_ref)
        if delay_ms is not None:
            raw_ms = raw_delay_s * 1000.0 if raw_delay_s is not None else float(delay_ms)
            results.append({
                'delay': float(delay_ms),
                'match': float(match_pct),
                'raw_delay': float(raw_delay_s) if raw_delay_s is not None else float(delay_ms) / 1000.0,
                'start': float(s),
            })
            if log_chunks:
                # integer (for mkvmerge) + raw with 3 decimals, both signed
                log(f"  Chunk {i}/{chunks} (@{s:.1f}s): delay = {int(delay_ms):+d} ms  (raw = {raw_ms:+.3f} ms, match={match_pct:.2f}%)")

    return results
