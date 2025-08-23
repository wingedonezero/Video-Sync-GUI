# -*- coding: utf-8 -*-

"""
Utilities for interacting with MKV files using MKVToolNix and FFprobe.
Includes track extraction and all chapter processing logic.
"""

import json
import bisect
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Any, Optional

from .process import CommandRunner

# --- Track and Attachment Extraction ---

def get_stream_info(mkv_path: str, runner: CommandRunner, tool_paths: dict) -> Optional[Dict[str, Any]]:
    """Gets multimedia stream information using mkvmerge -J."""
    out = runner.run(['mkvmerge', '-J', str(mkv_path)], tool_paths)
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        runner._log_message('[ERROR] Failed to parse mkvmerge -J JSON output.')
        return None

def _ext_for_codec(ttype: str, codec_id: str) -> str:
    """Determines a file extension based on track type and codec ID."""
    cid = (codec_id or '').upper()
    if ttype == 'video':
        if 'V_MPEGH/ISO/HEVC' in cid: return 'h265'
        if 'V_MPEG4/ISO/AVC' in cid: return 'h264'
        if 'V_MPEG1/2' in cid: return 'mpg'
        if 'V_VP9' in cid: return 'vp9'
        if 'V_AV1' in cid: return 'av1'
        return 'bin'
    if ttype == 'audio':
        if 'A_TRUEHD' in cid: return 'thd'
        if 'A_EAC3' in cid: return 'eac3'
        if 'A_AC3' in cid: return 'ac3'
        if 'A_DTS' in cid: return 'dts'
        if 'A_AAC' in cid: return 'aac'
        if 'A_FLAC' in cid: return 'flac'
        if 'A_OPUS' in cid: return 'opus'
        if 'A_VORBIS' in cid: return 'ogg'
        if 'A_PCM' in cid: return 'wav'
        return 'bin'
    if ttype == 'subtitles':
        if 'S_TEXT/ASS' in cid: return 'ass'
        if 'S_TEXT/SSA' in cid: return 'ssa'
        if 'S_TEXT/UTF8' in cid: return 'srt'
        if 'S_HDMV/PGS' in cid: return 'sup'
        if 'S_VOBSUB' in cid: return 'sub'
        return 'sub'
    return 'bin'

def extract_tracks(mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str, audio=True, subs=True, all_tracks=False) -> List[Dict[str, Any]]:
    """Extracts specified track types from an MKV file."""
    info = get_stream_info(mkv, runner, tool_paths)
    if not info:
        raise ValueError(f'Could not get stream info for extraction from {mkv}')

    tracks_to_extract, specs = [], []
    for track in info.get('tracks', []):
        ttype = track['type']
        want = all_tracks or (audio and ttype == 'audio') or (subs and ttype == 'subtitles')
        if not want:
            continue

        tid = track['id']
        codec = track.get('properties', {}).get('codec_id', '')
        ext = _ext_for_codec(ttype, codec)
        out_path = temp_dir / f'{role}_track_{Path(mkv).stem}_{tid}.{ext}'

        tracks_to_extract.append({
            'id': tid,
            'type': ttype,
            'lang': track.get('properties', {}).get('language', 'und'),
            'name': track.get('properties', {}).get('track_name', ''),
            'path': str(out_path),
            'codec_id': codec
        })
        specs.append(f'{tid}:{out_path}')

    if specs:
        runner.run(['mkvextract', str(mkv), 'tracks'] + specs, tool_paths)
    return tracks_to_extract

def extract_attachments(mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str) -> List[str]:
    """Extracts all attachments from an MKV file."""
    info = get_stream_info(mkv, runner, tool_paths)
    files, specs = [], []
    for attachment in (info or {}).get('attachments', []):
        out_path = temp_dir / f"{role}_att_{attachment['id']}_{attachment['file_name']}"
        specs.append(f"{attachment['id']}:{out_path}")
        files.append(str(out_path))

    if specs:
        runner.run(['mkvextract', str(mkv), 'attachments'] + specs, tool_paths)
    return files

