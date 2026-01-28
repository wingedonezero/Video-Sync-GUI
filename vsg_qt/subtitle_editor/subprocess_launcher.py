# vsg_qt/subtitle_editor/subprocess_launcher.py
# -*- coding: utf-8 -*-
"""
Subprocess launcher for the subtitle editor.

This module allows the subtitle editor to run in a completely separate
process, isolating MPV/OpenGL from the main application. When the
subprocess exits, all its resources are cleaned up by the OS.

Usage:
    python -m vsg_qt.subtitle_editor.subprocess_launcher <params_file> <result_file>
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
    with open(params_file, 'r') as f:
        params = json.load(f)

    # Initialize Qt application for this subprocess
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)

    # Import and create the editor
    from vsg_qt.subtitle_editor.editor_window import SubtitleEditorWindow

    editor = SubtitleEditorWindow(
        subtitle_path=params['subtitle_path'],
        video_path=params['video_path'],
        fonts_dir=params.get('fonts_dir'),
        existing_font_replacements=params.get('existing_font_replacements'),
        parent=None  # No parent in subprocess
    )

    # Run the dialog
    result_code = editor.exec()

    # Collect results
    result = {
        'accepted': result_code == 1,  # QDialog.Accepted = 1
        'style_patch': {},
        'font_replacements': {},
        'filter_config': {}
    }

    if result['accepted']:
        result['style_patch'] = editor.get_style_patch()
        result['font_replacements'] = editor.get_font_replacements()
        result['filter_config'] = editor.get_filter_config()

    # Write results
    with open(result_file, 'w') as f:
        json.dump(result, f)

    # Clean exit
    sys.exit(0)


if __name__ == '__main__':
    main()
