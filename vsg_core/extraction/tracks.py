# vsg_core/extraction/tracks.py
# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..io.runner import CommandRunner

# --- Mappings and Helpers for Detailed Track Info ---

_CODEC_ID_MAP = {
    # Video
    'V_MPEGH/ISO/HEVC': 'HEVC/H.265',
    'V_MPEG4/ISO/AVC': 'AVC/H.264',
    'V_MPEG1': 'MPEG-1',
    'V_MPEG2': 'MPEG-2',
    'V_VP9': 'VP9',
    'V_AV1': 'AV1',
    # Audio
    'A_AC3': 'AC-3',
    'A_EAC3': 'E-AC3 / DD+',
    'A_DTS': 'DTS',
    'A_TRUEHD': 'TrueHD',
    'A_FLAC': 'FLAC',
    'A_AAC': 'AAC',
    'A_OPUS': 'Opus',
    'A_VORBIS': 'Vorbis',
    'A_PCM/INT/LIT': 'PCM',
    'A_MS/ACM': 'MS-ACM',
    # Subtitles
    'S_HDMV/PGS': 'PGS',
    'S_TEXT/UTF8': 'SRT',
    'S_TEXT/ASS': 'ASS',
    'S_TEXT/SSA': 'SSA',
    'S_VOBSUB': 'VobSub',
}

def _get_channel_layout_str(props: Dict) -> Optional[str]:
    """Gets a friendly channel layout string."""
    if 'channel_layout' in props:
        return props['channel_layout']
    channels = props.get('audio_channels')
    if channels:
        return {1: 'Mono', 2: 'Stereo', 6: '5.1', 8: '7.1'}.get(channels)
    return None

def _parse_pcm_codec_name(name: str) -> Optional[str]:
    """Parses an ffprobe pcm codec name like 'pcm_s24le' into a readable string."""
    match = re.match(r"pcm_([suf])(\d+)([bl]e)?", name)
    if not match:
        return None

    type_map = {'s': 'Signed', 'u': 'Unsigned', 'f': 'Floating Point'}
    endian_map = {'le': 'Little Endian', 'be': 'Big Endian'}

    parts = []
    sample_type = type_map.get(match.group(1))
    if sample_type:
        parts.append(sample_type)

    endian = endian_map.get(match.group(3), '')
    if endian:
        parts.append(endian)

    return " ".join(parts) if parts else None


def _build_track_description(track: Dict) -> str:
    """Builds a rich, MediaInfo-like description string from combined track info."""
    props = track.get('properties', {})
    ttype = track.get('type')
    codec_id = props.get('codec_id', '')
    ffprobe_info = track.get('ffprobe_info', {})

    # --- Base Codec Name ---
    profile = ffprobe_info.get('profile', '')

    if 'DTS-HD MA' in profile:
        friendly_codec = 'DTS-HD MA'
    elif 'DTS-HD HRA' in profile:
        friendly_codec = 'DTS-HD HRA'
    elif 'Atmos' in ffprobe_info.get('codec_long_name', ''):
        friendly_codec = 'TrueHD / Atmos'
    else:
        if codec_id.startswith('V_MPEG') and codec_id not in _CODEC_ID_MAP:
            friendly_codec = 'MPEG'
        else:
            friendly_codec = _CODEC_ID_MAP.get(codec_id, codec_id)

    lang = props.get('language', 'und')
    name = f" '{props.get('track_name')}'" if props.get('track_name') else ""

    base_info = f"{friendly_codec} ({lang}){name}"
    details = []

    if ttype == 'video':
        detail_order = []
        if ffprobe_info.get('width') and ffprobe_info.get('height'):
            detail_order.append(f"{ffprobe_info['width']}x{ffprobe_info['height']}")

        if ffprobe_info.get('r_frame_rate', '0/1') != '0/1':
            try:
                num, den = map(int, ffprobe_info['r_frame_rate'].split('/'))
                detail_order.append(f"{num/den:.3f} fps")
            except (ValueError, ZeroDivisionError): pass

        if ffprobe_info.get('bit_rate'):
            try:
                mbps = int(ffprobe_info['bit_rate']) / 1_000_000
                detail_order.append(f"{mbps:.1f} Mb/s")
            except (ValueError, TypeError): pass

        if 'profile' in ffprobe_info:
            profile_str = ffprobe_info['profile']
            if 'level' in ffprobe_info:
                level_str = str(ffprobe_info['level'])
                if len(level_str) > 1:
                    profile_str += f"@L{level_str[0]}.{level_str[1]}"
                else:
                    profile_str += f"@L{level_str}"
            detail_order.append(profile_str)

        color_transfer = ffprobe_info.get('color_transfer', '')
        if color_transfer == 'smpte2084': detail_order.append('HDR')
        elif color_transfer == 'arib-std-b67': detail_order.append('HLG')

        side_data = ffprobe_info.get('side_data_list', [])
        if any(s.get('side_data_type') == 'DOVI configuration record' for s in side_data):
            detail_order.append('Dolby Vision')
        details = detail_order

    elif ttype == 'audio':
        detail_order = []
        if ffprobe_info.get('bit_rate'):
            try:
                kbps = int(ffprobe_info['bit_rate']) // 1000
                detail_order.append(f"{kbps:,} kb/s")
            except (ValueError, TypeError): pass

        if props.get('audio_sampling_frequency'):
            detail_order.append(f"{props['audio_sampling_frequency']} Hz")

        if props.get('audio_bits_per_sample'):
            detail_order.append(f"{props['audio_bits_per_sample']}-bit")

        if props.get('audio_channels'):
            detail_order.append(f"{props['audio_channels']} ch")

        layout = _get_channel_layout_str(props)
        if layout:
            detail_order.append(layout)

        if friendly_codec == 'PCM' and ffprobe_info.get('codec_name'):
            pcm_details = _parse_pcm_codec_name(ffprobe_info['codec_name'])
            if pcm_details:
                base_info += f" ({pcm_details})"

        details = detail_order

    return f"{base_info} | {', '.join(details)}" if details else base_info


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

