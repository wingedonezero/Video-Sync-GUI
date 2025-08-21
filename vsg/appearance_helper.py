from __future__ import annotations
import dearpygui.dearpygui as dpg
from pathlib import Path
from vsg.settings_core import CONFIG, register_listener

# Store created resources
__FONT_TAG = "app_font_main"
__THEME_INPUT = "theme_input"
__THEME_CTRL = "theme_ctrl"

def _try_font_candidates(size: int) -> str | None:
    candidates = [
        "DejaVuSans.ttf", "DejaVuSans/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return None

def load_fonts_and_themes():
    # Font
    if dpg.does_item_exist(__FONT_TAG):
        dpg.delete_item(__FONT_TAG)
    font_file = CONFIG.get("ui_font_path") or _try_font_candidates(int(CONFIG.get("ui_font_size", 18)))
    size = int(CONFIG.get("ui_font_size", 18))
    with dpg.font_registry():
        if font_file and Path(font_file).exists():
            dpg.add_font(font_file, size, tag=__FONT_TAG)
    if dpg.does_item_exist(__FONT_TAG):
        dpg.bind_font(__FONT_TAG)

    # Themes
    row_gap = int(CONFIG.get("row_gap", 8))
    compact = bool(CONFIG.get("ui_compact_controls", False))
    pad_y = 6 if compact else 10
    pad_x = 8 if compact else 12

    for tag in (__THEME_INPUT, __THEME_CTRL):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    with dpg.theme(tag=__THEME_INPUT):
        with dpg.theme_component(dpg.mvInputText):
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding, pad_x, pad_y)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, row_gap, row_gap)
    with dpg.theme(tag=__THEME_CTRL):
        for comp in (dpg.mvCombo, dpg.mvButton, dpg.mvProgressBar):
            with dpg.theme_component(comp):
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, pad_x, pad_y)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, row_gap, row_gap)

def rebind_ui_appearance():
    # bind font
    if dpg.does_item_exist(__FONT_TAG):
        dpg.bind_font(__FONT_TAG)
    # bind themes (existing items keep their theme but new ones need defaults)
    pass

def apply_line_heights():
    h = int(CONFIG.get("input_line_height", 40))
    for tag in ("ref_input", "sec_input", "ter_input"):
        if dpg.does_item_exist(tag):
            try:
                dpg.configure_item(tag, height=h)
            except Exception:
                pass

def _on_settings_applied():
    load_fonts_and_themes()
    apply_line_heights()

# ensure live updates after load/save
register_listener(_on_settings_applied)
