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

def find_required_tools():
    for tool in ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract']:
        path = shutil.which(tool)
        if not path:
            raise RuntimeError(f"Required tool '{tool}' not found in PATH.")
        ABS[tool] = path

def run_command(cmd: List[str], logger) -> Optional[str]:
    silent_capture = False  # default; set to True for noisy ffprobe JSON
    """
    Settings-driven compact logger:
      - If CONFIG['log_compact'] is True (default), prints one $ line and throttled "Progress: N%".
      - On failure prints a short stderr tail (CONFIG['log_error_tail']).
      - On success (compact mode) optionally prints last N stdout lines (CONFIG['log_tail_lines']).
      - If compact is False, streams all output like the original.
    """
    if not cmd:
        return None
    tool = cmd[0]
    cmd = [ABS.get(tool, tool)] + list(map(str, cmd[1:]))
    compact = bool(CONFIG.get('log_compact', True))
    tail_ok = int(CONFIG.get('log_tail_lines', 0))
    err_tail = int(CONFIG.get('log_error_tail', 20))
    prog_step = max(1, int(CONFIG.get('log_progress_step', 100)))
    try:
        import shlex
        pretty = ' '.join((shlex.quote(str(c)) for c in cmd))
    except Exception:
        pretty = ' '.join(map(str, cmd))
    _log(logger, '$ ' + pretty)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        out_buf = ''
        last_prog = -1
        if compact:
            from collections import deque
            tail = deque(maxlen=max(tail_ok, err_tail, 1))
        for line in iter(proc.stdout.readline, ''):
            if silent_capture:
                out_buf += line
                continue
            out_buf += line
            if compact:
                if line.startswith('Progress: '):
                    try:
                        pct = int(line.strip().split()[-1].rstrip('%'))
                    except Exception:
                        pct = None
                    if pct is not None and (last_prog < 0 or pct >= last_prog + prog_step or pct == 100):
                        _log(logger, f'Progress: {pct}%')
                        last_prog = pct
                else:
                    tail.append(line)
            else:
                _log(logger, line.rstrip('\n'))
        proc.wait()
        rc = proc.returncode or 0
        if rc and rc > 1:
            _log(logger, f'[!] Command failed with exit code {rc}')
            if compact and err_tail > 0:
                from itertools import islice
                t = list(tail)[-err_tail:] if 'tail' in locals() else []
                if t:
                    _log(logger, '[stderr/tail]\n' + ''.join(t).rstrip())
            return None
        if compact and tail_ok > 0 and ('tail' in locals()):
            t = list(tail)[-tail_ok:]
            if t:
                _log(logger, '[stdout/tail]\n' + ''.join(t).rstrip())
        return out_buf
    except Exception as e:
        _log(logger, f'[!] Failed to execute: {e}')
        return None

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

def extract_tracks(mkv: str, temp_dir: str, logger, role: str, audio=True, subs=True, all_tracks=False) -> List[Dict[str, Any]]:
    info = get_stream_info(mkv, logger)
    if not info:
        raise ValueError('Could not get stream info for extraction.')
    tracks, specs = ([], [])
    for tr in info.get('tracks', []):
        tid = tr['id']
        ttype = tr['type']
        lang = tr.get('properties', {}).get('language', 'und')
        name = tr.get('properties', {}).get('track_name', '')
        want = all_tracks or (audio and ttype == 'audio') or (subs and ttype == 'subtitles') or (ttype == 'video' and all_tracks)
        if not want:
            continue
        codec = tr.get('properties', {}).get('codec_id', '')
        ext = _ext_for_track(ttype, codec)
        out = Path(temp_dir) / f'{role}_track_{Path(mkv).stem}_{tid}.{ext}'
        tracks.append({'id': tid, 'type': ttype, 'lang': lang, 'name': name, 'path': str(out), 'codec_id': codec})
        specs.append(f'{tid}:{out}')
    if specs:
        run_command(['mkvextract', str(mkv), 'tracks'] + specs, logger)
    return tracks

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

