# === Thin GUI: import all non-UI logic from vsg.* ===
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings
from vsg.logbus import LOG_Q, _log, pump_logs
from vsg.tools import find_required_tools, run_command
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
from vsg.analysis.audio_xcorr import run_audio_correlation_workflow
from vsg.plan.build import build_plan, summarize_plan
from vsg.mux.tokens import build_mkvmerge_tokens
from vsg.mux.run import write_mkvmerge_json_options, run_mkvmerge_with_json
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job
from vsg.ui.options_modal import build_options_modal, show_options_modal
# === end Thin GUI import block ===

# === vsg direct imports (modularized) ===
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings
from vsg.logbus import LOG_Q, _log, pump_logs
from vsg.tools import find_required_tools, run_command
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
from vsg.analysis.audio_xcorr import run_audio_correlation_workflow
from vsg.plan.build import build_plan, summarize_plan
from vsg.mux.tokens import build_mkvmerge_tokens
from vsg.mux.run import write_mkvmerge_json_options, run_mkvmerge_with_json
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job
from vsg.ui.options_modal import build_options_modal, show_options_modal
# === end vsg direct imports ===

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Video/Audio Sync & Merge — DearPyGui (v2, labels-first UI + Global Options modal)
- Keeps the working JSON mkvmerge pipeline & ordering logic intact.
- Global Options modal for checkboxes; Analysis Settings modal for correlation/videodiff.
- Labels appear before inputs/checkboxes.
- Path inputs are taller via multiline=True, height=40 (compatible with DPG 2.1.0).

