"""
App entry that defers to the existing GUI, but gives us a stable entrypoint.
"""
from video_sync_gui import build_ui
if __name__ == "__main__":
    build_ui()
