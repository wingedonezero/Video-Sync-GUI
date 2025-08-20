# Moved from video_sync_gui.py (Phase A, move-only)
from __future__ import annotations
from vsg.logbus import LOG_Q, _log
import json
from pathlib import Path
from datetime import datetime
import dearpygui.dearpygui as dpg
import logging, queue, re, os, shutil, subprocess, sys
from typing import Any, Dict
SCRIPT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_PATH = SCRIPT_DIR / 'settings_gui.json'
CONFIG = {'output_folder': str(SCRIPT_DIR / 'sync_output'), 'temp_root': str(SCRIPT_DIR / 'temp_work'), 'analysis_mode': 'Audio Correlation', 'workflow': 'Analyze & Merge', 'scan_chunk_count': 10, 'scan_chunk_duration': 15, 'swap_subtitle_order': False, 'rename_chapters': False, 'match_jpn_secondary': True, 'match_jpn_tertiary': True, 'min_match_pct': 5.0, 'apply_dialog_norm_gain': False, 'videodiff_path': '', 'first_sub_default': True, 'videodiff_error_min': 0.0, 'videodiff_error_max': 100.0, 'snap_chapters': False, 'snap_mode': 'previous', 'snap_threshold_ms': 250, 'snap_starts_only': True, 'chapter_snap_verbose': False, 'chapter_snap_compact': True, 'log_compact': True, 'log_tail_lines': 0, 'log_error_tail': 20, 'log_progress_step': 20, 'log_show_options_pretty': False, 'log_show_options_json': False, 'log_autoscroll': True}

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
            _log('Settings initialized/updated with defaults.')
        except Exception as e:
            _log(f'Failed to save settings: {e}')
try:
    load_settings()
except Exception:
    pass



def save_settings():
    try:
        SETTINGS_PATH.write_text(json.dumps(CONFIG, indent=2), encoding='utf-8')
        _log('Settings saved.')
    except Exception as e:
        _log(f'Failed to save settings: {e}')
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
        _log('Settings applied to UI.')
    except Exception as e:
        _log(f'[WARN] apply_settings_to_ui failed: {e}')



def pull_ui_to_settings():
    try:
        for key, tag in _UI_BIND.items():
            if dpg.does_item_exist(tag):
                CONFIG[key] = dpg.get_value(tag)
        save_settings()
        _log('Settings saved from UI.')
    except Exception as e:
        _log(f'[ERROR] pull_ui_to_settings failed: {e}')



def sync_config_from_ui():
    """Pull current values from UI into CONFIG; ensure folders exist."""
    if not dpg.does_item_exist('out_input'):
        return
    CONFIG.update({'output_folder': dpg.get_value('out_input') or CONFIG.get('output_folder', str(SCRIPT_DIR / 'sync_output')), 'temp_root': dpg.get_value('temp_input') or CONFIG.get('temp_root', str(SCRIPT_DIR / 'temp_work')), 'analysis_mode': dpg.get_value('mode_combo') or CONFIG.get('analysis_mode', 'Audio Correlation'), 'workflow': dpg.get_value('workflow_combo') or CONFIG.get('workflow', 'Analyze & Merge'), 'scan_chunk_count': int(dpg.get_value('chunks_input')) if dpg.does_item_exist('chunks_input') else CONFIG.get('scan_chunk_count', 10), 'scan_chunk_duration': int(dpg.get_value('chunkdur_input')) if dpg.does_item_exist('chunkdur_input') else CONFIG.get('scan_chunk_duration', 15), 'min_match_pct': float(dpg.get_value('thresh_input')) if dpg.does_item_exist('thresh_input') else CONFIG.get('min_match_pct', 5.0), 'videodiff_error_min': float(dpg.get_value('vd_err_min')) if dpg.does_item_exist('vd_err_min') else CONFIG.get('videodiff_error_min', 0.0), 'videodiff_error_max': float(dpg.get_value('vd_err_max')) if dpg.does_item_exist('vd_err_max') else CONFIG.get('videodiff_error_max', 100.0), 'swap_subtitle_order': bool(dpg.get_value('swapsec_chk')) if dpg.does_item_exist('swapsec_chk') else CONFIG.get('swap_subtitle_order', False), 'rename_chapters': bool(dpg.get_value('chaprename_chk')) if dpg.does_item_exist('chaprename_chk') else CONFIG.get('rename_chapters', False), 'match_jpn_secondary': bool(dpg.get_value('jpnsec_chk')) if dpg.does_item_exist('jpnsec_chk') else CONFIG.get('match_jpn_secondary', True), 'match_jpn_tertiary': bool(dpg.get_value('jpnter_chk')) if dpg.does_item_exist('jpnter_chk') else CONFIG.get('match_jpn_tertiary', True), 'apply_dialog_norm_gain': bool(dpg.get_value('dialnorm_chk')) if dpg.does_item_exist('dialnorm_chk') else CONFIG.get('apply_dialog_norm_gain', False), 'first_sub_default': bool(dpg.get_value('firstsubdef_chk')) if dpg.does_item_exist('firstsubdef_chk') else CONFIG.get('first_sub_default', True), 'videodiff_path': dpg.get_value('vdiff_input') if dpg.does_item_exist('vdiff_input') else CONFIG.get('videodiff_path', ''), 'snap_chapters': bool(dpg.get_value('snap_chapters_chk')) if dpg.does_item_exist('snap_chapters_chk') else CONFIG.get('snap_chapters', False), 'snap_mode': dpg.get_value('snap_mode_opt') if dpg.does_item_exist('snap_mode_opt') else CONFIG.get('snap_mode', 'previous'), 'snap_threshold_ms': int(dpg.get_value('snap_threshold_ms')) if dpg.does_item_exist('snap_threshold_ms') else CONFIG.get('snap_threshold_ms', 250), 'snap_starts_only': bool(dpg.get_value('snap_starts_only_chk')) if dpg.does_item_exist('snap_starts_only_chk') else CONFIG.get('snap_starts_only', True)})
    Path(CONFIG['output_folder']).mkdir(parents=True, exist_ok=True)
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)



