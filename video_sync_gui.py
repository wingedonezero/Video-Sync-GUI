
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

import dearpygui.dearpygui as dpg
from vsg.appearance_helper import load_fonts_and_themes, apply_line_heights

from vsg.logbus import _log, LOG_Q, pump_logs
from vsg.settings import CONFIG, SETTINGS_PATH, load_settings, save_settings
from vsg.jobs.discover import discover_jobs
from vsg.jobs.merge_job import merge_job
from vsg.analysis.videodiff import run_videodiff, format_delay_ms
from vsg.analysis.audio_xcorr import run_audio_correlation_workflow, best_from_results
from vsg.ui.options_modal import show_options_modal


APP_NAME = "Video/Audio Sync & Merge"

# --- UI helpers ---
def set_status(msg: str) -> None:
    _log(msg)
    try:
        if dpg.does_item_exist("status_text"):
            dpg.set_value("status_text", msg)
    except Exception:
        pass

def set_progress(val: float) -> None:
    try:
        if dpg.does_item_exist("progress_bar"):
            dpg.set_value("progress_bar", max(0.0, min(1.0, float(val))))
    except Exception:
        pass

def on_pick_file(sender, app_data, user_data):
    try:
        tag = str(user_data)
        sel = app_data["file_path_name"]
        dpg.set_value(tag, sel)
    except Exception:
        pass

def on_pick_dir(sender, app_data, user_data):
    try:
        tag = str(user_data)
        sel = app_data["file_path_name"]
        dpg.set_value(tag, sel)
    except Exception:
        pass

def sync_config_from_ui():
    # Only paths; all other options come from Preferences modal / CONFIG json
    if dpg.does_item_exist("ref_input"):
        CONFIG["ref_path"] = dpg.get_value("ref_input") or CONFIG.get("ref_path", "")
    if dpg.does_item_exist("sec_input"):
        CONFIG["sec_path"] = dpg.get_value("sec_input") or CONFIG.get("sec_path", "")
    if dpg.does_item_exist("ter_input"):
        CONFIG["ter_path"] = dpg.get_value("ter_input") or CONFIG.get("ter_path", "")
    # Derive default folders if missing
    base = Path(__file__).resolve().parent
    out_root = CONFIG.get("output_folder") or str(base / "sync_output")
    temp_root = CONFIG.get("temp_root") or str(base / "temp_work")
    CONFIG["output_folder"] = out_root
    CONFIG["temp_root"] = temp_root
    Path(out_root).mkdir(parents=True, exist_ok=True)
    Path(temp_root).mkdir(parents=True, exist_ok=True)

# --- worker logic ---
RUNNING = False
RUN_LOCK = threading.Lock()

def _compute_delay_for_pair(ref_file: str, other_file: str, role: str, logger=None):
    if CONFIG.get("analysis_mode") == "VideoDiff":
        vdp = CONFIG.get("videodiff_path", "") or ""
        delay_ms, err = run_videodiff(ref_file, other_file, logger, vdp)
        emin = float(CONFIG.get("videodiff_error_min", 0.0))
        emax = float(CONFIG.get("videodiff_error_max", 100.0))
        _log(f"[{role}] VideoDiff result: delay={format_delay_ms(delay_ms)} error={err:.3f} (bounds {emin}..{emax})")
        if err < emin or err > emax:
            raise RuntimeError(f"[{role}] VideoDiff confidence {err:.3f} out of bounds {emin}..{emax}")
        return delay_ms
    else:
        lang = "jpn" if CONFIG.get("match_jpn_secondary") else None
        chunks = int(CONFIG.get("scan_chunk_count", 4))
        chunk_dur = int(CONFIG.get("scan_chunk_duration", 8))
        results = run_audio_correlation_workflow(ref_file, other_file, logger, chunks, chunk_dur, lang, role_tag=role)
        best = best_from_results(results, float(CONFIG.get("min_match_pct", 5.0)))
        if not best:
            raise RuntimeError(f"[{role}] No strong correlation result (min_match_pct={CONFIG.get('min_match_pct', 5.0)})")
        _log(f"[{role}] Audio correlation best: delay={format_delay_ms(best['delay'])} match={best['match']:.1f}%")
        return int(best["delay"])

def _run_jobs_impl(merge: bool):
    global RUNNING
    with RUN_LOCK:
        if RUNNING:
            _log("A job is already running.")
            return
        RUNNING = True
    try:
        sync_config_from_ui()
        ref = CONFIG.get("ref_path", "")
        sec = CONFIG.get("sec_path", "")
        ter = CONFIG.get("ter_path", "")
        set_status("Preparing jobs…")
        jobs = discover_jobs(ref, sec, ter)
        _log(f"Discovered {len(jobs)} job(s).")
        out_dir = CONFIG.get("output_folder")
        vdp = CONFIG.get("videodiff_path", "")
        for i, (r, s, t) in enumerate(jobs, start=1):
            set_status(f"Running job {i}/{len(jobs)}…")
            set_progress((i-1) / max(1, len(jobs)))
            if merge:
                merge_job(r, s, t, out_dir, logger=None, videodiff_path=Path(vdp) if vdp else Path(""))
            else:
                # analysis only: compute and log delays
                if s:
                    try:
                        _ = _compute_delay_for_pair(r, s, "sec", logger=None)
                    except Exception as e:
                        _log(f"[sec] analysis failed: {e}")
                if t:
                    try:
                        _ = _compute_delay_for_pair(r, t, "ter", logger=None)
                    except Exception as e:
                        _log(f"[ter] analysis failed: {e}")
        set_progress(1.0)
        set_status("All jobs complete.")
    except Exception as e:
        _log(f"[FAILED] {e}")
        set_status("Job failed.")
    finally:
        RUNNING = False