Requires: dearpygui (2.1.0), numpy, scipy, librosa, ffmpeg, mkvmerge, mkvextract
"""
import json
import os
import queue
import re
import shutil
import subprocess, shlex, time
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import librosa
import numpy as np
import bisect
import scipy.signal
import dearpygui.dearpygui as dpg
UI_FONT_ID = None
INPUT_FONT_ID = None

def load_fonts():
    """Load fonts and bind a regular 18pt UI font as the global default (not bold)."""
    global UI_FONT_ID, INPUT_FONT_ID
    try:
        with dpg.font_registry():
            import os
            regular_candidates = ('/usr/share/fonts/TTF/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/LiberationSans-Regular.ttf', '/usr/share/fonts/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/TTF/NotoSans-Regular.ttf', '/usr/share/fonts/noto/NotoSans-Regular.ttf')
            INPUT_FONT_ID = None
            UI_FONT_ID = None
            picked = None
            for fp in regular_candidates:
                if os.path.exists(fp):
                    picked = fp
                    break
            if picked:
                INPUT_FONT_ID = dpg.add_font(picked, 18, tag='input_font')
                UI_FONT_ID = dpg.add_font(picked, 18, tag='ui_font_regular18')
        if UI_FONT_ID:
            dpg.bind_font(UI_FONT_ID)
    except Exception as e:
        try:
            LOG_Q.put(f'[UI] load_fonts() failed: {e}')
        except Exception:
            pass
APP_NAME = 'Video/Audio Sync & Merge — GUI v2'
SCRIPT_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = SCRIPT_DIR / 'settings_gui.json'
ABS: Dict[str, str] = {}
CONFIG = {'output_folder': str(SCRIPT_DIR / 'sync_output'), 'temp_root': str(SCRIPT_DIR / 'temp_work'), 'analysis_mode': 'Audio Correlation', 'workflow': 'Analyze & Merge', 'scan_chunk_count': 10, 'scan_chunk_duration': 15, 'swap_subtitle_order': False, 'rename_chapters': False, 'match_jpn_secondary': True, 'match_jpn_tertiary': True, 'min_match_pct': 5.0, 'apply_dialog_norm_gain': False, 'videodiff_path': '', 'first_sub_default': True, 'videodiff_error_min': 0.0, 'videodiff_error_max': 100.0, 'snap_chapters': False, 'snap_mode': 'previous', 'snap_threshold_ms': 250, 'snap_starts_only': True, 'chapter_snap_verbose': False, 'chapter_snap_compact': True, 'log_compact': True, 'log_tail_lines': 0, 'log_error_tail': 20, 'log_progress_step': 20, 'log_show_options_pretty': False, 'log_show_options_json': False, 'log_autoscroll': True}
SIGNS_KEYS = ('sign', 'signs', 'song', 'songs', 'ops', 'eds', 'karaoke', 'titles')
LOG_Q: 'queue.Queue[str]' = queue.Queue()

def _log(logger, message: str):
    ts = datetime.now().strftime('%H:%M:%S')
    line = f'[{ts}] {message}'
    try:
        logger.info(line)
    except Exception:
        pass
    LOG_Q.put(line)

def pump_logs():
    try:
        while True:
            ln = LOG_Q.get_nowait()
            if dpg.does_item_exist('log_scroller'):
                dpg.add_text(ln, parent='log_scroller')
                if dpg.does_item_exist('log_child') and CONFIG.get('log_autoscroll', True):
                    try:
                        maxy = dpg.get_y_scroll_max('log_child')
                        dpg.set_y_scroll('log_child', maxy)
                    except Exception:
                        pass
    except queue.Empty:
        pass

def _bind_control_theme(item_tag: str):
    try:
        if dpg.does_item_exist(item_tag):
            dpg.bind_item_theme(item_tag, 'control_theme')
    except Exception:
        pass

def load_settings():
    changed = False
    if SETTINGS_PATH.exists():
        try:
            loaded = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                for k, v in CONFIG.items():
                    if k not in loaded:
                        loaded[k] = v
                        changed = True
                CONFIG.update(loaded)
            else:
                changed = True
        except Exception:
            changed = True
    else:
        changed = True
    Path(CONFIG['output_folder']).mkdir(parents=True, exist_ok=True)
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)
    if changed:
        try:
            SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2), encoding='utf-8')
            LOG_Q.put('Settings initialized/updated with defaults.')
        except Exception as e:
            LOG_Q.put(f'Failed to save settings: {e}')
try:
    load_settings()
except Exception:
    pass

def save_settings():
    try:
        SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2), encoding='utf-8')
        LOG_Q.put('Settings saved.')
    except Exception as e:
        LOG_Q.put(f'Failed to save settings: {e}')
_UI_BIND = {'temp_root': 'temp_input', 'output_folder': 'out_input', 'videodiff_path': 'vdiff_input', 'workflow': 'workflow_combo', 'analysis_mode': 'mode_combo', 'swap_subtitle_order': 'swapsec_chk', 'rename_chapters': 'chaprename_chk', 'match_jpn_secondary': 'jpnsec_chk', 'match_jpn_tertiary': 'jpnter_chk', 'apply_dialog_norm_gain': 'dialnorm_chk', 'first_sub_default': 'firstsubdef_chk', 'snap_chapters': 'snap_chapters_chk', 'snap_mode': 'snap_mode_opt', 'snap_starts_only': 'snap_starts_only_chk', 'log_compact': 'log_compact_chk', 'log_autoscroll': 'log_autoscroll_chk'}

def apply_settings_to_ui():
    try:
        for key, tag in _UI_BIND.items():
            if key in CONFIG and dpg.does_item_exist(tag):
                val = CONFIG[key]
                if tag.endswith('_combo') and (not isinstance(val, str)):
                    val = str(val)
                try:
                    dpg.set_value(tag, val)
                except Exception:
                    pass
        LOG_Q.put('Settings applied to UI.')
    except Exception as e:
        LOG_Q.put(f'[WARN] apply_settings_to_ui failed: {e}')

def pull_ui_to_settings():
    try:
        for key, tag in _UI_BIND.items():
            if dpg.does_item_exist(tag):
                CONFIG[key] = dpg.get_value(tag)
        save_settings()
        LOG_Q.put('Settings saved from UI.')
    except Exception as e:
        LOG_Q.put(f'[ERROR] pull_ui_to_settings failed: {e}')

def on_click_load_settings():
    load_settings()
    apply_settings_to_ui()

def sync_config_from_ui():
    """Pull current values from UI into CONFIG; ensure folders exist."""
    if not dpg.does_item_exist('out_input'):
        return
    CONFIG.update({'output_folder': dpg.get_value('out_input') or CONFIG.get('output_folder', str(SCRIPT_DIR / 'sync_output')), 'temp_root': dpg.get_value('temp_input') or CONFIG.get('temp_root', str(SCRIPT_DIR / 'temp_work')), 'analysis_mode': dpg.get_value('mode_combo') or CONFIG.get('analysis_mode', 'Audio Correlation'), 'workflow': dpg.get_value('workflow_combo') or CONFIG.get('workflow', 'Analyze & Merge'), 'scan_chunk_count': int(dpg.get_value('chunks_input')) if dpg.does_item_exist('chunks_input') else CONFIG.get('scan_chunk_count', 10), 'scan_chunk_duration': int(dpg.get_value('chunkdur_input')) if dpg.does_item_exist('chunkdur_input') else CONFIG.get('scan_chunk_duration', 15), 'min_match_pct': float(dpg.get_value('thresh_input')) if dpg.does_item_exist('thresh_input') else CONFIG.get('min_match_pct', 5.0), 'videodiff_error_min': float(dpg.get_value('vd_err_min')) if dpg.does_item_exist('vd_err_min') else CONFIG.get('videodiff_error_min', 0.0), 'videodiff_error_max': float(dpg.get_value('vd_err_max')) if dpg.does_item_exist('vd_err_max') else CONFIG.get('videodiff_error_max', 100.0), 'swap_subtitle_order': bool(dpg.get_value('swapsec_chk')) if dpg.does_item_exist('swapsec_chk') else CONFIG.get('swap_subtitle_order', False), 'rename_chapters': bool(dpg.get_value('chaprename_chk')) if dpg.does_item_exist('chaprename_chk') else CONFIG.get('rename_chapters', False), 'match_jpn_secondary': bool(dpg.get_value('jpnsec_chk')) if dpg.does_item_exist('jpnsec_chk') else CONFIG.get('match_jpn_secondary', True), 'match_jpn_tertiary': bool(dpg.get_value('jpnter_chk')) if dpg.does_item_exist('jpnter_chk') else CONFIG.get('match_jpn_tertiary', True), 'apply_dialog_norm_gain': bool(dpg.get_value('dialnorm_chk')) if dpg.does_item_exist('dialnorm_chk') else CONFIG.get('apply_dialog_norm_gain', False), 'first_sub_default': bool(dpg.get_value('firstsubdef_chk')) if dpg.does_item_exist('firstsubdef_chk') else CONFIG.get('first_sub_default', True), 'videodiff_path': dpg.get_value('vdiff_input') if dpg.does_item_exist('vdiff_input') else CONFIG.get('videodiff_path', ''), 'snap_chapters': bool(dpg.get_value('snap_chapters_chk')) if dpg.does_item_exist('snap_chapters_chk') else CONFIG.get('snap_chapters', False), 'snap_mode': dpg.get_value('snap_mode_opt') if dpg.does_item_exist('snap_mode_opt') else CONFIG.get('snap_mode', 'previous'), 'snap_threshold_ms': int(dpg.get_value('snap_threshold_ms')) if dpg.does_item_exist('snap_threshold_ms') else CONFIG.get('snap_threshold_ms', 250), 'snap_starts_only': bool(dpg.get_value('snap_starts_only_chk')) if dpg.does_item_exist('snap_starts_only_chk') else CONFIG.get('snap_starts_only', True)})
    Path(CONFIG['output_folder']).mkdir(parents=True, exist_ok=True)
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)

def get_stream_info(mkv_path: str, logger) -> Optional[Dict[str, Any]]:
    out = run_command(['mkvmerge', '-J', str(mkv_path)], logger)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        _log(logger, 'Failed to parse mkvmerge -J JSON output.')
        return None

def _ext_for_track(ttype: str, codec_id: str) -> str:
    cid = (codec_id or '').upper()
    if ttype == 'video':
        if 'V_MPEGH/ISO/HEVC' in cid or 'HEVC' in cid or 'H.265' in cid:
            return 'h265'
        if 'V_MPEG4/ISO/AVC' in cid or 'H.264' in cid or 'AVC' in cid:
            return 'h264'
        if 'V_VP9' in cid:
            return 'vp9'
        if 'V_AV1' in cid or 'AV1' in cid:
            return 'av1'
        return 'bin'
    if ttype == 'audio':
        if 'A_TRUEHD' in cid:
            return 'thd'
        if 'A_EAC3' in cid or 'E-AC-3' in cid:
            return 'eac3'
        if 'A_AC3' in cid:
            return 'ac3'
        if 'A_DTS' in cid:
            return 'dts'
        if 'A_AAC' in cid:
            return 'aac'
        if 'A_FLAC' in cid:
            return 'flac'
        if 'A_OPUS' in cid:
            return 'opus'
        if 'A_VORBIS' in cid:
            return 'ogg'
        if 'A_PCM' in cid or 'A_MS/ACM' in cid or 'LPCM' in cid:
            return 'wav'
        return 'bin'
    if ttype == 'subtitles':
        if 'S_TEXT/ASS' in cid or 'S_ASS' in cid:
            return 'ass'
        if 'S_TEXT/SSA' in cid or 'S_SSA' in cid:
            return 'ssa'
        if 'S_TEXT/UTF8' in cid or 'S_UTF8' in cid:
            return 'srt'
        if 'S_HDMV/PGS' in cid or 'PGS' in cid:
            return 'sup'
        if 'S_VOBSUB' in cid:
            return 'sub'
        return 'sub'
    return 'bin'

def extract_attachments(mkv: str, temp_dir: str, logger, role: str) -> List[str]:
    info = get_stream_info(mkv, logger)
    files, specs = ([], [])
    for a in (info or {}).get('attachments', []):
        out = Path(temp_dir) / f"{role}_att_{a['id']}_{a['file_name']}"
        specs.append(f"{a['id']}:{out}")
        files.append(str(out))
    if specs:
        run_command(['mkvextract', str(mkv), 'attachments'] + specs, logger)
    return files

def _normalize_chapter_end_times(root, logger=None):
    """Ensure each chapter's end time is <= next start, and > its own start.
    Uses nanosecond math. Returns (fixed_count, touched_indices)."""

    def _parse_ns(t: str) -> int:
        t = t.strip()
        hh, mm, rest = t.split(':')
        if '.' in rest:
            ss, frac = rest.split('.')
            frac = (frac + '000000000')[:9]
        else:
            ss, frac = (rest, '000000000')
        return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000000000 + int(frac)

    def _fmt_ns(ns: int) -> str:
        if ns < 0:
            ns = 0
        frac = ns % 1000000000
        tot = ns // 1000000000
        hh2 = tot // 3600
        mm2 = tot % 3600 // 60
        ss2 = tot % 60
        return f'{hh2:02d}:{mm2:02d}:{ss2:02d}.{frac:09d}'
    atoms = list(root.findall('.//ChapterAtom'))
    recs = []
    for idx, atom in enumerate(atoms):
        st_el = atom.find('ChapterTimeStart')
        en_el = atom.find('ChapterTimeEnd')
        st_ns = _parse_ns(st_el.text) if st_el is not None and st_el.text else None
        en_ns = _parse_ns(en_el.text) if en_el is not None and en_el.text else None
        recs.append((idx, atom, st_el, en_el, st_ns, en_ns))
    recs = sorted(recs, key=lambda r: r[4] if r[4] is not None else 0)
    fixed = 0
    touched = []
    for i, (idx, atom, st_el, en_el, st_ns, en_ns) in enumerate(recs):
        if st_ns is None:
            continue
        next_start_ns = None
        if i + 1 < len(recs):
            next_st = recs[i + 1][4]
            if next_st is not None:
                next_start_ns = next_st
        desired_en = en_ns
        if next_start_ns is not None:
            if desired_en is None or desired_en > next_start_ns:
                desired_en = next_start_ns
        if desired_en is None or desired_en <= st_ns:
            desired_en = st_ns + 1000000
        if en_el is None:
            en_el = ET.SubElement(atom, 'ChapterTimeEnd')
        old = en_el.text
        new = _fmt_ns(desired_en)
        if old != new:
            en_el.text = new
            fixed += 1
            touched.append(idx)
    if logger:
        _log(logger, f'[Chapters] Normalized chapter ends: {fixed} updated')
    return (fixed, touched)

def ffprobe_duration(path: str, logger) -> float:
    out = run_command(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)], logger)
    try:
        return float(out.strip()) if out else 0.0
    except Exception:
        return 0.0

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

def extract_audio_chunk(source_file: str, output_wav: str, start_time: float, duration: float, logger, stream_index: int):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', str(start_time), '-i', str(source_file), '-map', f'0:a:{stream_index}', '-t', str(duration), '-vn', '-acodec', 'pcm_s16le', '-ar', '48000', '-ac', '1', str(output_wav)]
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

def build_plan(ref_tracks, sec_tracks, ter_tracks, delays):
    plan = []
    for t in ref_tracks:
        if t['type'] == 'video':
            plan.append({'src': t['path'], 'type': 'video', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    for t in sec_tracks or []:
        if t['type'] == 'audio':
            plan.append({'src': t['path'], 'type': 'audio', 'lang': t['lang'], 'name': t['name'], 'from_group': 'sec', 'codec_id': t.get('codec_id', '')})
    for t in ref_tracks:
        if t['type'] == 'audio':
            plan.append({'src': t['path'], 'type': 'audio', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    for t in ter_tracks or []:
        if t['type'] == 'subtitles':
            plan.append({'src': t['path'], 'type': 'subtitles', 'lang': t['lang'], 'name': t['name'], 'from_group': 'ter', 'codec_id': t.get('codec_id', '')})
    for t in sec_tracks or []:
        if t['type'] == 'subtitles':
            plan.append({'src': t['path'], 'type': 'subtitles', 'lang': t['lang'], 'name': t['name'], 'from_group': 'sec', 'codec_id': t.get('codec_id', '')})
    for t in ref_tracks:
        if t['type'] not in ('video', 'audio'):
            plan.append({'src': t['path'], 'type': t['type'], 'lang': t['lang'], 'name': t['name'], 'from_group': 'ref', 'codec_id': t.get('codec_id', '')})
    return {'plan': plan, 'delays': delays}

def summarize_plan(plan_json, output_file, chapters_xml_path, attachments):
    """Return (track_order_str, lines[]) describing final output order & config."""
    lines = []
    plan = plan_json.get('plan', [])
    delays = plan_json.get('delays', {})
    lines.append('=== Merge Summary ===')
    lines.append(f'Output: {output_file}')
    lines.append(f"Chapters: {(chapters_xml_path if chapters_xml_path else '(none)')}")
    lines.append(f"Delays: secondary={delays.get('secondary_ms', 0)} ms, tertiary={delays.get('tertiary_ms', 0)} ms")
    lines.append('Inputs (grouped order):')
    for idx, trk in enumerate(plan):
        ttype = trk.get('type')
        grp = trk.get('from_group')
        lang = trk.get('lang') or 'und'
        name = (trk.get('name') or '').strip()
        codec = trk.get('codec_id') or ''
        lines.append(f"  [{idx}] {ttype:9s} | group={grp:3s} | lang={lang:3s} | name='{name}' | codec='{codec}'")
        lines.append(f"       path: {trk.get('src')}")
    if attachments:
        lines.append('Attachments:')
        for a in attachments:
            lines.append(f'  - {a}')
    else:
        lines.append('Attachments: (none)')
    track_order = ','.join((f'{i}:0' for i in range(len(plan))))
    lines.append(f'Track order: {track_order}')
    lines.append('=====================')
    return (track_order, lines)

def _tokens_for_track(track: Dict[str, Any], group: str, delays_ms: Dict[str, int], default_flag: Optional[bool]=None):
    toks: List[str] = []
    name = track.get('name', '')
    lang = track.get('lang', '')
    ttype = track.get('type', '')
    src = str(track.get('src', ''))
    grp = group if group in {'ref', 'sec', 'ter'} else None
    if not grp:
        if 'ter_track_' in src:
            grp = 'ter'
        elif 'sec_track_' in src:
            grp = 'sec'
        else:
            grp = 'ref'
    delay = 0
    if grp == 'sec':
        delay = int(delays_ms.get('secondary_ms', 0) or 0)
    elif grp == 'ter':
        delay = int(delays_ms.get('tertiary_ms', 0) or 0)
    else:
        delay = 0
    delay += int(delays_ms.get('_global_shift', 0) or 0)
    toks += ['--track-name', f"0:{name or ''}"]
    if lang:
        toks += ['--language', f'0:{lang}']
    toks += ['--sync', f'0:{delay}']
    if default_flag is not None:
        toks += ['--default-track-flag', f"0:{('yes' if default_flag else 'no')}"]
    return toks

def run_mkvmerge_with_json(json_path: str, logger) -> bool:
    out = run_command(['mkvmerge', f'@{json_path}'], logger)
    return out is not None

def format_delay_ms(ms):
    if ms is None:
        return '—'
    ms = int(ms)
    sign = '-' if ms < 0 else ''
    return f'{sign}{abs(ms)} ms'

def _probe_keyframes_ns(ref_video_path: str, shift_ms: int, logger) -> list[int]:
    """Return sorted keyframe timestamps in nanoseconds, already shifted by shift_ms."""
    args = ['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-skip_frame', 'nokey', '-show_entries', 'frame=pkt_pts_time,best_effort_timestamp_time,key_frame', '-of', 'json', ref_video_path]
    out = run_command(args, logger)
    if not out:
        _log(logger, '[WARN] ffprobe keyframes produced no output')
        return []
    try:
        data = json.loads(out)
    except Exception as e:
        _log(logger, f'[WARN] ffprobe JSON parse error: {e}')
        return []
    kfs_ns = []
    for fr in data.get('frames', []):
        try:
            if int(fr.get('key_frame', 0)) != 1:
                continue
            t = fr.get('pkt_pts_time') or fr.get('best_effort_timestamp_time')
            if t is None:
                continue
            sec = float(t)
            ns = int(round(sec * 1000000000))
            ns += int(shift_ms) * 1000000
            kfs_ns.append(ns)
        except Exception:
            continue
    kfs_ns.sort()
    _log(logger, f'[Chapters] Keyframes loaded: {len(kfs_ns)}')
    return kfs_ns

def set_status(msg):
    if dpg.does_item_exist('status_text'):
        dpg.set_value('status_text', msg)

def set_progress(x):
    if dpg.does_item_exist('progress_bar'):
        dpg.set_value('progress_bar', max(0.0, min(1.0, float(x))))

def on_pick_file(sender, app_data, user_data):
    tag = user_data
    if app_data and isinstance(app_data, dict):
        dpg.set_value(tag, app_data.get('file_path_name', dpg.get_value(tag)))

def on_pick_dir(sender, app_data, user_data):
    tag = user_data
    if app_data and isinstance(app_data, dict):
        dpg.set_value(tag, app_data.get('file_path_name', dpg.get_value(tag)))

def ui_save_settings(sender=None, app_data=None, user_data=None):
    sync_config_from_ui()
    save_settings()
    LOG_Q.put('Settings saved.')

def do_analyze_only(sender, app_data, user_data):
    threading.Thread(target=worker_run_jobs, kwargs={'and_merge': False}, daemon=True).start()

def do_analyze_and_merge(sender, app_data, user_data):
    threading.Thread(target=worker_run_jobs, kwargs={'and_merge': True}, daemon=True).start()

def worker_run_jobs(and_merge=False):
    try:
        find_required_tools()
    except Exception as e:
        LOG_Q.put(str(e))
        set_status('Missing tools.')
        return
    sync_config_from_ui()
    save_settings()
    ref = dpg.get_value('ref_input')
    sec = dpg.get_value('sec_input')
    ter = dpg.get_value('ter_input')
    out_dir = dpg.get_value('out_input') or CONFIG['output_folder']
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    set_status('Preparing jobs…')
    set_progress(0.0)
    try:
        jobs = discover_jobs(ref, sec, ter)
    except Exception as e:
        LOG_Q.put(f'Job discovery error: {e}')
        set_status('Job discovery error.')
        return
    vd_cfg = CONFIG.get('videodiff_path', '').strip()
    vd_path = Path(vd_cfg) if vd_cfg else Path(shutil.which('videodiff') or SCRIPT_DIR / 'videodiff')
    results = []
    for i, (r, s, t) in enumerate(jobs, 1):
        set_status(f'({i}/{len(jobs)}) {Path(r).name}')
        set_progress(0.0)
        log, out_root = job_logger_for(r, out_dir)
        _log(log, f'=== Job start: {Path(r).name} ===')
        try:
            prev = CONFIG['workflow']
            if not and_merge:
                CONFIG['workflow'] = 'Analyze Only'
            res = merge_job(r, s, t, out_root, log, vd_path)
            CONFIG['workflow'] = prev
            results.append({'name': Path(r).name, **res})
            if res.get('output'):
                _log(log, f"Output: {res['output']}")
            _log(log, f"Delays: Secondary={format_delay_ms(res.get('delay_sec'))}, Tertiary={format_delay_ms(res.get('delay_ter'))}")
            _log(log, '=== Job complete ===')
        except Exception as e:
            results.append({'name': Path(r).name, 'status': 'Failed', 'error': str(e)})
            _log(log, f'[FAILED] {e}')
            _log(log, '=== Job complete (failed) ===')
        set_progress(i / max(1, len(jobs)))
    LOG_Q.put('--- Summary ---')
    for r in results:
        if r.get('status') == 'Merged':
            LOG_Q.put(f"{r['name']}: Merged -> {r.get('output')} (Sec {format_delay_ms(r.get('delay_sec'))}, Ter {format_delay_ms(r.get('delay_ter'))})")
        elif r.get('status') == 'Analyzed':
            LOG_Q.put(f"{r['name']}: Analyzed (Sec {format_delay_ms(r.get('delay_sec'))}, Ter {format_delay_ms(r.get('delay_ter'))})")
        else:
            LOG_Q.put(f"{r['name']}: Failed — {r.get('error')}")
    set_status('All jobs finished.')
    set_progress(1.0)

def discover_jobs(ref_path, sec_path, ter_path):
    ref = Path(ref_path) if ref_path else None
    sec = Path(sec_path) if sec_path else None
    ter = Path(ter_path) if ter_path else None
    if not ref or not ref.exists():
        raise RuntimeError('Reference path must exist.')
    if ref.is_file():
        return [(str(ref), str(sec) if sec and sec.is_file() else None, str(ter) if ter and ter.is_file() else None)]
    if sec and sec.is_file() or (ter and ter.is_file()):
        raise RuntimeError('If Reference is a folder, Secondary/Tertiary must be folders too.')
    jobs = []
    for f in sorted(ref.iterdir()):
        if f.is_file():
            s = sec / f.name if sec else None
            t = ter / f.name if ter else None
            s_ok = str(s) if s and s.exists() and s.is_file() else None
            t_ok = str(t) if t and t.exists() and t.is_file() else None
            if s_ok or t_ok:
                jobs.append((str(f), s_ok, t_ok))
    return jobs

def job_logger_for(ref_path, output_root):
    output_root = Path(output_root)
    ref_src = Path(dpg.get_value('ref_input'))
    if ref_src.exists() and ref_src.is_dir():
        output_root = output_root / ref_src.name
    output_root.mkdir(parents=True, exist_ok=True)
    log_path = output_root / (Path(ref_path).stem + '.log')
    import logging
    logger = logging.getLogger(f'job_{Path(ref_path).stem}_{int(time.time())}')
    logger.setLevel(logging.INFO)
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fh = logging.FileHandler(log_path, mode='w', encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(fh)
    return (logger, str(output_root))

def build_ui():
    load_settings()
    dpg.create_context()
    load_fonts()
    INPUT_FONT_TAG = None
    try:
        with dpg.font_registry():
            _candidates = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/TTF/LiberationSans-Regular.ttf', '/usr/share/fonts/truetype/freefont/FreeSans.ttf', '/usr/share/fonts/TTF/FreeSans.ttf', '/usr/share/fonts/noto/NotoSans-Regular.ttf', '/usr/share/fonts/TTF/NotoSans-Regular.ttf', '/usr/share/fonts/cantarell/Cantarell-Regular.ttf', '/usr/share/fonts/cantarell/Cantarell-VF.otf']
            for _fp in _candidates:
                try:
                    import os
                    if os.path.exists(_fp):
                        dpg.add_font(_fp, 18, tag='input_font')
                        INPUT_FONT_TAG = 'input_font'
                        break
                except Exception:
                    pass
            if INPUT_FONT_TAG is None:
                try:
                    import os
                    preferred = ['DejaVuSans', 'LiberationSans', 'NotoSans', 'Cantarell', 'FreeSans']
                    found_any = ''
                    found_pref = ''
                    for root, _, files in os.walk('/usr/share/fonts'):
                        for f in files:
                            if f.lower().endswith(('.ttf', '.otf')):
                                p = os.path.join(root, f)
                                if not found_any:
                                    found_any = p
                                if any((k.lower() in f.lower() for k in preferred)):
                                    found_pref = p
                                    break
                        if found_pref:
                            break
                    chosen = found_pref or found_any
                    if chosen:
                        dpg.add_font(chosen, 18, tag='input_font')
                        INPUT_FONT_TAG = 'input_font'
                except Exception:
                    pass
    except Exception:
        INPUT_FONT_TAG = None
    try:
        with dpg.theme(tag='input_theme'):
            with dpg.theme_component(dpg.mvInputText):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 8, category=dpg.mvThemeCat_Core)
    except Exception:
        pass
    try:
        with dpg.theme(tag='control_theme'):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 12, 10, category=dpg.mvThemeCat_Core)
            with dpg.theme_component(dpg.mvCombo):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 10, 9, category=dpg.mvThemeCat_Core)
            with dpg.theme_component(dpg.mvProgressBar):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 6, 6, category=dpg.mvThemeCat_Core)
    except Exception:
        pass

    def _safe_bind_input_enhancements(item_tag: str):
        try:
            if dpg.does_item_exist(item_tag):
                try:
                    dpg.bind_item_theme(item_tag, 'input_theme')
                except Exception:
                    pass
                if INPUT_FONT_TAG:
                    try:
                        dpg.bind_item_font(item_tag, INPUT_FONT_TAG)
                    except Exception:
                        pass
        except Exception:
            pass
    with dpg.window(tag='main_window', label=APP_NAME, width=1180, height=780):
        with dpg.group(tag='header_options_row'):
            dpg.add_button(tag='options_btn_main', label='Options…', callback=lambda *_: show_options_modal())
                dpg.add_separator()
                dpg.add_text('Inputs')
                with dpg.group(horizontal=True):
                    dpg.add_button(label='Storage…', callback=lambda: dpg.configure_item('storage_modal', show=True))
                    dpg.add_button(label='Analysis Settings…', callback=lambda: dpg.configure_item('analysis_modal', show=True))
                    dpg.add_button(label='Global Options…', callback=lambda: dpg.configure_item('global_modal', show=True))
                with dpg.group(horizontal=True):
                    dpg.add_text('Reference')
                    dpg.add_input_text(tag='ref_input', label='', width=900, multiline=False, height=40)
                    if INPUT_FONT_ID:
                        dpg.bind_item_font('ref_input', INPUT_FONT_ID)
                    _safe_bind_input_enhancements('ref_input')
                    dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('file_dialog_ref'))
                with dpg.group(horizontal=True):
                    dpg.add_text('Secondary')
                    dpg.add_input_text(tag='sec_input', label='', width=900, multiline=False, height=40)
                    if INPUT_FONT_ID:
                        dpg.bind_item_font('sec_input', INPUT_FONT_ID)
                    _safe_bind_input_enhancements('sec_input')
                    dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('file_dialog_sec'))
                with dpg.group(horizontal=True):
                    dpg.add_text('Tertiary')
                    dpg.add_input_text(tag='ter_input', label='', width=900, multiline=False, height=40)
                    if INPUT_FONT_ID:
                        dpg.bind_item_font('ter_input', INPUT_FONT_ID)
                    _safe_bind_input_enhancements('ter_input')
                    dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('file_dialog_ter'))
                dpg.add_separator()
                dpg.add_text('Settings')
                with dpg.group(horizontal=True):
                    dpg.add_text('Workflow')
                    dpg.add_combo(tag='workflow_combo', items=['Analyze & Merge', 'Analyze Only'], default_value=CONFIG['workflow'], width=260)
                    _bind_control_theme('workflow_combo')
                    dpg.add_spacer(width=12)
                    dpg.add_text('Mode')
                    dpg.add_combo(tag='mode_combo', items=['Audio Correlation', 'VideoDiff'], default_value=CONFIG['analysis_mode'], width=260)
                    _bind_control_theme('mode_combo')
                dpg.add_separator()
                dpg.add_text('Actions')
                with dpg.group(horizontal=True):
                    dpg.add_button(tag='btn_analyze_only', label='Analyze Only', callback=do_analyze_only, width=150, height=36)
                    _bind_control_theme('btn_analyze_only')
                    dpg.add_button(tag='btn_analyze_merge', label='Analyze & Merge', callback=do_analyze_and_merge, width=170, height=36)
                    _bind_control_theme('btn_analyze_merge')
                    dpg.add_progress_bar(tag='progress_bar', overlay='Progress', default_value=0.0, width=420, height=26)
                    _bind_control_theme('progress_bar')
                    dpg.add_text('Status:')
                    dpg.add_text(tag='status_text', default_value='')
                dpg.add_separator()
                dpg.add_text('Results (latest job)')
                with dpg.group(horizontal=True):
                    dpg.add_text('Secondary delay:')
                    dpg.add_text(tag='sec_delay_val', default_value='—')
                    dpg.add_text('   |   ')
                    dpg.add_text('Tertiary delay:')
                    dpg.add_text(tag='ter_delay_val', default_value='—')
                dpg.add_separator()
                dpg.add_text('Log')
                with dpg.child_window(tag='log_child', width=-1, height=320, horizontal_scrollbar=True):
                    dpg.add_child_window(tag='log_scroller', width=-1, height=-1)
                with dpg.file_dialog(tag='file_dialog_ref', label='Pick Reference', callback=on_pick_file, user_data='ref_input', width=700, height=400, directory_selector=False, show=False):
                    dpg.add_file_extension('.*', color=(150, 255, 150, 255))
                with dpg.file_dialog(tag='file_dialog_sec', label='Pick Secondary', callback=on_pick_file, user_data='sec_input', width=700, height=400, directory_selector=False, show=False):
                    dpg.add_file_extension('.*', color=(150, 255, 150, 255))
                with dpg.file_dialog(tag='file_dialog_ter', label='Pick Tertiary', callback=on_pick_file, user_data='ter_input', width=700, height=400, directory_selector=False, show=False):
                    dpg.add_file_extension('.*', color=(150, 255, 150, 255))
                with dpg.file_dialog(tag='dir_dialog_out', label='Pick Output Directory', callback=on_pick_dir, user_data='out_input', width=700, height=400, directory_selector=True, show=False):
                    pass
                with dpg.file_dialog(tag='dir_dialog_temp', label='Pick Temp Directory', callback=on_pick_dir, user_data='temp_input', width=700, height=400, directory_selector=True, show=False):
                    pass
                with dpg.file_dialog(tag='file_dialog_vdiff', label='Pick videodiff binary', callback=on_pick_file, user_data='vdiff_input', width=700, height=400, directory_selector=False, show=False):
                    dpg.add_file_extension('.*', color=(150, 255, 150, 255))
                with dpg.window(tag='storage_modal', label='Storage Settings', modal=True, show=False, no_resize=False, width=800, height=300):
                    dpg.add_text('Set directories for temporary work and final outputs; optionally set videodiff path')
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text('Temp Directory')
                        dpg.add_input_text(tag='temp_input', label='', default_value=CONFIG['temp_root'], width=600, multiline=False, height=40)
                        if INPUT_FONT_ID:
                            dpg.bind_item_font('temp_input', INPUT_FONT_ID)
                        _safe_bind_input_enhancements('temp_input')
                        dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('dir_dialog_temp'))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Output Directory')
                        dpg.add_input_text(tag='out_input', label='', default_value=CONFIG['output_folder'], width=600, multiline=False, height=40)
                        if INPUT_FONT_ID:
                            dpg.bind_item_font('out_input', INPUT_FONT_ID)
                        _safe_bind_input_enhancements('out_input')
                        dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('dir_dialog_out'))
                    with dpg.group(horizontal=True):
                        dpg.add_text('videodiff Path')
                        dpg.add_input_text(tag='vdiff_input', label='', default_value=CONFIG.get('videodiff_path', ''), width=600, multiline=False, height=40)
                        if INPUT_FONT_ID:
                            dpg.bind_item_font('vdiff_input', INPUT_FONT_ID)
                        _safe_bind_input_enhancements('vdiff_input')
                        dpg.add_button(label='Browse…', callback=lambda: dpg.show_item('file_dialog_vdiff'))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_button(label='Save', callback=lambda s, a, u: (ui_save_settings(), dpg.configure_item('storage_modal', show=False)))
                        dpg.add_button(label='Cancel', callback=lambda: dpg.configure_item('storage_modal', show=False))
                with dpg.window(tag='global_modal', label='Global Options', modal=True, show=False, no_resize=False, width=720, height=280):
                    dpg.add_text('Toggle global behaviors that affect extraction and merge')
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text('Swap first 2 subtitles (Secondary only)')
                        dpg.add_checkbox(tag='swapsec_chk', label='', default_value=bool(CONFIG['swap_subtitle_order']))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Rename chapters (Reference)')
                        dpg.add_checkbox(tag='chaprename_chk', label='', default_value=bool(CONFIG['rename_chapters']))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Prefer JPN audio on Secondary')
                        dpg.add_checkbox(tag='jpnsec_chk', label='', default_value=bool(CONFIG['match_jpn_secondary']))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Prefer JPN audio on Tertiary')
                        dpg.add_checkbox(tag='jpnter_chk', label='', default_value=bool(CONFIG['match_jpn_tertiary']))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Remove dialog normalization (AC-3/E-AC-3)')
                        dpg.add_checkbox(tag='dialnorm_chk', label='', default_value=bool(CONFIG['apply_dialog_norm_gain']))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Make first subtitle in final order the DEFAULT')
                        dpg.add_checkbox(tag='firstsubdef_chk', label='', default_value=bool(CONFIG.get('first_sub_default', True)))
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_button(label='Save', callback=lambda s, a, u: (ui_save_settings(), dpg.configure_item('global_modal', show=False)))
                        dpg.add_button(label='Cancel', callback=lambda: dpg.configure_item('global_modal', show=False))
                    dpg.add_separator()
                    dpg.add_text('Chapters / Keyframe snapping')
                    with dpg.group(horizontal=True):
                        dpg.add_text('Snap chapters to keyframes')
                        dpg.add_checkbox(tag='snap_chapters_chk', label='', default_value=bool(CONFIG.get('snap_chapters', False)))
                    with dpg.group(horizontal=True):
                        dpg.add_text('Snap mode')
                        dpg.add_combo(tag='snap_mode_opt', items=['previous', 'nearest'], default_value=CONFIG.get('snap_mode', 'previous'), width=140)
                    with dpg.group(horizontal=True):
                        dpg.add_text('Max snap distance (ms)')
                        dpg.add_input_int(tag='snap_threshold_ms', default_value=int(CONFIG.get('snap_threshold_ms', 250)), min_value=0, width=120)
                    with dpg.group(horizontal=True):
                        dpg.add_text('Starts only')
                        dpg.add_checkbox(tag='snap_starts_only_chk', label='', default_value=bool(CONFIG.get('snap_starts_only', True)))
                with dpg.window(tag='analysis_modal', label='Analysis Settings', modal=True, show=False, no_resize=False, width=800, height=320):
                    dpg.add_text('Configure analysis parameters')
                    dpg.add_separator()
                    dpg.add_text('Audio Cross-Correlation')
                    with dpg.group(horizontal=True):
                        dpg.add_text('Chunks')
                        dpg.add_input_int(tag='chunks_input', label='', default_value=int(CONFIG['scan_chunk_count']), min_value=1, max_value=50, width=100)
                        dpg.add_spacer(width=12)
                        dpg.add_text('Chunk Dur (s)')
                        dpg.add_input_int(tag='chunkdur_input', label='', default_value=int(CONFIG['scan_chunk_duration']), min_value=2, max_value=120, width=120)
                        dpg.add_spacer(width=12)
                        dpg.add_text('Min Match %')
                        dpg.add_input_float(tag='thresh_input', label='', default_value=float(CONFIG['min_match_pct']), width=120)
                    dpg.add_text('VideoDiff')
                    with dpg.group(horizontal=True):
                        dpg.add_text('Min error')
                        dpg.add_input_float(tag='vd_err_min', label='', default_value=float(CONFIG.get('videodiff_error_min', 0.0)), width=100, format='%.2f')
                        dpg.add_spacer(width=12)
                        dpg.add_text('Max error')
                        dpg.add_input_float(tag='vd_err_max', label='', default_value=float(CONFIG.get('videodiff_error_max', 100.0)), width=100, format='%.2f')
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_button(label='Save', callback=lambda s, a, u: (ui_save_settings(), dpg.configure_item('analysis_modal', show=False)))
                        dpg.add_button(label='Cancel', callback=lambda: dpg.configure_item('analysis_modal', show=False))
            Path(CONFIG['output_folder']).mkdir(parents=True, exist_ok=True)
            Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)
            try:
                apply_settings_to_ui()
            except Exception as _e:
                LOG_Q.put(f'[WARN] apply_settings_to_ui at build: {_e}')
            dpg.create_viewport(title=APP_NAME, width=1200, height=820)
            dpg.setup_dearpygui()
            dpg.show_viewport()
            dpg.set_primary_window('main_window', True)
            last = time.time()
            while dpg.is_dearpygui_running():
                now = time.time()
                if now - last > 0.1:
                    pump_logs()
                    last = now
                dpg.render_dearpygui_frame()
            dpg.destroy_context()
        if __name__ == '__main__':
            build_ui()
        
        # --- BEGIN_INJECT_MERGE_SUMMARY ---
# Merge Summary helpers (logging-only utilities)
def _vsg_tokenize_opts_json(path: str) -> list[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and all(isinstance(x, str) for x in data):
            return data
    except Exception:
        pass
    return []

def _vsg_parse_mkvmerge_tokens(tokens: list[str]) -> dict:
    res = {"inputs": [], "track_order": "", "chapters": ""}
    cur_opts = []
    i = 0
    n = len(tokens)
    def add_input(pth: str, opts: list[str]):
        d = {}
        it = iter(opts)
        for t in it:
            if t in ("--language","--track-name","--default-track-flag","--forced-track-flag","--sync","--compression"):
                try:
                    d[t] = next(it)
                except StopIteration:
                    d[t] = ""
        res["inputs"].append({"path": pth, "opts": d})
    while i < n:
        t = tokens[i]
        if t == "(":
            p = tokens[i+1] if (i + 1) < n else ""
            j = i + 2
            while j < n and tokens[j] != ")":
                j += 1
            add_input(p, cur_opts)
            cur_opts = []
            i = j + 1
            continue
        elif t == "--track-order" and (i + 1) < n:
            res["track_order"] = tokens[i+1]
            i += 2; continue
        elif t == "--chapters" and (i + 1) < n:
            res["chapters"] = tokens[i+1]
            i += 2; continue
        else:
            cur_opts.append(t)
            i += 1
    return res

def _vsg_ms_from_sync(sync_val: str) -> str:
    try:
        _, v = sync_val.split(":", 1)
        v = int(float(v))
        return f"{v} ms"
    except Exception:
        return "0 ms"

def _vsg_log_merge_summary_from_opts(logger, opts_path: str):
    tokens = _vsg_tokenize_opts_json(opts_path)
    if not tokens:
        return
    parsed = _vsg_parse_mkvmerge_tokens(tokens)
    _log(logger, "=== Merge Summary ===")
    if parsed.get("track_order"):
        _log(logger, f"Track order: {parsed['track_order']}")
    if parsed.get("chapters"):
        _log(logger, f"Chapters   : {parsed['chapters']}")
    for idx, item in enumerate(parsed.get("inputs", [])):
        p = item.get("path", "")
        o = item.get("opts", {})
        lang = o.get("--language", "")
        name = o.get("--track-name", "")
        dflt = o.get("--default-track-flag", "")
        forc = o.get("--forced-track-flag", "")
        sync = o.get("--sync", "")
        sync_ms = _vsg_ms_from_sync(sync) if sync else "0 ms"
        details = []
        if lang: details.append(f"lang={lang}")
        if name: details.append(f"name={name}")
        if dflt: details.append(f"default={dflt}")
        if forc: details.append(f"forced={forc}")
        if sync: details.append(f"sync={sync_ms}")
        det = "; ".join(details) if details else "no per-file flags"
        _log(logger, f"{idx:02d}) {p}  [{det}]")
    _log(logger, f"Options file: {opts_path}")
    _log(logger, "====================")
# --- END_INJECT_MERGE_SUMMARY ---


def _register_options_hotkey():
    import dearpygui.dearpygui as dpg
    try:
        if not dpg.does_item_exist('opt_hotkey_reg'):
            with dpg.handler_registry(tag='opt_hotkey_reg'):
                dpg.add_key_press_handler(key=dpg.mvKey_F9, callback=lambda *_: show_options_modal())
    except Exception:
        pass
