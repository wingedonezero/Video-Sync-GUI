from __future__ import annotations
import dearpygui.dearpygui as dpg
from pathlib import Path
from vsg.settings_core import CONFIG, register_listener

_STATE = {"font_tag": None, "theme_tag": None}

def _pick_font_file() -> str | None:
    user = (CONFIG.get("ui_font_path") or "").strip()
    if user and Path(user).exists():
        return user
    for p in [
        "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]:
        if Path(p).exists():
            return p
    return None

def _apply_next_frame(fn):
    try:
        dpg.add_timer(0.01, callback=lambda: fn())
    except Exception:
        try:
            dpg.set_frame_callback(5, lambda: fn())
        except Exception:
            fn()

def load_fonts_and_themes():
    size = int(CONFIG.get("ui_font_size", 18))
    font_path = _pick_font_file()

    # Add (don't delete) a new font and bind it
    if font_path and Path(font_path).exists():
        with dpg.font_registry():
            tag = f"app_font_{size}_{hash(font_path)%10000}"
            if not dpg.does_item_exist(tag):
                dpg.add_font(font_path, size, tag=tag)
            _STATE["font_tag"] = tag
            dpg.bind_font(tag)

    # Build a global theme (mvAll) for padding/spacing
    pad_y = 6 if CONFIG.get("ui_compact_controls") else 10
    pad_x = 8 if CONFIG.get("ui_compact_controls") else 12
    row_gap = int(CONFIG.get("row_gap", 8))

    theme_tag = f"app_theme_{pad_x}_{pad_y}_{row_gap}"
    if not dpg.does_item_exist(theme_tag):
        with dpg.theme(tag=theme_tag):
            with dpg.theme_component(dpg.mvAll):
                try:
                    dpg.add_theme_style(dpg.mvStyleVar_FramePadding, pad_x, pad_y)
                except Exception:
                    pass
                try:
                    dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, row_gap, row_gap)
                except Exception:
                    pass
    _STATE["theme_tag"] = theme_tag
    dpg.bind_theme(theme_tag)

def apply_line_heights():
    h = int(CONFIG.get("input_line_height", 40))
    for tag in ("ref_input", "sec_input", "ter_input"):
        if dpg.does_item_exist(tag):
            try:
                dpg.configure_item(tag, height=h)
            except Exception:
                pass

def _on_settings_applied():
    _apply_next_frame(lambda: (load_fonts_and_themes(), apply_line_heights()))

register_listener(_on_settings_applied)
