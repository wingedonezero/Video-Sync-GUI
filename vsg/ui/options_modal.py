from __future__ import annotations
import json
from pathlib import Path
import dearpygui.dearpygui as dpg
from vsg.settings import CONFIG, DEFAULT_CONFIG, save_settings
from vsg.logbus import _log

class Binder:
    def __init__(self): self.map = {}
    def bind(self, tag, key):
        self.map[tag] = key
        try: dpg.set_value(tag, CONFIG.get(key))
        except Exception: pass
    def on_changed(self, sender, app_data, user_data):
        key = self.map.get(sender)
        if key is not None:
            CONFIG[key] = app_data
            _log(f"[options] {key} -> {app_data!r}")

B = Binder()

def _tip(for_tag: str, text: str):
    with dpg.tooltip(for_tag):
        dpg.add_text(text, wrap=520)

def _row_text(label, tag, key, hint="", width=520, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_text(tag=tag, width=width, hint=hint, callback=B.on_changed)
        B.bind(tag, key)
        if tip: _tip(tag, tip)

def _row_check(label, tag, key, tip=""):
    dpg.add_checkbox(tag=tag, label=label, callback=B.on_changed)
    B.bind(tag, key)
    if tip: _tip(tag, tip)

def _row_int(label, tag, key, minv=0, maxv=1_000_000, step=1, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_int(tag=tag, min_value=minv, max_value=maxv, step=step, callback=B.on_changed)
        B.bind(tag, key)
        if tip: _tip(tag, tip)

def _row_float(label, tag, key, step=0.1, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_input_float(tag=tag, step=step, callback=B.on_changed)
        B.bind(tag, key)
        if tip: _tip(tag, tip)

def _row_combo(label, tag, key, items, tip=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label)
        dpg.add_combo(tag=tag, items=items, width=260, callback=B.on_changed)
        B.bind(tag, key)
        if tip: _tip(tag, tip)

def _load_settings_dialog():
    def _on_pick(sender, app_data):
        p = app_data.get("file_path_name")
        if not p: return
        try:
            data = json.loads(Path(p).read_text())
            CONFIG.clear(); CONFIG.update({**DEFAULT_CONFIG, **data})
            save_settings()
            for tag, key in B.map.items():
                if dpg.does_item_exist(tag):
                    try: dpg.set_value(tag, CONFIG.get(key))
                    except Exception: pass
            _log(f"[options] Loaded settings from {p}")
        except Exception as e:
            _log(f"[options] Load failed: {e}")
    if not dpg.does_item_exist("opt_load_fd"):
        with dpg.file_dialog(tag="opt_load_fd", show=False, callback=_on_pick):
            dpg.add_file_extension(".json"); dpg.add_file_extension(".*")
    dpg.configure_item("opt_load_fd", show=True)

def _export_settings_dialog():
    def _on_pick(sender, app_data):
        p = app_data.get("file_path_name")
        if not p: return
        try:
            Path(p).write_text(json.dumps(CONFIG, indent=2))
            _log(f"[options] Exported settings to {p}")
        except Exception as e:
            _log(f"[options] Export failed: {e}")
    if not dpg.does_item_exist("opt_save_fd"):
        with dpg.file_dialog(tag="opt_save_fd", show=False, callback=_on_pick):
            dpg.add_file_extension(".json")
    dpg.configure_item("opt_save_fd", show=True)

def build_options_modal():
    if dpg.does_item_exist("options_modal"): return
    with dpg.window(tag="options_modal", label="Preferences", width=860, height=600, modal=True, show=False, pos=(120,80)):
        with dpg.tab_bar():
            # Storage
            with dpg.tab(label="Storage"):
                _row_text("Output folder", "op_out", "output_folder",
                          hint="Where final MKVs are written.",
                          tip="Final muxed files are written here.")
                _row_text("Temp folder", "op_tmp", "temp_root",
                          hint="Working scratch directory.",
                          tip="Temporary files are created here during analysis/merge.")
                dpg.add_separator()
                for key, label, tip in [
                    ("ffmpeg_path","FFmpeg path","Path to ffmpeg."),
                    ("ffprobe_path","FFprobe path","Path to ffprobe."),
                    ("mkvmerge_path","mkvmerge path","Path to mkvmerge."),
                    ("mkvextract_path","mkvextract path","Path to mkvextract."),
                    ("videodiff_path","VideoDiff path","Optional: VideoDiff binary for video-mode analysis."),
                ]:
                    _row_text(label, f"op_{key}", key, tip=tip)

            # Analysis
            with dpg.tab(label="Analysis"):
                _row_combo("Workflow", "op_workflow", "workflow", ["Analyze & Merge", "Analyze Only"],
                           tip="Analyze only vs analyze+merge.")
                _row_combo("Mode", "op_mode", "analysis_mode", ["Audio Correlation", "VideoDiff"],
                           tip="Audio vs Video analysis mode.")
                _row_int("Scan chunk count", "op_scan_count", "scan_chunk_count", 1, 128, 1,
                         tip="Number of evenly spaced samples across the timeline.")
                _row_int("Chunk duration (s)", "op_scan_dur", "scan_chunk_duration", 1,
                         tip="Seconds per sampled segment.")
                _row_float("Minimum match %", "op_min_match", "min_match_pct", 0.1,
                           tip="Reject matches below this percentage (e.g., 5 = 5%).")

            with dpg.tab(label="Global"):

                _row_check("Rename chapters", "op_ren_chap", "rename_chapters",
                           tip="Normalize chapter titles based on language preference.")
                _row_check("Prefer JPN audio on Secondary", "op_pref_jpn_sec", "prefer_jpn_secondary",
                           tip="Choose Japanese on the Secondary when multiple audio tracks exist.")
                _row_check("Prefer JPN audio on Tertiary", "op_pref_jpn_ter", "prefer_jpn_tertiary",
                           tip="Choose Japanese on the Tertiary when multiple audio tracks exist.")
                _row_check("Remove dialog normalization (AC-3/eAC-3)", "op_dialog_norm", "apply_dialog_norm_gain",
                           tip="Remove dialnorm so volume-based analysis is comparable.")
                dpg.add_separator()
                dpg.add_text("Chapters / Keyframe snapping")
                _row_check("Snap chapters to keyframes", "op_snap", "snap_chapters",
                           tip="Adjust chapter times to nearby keyframes for clean seeking.")
                _row_combo("Snap mode", "op_snap_mode", "snap_mode", ["previous","next","nearest"],
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
                    dpg.add_button(label="Load…", callback=lambda *_: _load_settings_dialog())
                    dpg.add_button(label="Export…", callback=lambda *_: _export_settings_dialog())

def show_options_modal():
    load_settings()
    if not dpg.does_item_exist("options_modal"):
        build_options_modal()
    dpg.configure_item("options_modal", show=True)
