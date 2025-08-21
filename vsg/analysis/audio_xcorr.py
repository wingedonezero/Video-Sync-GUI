"""Moved implementations for analysis.audio_xcorr (full-move RC)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.tools import run_command


def get_audio_stream_index(file_path: str, logger, language: Optional[str]) -> Optional[int]:
    info = get_stream_info(file_path, logger)
    if not info:
        return None
    idx = -1
    found = None
    for t in info.get('tracks', []):
        if t.get('type') == 'audio':
            idx += 1
            if language and t.get('properties', {}).get('language') == language:
                return idx
            if found is None:
                found = idx
    return found


def extract_audio_chunk(source_file: str, output_wav: str, start_time: float, duration: float, logger,
                        stream_index: int):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', str(start_time), '-i', str(source_file), '-map', f'0:a:{stream_index}',
           '-t', str(duration), '-vn', '-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '1', str(output_wav)]
    return run_command(cmd, logger) is not None


def find_audio_delay(ref_wav: str, sec_wav: str, logger):
    try:
        ref_sig, rate_ref = librosa.load(ref_wav, sr=None, mono=True)
        sec_sig, rate_sec = librosa.load(sec_wav, sr=None, mono=True)
        if rate_ref != rate_sec:
            return (None, 0.0, None)
        ref_sig = (ref_sig - np.mean(ref_sig)) / (np.std(ref_sig) + 1e-09)
        sec_sig = (sec_sig - np.mean(sec_sig)) / (np.std(sec_sig) + 1e-09)
        corr = scipy.signal.correlate(ref_sig, sec_sig, mode='full', method='auto')
        lag_samples = int(np.argmax(corr)) - (len(sec_sig) - 1)
        raw_delay_s = lag_samples / float(rate_ref)
        norm = np.sqrt(np.sum(ref_sig ** 2) * np.sum(sec_sig ** 2))
        match_pct = np.max(np.abs(corr)) / (norm + 1e-09) * 100.0
        return (round(raw_delay_s * 1000), match_pct, raw_delay_s)
    except Exception as e:
        _log(logger, f'find_audio_delay error: {e}')
        return (None, 0.0, None)


def best_from_results(results: List[Dict[str, Any]], min_pct=5.0):
    if not results:
        return None
    valid = [r for r in results if r['match'] > float(min_pct)]
    if not valid:
        return None
    from collections import Counter
    counts = Counter((r['delay'] for r in valid))
    max_freq = counts.most_common(1)[0][1]
    contenders = [d for d, f in counts.items() if f == max_freq]
    bests = [max([r for r in valid if r['delay'] == d], key=lambda x: x['match']) for d in contenders]
    return max(bests, key=lambda x: x['match'])


def run_audio_correlation_workflow(file1: str, file2: str, logger, chunks: int, chunk_dur: int,
                                   match_lang: Optional[str], role_tag: str):
    _log(logger, f'Analyzing (Audio): {file1} vs {file2}')
    idx1 = get_audio_stream_index(file1, logger, language=None)
    idx2 = get_audio_stream_index(file2, logger, language=match_lang)
    _log(logger, f"Chosen streams -> ref a:{idx1}, target a:{idx2} (prefer='{match_lang or 'first'}')")
    if idx1 is None or idx2 is None:
        raise ValueError('Could not locate audio streams for correlation.')
    dur = ffprobe_duration(file1, logger)
    scan_range = max(0.0, dur * 0.8)
    start_offset = dur * 0.1
    starts = [start_offset + scan_range / max(1, chunks - 1) * i for i in range(chunks)]
    results = []
    for i, st in enumerate(starts, 1):
        set_status(f'Correlating chunk {i}/{chunks}…')
        set_progress(i / max(1, chunks))
        tmp1 = Path(CONFIG['temp_root']) / f'wav_ref_{Path(file1).stem}_{int(st)}_{i}.wav'
        tmp2 = Path(CONFIG['temp_root']) / f'wav_{role_tag}_{Path(file2).stem}_{int(st)}_{i}.wav'
        try:
            ok1 = extract_audio_chunk(file1, str(tmp1), st, chunk_dur, logger, idx1)
            ok2 = extract_audio_chunk(file2, str(tmp2), st, chunk_dur, logger, idx2)
            if ok1 and ok2:
                delay, match, raw = find_audio_delay(str(tmp1), str(tmp2), logger)
                if delay is not None:
                    results.append({'delay': delay, 'match': match, 'raw_delay': raw, 'start': st})
                    _log(logger, f'Chunk @{int(st)}s -> Delay {delay:+} ms (Match {match:.2f}%) Raw {raw:.6f}s')
        finally:
            for p in (tmp1, tmp2):
                try:
                    if Path(p).exists():
                        Path(p).unlink()
                except Exception:
                    pass
    return results
