
from __future__ import annotations
import json
import dearpygui.dearpygui as dpg
from vsg.settings_core import CONFIG, load_settings, save_settings, on_change, adopt_into_app, SETTINGS_PATH

PFX = "prefs_"
WIN = PFX + "options_modal"

def _ui_log(msg: str):
    try:
        from vsg.logbus import _log
        _log(msg); return
    except Exception:
        pass
    try: dpg.log_info(msg)
    except Exception: pass

# Legacy things to purge so the modal is the only source of truth
LEGACY_BUTTON_LABELS = {"Storage?", "Analysis Settings?", "Global Options?"}
LEGACY_WINDOW_LABELS = {"Storage Settings", "Analysis Settings", "Global Options"}

def _purge_legacy_settings_ui():
    try:
        for item in dpg.get_all_items():
            try: lbl = dpg.get_item_label(item)
            except Exception: continue
            if lbl in LEGACY_BUTTON_LABELS or lbl in LEGACY_WINDOW_LABELS:
                try: dpg.delete_item(item)
                except Exception: pass
    except Exception:
        pass

class Binder:
    def __init__(self): self.map = {}
    def bind(self, tag, key): self.map[tag] = key
    def on_changed(self, sender, app_data):
        key = self.map.get(sender)
        if key is None: return
        on_change(key, app_data)
        if key == "analysis_mode":
            _apply_mode_visibility()
    def refresh(self):
        for tag, key in self.map.items():
            if dpg.does_item_exist(tag):
                val = CONFIG.get(key)
                if val is None: val = ""  # text wants blank not None
                try: dpg.set_value(tag, val)
                except Exception: pass
        _apply_mode_visibility()

B = Binder()

def _tip(text):
    if not text: return
    dpg.add_tooltip(dpg.last_item()); dpg.add_text(text)