def get_stream_info_with_delays(mkv_path: str, runner: CommandRunner, tool_paths: dict) -> Optional[Dict[str, Any]]:
    """Get stream info including container delays from mkvmerge -J output."""
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out or not isinstance(out, str): return None
    try:
        info = json.loads(out)

        # Extract container delays for each track
        for track in info.get('tracks', []):
            props = track.get('properties', {})
            track_type = track.get('type', '')

            # ONLY read container delays for audio and video tracks
            # Subtitles don't have meaningful container delays in MKV
            if track_type in ['audio', 'video']:
                min_timestamp = props.get('minimum_timestamp', 0)

                if min_timestamp:
                    # Use round() for proper rounding of negative values
                    # int() truncates toward zero: int(-1001.825) = -1001 (wrong)
                    # round() rounds to nearest: round(-1001.825) = -1002 (correct)
                    track['container_delay_ms'] = round(min_timestamp / 1_000_000)
                else:
                    track['container_delay_ms'] = 0
            else:
                # Explicitly set subtitle delays to 0
                track['container_delay_ms'] = 0

        return info
    except json.JSONDecodeError:
        runner._log_message('[ERROR] Failed to parse mkvmerge -J JSON output.')
        return None

def _get_detailed_stream_info(filepath: str, runner: CommandRunner, tool_paths: dict) -> Dict[int, Dict]:
    cmd = ['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(filepath)]
    out = runner.run(cmd, tool_paths)
    if not out: return {}
    try:
        ffprobe_data = json.loads(out)
        return {s['index']: s for s in ffprobe_data.get('streams', [])}
    except json.JSONDecodeError:
        runner._log_message('[WARN] Failed to parse ffprobe JSON output.')
        return {}

def _ext_for_codec(ttype: str, codec_id: str) -> str:
    cid = (codec_id or '').upper()
    if ttype == 'video':
        if 'V_MPEGH/ISO/HEVC' in cid: return 'h265'
        if 'V_MPEG4/ISO/AVC' in cid:  return 'h264'
        if 'V_MPEG' in cid:         return 'mpg'
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
    """
    Extract tracks from MKV with enhanced error detection.
    NOW REPORTS: Which source, which specific track failed, with full details.
    """
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
            'codec_id': codec, 'source': role
        }
        tracks_to_extract.append(record)

        if ttype == 'audio' and 'A_MS/ACM' in codec.upper():
            out_path = out_path.with_suffix('.wav')
            record['path'] = str(out_path)
            bit_depth = props.get('audio_bits_per_sample') or props.get('bit_depth')
            pcm_codec = _pcm_codec_from_bit_depth(bit_depth)
            ffmpeg_jobs.append({'idx': audio_idx, 'tid': tid, 'out': str(out_path), 'pcm': pcm_codec, 'name': record['name']})
        else:
            specs.append(f'{tid}:{out_path}')

    # === ENHANCED: Extraction with detailed per-track error reporting ===
    if specs:
        runner._log_message(f"[{role}] Extracting {len(specs)} track(s) with mkvextract...")
        result = runner.run(['mkvextract', str(mkv), 'tracks'] + specs, tool_paths)

        if result is None:
            runner._log_message(f"[{role}] [ERROR] mkvextract command failed!")

            # Check which tracks succeeded/failed
            failed_tracks = []
            successful_tracks = []

            for spec in specs:
                tid = int(spec.split(':')[0])
                out_path = Path(spec.split(':', 1)[1])
                track_info = next((t for t in tracks_to_extract if t['id'] == tid), None)

                if not track_info:
                    continue

                track_name = track_info.get('name') or f"Track {tid}"
                track_type = track_info['type'].capitalize()
                track_lang = track_info.get('lang', 'und')
                track_codec = track_info.get('codec_id', 'unknown')

                if out_path.exists() and out_path.stat().st_size > 0:
                    file_size_mb = out_path.stat().st_size / (1024 * 1024)
                    successful_tracks.append(
                        f"  ✓ {track_name} (ID {tid}, {track_type}, {track_lang}, {track_codec}) [{file_size_mb:.1f} MB]"
                    )
                else:
                    status = "not created" if not out_path.exists() else "empty (0 bytes)"
                    failed_tracks.append(
                        f"  ✗ {track_name} (ID {tid}, {track_type}, {track_lang}, {track_codec}) - {status}"
                    )

            # Build detailed error message
            error_msg = f"\n{'='*80}\n"
            error_msg += f"EXTRACTION FAILED\n"
            error_msg += f"{'='*80}\n"
            error_msg += f"Source: {role}\n"
            error_msg += f"File: {Path(mkv).name}\n"
            error_msg += f"Full Path: {mkv}\n"
            error_msg += f"{'='*80}\n\n"

            if successful_tracks:
                error_msg += f"Successfully extracted ({len(successful_tracks)} tracks):\n"
                error_msg += "\n".join(successful_tracks) + "\n\n"

            if failed_tracks:
                error_msg += f"❌ FAILED to extract ({len(failed_tracks)} tracks):\n"
                error_msg += "\n".join(failed_tracks) + "\n\n"
                error_msg += "⚠️  The track(s) marked with ✗ above failed to extract.\n"
                error_msg += "    These specific tracks have issues and need investigation.\n\n"
            else:
                error_msg += "⚠️  All tracks appear extracted, but mkvextract returned an error.\n"
                error_msg += "    This may indicate a warning or non-fatal issue.\n\n"

            error_msg += "Possible causes:\n"
            error_msg += "  • Corrupted track data in the source file\n"
            error_msg += "  • Insufficient disk space in temp directory\n"
            error_msg += "  • Insufficient read/write permissions\n"
            error_msg += "  • Unsupported codec or malformed stream data\n"
            error_msg += "  • Hardware/storage errors (bad sectors)\n"
            error_msg += "  • File system issues (FAT32 4GB limit, etc.)\n\n"

            error_msg += "Troubleshooting:\n"
            error_msg += f"  1. Verify source integrity: mkvmerge -i \"{mkv}\"\n\n"
            error_msg += f"  2. Try extracting failed track(s) manually:\n"
            if failed_tracks:
                for track_line in failed_tracks[:3]:
                    tid = track_line.split('ID ')[1].split(',')[0]
                    error_msg += f"     mkvextract \"{mkv}\" tracks {tid}:test_track_{tid}.bin\n"
            error_msg += f"\n  3. Check disk space in: {temp_dir}\n\n"
            error_msg += f"  4. Try playing source file to check for corruption\n\n"
            error_msg += f"  5. Check log file for detailed mkvextract error messages\n"
            error_msg += f"{'='*80}\n"

            raise RuntimeError(error_msg)

        runner._log_message(f"[{role}] ✓ Successfully extracted {len(specs)} track(s)")

        # Post-extraction verification
        verification_failed = []
        for spec in specs:
            tid = int(spec.split(':')[0])
            out_path = Path(spec.split(':', 1)[1])
            track_info = next((t for t in tracks_to_extract if t['id'] == tid), None)

            if not out_path.exists():
                track_name = track_info.get('name', f"Track {tid}") if track_info else f"Track {tid}"
                verification_failed.append(f"  • {track_name} (ID {tid}): File not created")
            elif out_path.stat().st_size == 0:
                track_name = track_info.get('name', f"Track {tid}") if track_info else f"Track {tid}"
                verification_failed.append(f"  • {track_name} (ID {tid}): File is empty (0 bytes)")

        if verification_failed:
            error_msg = f"\n{'='*80}\n"
            error_msg += f"POST-EXTRACTION VERIFICATION FAILED\n"
            error_msg += f"{'='*80}\n"
            error_msg += f"Source: {role}\n"
            error_msg += f"File: {Path(mkv).name}\n"
            error_msg += f"{'='*80}\n\n"
            error_msg += "Tracks failed verification:\n"
            error_msg += "\n".join(verification_failed)
            error_msg += "\n\nmkvextract reported success but some files are missing/empty.\n"
            error_msg += "This may indicate:\n"
            error_msg += "  • A bug in mkvextract\n"
            error_msg += "  • Filesystem issues (delayed writes, caching)\n"
            error_msg += "  • Antivirus interference\n"
            error_msg += "  • Disk I/O errors\n"
            error_msg += f"{'='*80}\n"
            raise RuntimeError(error_msg)

    # Handle A_MS/ACM audio with ffmpeg
    for job in ffmpeg_jobs:
        track_name = job.get('name') or f"Track {job['tid']}"

        runner._log_message(f"[{role}] Extracting A_MS/ACM track '{track_name}' (ID {job['tid']})...")

        copy_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-i', str(mkv),
                    '-map', f"0:a:{job['idx']}", '-vn', '-sn', '-c:a', 'copy', job['out']]
        if runner.run(copy_cmd, tool_paths) is None:
            runner._log_message(f"[{role}] Stream copy refused. Falling back to PCM ({job['pcm']})...")

            pcm_cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-i', str(mkv),
                       '-map', f"0:a:{job['idx']}", '-vn', '-sn', '-acodec', job['pcm'], job['out']]
            if runner.run(pcm_cmd, tool_paths) is None:
                error_msg = f"\n{'='*80}\n"
                error_msg += f"A_MS/ACM AUDIO EXTRACTION FAILED\n"
                error_msg += f"{'='*80}\n"
                error_msg += f"Source: {role}\n"
                error_msg += f"File: {Path(mkv).name}\n"
                error_msg += f"Track: {track_name} (ID {job['tid']})\n"
                error_msg += f"Codec: A_MS/ACM\n"
                error_msg += f"{'='*80}\n\n"
                error_msg += "Both stream copy and PCM conversion failed.\n\n"
                error_msg += "This track may:\n"
                error_msg += "  • Use an unsupported ACM codec variant\n"
                error_msg += "  • Be corrupted or have malformed headers\n"
                error_msg += "  • Require specific codec drivers\n\n"
                error_msg += "Troubleshooting:\n"
                error_msg += f"  1. Try playing this audio track in VLC\n"
                error_msg += f"  2. Try: mkvextract \"{mkv}\" tracks {job['tid']}:test.wav\n"
                error_msg += f"  3. Consider remuxing the source file\n"
                error_msg += f"{'='*80}\n"
                raise RuntimeError(error_msg)

            runner._log_message(f"[{role}] ✓ Converted to {job['pcm']}")
        else:
            runner._log_message(f"[{role}] ✓ Extracted successfully")

    return tracks_to_extract

