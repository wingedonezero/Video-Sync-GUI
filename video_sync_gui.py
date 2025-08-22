from __future__ import annotations

# Ensure settings_gui.json is loaded before building any UI
import vsg.boot  # side-effect: preload_from_disk()

import dearpygui.dearpygui as dpg

from vsg.settings_core import CONFIG, notify_settings_applied, on_change
from vsg.ui.options_modal import show_options_modal
from vsg.appearance_helper import enable_live_appearance, load_fonts_and_themes, apply_line_heights

# --- Optional analysis functions (use existing ones if present) ----------------
try:
    from analyze_only import do_analyze_only as _do_analyze_only
except Exception:  # noqa: BLE001
    _do_analyze_only = None

try:
    from analyze_and_merge import do_analyze_and_merge as _do_analyze_and_merge
except Exception:  # noqa: BLE001
    _do_analyze_and_merge = None


# --- Small helpers -------------------------------------------------------------

def _log(msg: str) -> None:
    """Append a line to the log box if it exists."""
    try:
        prev = dpg.get_value("log_multiline")
        dpg.set_value("log_multiline", (prev + msg + "\n") if prev else (msg + "\n"))
    except Exception:
        pass


def _run_analyze_only() -> None:
    if _do_analyze_only is None:
        _log("[FAILED] Analyze Only: function not found (do_analyze_only).")
        return
    _log("=== Job start (Analyze Only) ===")
    try:
        _do_analyze_only()
        _log("=== Job complete ===")
    except Exception as e:  # noqa: BLE001
        _log(f"[FAILED] {e!r}")
        _log("=== Job complete (failed) ===")


def _run_analyze_and_merge() -> None:
    if _do_analyze_and_merge is None:
        _log("[FAILED] Analyze & Merge: function not found (do_analyze_and_merge).")
        return
    _log("=== Job start (Analyze & Merge) ===")
    try:
        _do_analyze_and_merge()
        _log("=== Job complete ===")
    except Exception as e:  # noqa: BLE001
        _log(f"[FAILED] {e!r}")
        _log("=== Job complete (failed) ===")


def _sync_header_from_config() -> None:
    """Reflect CONFIG into the small header controls."""
    try:
        if dpg.does_item_exist("wf_combo"):
            dpg.set_value("wf_combo", CONFIG.get("workflow", "Analyze & Merge"))
        if dpg.does_item_exist("mode_combo"):
            dpg.set_value("mode_combo", CONFIG.get("analysis_mode", "Audio Correlation"))
    except Exception:
        pass


# Listener: when settings are applied elsewhere (Save/Load), reflect in header
def _on_settings_applied() -> None:
    _sync_header_from_config()
    # Re-apply appearance on-the-fly
    try:
        load_fonts_and_themes()
        apply_line_heights()
    except Exception:
        pass
    _log("Settings applied to UI.")


# --- UI construction -----------------------------------------------------------

def build_ui() -> None:
    """
    Build the main window controls.
    Assumes context/viewport are created by your launcher (e.g., app_direct.py).
    """
    # Hook live appearance updates
    enable_live_appearance()
    # Also listen for settings-changed notifications (Save/Load from Options modal)
    try:
        from vsg.settings_core import register_listener
        register_listener(_on_settings_applied)
    except Exception:
        pass

    # Apply appearance once on build
    load_fonts_and_themes()
    apply_line_heights()

    # Main window (use an existing primary window if you already have one)
    if not dpg.does_item_exist("main_window"):
        with dpg.window(tag="main_window", label="Video/Audio Sync & Merge — GUI v2", width=1150, height=700):
            pass

    dpg.focus_item("main_window")
    with dpg.group(parent="main_window"):
        # Top row – Options button
        with dpg.group(horizontal=True):
            dpg.add_button(tag="options_btn_main", label="Options…",
                           callback=lambda: show_options_modal())

        # Inputs rows
        dpg.add_text("Reference")
        dpg.add_input_text(tag="inp_ref", width=900)
        dpg.add_text("Secondary")
        dpg.add_input_text(tag="inp_sec", width=900)
        dpg.add_text("Tertiary")
        dpg.add_input_text(tag="inp_ter", width=900)

        # Settings header (workflow/mode only; detailed values live in Options)
        dpg.add_separator()
        dpg.add_text("Settings")
        with dpg.group(horizontal=True):
            dpg.add_text("Workflow")
            dpg.add_combo(tag="wf_combo",
                          items=["Analyze Only", "Analyze & Merge"],
                          default_value=CONFIG.get("workflow", "Analyze & Merge"),
                          width=200,
                          callback=lambda s, a: on_change(s, a, "workflow"))
            dpg.add_text("Mode")
            dpg.add_combo(tag="mode_combo",
                          items=["Audio Correlation", "VideoDiff"],
                          default_value=CONFIG.get("analysis_mode", "Audio Correlation"),
                          width=220,
                          callback=lambda s, a: on_change(s, a, "analysis_mode"))

        # Actions row
        dpg.add_separator()
        dpg.add_text("Actions")
        with dpg.group(horizontal=True):
            dpg.add_button(tag="btn_analyze_only", label="Analyze Only", width=150,
                           callback=_run_analyze_only)
            dpg.add_button(tag="btn_analyze_merge", label="Analyze & Merge", width=180,
                           callback=_run_analyze_and_merge)
            # Simple progress placeholder and status
            with dpg.group():
                dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=400)
            dpg.add_text(tag="status_text", default_value="Status:")

        # Results
        dpg.add_separator()
        dpg.add_text("Results (latest job)")
        with dpg.group(horizontal=True):
            dpg.add_text("Secondary delay:  ?")
            dpg.add_text("|")
            dpg.add_text("Tertiary delay:  ?")

        # Log
        dpg.add_separator()
        dpg.add_text("Log")
        dpg.add_input_text(tag="log_multiline", multiline=True, readonly=True, width=1100, height=320)

    # Reflect current settings into the small header
    _sync_header_from_config()
    # Tell any subscribers that UI is ready to consume settings
    notify_settings_applied()
    _log("Settings initialized/updated with defaults.")
    _log("Settings applied to UI.")
