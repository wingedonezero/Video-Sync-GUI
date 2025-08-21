
from __future__ import annotations
import dearpygui.dearpygui as dpg
from video_sync_gui import CONFIG, load_settings, save_settings  # share the app's state
from vsg.logbus import _log

class Binder:
    def __init__(self):
        self.map = {}
    def bind(self, tag: str, key: str):
        self.map[tag] = key
    def on_changed(self, sender, app_data):
        key = self.map.get(sender)
        if key is not None:
            CONFIG[key] = app_data
            if key == "analysis_mode":
                _apply_mode_visibility()
    def refresh(self):
        for tag, key in self.map.items():
            if dpg.does_item_exist(tag):
                try:
                    dpg.set_value(tag, CONFIG.get(key))
                except Exception:
                    pass
        _apply_mode_visibility()

B = Binder()

def _row_text(label: str, tag: str, key: str, width: int = 520, hint: str = "", tip: str = ""):
    dpg.add_group(horizontal=True)
    dpg.add_text(label)
    dpg.add_input_text(tag=tag, width=width, hint=hint, default_value=str(CONFIG.get(key, "")), callback=B.on_changed)
    B.bind(tag, key)
    if tip:
        dpg.add_tooltip(dpg.last_item()); dpg.add_text(tip)

def _row_check(label: str, tag: str, key: str, tip: str = ""):
    dpg.add_checkbox(tag=tag, label=label, default_value=bool(CONFIG.get(key, False)), callback=B.on_changed)
    B.bind(tag, key); 
    if tip:
        dpg.add_tooltip(dpg.last_item()); dpg.add_text(tip)

def _row_int(label: str, tag: str, key: str, minv: int, maxv: int, step: int = 1, tip: str = ""):
    dpg.add_group(horizontal=True)
    dpg.add_text(label)
    dpg.add_input_int(tag=tag, min_value=minv, max_value=maxv, step=step,
                      default_value=int(CONFIG.get(key, minv)), callback=B.on_changed)
    B.bind(tag, key)
    if tip:
        dpg.add_tooltip(dpg.last_item()); dpg.add_text(tip)

def _row_float(label: str, tag: str, key: str, step: float = 0.01, tip: str = ""):
    dpg.add_group(horizontal=True)
    dpg.add_text(label)
    dpg.add_input_float(tag=tag, step=step, default_value=float(CONFIG.get(key, 0.0)), callback=B.on_changed)
    B.bind(tag, key)
    if tip:
        dpg.add_tooltip(dpg.last_item()); dpg.add_text(tip)

def _row_combo(label: str, tag: str, key: str, items: list[str], tip: str = ""):
    dpg.add_group(horizontal=True)
    dpg.add_text(label)
    dpg.add_combo(tag=tag, items=items, width=260,
                  default_value=CONFIG.get(key, items[0] if items else ""),
                  callback=lambda s, a: (B.on_changed(s, a), _apply_mode_visibility() if key == "analysis_mode" else None))
    B.bind(tag, key)
    if tip:
        dpg.add_tooltip(dpg.last_item()); dpg.add_text(tip)

def _apply_mode_visibility():
    mode = str(CONFIG.get("analysis_mode", "Audio Correlation")).lower()
    show_xcorr = ("audio" in mode) or (mode == "audio_xcorr")
    if dpg.does_item_exist("xcorr_panel"):
        dpg.configure_item("xcorr_panel", show=show_xcorr)
    if dpg.does_item_exist("vd_panel"):
        dpg.configure_item("vd_panel", show=not show_xcorr)