def _row_text(label, tag, key, width=520, hint="", tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_text(tag=tag, width=width, hint=hint,
                           default_value=(CONFIG.get(key) if CONFIG.get(key) is not None else ""),
                           callback=B.on_changed)
        _tip(tip); B.bind(tag, key)

def _row_check(label, tag, key, tip=""):
    dpg.add_checkbox(tag=tag, label=label,
                     default_value=bool(CONFIG.get(key, False)),
                     callback=B.on_changed)
    _tip(tip); B.bind(tag, key)

def _row_int(label, tag, key, minv, maxv, step=1, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_int(tag=tag, min_value=minv, max_value=maxv, step=step,
                          default_value=int(CONFIG.get(key, minv)),
                          callback=B.on_changed)
        _tip(tip); B.bind(tag, key)

def _row_float(label, tag, key, step=0.01, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_float(tag=tag, step=step,
                            default_value=float(CONFIG.get(key, 0.0)),
                            callback=B.on_changed)
        _tip(tip); B.bind(tag, key)

def _row_combo(label, tag, key, items, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_combo(tag=tag, items=items, width=260,
                      default_value=CONFIG.get(key, items[0] if items else ""),
                      callback=lambda s,a: (B.on_changed(s,a), _apply_mode_visibility() if key=='analysis_mode' else None))
        _tip(tip); B.bind(tag, key)

def _apply_mode_visibility():
    # Prefer the current UI value; fallback to CONFIG
    mode = CONFIG.get("analysis_mode", "Audio Correlation")
    if dpg.does_item_exist(PFX + "op_mode"):
        try: mode = dpg.get_value(PFX + "op_mode")
        except Exception: pass
    m = str(mode).lower()
    show_audio = ("audio" in m) or (m == "audio correlation") or (m == "audio_xcorr")
    if dpg.does_item_exist(PFX + "xcorr_panel"):
        dpg.configure_item(PFX + "xcorr_panel", show=show_audio)
    if dpg.does_item_exist(PFX + "vd_panel"):
        dpg.configure_item(PFX + "vd_panel", show=not show_audio)

def build_options_modal():
    if dpg.does_item_exist(WIN): dpg.delete_item(WIN)
    with dpg.window(tag=WIN, label="Preferences", modal=True, show=False, width=980, height=660):
        with dpg.tab_bar():

            # Storage
            with dpg.tab(label="Storage"):
                _row_text("Output folder", PFX + "op_out", "output_folder",
                          hint="Where final MKVs are written.",
                          tip="Final muxed files are written here.")
                _row_text("Temp folder", PFX + "op_temp", "temp_root",
                          hint="Where work files are written.",
                          tip="Temporary intermediates / extracted assets.")
                dpg.add_separator(); dpg.add_text("Optional tool paths (leave blank to use PATH)")
                _row_text("FFmpeg path",     PFX + "op_ffmpeg",    "ffmpeg_path")
                _row_text("FFprobe path",    PFX + "op_ffprobe",   "ffprobe_path")
                _row_text("mkvmerge path",   PFX + "op_mkvmerge",  "mkvmerge_path")
                _row_text("mkvextract path", PFX + "op_mkvextract","mkvextract_path")
                _row_text("VideoDiff path",  PFX + "op_videodiff", "videodiff_path")

            # Analysis
            with dpg.tab(label="Analysis"):
                _row_combo("Workflow", PFX + "op_workflow", "workflow",
                           ["Analyze & Merge", "Analyze Only"],
                           tip="Analyze only vs analyze+merge.")
                _row_combo("Mode", PFX + "op_mode", "analysis_mode",
                           ["Audio Correlation", "VideoDiff"],
                           tip="Pick analysis engine.")
                with dpg.group(tag=PFX + "xcorr_panel"):
                    _row_int("Scan chunk count", PFX + "op_scan_count", "scan_chunk_count", 1, 128, 1,
                             tip="Number of evenly spaced samples across the timeline.")
                    _row_int("Chunk duration (s)", PFX + "op_scan_dur", "scan_chunk_duration", 1, 3600, 1,
                             tip="Seconds per sampled segment.")
                    _row_float("Minimum match %", PFX + "op_min_match", "min_match_pct", 0.1,
                               tip="Reject matches below this percentage (e.g. 5 = 5%).")
                with dpg.group(tag=PFX + "vd_panel"):
                    _row_float("Min error (VideoDiff)", PFX + "vd_err_min", "videodiff_error_min", 0.01,
                               tip="Stop if below this error.")
                    _row_float("Max error (VideoDiff)", PFX + "vd_err_max", "videodiff_error_max", 0.01,
                               tip="Stop if above this error.")

            # Global
            with dpg.tab(label="Global"):
                _row_check("Rename chapters", PFX + "op_rename_chapters", "rename_chapters",
                           tip="Rename chapters in the output.")
                _row_check("Prefer JPN audio on Secondary", PFX + "op_jpn_sec", "match_jpn_secondary",
                           tip="Prefer Japanese audio on Secondary.")
                _row_check("Prefer JPN audio on Tertiary", PFX + "op_jpn_ter", "match_jpn_tertiary",
                           tip="Prefer Japanese audio on Tertiary.")
                _row_check("Remove dialog normalization (AC-3/eAC-3)", PFX + "op_dialog_norm",
                           "apply_dialog_norm_gain",
                           tip="Remove dialnorm so volume-based analysis is comparable.")
                _row_check("Make first subtitle in final order the DEFAULT", PFX + "op_first_sub_def",
                           "first_sub_default",
                           tip="Mark first subtitle track as default in the merged output.")
                dpg.add_separator(); dpg.add_text("Chapters / Keyframe snapping")
                _row_check("Snap chapters to keyframes", PFX + "op_snap", "snap_chapters",
                           tip="Adjust chapter times to nearby keyframes for clean seeking.")
                _row_combo("Snap mode", PFX + "op_snap_mode", "snap_mode",
                           ["previous","next","nearest"],
                           tip="Direction when snapping to keyframes.")
                _row_int("Max snap distance (ms)", PFX + "op_snap_thr", "snap_threshold_ms", 0, 5000, 10,
                         tip="No snap if the keyframe is farther than this many ms.")
                _row_check("Starts only", PFX + "op_snap_starts", "snap_starts_only",
                           tip="Only snap chapter starts (not ends).")

            # Logging
            with dpg.tab(label="Logging"):
                _row_check("Compact subprocess log", PFX + "op_log_compact", "log_compact",
                           tip="Shorten repeated stdout/stderr lines from tools.")
                _row_int("Tail lines (0=all)", PFX + "op_log_tail", "log_tail_lines", 0, 50000, 10,
                         tip="How many lines to keep in memory.")
                _row_int("Error tail lines", PFX + "op_log_err_tail", "log_error_tail", 0, 10000, 1,
                         tip="Trailing lines to include on failure.")
                _row_int("Progress step (%)", PFX + "op_log_prog_step", "log_progress_step", 1, 100, 1,
                         tip="Emit a log update every N percent of work done.")
                _row_check("Show Options (pretty)", PFX + "op_log_show_pretty", "log_show_options_pretty",
                           tip="Print human-readable options blocks to the log.")
                _row_check("Show Options (JSON)", PFX + "op_log_show_json", "log_show_options_json",
                           tip="Print raw JSON options blocks to the log.")
                _row_check("Log autoscroll", PFX + "op_log_autoscroll", "log_autoscroll",
                           tip="Keep the log view pinned to the bottom while running.")

            # Save / Load
            with dpg.tab(label="Save / Load"):
                dpg.add_text("Persist, reload, or export all preferences.")
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Save", callback=lambda *_: (_ui_log(f"Saved settings -> {SETTINGS_PATH}"), save_settings()))
                    dpg.add_button(label="Load", callback=lambda *_: (_ui_log(f"Loading settings <- {SETTINGS_PATH}"),
                                                                      load_settings(), adopt_into_app(), B.refresh(), _apply_mode_visibility()))
                    dpg.add_button(label="Export…", callback=lambda *_: _export_settings_dialog())
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Show Path", callback=lambda *_: _ui_log(str(SETTINGS_PATH)))
                    dpg.add_button(label="Dump CONFIG", callback=lambda *_: _ui_log(json.dumps(CONFIG, indent=2)))
                    dpg.add_button(label="Force Refresh", callback=lambda *_: (B.refresh(), _apply_mode_visibility()))

    _apply_mode_visibility()

def _export_settings_dialog():
    try:
        from vsg.settings import export_settings_dialog as _export
        _export()
    except Exception:
        pass

def show_options_modal():
    load_settings(); adopt_into_app()
    _purge_legacy_settings_ui()
    if not dpg.does_item_exist(WIN):
        build_options_modal()
    B.refresh()
    _apply_mode_visibility()
    dpg.configure_item(WIN, show=True)