def get_track_info_for_dialog(sources: Dict[str, str], runner: CommandRunner, tool_paths: dict) -> Dict[str, List[Dict]]:
    all_tracks: Dict[str, List[Dict]] = {key: [] for key in sources}
    for source_key, filepath in sources.items():
        if not filepath or not Path(filepath).exists():
            continue

        mkvmerge_info = get_stream_info(filepath, runner, tool_paths)
        if not mkvmerge_info or 'tracks' not in mkvmerge_info:
            continue

        ffprobe_details = _get_detailed_stream_info(filepath, runner, tool_paths)

        type_counters = {'video': 0, 'audio': 0, 'subtitles': 0}
        ffprobe_streams_by_type = {
            'video': sorted([s for s in ffprobe_details.values() if s.get('codec_type') == 'video'], key=lambda s: s['index']),
            'audio': sorted([s for s in ffprobe_details.values() if s.get('codec_type') == 'audio'], key=lambda s: s['index']),
            'subtitles': sorted([s for s in ffprobe_details.values() if s.get('codec_type') == 'subtitle'], key=lambda s: s['index'])
        }

        for track in mkvmerge_info.get('tracks', []):
            track_type = track['type']
            type_index = type_counters.get(track_type, 0)

            if type_index < len(ffprobe_streams_by_type.get(track_type, [])):
                track['ffprobe_info'] = ffprobe_streams_by_type[track_type][type_index]

            type_counters[track_type] = type_index + 1

            props = track.get('properties', {}) or {}
            record = {
                'source': source_key, 'original_path': filepath, 'id': track['id'],
                'type': track['type'], 'codec_id': props.get('codec_id', 'N/A'),
                'lang': props.get('language', 'und'), 'name': props.get('track_name', ''),
                'description': _build_track_description(track)
            }
            all_tracks[source_key].append(record)

    return all_tracks