# --- Chapter Processing ---

def _parse_ns(t: str) -> int:
    """Parses HH:MM:SS.fffffffff time string to nanoseconds."""
    hh, mm, rest = t.strip().split(':')
    ss, frac = (rest.split('.') + ['0'])[:2]
    frac = (frac + '000000000')[:9]
    return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1_000_000_000 + int(frac)

def _fmt_ns(ns: int) -> str:
    """Formats nanoseconds to HH:MM:SS.fffffffff time string."""
    ns = max(0, ns)
    frac = ns % 1_000_000_000
    total_s = ns // 1_000_000_000
    hh = total_s // 3600
    mm = (total_s % 3600) // 60
    ss = total_s % 60
    return f'{hh:02d}:{mm:02d}:{ss:02d}.{frac:09d}'

def _normalize_chapter_end_times(root: ET.Element, runner: CommandRunner):
    """Ensures each chapter's end time is valid."""
    atoms = root.findall('.//ChapterAtom')
    chapters = []
    for atom in atoms:
        st_el = atom.find('ChapterTimeStart')
        if st_el is not None and st_el.text:
            chapters.append({'atom': atom, 'start_ns': _parse_ns(st_el.text)})

    chapters.sort(key=lambda x: x['start_ns'])

    fixed_count = 0
    for i, chap in enumerate(chapters):
        atom = chap['atom']
        st_ns = chap['start_ns']
        en_el = atom.find('ChapterTimeEnd')

        next_start_ns = chapters[i + 1]['start_ns'] if i + 1 < len(chapters) else None

        desired_en_ns = _parse_ns(en_el.text) if en_el is not None and en_el.text else st_ns + 1_000_000

        if next_start_ns is not None:
            desired_en_ns = min(desired_en_ns, next_start_ns)

        desired_en_ns = max(desired_en_ns, st_ns + 1) # Ensure end is after start

        if en_el is None:
            en_el = ET.SubElement(atom, 'ChapterTimeEnd')

        new_text = _fmt_ns(desired_en_ns)
        if en_el.text != new_text:
            en_el.text = new_text
            fixed_count += 1

    if fixed_count > 0:
        runner._log_message(f'[Chapters] Normalized {fixed_count} chapter end times.')


def process_chapters(ref_mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, config: dict, shift_ms: int) -> Optional[str]:
    """Main function to handle all chapter operations: rename, shift, and snap."""
    xml_content = runner.run(['mkvextract', str(ref_mkv), 'chapters', '-'], tool_paths)
    if not xml_content or not xml_content.strip():
        runner._log_message('No chapters found in reference file.')
        return None

    try:
        if xml_content.startswith('\ufeff'):
            xml_content = xml_content[1:]

        root = ET.fromstring(xml_content)

        if config.get('rename_chapters', False):
            for i, atom in enumerate(root.findall('.//ChapterAtom'), 1):
                disp = atom.find('ChapterDisplay')
                if disp is not None:
                    atom.remove(disp)
                new_disp = ET.SubElement(atom, 'ChapterDisplay')
                ET.SubElement(new_disp, 'ChapterString').text = f'Chapter {i:02d}'
                ET.SubElement(new_disp, 'ChapterLanguage').text = 'und'
            runner._log_message('[Chapters] Renamed chapters to "Chapter NN".')

        shift_ns = shift_ms * 1_000_000
        if shift_ns != 0:
            for atom in root.findall('.//ChapterAtom'):
                for tag in ('ChapterTimeStart', 'ChapterTimeEnd'):
                    node = atom.find(tag)
                    if node is not None and node.text:
                        node.text = _fmt_ns(_parse_ns(node.text) + shift_ns)
            runner._log_message(f'[Chapters] Shifted all timestamps by +{shift_ms} ms.')

        if config.get('snap_chapters', False):
            keyframes_ns = _probe_keyframes_ns(ref_mkv, runner, tool_paths)
            if keyframes_ns:
                _snap_chapter_times_inplace(root, keyframes_ns, config, runner)
            else:
                runner._log_message('[Chapters] Snap skipped: could not load keyframes.')

        _normalize_chapter_end_times(root, runner)

        out_path = temp_dir / f'{Path(ref_mkv).stem}_chapters_modified.xml'
        tree = ET.ElementTree(root)
        tree.write(out_path, encoding='UTF-8', xml_declaration=True)
        runner._log_message(f'Chapters XML written to: {out_path}')
        return str(out_path)

    except Exception as e:
        runner._log_message(f'[ERROR] Chapter processing failed: {e}')
        return None


