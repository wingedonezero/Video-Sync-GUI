from __future__ import annotations
import dearpygui.dearpygui as dpg
from vsg.settings_core import CONFIG, save_settings, load_settings, on_change, adopt_into_app, apply_and_notify

# helpers to build rows
def _row_label(text: str):
    dpg.add_text(text)
def _row_spacer(h: int = 8):
    dpg.add_spacer(height=h)

def _row_text(label: str, tag: str, key: str, hint: str = "", tip: str = "", width: int = 540):
    _row_label(label)
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag=tag, hint=hint, width=width, default_value=str(CONFIG.get(key, "")),
                           callback=lambda s,a,u=key: on_change(s,a,user_data=u))
    if tip: dpg.add_text(tip, bullet=True)

def _row_int(label: str, tag: str, key: str, step: int, minv: int, maxv: int, tip: str = "", width: int = 140):
    _row_label(label)
    with dpg.group(horizontal=True):
        dpg.add_input_int(tag=tag, width=width, min_value=minv, max_value=maxv, step=step,
                          default_value=int(CONFIG.get(key, 0)),
                          callback=lambda s,a,u=key: on_change(s,a,user_data=u))

def _row_float(label: str, tag: str, key: str, step: float, minv: float, maxv: float, tip: str = "", width: int = 140):
    _row_label(label)
    with dpg.group(horizontal=True):
        dpg.add_input_float(tag=tag, width=width, min_value=minv, max_value=maxv, step=step,
                            default_value=float(CONFIG.get(key, 0.0)),
                            callback=lambda s,a,u=key: on_change(s,a,user_data=u))

def _row_checkbox(label: str, tag: str, key: str, tip: str = ""):
    with dpg.group(horizontal=True):
        dpg.add_checkbox(tag=tag, label=label, default_value=bool(CONFIG.get(key, False)),
                         callback=lambda s,a,u=key: on_change(s,a,user_data=u))

def _show_save_load():
    with dpg.group():
        dpg.add_text("Persist or import/export all preferences.")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save", callback=lambda: apply_and_notify())
            dpg.add_button(label="Load", callback=_do_live_load)

def _do_live_load():
    conf = load_settings()
    adopt_into_app(conf)  # will notify listeners (fonts/themes rebind, ui refresh)

def build_options_modal():
    if dpg.does_item_exist("options_modal"):
        dpg.delete_item("options_modal")
    with dpg.window(modal=True, label="Preferences", tag="options_modal", width=860, height=540, pos=(120, 60)):
        with dpg.tab_bar():
            # Storage
            with dpg.tab(label="Storage"):
                _row_text("Output folder", "op_out", "output_folder", hint="Where final MKVs are written.")
                _row_text("Temp folder", "op_temp", "temp_root", hint="Where intermediate files go.")
                dpg.add_separator()
                dpg.add_text("Optional tool paths (leave blank to use PATH)")
                _row_text("FFmpeg path", "op_ffmpeg", "ffmpeg_path")
                _row_text("FFprobe path", "op_ffprobe", "ffprobe_path")
                _row_text("mkvmerge path", "op_mkvmerge", "mkvmerge_path")
                _row_text("mkvextract path", "op_mkvextract", "mkvextract_path")
                _row_text("VideoDiff path", "op_vdiff", "videodiff_path")

            # Analysis
            with dpg.tab(label="Analysis"):
                _row_label("Workflow")
                with dpg.group(horizontal=True):
                    dpg.add_combo(items=["Analyze Only", "Analyze & Merge"],
                                  default_value=str(CONFIG.get("workflow","Analyze & Merge")),
                                  callback=lambda s,a: on_change(s,a,user_data="workflow"))
                    dpg.add_text("Analyze only vs analyze+merge.")
                _row_label("Mode")
                with dpg.group(horizontal=True):
                    dpg.add_combo(items=["Audio Correlation","VideoDiff"],
                                  default_value=str(CONFIG.get("analysis_mode","Audio Correlation")),
                                  callback=lambda s,a: on_change(s,a,user_data="analysis_mode"))
                    dpg.add_text("Pick analysis engine.")
                _row_int("Scan chunk count", "op_scan_cnt", "scan_chunk_count", 1, 1, 200,
                         tip="Number of evenly spaced samples across the timeline.")
                _row_int("Chunk duration (s)", "op_scan_dur", "scan_chunk_duration", 1, 1, 3600,
                         tip="Seconds per sampled segment.")
                _row_float("Minimum match %", "op_min_match", "min_match_pct", 0.5, 0.0, 100.0,
                           tip="Reject matches below this percent.")
                dpg.add_separator()
                _row_float("Min error (VideoDiff)", "vd_err_min", "videodiff_error_min", 0.01, 0.0, 10000.0,
                           tip="Stop if below this error.")
                _row_float("Max error (VideoDiff)", "vd_err_max", "videodiff_error_max", 0.01, 0.0, 10000.0,
                           tip="Stop if above this error.")

            # Global
            with dpg.tab(label="Global"):
                dpg.add_text("Rename chapters")
                _row_checkbox("Prefer JPN audio on Secondary", "op_jpn_sec", "match_jpn_secondary")
                _row_checkbox("Prefer JPN audio on Tertiary", "op_jpn_ter", "match_jpn_tertiary")
                _row_checkbox("Remove dialog normalization (AC-3/eAC-3)", "op_rm_dn", "apply_dialog_norm_gain")
                dpg.add_separator()
                dpg.add_text("Chapters / Keyframe snapping")
                _row_checkbox("Snap chapters to keyframes", "op_snap", "snap_chapters")
                _row_label("Snap mode")
                with dpg.group(horizontal=True):
                    dpg.add_combo(items=["previous","next","nearest","None"],
                                  default_value=str(CONFIG.get("snap_mode","previous")),
                                  callback=lambda s,a: on_change(s,a,user_data="snap_mode"))
                _row_int("Max snap distance (ms)", "op_snap_ms", "snap_threshold_ms", 5, 0, 10000)
                _row_checkbox("Starts only", "op_snap_starts", "snap_starts_only")
                dpg.add_separator()
                dpg.add_text("Appearance")
                _row_text("UI font file", "op_font_file", "ui_font_path", hint="Leave blank to auto-pick a sane font.")
                _row_int("Font size", "op_font_size", "ui_font_size", 1, 8, 48)
                _row_int("Input line height", "op_line_h", "input_line_height", 1, 20, 72)
                _row_int("Row spacing", "op_row_gap", "row_gap", 1, 0, 32)
                _row_checkbox("Compact controls", "op_compact", "ui_compact_controls")
                dpg.add_button(label="Apply Appearance", callback=lambda: apply_and_notify())

            # Logging
            with dpg.tab(label="Logging"):
                _row_checkbox("Compact log view", "op_log_compact", "log_compact")
                _row_int("Log tail lines", "op_log_tail", "log_tail_lines", 1, 0, 100000)
                _row_int("Error tail lines", "op_log_err_tail", "log_error_tail", 1, 0, 100000)
                _row_int("Progress step", "op_log_prog_step", "log_progress_step", 1, 1, 100000)
                _row_checkbox("Auto scroll log", "op_log_auto", "log_autoscroll")

            with dpg.tab(label="Save / Load"):
                _show_save_load()

def show_options_modal():
    build_options_modal()
    dpg.configure_item("options_modal", show=True)
