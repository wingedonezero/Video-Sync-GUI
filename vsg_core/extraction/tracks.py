# vsg_core/extraction/tracks.py
# -*- coding: utf-8 -*-
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..io.runner import CommandRunner

def _pcm_codec_from_bit_depth(bit_depth):
    try:
        bd = int(bit_depth) if bit_depth is not None else 16
    except (TypeError, ValueError):
        bd = 16
    if bd >= 64: return 'pcm_f64le'
    if bd >= 32: return 'pcm_s32le'
    if bd >= 24: return 'pcm_s24le'
    return 'pcm_s16le'

def get_stream_info(mkv_path: str, runner: CommandRunner, tool_paths: dict) -> Optional[Dict[str, Any]]:
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str): return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        runner._log_message('[ERROR] Failed to parse mkvmerge -J JSON output.')
        return None

def _ext_for_codec(ttype: str, codec_id: str) -> str:
    cid = (codec_id or '').upper()
    if ttype == 'video':
        if 'V_MPEGH/ISO/HEVC' in cid: return 'h265'
        if 'V_MPEG4/ISO/AVC' in cid:  return 'h264'
        if 'V_MPEG1/2' in cid:      return 'mpg'
        if 'V_VP9' in cid:          return 'vp9'
        if 'V_AV1' in cid:          return 'av1'
        return 'bin'
    if ttype == 'audio':
        if 'A_TRUEHD' in cid: return 'thd'
        if 'A_EAC3' in cid:  return 'eac3'
        if 'A_AC3' in cid:   return 'ac3'
        if 'A_DTS' in cid:   return 'dts'
        if 'A_AAC' in cid:   return 'aac'
        if 'A_FLAC' in cid:  return 'flac'
        if 'A_OPUS' in cid:  return 'opus'
        if 'A_VORBIS' in cid:return 'ogg'
        if 'A_PCM' in cid:   return 'wav'
        return 'bin'
    if ttype == 'subtitles':
        if 'S_TEXT/ASS' in cid: return 'ass'
        if 'S_TEXT/SSA' in cid: return 'ssa'
        if 'S_TEXT/UTF8' in cid:return 'srt'
        if 'S_HDMV/PGS' in cid: return 'sup'
        if 'S_VOBSUB' in cid:  return 'sub'
        return 'sub'
    return 'bin'

def extract_tracks(mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str,
                   specific_tracks: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    info = get_stream_info(mkv, runner, tool_paths)
    if not info:
        raise ValueError(f'Could not get stream info for extraction from {mkv}')

    tracks_to_extract, specs, ffmpeg_jobs = [], [], []
    audio_idx = -1

    for track in info.get('tracks', []):
        ttype, tid = track['type'], track['id']
        if specific_tracks is not None and tid not in specific_tracks:
            continue

        if ttype == 'audio':
            audio_idx += 1

        props = track.get('properties', {}) or {}
        codec = props.get('codec_id') or ''
        ext = _ext_for_codec(ttype, codec)
        safe_role = role.replace(" ", "_")
        out_path = temp_dir / f"{safe_role}_track_{Path(mkv).stem}_{tid}.{ext}"

        record = {
            'id': tid, 'type': ttype, 'lang': props.get('language', 'und'),
            'name': props.get('track_name', ''), 'path': str(out_path),
            'codec_id': codec, 'source': role # Standardize to 'source'
        }
        tracks_to_extract.append(record)

        if ttype == 'audio' and 'A_MS/ACM' in codec.upper():
            out_path = out_path.with_suffix('.wav')
            record['path'] = str(out_path)
            bit_depth = props.get('audio_bits_per_sample') or props.get('bit_depth')
            pcm_codec = _pcm_codec_from_bit_depth(bit_depth)
            ffmpeg_jobs.append({'idx': audio_idx, 'tid': tid, 'out': str(out_path), 'pcm': pcm_codec})
        else:
            specs.append(f'{tid}:{out_path}')

    if specs:
        runner.run(['mkvextract', str(mkv), 'tracks'] + specs, tool_paths)

    for job in ffmpeg_jobs:
        copy_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-i', str(mkv), '-map', f"0:a:{job['idx']}", '-vn', '-sn', '-c:a', 'copy', job['out']]
        if runner.run(copy_cmd, tool_paths) is None:
            runner._log_message(f"Stream copy refused for A_MS/ACM (track {job['tid']}). Falling back to {job['pcm']}.")
            pcm_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-i', str(mkv), '-map', f"0:a:{job['idx']}", '-vn', '-sn', '-acodec', job['pcm'], job['out']]
            runner.run(pcm_cmd, tool_paths)

    return tracks_to_extract

def get_track_info_for_dialog(sources: Dict[str, str], runner: CommandRunner, tool_paths: dict) -> Dict[str, List[Dict]]:
    all_tracks: Dict[str, List[Dict]] = {key: [] for key in sources}
    for source_key, filepath in sources.items():
        if not filepath or not Path(filepath).exists():
            continue
        info = get_stream_info(filepath, runner, tool_paths)
        if not info or 'tracks' not in info:
            continue
        for track in info.get('tracks', []):
            props = track.get('properties', {}) or {}
            record = {
                'source': source_key, 'original_path': filepath, 'id': track['id'],
                'type': track['type'], 'codec_id': props.get('codec_id', 'N/A'),
                'lang': props.get('language', 'und'), 'name': props.get('track_name', '')
            }
            all_tracks[source_key].append(record)
    return all_tracks
