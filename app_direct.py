# app_direct.py
from __future__ import annotations
import dearpygui.dearpygui as dpg

# build_ui() constructs the UI; settings are preloaded by video_sync_gui via `import vsg.boot`
from video_sync_gui import build_ui


def main() -> None:
    # 1) Create DPG context + viewport
    dpg.create_context()
    dpg.create_viewport(title="Video/Audio Sync & Merge", width=1200, height=800)

    # 2) Build your UI (no context creation inside build_ui)
    build_ui()

    # 3) Setup + show + run
    dpg.setup_dearpygui()
    dpg.show_viewport()
    try:
        dpg.start_dearpygui()
    finally:
        # 4) Always destroy context to avoid exit segfaults
        dpg.destroy_context()


if __name__ == "__main__":
    main()