def do_analyze_only():
    threading.Thread(target=_run_jobs_impl, kwargs={"merge": False}, daemon=True).start()

def do_analyze_and_merge():
    threading.Thread(target=_run_jobs_impl, kwargs={"merge": True}, daemon=True).start()

# --- UI build ---
def build_ui():
    load_settings()  # populate CONFIG first
    dpg.create_context()
    dpg.create_viewport(title=APP_NAME, width=1180, height=780)
    with dpg.window(tag="main_window", label=APP_NAME, width=-1, height=-1):
        with dpg.group(tag="header_options_row"):
            dpg.add_button(tag="options_btn_main", label="Options…", callback=lambda *_: show_options_modal())
        # File inputs
        dpg.add_text("Reference")
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="ref_input", width=900)
            dpg.add_button(label="Browse…", callback=lambda: dpg.show_item("file_dialog_ref"))
        dpg.add_text("Secondary")
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="sec_input", width=900)
            dpg.add_button(label="Browse…", callback=lambda: dpg.show_item("file_dialog_sec"))
        dpg.add_text("Tertiary")
        with dpg.group(horizontal=True):
            dpg.add_input_text(tag="ter_input", width=900)
            dpg.add_button(label="Browse…", callback=lambda: dpg.show_item("file_dialog_ter"))
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(tag="btn_analyze_only", label="Analyze Only", width=150, height=36, callback=lambda *_: do_analyze_only())
            dpg.add_button(tag="btn_analyze_merge", label="Analyze & Merge", width=170, height=36, callback=lambda *_: do_analyze_and_merge())
            dpg.add_progress_bar(tag="progress_bar", overlay="Progress", default_value=0.0, width=420, height=26)
        dpg.add_text("Status:")
        dpg.add_text(tag="status_text", default_value="")
        dpg.add_separator()
        dpg.add_text("Log")
        with dpg.child_window(tag="log_child", width=-1, height=320, horizontal_scrollbar=True):
            dpg.add_child_window(tag="log_scroller", width=-1, height=-1)
        # dialogs
        with dpg.file_dialog(tag="file_dialog_ref", label="Pick Reference", callback=on_pick_file,
                             user_data="ref_input", width=700, height=400, directory_selector=False, show=False):
            dpg.add_file_extension(".*", color=(150,255,150,255))
        with dpg.file_dialog(tag="file_dialog_sec", label="Pick Secondary", callback=on_pick_file,
                             user_data="sec_input", width=700, height=400, directory_selector=False, show=False):
            dpg.add_file_extension(".*", color=(150,255,150,255))
        with dpg.file_dialog(tag="file_dialog_ter", label="Pick Tertiary", callback=on_pick_file,
                             user_data="ter_input", width=700, height=400, directory_selector=False, show=False):
            dpg.add_file_extension(".*", color=(150,255,150,255))
    # Prefill inputs from CONFIG
    dpg.set_value("ref_input", CONFIG.get("ref_path",""))
    dpg.set_value("sec_input", CONFIG.get("sec_path",""))
    dpg.set_value("ter_input", CONFIG.get("ter_path",""))
    # pump log timer
    try:
        dpg.add_timer(callback=lambda: pump_logs(), period=0.15, tag="log_timer")
    except Exception:
        # fallback: a frame callback every ~10 frames
        def _pump():
            pump_logs()
            try:
                dpg.set_frame_callback(dpg.get_frame_count()+10, _pump)
            except Exception:
                pass
        dpg.set_frame_callback(10, _pump)

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("main_window", True)
    dpg.start_dearpygui()
    dpg.destroy_context()

# -- Appearance: bind fonts/themes and input heights after UI builds --
try:
    _orig_build_ui = build_ui
    def build_ui(*args, **kwargs):
        result = _orig_build_ui(*args, **kwargs)
        try:
            load_fonts_and_themes()
            apply_line_heights()
        except Exception:
            pass
        return result
except Exception:
    # If build_ui isn't defined yet, ignore; app_direct can call helpers instead.
    pass

# === Appearance Hook: apply fonts/themes and input heights AFTER UI builds ===
try:
    from vsg.appearance_helper import load_fonts_and_themes, apply_line_heights
    _VSG__orig_build_ui = build_ui
    def build_ui(*args, **kwargs):
        result = _VSG__orig_build_ui(*args, **kwargs)
        try:
            load_fonts_and_themes()
            apply_line_heights()
        except Exception:
            pass
        return result
except Exception:
    # If helper isn't available, keep original build_ui unchanged
    pass
# === End Appearance Hook ===