def build_options_modal():
    if dpg.does_item_exist("options_modal"):
        dpg.delete_item("options_modal")
    with dpg.window(tag="options_modal", label="Preferences", modal=True, show=False, width=920, height=620):
        with dpg.tab_bar():
            # Storage
            with dpg.tab(label="Storage"):
                _row_text("Output folder", "op_out", "output_folder",
                          hint="Where final MKVs are written.",
                          tip="Final muxed files are written here.")
                _row_text("Temp folder", "op_temp", "temp_root",
                          hint="Where work files are written.",
                          tip="Temporary intermediates / extracted assets.")

                dpg.add_separator()
                dpg.add_text("Optional tool paths (leave blank to use PATH)")
                _row_text("FFmpeg path", "op_ffmpeg", "ffmpeg_path")
                _row_text("FFprobe path", "op_ffprobe", "ffprobe_path")
                _row_text("mkvmerge path", "op_mkvmerge", "mkvmerge_path")
                _row_text("mkvextract path", "op_mkvextract", "mkvextract_path")
                _row_text("VideoDiff path", "op_videodiff", "videodiff_path")

            # Analysis
            with dpg.tab(label="Analysis"):
                _row_combo("Workflow", "op_workflow", "workflow",
                           ["Analyze & Merge", "Analyze Only"],
                           tip="Analyze only vs analyze+merge.")
                _row_combo("Mode", "op_mode", "analysis_mode",
                           ["Audio Correlation", "VideoDiff"],
                           tip="Pick analysis engine.")

                with dpg.group(tag="xcorr_panel"):
                    _row_int("Scan chunk count", "op_scan_count", "scan_chunk_count", 1, 128, 1,
                             tip="Number of evenly spaced samples across the timeline.")
                    _row_int("Chunk duration (s)", "op_scan_dur", "scan_chunk_duration", 1,
                             tip="Seconds per sampled segment.")
                    _row_float("Minimum match %", "op_min_match", "min_match_pct", 0.1,
                               tip="Reject matches below this percentage (e.g. 5 = 5%).")
                with dpg.group(tag="vd_panel"):
                    _row_float("Min error (VideoDiff)", "vd_err_min", "videodiff_error_min", 0.01,
                               tip="Stop if below this error.")
                    _row_float("Max error (VideoDiff)", "vd_err_max", "videodiff_error_max", 0.01,
                               tip="Stop if above this error.")

            # Global
            with dpg.tab(label="Global"):
                _row_check("Rename chapters", "op_rename_chapters", "rename_chapters",
                           tip="Rename chapters in the output.")
                _row_check("Prefer JPN audio on Secondary", "op_jpn_sec", "match_jpn_secondary",
                           tip="When multiple audio tracks, prefer Japanese on secondary.")
                _row_check("Prefer JPN audio on Tertiary", "op_jpn_ter", "match_jpn_tertiary",
                           tip="Prefer Japanese on tertiary.")
                _row_check("Remove dialog normalization (AC-3/eAC-3)", "op_dialog_norm",
                           "apply_dialog_norm_gain",
                           tip="Remove dialnorm so volume-based analysis is comparable.")
                dpg.add_separator()
                dpg.add_text("Chapters / Keyframe snapping")
                _row_check("Snap chapters to keyframes", "op_snap", "snap_chapters",
                           tip="Adjust chapter times to nearby keyframes for clean seeking.")
                _row_combo("Snap mode", "op_snap_mode", "snap_mode",
                           ["previous","next","nearest"],
                           tip="Direction when snapping to keyframes.")
                _row_int("Max snap distance (ms)", "op_snap_thr", "snap_threshold_ms", 0, 5000, 10,
                         tip="No snap if the keyframe is farther than this many ms.")
                _row_check("Starts only", "op_snap_starts", "snap_starts_only",
                           tip="Only snap chapter starts (not ends).")

            # Save / Load
            with dpg.tab(label="Save / Load"):
                dpg.add_text("Persist or import/export all preferences.")
                dpg.add_spacer(height=6)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Save", callback=lambda *_: save_settings())
                    dpg.add_button(label="Load", callback=lambda *_: (load_settings(), B.refresh()))
                    dpg.add_button(label="Export…", callback=lambda *_: _export_settings_dialog())

    _apply_mode_visibility()

def _export_settings_dialog():
    # keep your existing dialog-based export (optional)
    try:
        from vsg.settings import export_settings_dialog as _export  # if you kept helper
        _export()
    except Exception:
        pass

def show_options_modal():
    load_settings()
    if not dpg.does_item_exist("options_modal"):
        build_options_modal()
    B.refresh()
    dpg.configure_item("options_modal", show=True)
