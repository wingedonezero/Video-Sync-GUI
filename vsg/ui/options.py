from __future__ import annotations

import json
from pathlib import Path

import dearpygui.dearpygui as dpg

from vsg.logbus import _log
from vsg.settings import CONFIG, DEFAULT_CONFIG, save_settings

SETTINGS_DIRTY = False  # explicit save model


class SettingsBinder:
    def __init__(self):
        self._map: dict[str, str] = {}

    def bind(self, item_tag: str, config_key: str):
        self._map[item_tag] = config_key
        try:
            dpg.set_value(item_tag, CONFIG.get(config_key))
        except Exception:
            pass

    def on_changed(self, sender, app_data, user_data):
        global SETTINGS_DIRTY
        key = self._map.get(sender)
        if not key:
            return
        CONFIG[key] = app_data
        SETTINGS_DIRTY = True
        _log(f"[options] Changed: {key} = {app_data!r} (unsaved)")


BINDER = SettingsBinder()


def _input_text_row(label: str, tag: str, key: str, width=520, hint=""):
    with dpg.group(horizontal=True):
        dpg.add_text(label, width=200)
        dpg.add_input_text(tag=tag, width=width, hint=hint, callback=BINDER.on_changed)
        BINDER.bind(tag, key)


def _checkbox_row(label: str, tag: str, key: str):
    with dpg.group(horizontal=True):
        dpg.add_checkbox(tag=tag, label=label, callback=BINDER.on_changed)
        BINDER.bind(tag, key)


def _int_row(label: str, tag: str, key: str, minv=0, maxv=999999, step=1):
    with dpg.group(horizontal=True):
        dpg.add_text(label, width=200)
        dpg.add_input_int(tag=tag, min_value=minv, max_value=maxv, step=step, callback=BINDER.on_changed)
        BINDER.bind(tag, key)


def _float_row(label: str, tag: str, key: str, step=0.1):
    with dpg.group(horizontal=True):
        dpg.add_text(label, width=200)
        dpg.add_input_float(tag=tag, step=step, callback=BINDER.on_changed)
        BINDER.bind(tag, key)


def _combo_row(label: str, tag: str, key: str, items):
    with dpg.group(horizontal=True):
        dpg.add_text(label, width=200)
        dpg.add_combo(tag=tag, items=items, width=250, callback=BINDER.on_changed)
        BINDER.bind(tag, key)


def _browse_button(tag_btn: str, target_tag: str):
    def _do_browse():
        def _on_pick(sender, app_data):
            sel = app_data.get("file_path_name")
            if not sel:
                return
            dpg.set_value(target_tag, sel)
            BINDER.on_changed(target_tag, sel, None)

        if not dpg.does_item_exist("options_fd"):
            with dpg.file_dialog(tag="options_fd", directory_selector=False, show=False, callback=_on_pick):
                dpg.add_file_extension(".*", color=(150, 150, 150, 255))
        dpg.configure_item("options_fd", show=True)

    dpg.add_button(tag=tag_btn, label="Browse…", callback=lambda *_: _do_browse())


def _save_now():
    global SETTINGS_DIRTY
    save_settings()
    SETTINGS_DIRTY = False
    _log("[options] Settings saved.")


def _load_settings_dialog():
    def _on_pick(sender, app_data):
        path = app_data.get("file_path_name")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text())
            CONFIG.clear()
            CONFIG.update({**DEFAULT_CONFIG, **data})
            _save_now()
            _rebind_all()
            _log(f"[options] Loaded settings from {path}")
        except Exception as e:
            _log(f"[options] Failed to load: {e}")

    if not dpg.does_item_exist("opt_load_fd"):
        with dpg.file_dialog(tag="opt_load_fd", show=False, callback=_on_pick):
            dpg.add_file_extension(".json", color=(100, 200, 255, 255))
            dpg.add_file_extension(".*")
    dpg.configure_item("opt_load_fd", show=True)


def _export_settings_dialog():
    def _on_pick(sender, app_data):
        path = app_data.get("file_path_name")
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(CONFIG, indent=2))
            _log(f"[options] Exported settings to {path}")
        except Exception as e:
            _log(f"[options] Failed to export: {e}")

    if not dpg.does_item_exist("opt_save_fd"):
        with dpg.file_dialog(tag="opt_save_fd", show=False, callback=_on_pick, modal=True):
            dpg.add_file_extension(".json", color=(100, 200, 255, 255))
    dpg.configure_item("opt_save_fd", show=True)


