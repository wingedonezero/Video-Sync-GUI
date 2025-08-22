
from __future__ import annotations
from pathlib import Path
import dearpygui.dearpygui as dpg
from vsg.settings_core import CONFIG, register_listener

# -----------------------------------------------------------------------------
# Appearance helpers (fail-safe)
# -----------------------------------------------------------------------------

def load_fonts_and_themes():
    """Bind font if provided; otherwise keep default. Safe (wrapped)."""
    try:
        if not dpg.does_item_exist("vsg_font_registry"):
            with dpg.font_registry(tag="vsg_font_registry"):
                pass
        p = CONFIG.get("ui_font_path") or ""
        size = int(CONFIG.get("ui_font_size", 18))
        if p and Path(p).exists():
            try:
                font_id = dpg.add_font(p, size)
                dpg.bind_font(font_id)
            except Exception:
                pass
    except Exception:
        pass

def apply_line_heights():
    """Apply row spacing via a theme."""
    try:
        if dpg.does_item_exist("vsg_theme"):
            dpg.delete_item("vsg_theme")
        with dpg.theme(tag="vsg_theme"):
            with dpg.theme_component(dpg.mvAll):
                gap = int(CONFIG.get("row_gap", 8))
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, gap, gap, category=dpg.mvThemeCat_Core)
        dpg.bind_theme("vsg_theme")
    except Exception:
        pass

def _on_settings_applied():
    try:
        load_fonts_and_themes()
        apply_line_heights()
    except Exception:
        pass

def enable_live_appearance():
    """Call from app AFTER UI exists to enable live updates."""
    try:
        register_listener(_on_settings_applied)
    except Exception:
        pass
