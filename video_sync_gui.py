# === Thin GUI: import all non-UI logic from vsg.* ===
# === end Thin GUI import block ===

from vsg.analysis.videodiff import format_delay_ms
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job
from vsg.logbus import LOG_Q, _log, pump_logs
# === vsg direct imports (modularized) ===
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings
from vsg.tools import find_required_tools, run_command
from vsg.ui.options_modal import show_options_modal

# === end vsg direct imports ===

# !/usr/bin/env python3
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
import queue
import shutil
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import librosa
import numpy as np
import scipy.signal
# --- purge inline settings row created by older builds ---
def _remove_inline_settings_row():
    try:
        # These were the tags used for the old header controls
        for tag in ('mode_combo', 'workflow_combo', 'chunks_input', 'chunkdur_input', 'thresh_input',
                    'vd_err_min', 'vd_err_max', 'out_input', 'temp_input'):
            if dpg.does_item_exist(tag):
                try: dpg.delete_item(tag)
                except Exception: pass
    except Exception:
        pass
try:
    dpg.set_frame_callback(20, _remove_inline_settings_row)
except Exception:
    pass
# --- end purge ---

import dearpygui.dearpygui as dpg

UI_FONT_ID = None
INPUT_FONT_ID = None


def load_fonts():
    """Load fonts and bind a regular 18pt UI font as the global default (not bold)."""
    global UI_FONT_ID, INPUT_FONT_ID
    try:
        with dpg.font_registry():
            import os
            regular_candidates = ('/usr/share/fonts/TTF/DejaVuSans.ttf',
                                  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                                  '/usr/share/fonts/TTF/LiberationSans-Regular.ttf',
                                  '/usr/share/fonts/liberation/LiberationSans-Regular.ttf',
                                  '/usr/share/fonts/TTF/NotoSans-Regular.ttf',
                                  '/usr/share/fonts/noto/NotoSans-Regular.ttf')
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
CONFIG = {'output_folder': str(SCRIPT_DIR / 'sync_output'), 'temp_root': str(SCRIPT_DIR / 'temp_work'),
          'analysis_mode': 'Audio Correlation', 'workflow': 'Analyze & Merge', 'scan_chunk_count': 10,
          'scan_chunk_duration': 15, 'swap_subtitle_order': False, 'rename_chapters': False,
          'match_jpn_secondary': True, 'match_jpn_tertiary': True, 'min_match_pct': 5.0,
          'apply_dialog_norm_gain': False, 'videodiff_path': '', 'first_sub_default': True, 'videodiff_error_min': 0.0,
          'videodiff_error_max': 100.0, 'snap_chapters': False, 'snap_mode': 'previous', 'snap_threshold_ms': 250,
          'snap_starts_only': True, 'chapter_snap_verbose': False, 'chapter_snap_compact': True, 'log_compact': True,
          'log_tail_lines': 0, 'log_error_tail': 20, 'log_progress_step': 20, 'log_show_options_pretty': False,
          'log_show_options_json': False, 'log_autoscroll': True}
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


