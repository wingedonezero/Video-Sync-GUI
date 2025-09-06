# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Callable

import json
import librosa
import numpy as np
import scipy.signal

from ..io.runner import CommandRunner

LogFn = Callable[[str], None]

def _get_audio_stream_index(mkv_path: str, runner: CommandRunner, tool_paths: dict, language: Optional[str]) -> Optional[int]:
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out:
        return None
    try:
        info = json.loads(out)
        idx = -1
        first_found_idx = None
        for t in info.get('tracks', []):
            if t.get('type') == 'audio':
                idx += 1
                if first_found_idx is None:
                    first_found_idx = idx
                if language and t.get('properties', {}).get('language') == language:
                    return idx
        return first_found_idx
    except json.JSONDecodeError:
        return None

def _extract_audio_chunk(source_file: str, output_wav: str, start_time: float, duration: float,
                         runner: CommandRunner, tool_paths: dict, stream_index: int) -> bool:
    cmd = [
        'ffmpeg', '-y', '-v', 'error', '-ss', str(start_time),
        '-i', str(source_file), '-map', f'0:a:{stream_index}', '-t', str(duration),
        '-vn', '-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '1', str(output_wav)
    ]
    return runner.run(cmd, tool_paths) is not None

def _find_audio_delay(ref_wav: str, sec_wav: str, log: LogFn) -> Tuple[Optional[int], float, Optional[float]]:
    try:
        ref_sig, rate_ref = librosa.load(ref_wav, sr=None, mono=True)
        sec_sig, rate_sec = librosa.load(sec_wav, sr=None, mono=True)
        if rate_ref != rate_sec:
            log("Sample rates do not match, skipping correlation.")
            return None, 0.0, None

        ref_sig = (ref_sig - np.mean(ref_sig)) / (np.std(ref_sig) + 1e-9)
        sec_sig = (sec_sig - np.mean(sec_sig)) / (np.std(sec_sig) + 1e-9)

        corr = scipy.signal.correlate(ref_sig, sec_sig, mode='full', method='auto')
        lag_samples = np.argmax(corr) - (len(sec_sig) - 1)
        raw_delay_s = float(lag_samples) / float(rate_ref)

        norm_factor = np.sqrt(np.sum(ref_sig**2) * np.sum(sec_sig**2))
        match_pct = (np.max(np.abs(corr)) / (norm_factor + 1e-9)) * 100.0

        return round(raw_delay_s * 1000), match_pct, raw_delay_s
    except Exception as e:
        log(f'Error in find_audio_delay: {e}')
        return None, 0.0, None

def run_audio_correlation(
    ref_file: str, target_file: str, temp_dir: Path, config: dict,
    runner: CommandRunner, tool_paths: dict, ref_lang: Optional[str],
    target_lang: Optional[str], role_tag: str
) -> List[Dict[str, Any]]:
    idx1 = _get_audio_stream_index(ref_file, runner, tool_paths, language=ref_lang)
    idx2 = _get_audio_stream_index(target_file, runner, tool_paths, language=target_lang)

    runner._log_message(
        f"Selected streams for analysis: REF (lang='{ref_lang or 'first'}', index={idx1}), "
        f"{role_tag.upper()} (lang='{target_lang or 'first'}', index={idx2})"
    )

    if idx1 is None or idx2 is None:
        raise ValueError('Could not locate required audio streams for correlation.')

    out = runner.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                      '-of', 'csv=p=0', str(ref_file)], tool_paths)
    try:
        duration = float(out.strip()) if out else 0.0
    except (ValueError, TypeError):
        duration = 0.0

    chunks = int(config.get('scan_chunk_count', 10))
    chunk_dur = int(config.get('scan_chunk_duration', 15))

    scan_range = max(0.0, duration * 0.8)
    start_offset = duration * 0.1
    starts = [start_offset + (scan_range / max(1, chunks - 1) * i) for i in range(chunks)]

    results = []
    for i, start_time in enumerate(starts, 1):
        tmp1 = temp_dir / f'wav_ref_{Path(ref_file).stem}_{int(start_time)}_{i}.wav'
        tmp2 = temp_dir / f'wav_{role_tag}_{Path(target_file).stem}_{int(start_time)}_{i}.wav'
        try:
            ok1 = _extract_audio_chunk(ref_file, str(tmp1), start_time, chunk_dur, runner, tool_paths, idx1)
            ok2 = _extract_audio_chunk(target_file, str(tmp2), start_time, chunk_dur, runner, tool_paths, idx2)
            if ok1 and ok2:
                delay, match, raw = _find_audio_delay(str(tmp1), str(tmp2), runner._log_message)
                if delay is not None:
                    result = {'delay': delay, 'match': match, 'raw_delay': raw, 'start': start_time}
                    results.append(result)
                    runner._log_message(f"Chunk @{int(start_time)}s -> Delay {delay:+} ms (Match {match:.2f}%)")
        finally:
            for p in (tmp1, tmp2):
                if p.exists():
                    p.unlink()
    return results
