from vsg.settings_core import load_settings, adopt_into_app
from vsg.appearance_helper import load_fonts_and_themes, apply_line_heights
from video_sync_gui import build_ui

def main():
    # Ensure CONFIG is loaded and adopted before UI build
    adopt_into_app(load_settings())

    # Build the UI (your build_ui usually creates the context/viewport and shows it)
    build_ui()

    # Apply appearance (font, themes, input heights) immediately after the UI is created
    try:
        load_fonts_and_themes()
        apply_line_heights()
    except Exception:
        # Never crash the app over appearance; fall back silently
        pass

if __name__ == "__main__":
    main()