_UI_BIND = {'temp_root': 'temp_input', 'output_folder': 'out_input', 'videodiff_path': 'vdiff_input',
            'workflow': 'workflow_combo', 'analysis_mode': 'mode_combo', 'swap_subtitle_order': 'swapsec_chk',
            'rename_chapters': 'chaprename_chk', 'match_jpn_secondary': 'jpnsec_chk',
            'match_jpn_tertiary': 'jpnter_chk', 'apply_dialog_norm_gain': 'dialnorm_chk',
            'first_sub_default': 'firstsubdef_chk', 'snap_chapters': 'snap_chapters_chk', 'snap_mode': 'snap_mode_opt',
            'snap_starts_only': 'snap_starts_only_chk', 'log_compact': 'log_compact_chk',
            'log_autoscroll': 'log_autoscroll_chk'}


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
    """Only collect file paths from the main inputs. All other options come from Preferences/CONFIG."""
    try:
        if dpg.does_item_exist('ref_input'):
            CONFIG['ref_path'] = dpg.get_value('ref_input') or CONFIG.get('ref_path','')
        if dpg.does_item_exist('sec_input'):
            CONFIG['sec_path'] = dpg.get_value('sec_input') or CONFIG.get('sec_path','')
        if dpg.does_item_exist('ter_input'):
            CONFIG['ter_path'] = dpg.get_value('ter_input') or CONFIG.get('ter_path','')
    except Exception:
        pass
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
            _log(log,
                 f"Delays: Secondary={format_delay_ms(res.get('delay_sec'))}, Tertiary={format_delay_ms(res.get('delay_ter'))}")
            _log(log, '=== Job complete ===')
        except Exception as e:
            results.append({'name': Path(r).name, 'status': 'Failed', 'error': str(e)})
            _log(log, f'[FAILED] {e}')
            _log(log, '=== Job complete (failed) ===')
        set_progress(i / max(1, len(jobs)))
    LOG_Q.put('--- Summary ---')
    for r in results:
        if r.get('status') == 'Merged':
            LOG_Q.put(
                f"{r['name']}: Merged -> {r.get('output')} (Sec {format_delay_ms(r.get('delay_sec'))}, Ter {format_delay_ms(r.get('delay_ter'))})")
        elif r.get('status') == 'Analyzed':
            LOG_Q.put(
                f"{r['name']}: Analyzed (Sec {format_delay_ms(r.get('delay_sec'))}, Ter {format_delay_ms(r.get('delay_ter'))})")
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
            _candidates = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf',
                           '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                           '/usr/share/fonts/liberation/LiberationSans-Regular.ttf',
                           '/usr/share/fonts/TTF/LiberationSans-Regular.ttf',
                           '/usr/share/fonts/truetype/freefont/FreeSans.ttf', '/usr/share/fonts/TTF/FreeSans.ttf',
                           '/usr/share/fonts/noto/NotoSans-Regular.ttf', '/usr/share/fonts/TTF/NotoSans-Regular.ttf',
                           '/usr/share/fonts/cantarell/Cantarell-Regular.ttf',
                           '/usr/share/fonts/cantarell/Cantarell-VF.otf']
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
            # (old header buttons removed)
            with dpg.group(horizontal=True):
                dpg.add_button(label='Storage…', callback=lambda: dpg.configure_item('storage_modal', show=True))
                               callback=lambda: dpg.configure_item('analysis_modal', show=True))
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
            dpg.add_text('Actions')
            with dpg.group(horizontal=True):
                dpg.add_button(tag='btn_analyze_only', label='Analyze Only', callback=do_analyze_only, width=150,
                               height=36)
                _bind_control_theme('btn_analyze_only')
                dpg.add_button(tag='btn_analyze_merge', label='Analyze & Merge', callback=do_analyze_and_merge,
                               width=170, height=36)
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
            with dpg.file_dialog(tag='file_dialog_ref', label='Pick Reference', callback=on_pick_file,
                                 user_data='ref_input', width=700, height=400, directory_selector=False, show=False):
                dpg.add_file_extension('.*', color=(150, 255, 150, 255))
            with dpg.file_dialog(tag='file_dialog_sec', label='Pick Secondary', callback=on_pick_file,
                                 user_data='sec_input', width=700, height=400, directory_selector=False, show=False):
                dpg.add_file_extension('.*', color=(150, 255, 150, 255))
            with dpg.file_dialog(tag='file_dialog_ter', label='Pick Tertiary', callback=on_pick_file,
                                 user_data='ter_input', width=700, height=400, directory_selector=False, show=False):
                dpg.add_file_extension('.*', color=(150, 255, 150, 255))
            with dpg.file_dialog(tag='dir_dialog_out', label='Pick Output Directory', callback=on_pick_dir,
                                 user_data='out_input', width=700, height=400, directory_selector=True, show=False):
                pass
            with dpg.file_dialog(tag='dir_dialog_temp', label='Pick Temp Directory', callback=on_pick_dir,
                                 user_data='temp_input', width=700, height=400, directory_selector=True, show=False):
                pass
            with dpg.file_dialog(tag='file_dialog_vdiff', label='Pick videodiff binary', callback=on_pick_file,
                                 user_data='vdiff_input', width=700, height=400, directory_selector=False, show=False):
                dpg.add_file_extension('.*', color=(150, 255, 150, 255))