def rename_chapters_xml(ref_mkv: str, temp_dir: str, logger, shift_ms: int=0) -> Optional[str]:
    out = run_command(['mkvextract', str(ref_mkv), 'chapters', '-'], logger)
    if not out or not out.strip():
        _log(logger, 'No chapters found to rename.')
        return None
    try:
        if out.startswith('\ufeff'):
            out = out[1:]
        root = ET.fromstring(out)
        for i, atom in enumerate(root.findall('.//ChapterAtom'), 1):
            disp = atom.find('ChapterDisplay')
            if disp is not None:
                atom.remove(disp)
            nd = ET.SubElement(atom, 'ChapterDisplay')
            ET.SubElement(nd, 'ChapterString').text = f'Chapter {i:02d}'
            ET.SubElement(nd, 'ChapterLanguage').text = 'und'
        path = Path(temp_dir) / f'{Path(ref_mkv).stem}_chapters_mod.xml'
        try:
            shift_ns = int(shift_ms) * 1000000

            def _parse_hhmmss_ns(t: str):
                t = t.strip()
                hh, mm, rest = t.split(':')
                if '.' in rest:
                    ss, frac = rest.split('.')
                    frac = (frac + '000000000')[:9]
                else:
                    ss, frac = (rest, '000000000')
                total_ns = (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000000000 + int(frac)
                return total_ns

            def _fmt_ns(total_ns: int):
                if total_ns < 0:
                    total_ns = 0
                ns = total_ns % 1000000000
                total_s = total_ns // 1000000000
                hh2 = total_s // 3600
                mm2 = total_s % 3600 // 60
                ss2 = total_s % 60
                return f'{hh2:02d}:{mm2:02d}:{ss2:02d}.{ns:09d}'
            for atom in root.findall('.//ChapterAtom'):
                for tag in ('ChapterTimeStart', 'ChapterTimeEnd'):
                    node = atom.find(tag)
                    if node is not None and node.text:
                        total_ns = _parse_hhmmss_ns(node.text)
                        total_ns += shift_ns
                        node.text = _fmt_ns(total_ns)
        except Exception as _e:
            _log(logger, f'[WARN] Chapter time shift failed: {_e}')
        if CONFIG.get('chapter_snap_verbose', False):
            _log(logger, '[Chapters] Pre-snap audit: verbose enabled')
        try:
            _log(logger, '[Chapters] Snap: enabled=%s mode=%s thr=%sms starts_only=%s' % (CONFIG.get('snap_chapters'), CONFIG.get('snap_mode'), CONFIG.get('snap_threshold_ms'), CONFIG.get('snap_starts_only')))
            if CONFIG.get('snap_chapters', False):
                kfs = _probe_keyframes_ns(ref_mkv, shift_ms, logger)
                if not kfs:
                    _log(logger, '[Chapters] Snap skipped: no keyframes found')
                sidecar = str(Path(temp_dir) / 'chapters_snapmap.json')
                _snap_chapter_times_inplace(root, kfs, bool(CONFIG.get('snap_starts_only', True)), str(CONFIG.get('snap_mode', 'previous')), int(CONFIG.get('snap_threshold_ms', 250)), logger, sidecar, int(shift_ms))
                _log(logger, f'[Chapters] Snap sidecar path: {sidecar}') if CONFIG.get('chapter_snap_verbose', False) else None
                try:
                    import json as _json, bisect as _bis
                    thr_ns = int(CONFIG.get('snap_threshold_ms', 250)) * 1000000
                    mode_ = str(CONFIG.get('snap_mode', 'previous'))
                    with open(sidecar, 'r', encoding='utf-8') as _f:
                        _data = _json.load(_f)
                    recs = _data.get('chapters', [])
                    moved = 0
                    on_kf = 0
                    near_nochange = 0
                    too_far = 0
                    deltas_ms = []

                    def _pick_candidate(ts_ns: int) -> int:
                        if not kfs:
                            return ts_ns
                        i = _bis.bisect_right(kfs, ts_ns)
                        prev_kf = kfs[i - 1] if i > 0 else kfs[0]
                        if mode_ == 'nearest':
                            next_kf = kfs[i] if i < len(kfs) else kfs[-1]
                            if abs(next_kf - ts_ns) <= abs(prev_kf - ts_ns):
                                return next_kf
                        return prev_kf
                    for r in recs:
                        d = int(r.get('delta_start_ns', 0) or 0)
                        if d != 0:
                            moved += 1
                            deltas_ms.append(int(round(d / 1000000)))
                        else:
                            orig_ns = int(r.get('shifted_start_ns', 0) or 0)
                            cand = _pick_candidate(orig_ns)
                            dist = abs(cand - orig_ns)
                            if dist == 0:
                                on_kf += 1
                            elif dist <= thr_ns:
                                near_nochange += 1
                            else:
                                too_far += 1
                    parts = [f'moved={moved}', f'on_kf={on_kf}', f'too_far={too_far}']
                    if near_nochange:
                        parts.append(f'near={near_nochange}')
                    if deltas_ms:
                        parts.append(f'min={min(deltas_ms)}ms max={max(deltas_ms)}ms')
                    _log(logger, '[Chapters] Snap result: ' + ', '.join(parts) + f" (kfs={len(kfs)}, mode={mode_}, thr={int(CONFIG.get('snap_threshold_ms', 250))}ms)")
                    if moved == 0:
                        _log(logger, '[Chapters] Snap note: no chapter starts changed')
                except Exception as _e:
                    _log(logger, f'[ERROR] Snap classification failed: {_e}')
                try:
                    import json as _json
                    thr_ns = int(CONFIG.get('snap_threshold_ms', 250)) * 1000000
                    mode_ = str(CONFIG.get('snap_mode', 'previous'))
                    with open(sidecar, 'r', encoding='utf-8') as _f:
                        _data = _json.load(_f)
                    recs = _data.get('chapters', [])
                    moved = 0
                    on_kf = 0
                    near_nochange = 0
                    too_far = 0
                    deltas_ms = []
                    import bisect as _bis

                    def _pick_candidate(ts_ns: int) -> int:
                        if not kfs:
                            return ts_ns
                        i = _bis.bisect_right(kfs, ts_ns)
                        prev_kf = kfs[i - 1] if i > 0 else kfs[0]
                        if mode_ == 'nearest':
                            next_kf = kfs[i] if i < len(kfs) else kfs[-1]
                            if abs(next_kf - ts_ns) <= abs(prev_kf - ts_ns):
                                return next_kf
                        return prev_kf
                    for r in recs:
                        d = int(r.get('delta_start_ns', 0) or 0)
                        if d != 0:
                            moved += 1
                            deltas_ms.append(int(round(d / 1000000)))
                        else:
                            orig_ns = int(r.get('shifted_start_ns', 0) or 0)
                            cand = _pick_candidate(orig_ns)
                            dist = abs(cand - orig_ns)
                            if dist == 0:
                                on_kf += 1
                            elif dist <= thr_ns:
                                near_nochange += 1
                            else:
                                too_far += 1
                    parts = [f'moved={moved}', f'on_kf={on_kf}', f'too_far={too_far}']
                    if near_nochange:
                        parts.append(f'near_nochange={near_nochange}')
                    if deltas_ms:
                        parts.append(f'min={min(deltas_ms)}ms max={max(deltas_ms)}ms')
                    _log(logger, '[Chapters] Snap classify: ' + ', '.join(parts) + f" (mode={mode_}, thr={int(CONFIG.get('snap_threshold_ms', 250))}ms)")
                    if CONFIG.get('chapter_snap_verbose', False) and near_nochange:
                        _log(logger, '[Chapters] note: near_nochange > 0 means start was inside threshold but unchanged (edge case).')
                except Exception as _e:
                    _log(logger, f'[WARN] Snap classification failed: {_e}')
                try:
                    import json as _json
                    with open(sidecar, 'r', encoding='utf-8') as _f:
                        _data = _json.load(_f)
                    _moved = []
                    for _rec in _data.get('chapters', []):
                        d = _rec.get('delta_start_ns', 0)
                        if d:
                            _moved.append(int(round(d / 1000000)))
                    if _moved:
                        _log(logger, f'[Chapters] Snap summary: moved {len(_moved)} starts; min={min(_moved)}ms max={max(_moved)}ms')
                    else:
                        _log(logger, '[Chapters] Snap summary: no starts moved')
                except Exception as _e:
                    _log(logger, f'[Chapters] Snap summary unavailable: {_e}')
            else:
                _log(logger, '[Chapters] Snap: disabled')
        except Exception as _e:
            _log(logger, f'[WARN] Chapter keyframe snapping skipped: {_e}')
        _normalize_chapter_end_times(root, logger)
        ET.ElementTree(root).write(path, encoding='UTF-8', xml_declaration=True)
        _log(logger, f'Chapters XML written: {path}')
        return str(path)
    except Exception as e:
        _log(logger, f'Chapter XML rewrite failed: {e}')
        return None

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

def run_audio_correlation_workflow(file1: str, file2: str, logger, chunks: int, chunk_dur: int, match_lang: Optional[str], role_tag: str):
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

def build_mkvmerge_tokens(plan_json, output_file, chapters_xml_path, attachments, track_order_str=None):
    """Return JSON array-of-strings for mkvmerge @opts.json; each input wrapped in parentheses;
       add --compression 0:none for each input; optional dialnorm removal; explicit --track-order.
       Set languages for all tracks; compute default flags:
         - Video: first/only video = yes
         - Audio: first audio = yes; others = no
         - Subtitles: Signs/Songs = yes; else if NO English audio -> first subtitle = yes; others = no
    """
    tokens: List[str] = ['--output', str(output_file)]
    if chapters_xml_path:
        tokens += ['--chapters', str(chapters_xml_path)]
    delays = plan_json.get('delays', {})
    plan = list(plan_json.get('plan', []))
    audio_langs = [(t.get('lang') or '').lower() for t in plan if t.get('type') == 'audio']
    has_english_audio = any((l in ('en', 'eng') for l in audio_langs))
    video_indices = [i for i, t in enumerate(plan) if t.get('type') == 'video']
    audio_indices = [i for i, t in enumerate(plan) if t.get('type') == 'audio']
    sub_indices = [i for i, t in enumerate(plan) if t.get('type') == 'subtitles']
    first_video_idx = video_indices[0] if video_indices else None
    first_audio_idx = audio_indices[0] if audio_indices else None
    default_sub_idx = None
    if CONFIG.get('first_sub_default', True):

        def is_signs_name(name: str) -> bool:
            low = (name or '').lower()
            return any((k in low for k in SIGNS_KEYS))
        for i in sub_indices:
            if is_signs_name(plan[i].get('name', '')):
                default_sub_idx = i
                break
        if default_sub_idx is None and (not has_english_audio) and sub_indices:
            default_sub_idx = sub_indices[0]
    track_order_indices: List[str] = []
    input_idx = 0
    for idx, trk in enumerate(plan):
        default_flag = None
        if trk.get('type') == 'video':
            default_flag = idx == first_video_idx
        elif trk.get('type') == 'audio':
            default_flag = idx == first_audio_idx
        elif trk.get('type') == 'subtitles':
            default_flag = idx == default_sub_idx
        perfile = []
        perfile += _tokens_for_track(trk, trk.get('from_group'), delays, default_flag=default_flag)
        perfile += ['--compression', '0:none']
        if CONFIG.get('apply_dialog_norm_gain') and trk.get('type') == 'audio':
            codec = (trk.get('codec_id') or '').upper()
            if 'AC-3' in codec or 'E-AC-3' in codec or 'A_AC3' in codec or ('A_EAC3' in codec):
                perfile += ['--remove-dialog-normalization-gain', '0']
        tokens += perfile + ['(', str(trk['src']), ')']
        track_order_indices.append(f'{input_idx}:0')
        input_idx += 1
    for a in attachments or []:
        tokens += ['--attach-file', str(a)]
    final_track_order = track_order_str or ','.join(track_order_indices)
    if final_track_order:
        tokens += ['--track-order', final_track_order]
    return tokens

def write_mkvmerge_json_options(tokens: List[str], json_path: Path, logger) -> str:
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    raw_json = json.dumps(tokens, ensure_ascii=False)
    json_path.write_text(raw_json, encoding='utf-8')
    pretty_path = json_path.parent / 'opts.pretty.txt'
    pretty_txt = ' \\n  '.join(tokens)
    pretty_path.write_text(pretty_txt, encoding='utf-8')
    _log(logger, f'@JSON options written: {json_path}')
    if CONFIG.get('log_show_options_pretty', False):
        _log(logger, '[OPTIONS] mkvmerge tokens (pretty):')
        for line in pretty_txt.splitlines():
            _log(logger, '  ' + line)
    if CONFIG.get('log_show_options_json', False):
        _log(logger, '[OPTIONS] mkvmerge tokens (raw JSON array):')
        for i in range(0, len(raw_json), 512):
            _log(logger, raw_json[i:i + 512])
    return str(json_path)

def run_mkvmerge_with_json(json_path: str, logger) -> bool:
    out = run_command(['mkvmerge', f'@{json_path}'], logger)
    return out is not None

def format_delay_ms(ms):
    if ms is None:
        return '—'
    ms = int(ms)
    sign = '-' if ms < 0 else ''
    return f'{sign}{abs(ms)} ms'

def run_videodiff(ref: str, target: str, logger, videodiff_path: Path | str) -> Tuple[int, float]:
    """Run videodiff once and parse ONLY the final '[Result] - (itsoffset|ss): X.XXXXXs, ... error: YYY' line.
       Returns (delay_ms, error_value).  Mapping: itsoffset -> +ms, ss -> -ms.
    """
    vp = str(videodiff_path) if videodiff_path else ''
    if not vp:
        vp = shutil.which('videodiff') or str(SCRIPT_DIR / 'videodiff')
    vp_path = Path(vp)
    if not vp_path.exists():
        raise FileNotFoundError(f'videodiff not found at {vp_path}')
    _log(logger, f'videodiff path: {vp_path}')
    out = run_command([str(vp_path), str(ref), str(target)], logger)
    if not out:
        raise RuntimeError('videodiff produced no output')
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    last_line = ''
    for ln in reversed(lines):
        if '[Result]' in ln and ('ss:' in ln or 'itsoffset:' in ln):
            last_line = ln
            break
    if not last_line:
        last_line = lines[-1] if lines else ''
    m = re.search('(itsoffset|ss)\\s*:\\s*(-?\\d+(?:\\.\\d+)?)s.*?error:\\s*([0-9.]+)', last_line, flags=re.IGNORECASE)
    if not m:
        raise RuntimeError(f"videodiff: could not parse final line: '{last_line}'")
    kind, sval, err = m.groups()
    seconds = float(sval)
    delay_ms = int(round(seconds * 1000))
    if kind.lower() == 'ss':
        delay_ms = -delay_ms
    err_val = float(err)
    _log(logger, f'[VideoDiff] final -> {kind.lower()} {seconds:.5f}s, error {err_val:.2f}  =>  delay {delay_ms:+} ms')
    return (delay_ms, err_val)

def merge_job(ref_file: str, sec_file: Optional[str], ter_file: Optional[str], out_dir: str, logger, videodiff_path: Path):
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    delays = {'secondary_ms': 0, 'tertiary_ms': 0}
    set_status('Analyzing…')
    set_progress(0.0)
    delay_sec = None
    delay_ter = None
    if sec_file:
        if CONFIG['analysis_mode'] == 'VideoDiff':
            delay_sec, err_sec = run_videodiff(ref_file, sec_file, logger, videodiff_path)
            if err_sec < float(CONFIG.get('videodiff_error_min', 0.0)) or err_sec > float(CONFIG.get('videodiff_error_max', 100.0)):
                raise RuntimeError(f"VideoDiff confidence out of bounds: error={err_sec:.2f} (allowed {CONFIG.get('videodiff_error_min')}..{CONFIG.get('videodiff_error_max')})")
        else:
            lang = 'jpn' if CONFIG['match_jpn_secondary'] else None
            results = run_audio_correlation_workflow(ref_file, sec_file, logger, CONFIG['scan_chunk_count'], CONFIG['scan_chunk_duration'], lang, role_tag='sec')
            best = best_from_results(results, CONFIG['min_match_pct'])
            if not best:
                raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
            delay_sec = best['delay']
        _log(logger, f'Secondary delay: {delay_sec} ms')
    if ter_file:
        if CONFIG['analysis_mode'] == 'VideoDiff':
            delay_ter, err_ter = run_videodiff(ref_file, ter_file, logger, videodiff_path)
            if err_ter < float(CONFIG.get('videodiff_error_min', 0.0)) or err_ter > float(CONFIG.get('videodiff_error_max', 100.0)):
                raise RuntimeError(f"VideoDiff confidence out of bounds: error={err_ter:.2f} (allowed {CONFIG.get('videodiff_error_min')}..{CONFIG.get('videodiff_error_max')})")
        else:
            lang = 'jpn' if CONFIG['match_jpn_tertiary'] else None
            results = run_audio_correlation_workflow(ref_file, ter_file, logger, CONFIG['scan_chunk_count'], CONFIG['scan_chunk_duration'], lang, role_tag='ter')
            best = best_from_results(results, CONFIG['min_match_pct'])
            if not best:
                raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
            delay_ter = best['delay']
        _log(logger, f'Tertiary delay: {delay_ter} ms')
    if dpg.does_item_exist('sec_delay_val'):
        dpg.set_value('sec_delay_val', format_delay_ms(delay_sec))
    if dpg.does_item_exist('ter_delay_val'):
        dpg.set_value('ter_delay_val', format_delay_ms(delay_ter))
    if CONFIG['workflow'] == 'Analyze Only':
        set_status('Analysis complete (no merge).')
        set_progress(1.0)
        return {'status': 'Analyzed', 'delay_sec': delay_sec, 'delay_ter': delay_ter}
    delays['secondary_ms'] = int(delay_sec or 0)
    delays['tertiary_ms'] = int(delay_ter or 0)
    present = [0]
    if sec_file is not None and delay_sec is not None:
        present.append(int(delay_sec))
    if ter_file is not None and delay_ter is not None:
        present.append(int(delay_ter))
    min_delay = min(present) if present else 0
    global_shift = -min_delay if min_delay < 0 else 0
    delays['_global_shift'] = int(global_shift)
    _log(logger, f'[Delay] Raw group delays (ms): ref=0, sec={int(delay_sec or 0)}, ter={int(delay_ter or 0)}')
    _log(logger, f'[Delay] Lossless global shift: +{int(global_shift)} ms')
    job_temp = Path(CONFIG['temp_root']) / f'job_{Path(ref_file).stem}_{int(time.time())}'
    job_temp.mkdir(parents=True, exist_ok=True)
    merge_ok = False
    try:
        set_status('Preparing merge…')
        set_progress(0.05)
        chapters_xml = None
        if CONFIG['rename_chapters']:
            chapters_xml = rename_chapters_xml(ref_file, str(job_temp), logger, shift_ms=int(delays.get('_global_shift', 0)))
        ref_tracks = extract_tracks(ref_file, str(job_temp), logger, role='ref', all_tracks=True)
        sec_tracks = extract_tracks(sec_file, str(job_temp), logger, role='sec', audio=True, subs=True) if sec_file else []
        ter_tracks = extract_tracks(ter_file, str(job_temp), logger, role='ter', audio=False, subs=True) if ter_file else []
        ter_atts = extract_attachments(ter_file, str(job_temp), logger, role='ter') if ter_file else []
        if CONFIG['swap_subtitle_order'] and sec_tracks:
            only_subs = [t for t in sec_tracks if t['type'] == 'subtitles']
            if len(only_subs) >= 2:
                i0, i1 = (sec_tracks.index(only_subs[0]), sec_tracks.index(only_subs[1]))
                sec_tracks[i0], sec_tracks[i1] = (sec_tracks[i1], sec_tracks[i0])
        if not sec_tracks and (not ter_tracks):
            raise RuntimeError('No tracks to merge from Secondary/Tertiary.')
        plan = build_plan(ref_tracks, sec_tracks, ter_tracks, delays)
        out_file = str(Path(out_dir) / Path(ref_file).name)
        track_order_str, summary_lines = summarize_plan(plan, out_file, chapters_xml, ter_atts)
        for ln in summary_lines:
            _log(logger, ln)
        tokens = build_mkvmerge_tokens(plan, out_file, chapters_xml, ter_atts, track_order_str=track_order_str)
        json_opts = write_mkvmerge_json_options(tokens, job_temp / 'opts.json', logger)
        set_status('Merging…')
        set_progress(0.5)
        merge_ok = run_mkvmerge_with_json(json_opts, logger)
        if not merge_ok:
            raise RuntimeError('mkvmerge failed.')
        set_status('Merge complete.')
        set_progress(1.0)
        _log(logger, f'[OK] Output: {out_file}')
        return {'status': 'Merged', 'output': out_file, 'delay_sec': delay_sec, 'delay_ter': delay_ter}
    finally:
        if merge_ok or CONFIG['workflow'] == 'Analyze Only':
            try:
                shutil.rmtree(job_temp, ignore_errors=True)
            except Exception:
                pass

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

def _snap_chapter_times_inplace(root, keyframes_ns: list[int], starts_only: bool, mode: str, threshold_ms: int, logger, sidecar_path: str | None, global_shift_ms: int):
    """Modify ChapterTimeStart/End in-place to keyframes per options. Write a sidecar JSON for revert."""

    def _parse_ns(t: str) -> int:
        t = t.strip()
        hh, mm, rest = t.split(':')
        if '.' in rest:
            ss, frac = rest.split('.')
            frac = (frac + '000000000')[:9]
        else:
            ss, frac = (rest, '000000000')
        return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000000000 + int(frac)

    def _fmt_ns(total_ns: int) -> str:
        if total_ns < 0:
            total_ns = 0
        ns = total_ns % 1000000000
        total_s = total_ns // 1000000000
        hh2 = total_s // 3600
        mm2 = total_s % 3600 // 60
        ss2 = total_s % 60
        return f'{hh2:02d}:{mm2:02d}:{ss2:02d}.{ns:09d}'
    threshold_ns = max(0, int(threshold_ms)) * 1000000
    changed = 0
    records = []

    def _pick(ts_ns: int) -> tuple[int, int]:
        """Return (snapped_ns, delta_ns)."""
        if not keyframes_ns:
            return (ts_ns, 0)
        i = bisect.bisect_right(keyframes_ns, ts_ns)
        prev_kf = keyframes_ns[i - 1] if i > 0 else keyframes_ns[0]
        if mode == 'previous':
            snap = prev_kf if prev_kf <= ts_ns else keyframes_ns[0]
        else:
            next_kf = keyframes_ns[i] if i < len(keyframes_ns) else keyframes_ns[-1]
            snap = prev_kf if abs(prev_kf - ts_ns) <= abs(next_kf - ts_ns) else next_kf
        if abs(snap - ts_ns) > threshold_ns:
            return (ts_ns, 0)
        return (snap, snap - ts_ns)
    atoms = list(root.findall('.//ChapterAtom'))
    for idx, atom in enumerate(atoms, start=1):
        st = atom.find('ChapterTimeStart')
        en = atom.find('ChapterTimeEnd')
        rec = {'index': idx}
        if st is not None and st.text:
            orig = _parse_ns(st.text)
            snap = orig
            if keyframes_ns:
                snap, delta = _pick(orig)
            else:
                delta = 0
            rec['shifted_start_ns'] = orig
            rec['snapped_start_ns'] = snap
            rec['delta_start_ns'] = delta
            if delta != 0:
                st.text = _fmt_ns(snap)
                changed += 1
            if not starts_only and en is not None and en.text:
                e_orig = _parse_ns(en.text)
                e_snap, e_delta = _pick(e_orig)
                rec['shifted_end_ns'] = e_orig
                rec['snapped_end_ns'] = e_snap
                rec['delta_end_ns'] = e_delta
                if e_delta != 0:
                    en.text = _fmt_ns(e_snap)
                    changed += 1
            if en is not None and en.text:
                try:
                    e_now = _parse_ns(en.text)
                    s_now = _parse_ns(st.text)
                    if e_now <= s_now:
                        en.text = _fmt_ns(s_now + 1000000)
                except Exception:
                    pass
        records.append(rec)
    _log(logger, f'[Chapters] Snapped chapters: {changed}/{len(atoms)} (mode={mode}, threshold={threshold_ms} ms, starts_only={starts_only})')
    if sidecar_path:
        try:
            with open(sidecar_path, 'w', encoding='utf-8') as f:
                json.dump({'global_shift_ms': int(global_shift_ms), 'mode': mode, 'threshold_ms': int(threshold_ms), 'starts_only': bool(starts_only), 'chapters': records}, f, indent=2)
            _log(logger, f'[Chapters] Sidecar written: {sidecar_path}')
        except Exception as e:
            _log(logger, f'[WARN] Sidecar write failed: {e}')

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
        dpg.add_text('Make Secondary/Tertiary match Reference — GUI (v20 pipeline)')
        dpg.add_separator()
        dpg.add_text('Inputs')
        with dpg.group(horizontal=True):
            dpg.add_button(label='Storage…', callback=lambda: dpg.configure_item('storage_modal', show=True))
            dpg.add_button(label='Analysis Settings…', callback=lambda: dpg.configure_item('analysis_modal', show=True))
            dpg.add_button(label='Global Options…', callback=lambda: dpg.configure_item('global_modal', show=True))
            dpg.add_button(label='Save Settings', callback=ui_save_settings)
            dpg.add_button(label='Load Settings', callback=on_click_load_settings)
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

