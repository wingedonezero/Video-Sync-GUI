# vsg_qt/subtitle_editor/subprocess_launcher.py
"""
Subprocess launcher for the subtitle editor.

This module allows the subtitle editor to run in a completely separate
process, isolating MPV/OpenGL from the main application. When the
subprocess exits, all its resources are cleaned up by the OS.

Usage:
    python -m vsg_qt.subtitle_editor.subprocess_launcher <params_file> <result_file>

JSON Format (v1.0):

Input params:
{
    "version": "1.0",
    "session_id": "abc12345",
    "subtitle_path": "/path/to/subtitle.ass",
    "video_path": "/path/to/video.mkv",
    "fonts_dir": "/tmp/vsg_fonts_video/",
    "existing_state": {
        "style_patch": {"StyleName": {"fontsize": 48, ...}},
        "font_replacements": {"OriginalFont": "ReplacementFont"},
        "filter_config": {"mode": "include", "styles": ["Signs"]}
    }
}

Output result:
{
    "version": "1.0",
    "session_id": "abc12345",
    "accepted": true,
    "style_patch": {...},
    "font_replacements": {...},
    "filter_config": {...},
    "error": null
}
"""
import json
import sys
from pathlib import Path


def main():
    """Main entry point for subprocess."""
    if len(sys.argv) != 3:
        print("Usage: python -m vsg_qt.subtitle_editor.subprocess_launcher <params_file> <result_file>")
        sys.exit(1)

    params_file = Path(sys.argv[1])
    result_file = Path(sys.argv[2])

    # Read parameters
    with open(params_file) as f:
        params = json.load(f)

    # Handle versioned format (v1.0+) and legacy format
    version = params.get('version', '0.0')
    session_id = params.get('session_id', '')

    if version >= '1.0':
        # New format with existing_state
        existing_state = params.get('existing_state', {})
        existing_style_patch = existing_state.get('style_patch', {})
        existing_font_replacements = existing_state.get('font_replacements', {})
        existing_filter_config = existing_state.get('filter_config', {})
    else:
        # Legacy format
        existing_style_patch = {}
        existing_font_replacements = params.get('existing_font_replacements', {})
        existing_filter_config = {}

    # Initialize Qt application for this subprocess
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # Import and create the editor
    from vsg_qt.subtitle_editor.editor_window import SubtitleEditorWindow

    error_msg = None
    try:
        editor = SubtitleEditorWindow(
            subtitle_path=params['subtitle_path'],
            video_path=params['video_path'],
            fonts_dir=params.get('fonts_dir'),
            existing_font_replacements=existing_font_replacements,
            existing_style_patch=existing_style_patch,
            existing_filter_config=existing_filter_config,
            parent=None  # No parent in subprocess
        )

        # Run the dialog
        result_code = editor.exec()
        accepted = result_code == 1  # QDialog.Accepted = 1

        # Collect results
        if accepted:
            style_patch = editor.get_style_patch()
            font_replacements = editor.get_font_replacements()
            filter_config = editor.get_filter_config()
        else:
            style_patch = {}
            font_replacements = {}
            filter_config = {}

    except Exception as e:
        import traceback
        error_msg = f"{e}\n{traceback.format_exc()}"
        accepted = False
        style_patch = {}
        font_replacements = {}
        filter_config = {}

    # Write results (versioned format)
    result = {
        'version': '1.0',
        'session_id': session_id,
        'accepted': accepted,
        'style_patch': style_patch,
        'font_replacements': font_replacements,
        'filter_config': filter_config,
        'error': error_msg
    }

    with open(result_file, 'w') as f:
        json.dump(result, f, indent=2)

    # Clean exit
    sys.exit(0 if accepted or error_msg is None else 1)


if __name__ == '__main__':
    main()