def _probe_keyframes_ns(ref_video_path: str, runner: CommandRunner, tool_paths: dict) -> list[int]:
    """Returns a sorted list of keyframe timestamps in nanoseconds."""
    args = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'frame=pkt_pts_time,key_frame', '-of', 'json', str(ref_video_path)
    ]
    out = runner.run(args, tool_paths)
    if not out:
        runner._log_message('[WARN] ffprobe for keyframes produced no output.')
        return []

    try:
        data = json.loads(out)
        kfs_ns = [
            int(round(float(frame['pkt_pts_time']) * 1_000_000_000))
            for frame in data.get('frames', [])
            if 'pkt_pts_time' in frame and frame.get('key_frame') == 1
        ]
        kfs_ns.sort()
        runner._log_message(f'[Chapters] Found {len(kfs_ns)} keyframes for snapping.')
        return kfs_ns
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        runner._log_message(f'[WARN] Could not parse ffprobe keyframe JSON: {e}')
        return []


def _snap_chapter_times_inplace(root: ET.Element, keyframes_ns: list[int], config: dict, runner: CommandRunner):
    """Modifies chapter start/end times in the XML tree to snap to keyframes."""
    mode = config.get('snap_mode', 'previous')
    threshold_ms = config.get('snap_threshold_ms', 250)
    starts_only = config.get('snap_starts_only', True)
    threshold_ns = threshold_ms * 1_000_000

    changed_count = 0
    moved = 0
    on_kf = 0
    too_far = 0

    def pick_candidate(ts_ns: int) -> int:
        """Find the best keyframe candidate based on mode."""
        if not keyframes_ns:
            return ts_ns

        i = bisect.bisect_right(keyframes_ns, ts_ns)

        prev_kf = keyframes_ns[i - 1] if i > 0 else keyframes_ns[0]

        if mode == 'previous':
            return prev_kf
        else:  # nearest
            next_kf = keyframes_ns[i] if i < len(keyframes_ns) else keyframes_ns[-1]
            return prev_kf if abs(ts_ns - prev_kf) <= abs(ts_ns - next_kf) else next_kf

    for atom in root.findall('.//ChapterAtom'):
        tags_to_snap = ['ChapterTimeStart']
        if not starts_only:
            tags_to_snap.append('ChapterTimeEnd')

        for tag in tags_to_snap:
            node = atom.find(tag)
            if node is not None and node.text:
                original_ns = _parse_ns(node.text)
                candidate_ns = pick_candidate(original_ns)
                delta_ns = abs(original_ns - candidate_ns)

                if delta_ns == 0:
                    if tag == 'ChapterTimeStart': on_kf +=1
                elif delta_ns <= threshold_ns:
                    node.text = _fmt_ns(candidate_ns)
                    changed_count += 1
                    if tag == 'ChapterTimeStart': moved += 1
                else:
                    if tag == 'ChapterTimeStart': too_far += 1

    summary = f'Snap result: moved={moved}, on_kf={on_kf}, too_far={too_far}'
    details = f'(kfs={len(keyframes_ns)}, mode={mode}, thr={threshold_ms}ms, starts_only={starts_only})'
    runner._log_message(f'[Chapters] {summary} {details}')