def _reset_defaults_confirm():
    CONFIG.clear()
    CONFIG.update(DEFAULT_CONFIG.copy())
    _save_now()
    _rebind_all()
    _log("[options] Reset to defaults.")


def _rebind_all():
    for item_tag, key in list(BINDER._map.items()):
        if dpg.does_item_exist(item_tag):
            try:
                dpg.set_value(item_tag, CONFIG.get(key))
            except Exception:
                pass


def build_options_window():
    if dpg.does_item_exist("options_win"):
        return
    with dpg.window(tag="options_win", label="Options", pos=(120, 80), width=880, height=660, show=False):
        with dpg.tab_bar():
            with dpg.tab(label="General"):
                _combo_row("Workflow", "opt_workflow", "workflow", ["Analyze & Merge", "Analyze Only"])
                _combo_row("Mode", "opt_mode", "analysis_mode", ["videodiff", "audio_xcorr"])
                _input_text_row("Output folder", "opt_out", "output_folder", hint="Folder for final MKVs")
                _input_text_row("Temp folder", "opt_temp", "temp_root", hint="Scratch working folder")
            with dpg.tab(label="Analysis"):
                _int_row("Scan chunk count", "opt_scan_count", "scan_chunk_count", 1, 128, 1)
                _float_row("Scan chunk duration (s)", "opt_scan_dur", "scan_chunk_duration", 0.1)
                _float_row("Minimum match (0.0–1.0)", "opt_min_match", "min_match_pct", 0.01)
                _checkbox_row("Apply dialog normalization gain", "opt_dialog_norm", "apply_dialog_norm_gain")
            with dpg.tab(label="Chapters"):
                _checkbox_row("Rename chapters", "opt_ren_chap", "rename_chapters")
                _checkbox_row("Snap to keyframes", "opt_snap", "snap_chapters")
                _combo_row("Snap mode", "opt_snap_mode", "snap_mode", ["previous", "next", "nearest"])
                _int_row("Snap threshold (ms)", "opt_snap_thr", "snap_threshold_ms", 0, 5000, 10)
                _checkbox_row("Snap starts only", "opt_snap_starts", "snap_starts_only")
                _checkbox_row("Default to first subtitle", "opt_first_sub", "first_sub_default")
            with dpg.tab(label="Tools"):
                for key, label in [
                    ("ffmpeg_path", "FFmpeg path"),
                    ("ffprobe_path", "FFprobe path"),
                    ("mkvmerge_path", "mkvmerge path"),
                    ("mkvextract_path", "mkvextract path"),
                    ("videodiff_path", "VideoDiff path"),
                ]:
                    with dpg.group(horizontal=True):
                        dpg.add_text(label, width=200)
                        tag = f"opt_{key}"
                        dpg.add_input_text(tag=tag, width=520, callback=BINDER.on_changed)
                        BINDER.bind(tag, key)
                        _browse_button(f"browse_{key}", tag)
            with dpg.tab(label="Logging"):
                _checkbox_row("Autoscroll log", "opt_log_auto", "log_autoscroll")
                _checkbox_row("Compact log", "opt_log_compact", "log_compact")
                _checkbox_row("Error tail", "opt_log_tail", "log_error_tail")
                _int_row("Tail lines", "opt_log_tail_lines", "log_tail_lines", 10, 5000, 10)
            with dpg.tab(label="Advanced"):
                dpg.add_text("Load / Export / Reset settings")
    dpg.add_spacer(height=8)
    with dpg.group(horizontal=True):
        dpg.add_button(label="Save", callback=lambda *_: _save_now())
        dpg.add_button(label="Load…", callback=lambda *_: _load_settings_dialog())
        dpg.add_button(label="Export…", callback=lambda *_: _export_settings_dialog())
        dpg.add_button(label="Reset to Defaults", callback=lambda *_: _reset_defaults_confirm())


def show_options():
    if not dpg.does_item_exist("options_win"):
        build_options_window()
    dpg.configure_item("options_win", show=True)
