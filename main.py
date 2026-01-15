#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Video/Audio Sync & Merge — PyQt6/PySide6 Edition
Main application entry point.
"""

import os
import sys

# Note: NANOBIND_DISABLE_LEAK_CHECK was previously needed due to VideoTimestamps cache leaks
# This has been fixed by implementing proper cleanup in frame_utils.clear_vfr_cache()
# os.environ.setdefault("NANOBIND_DISABLE_LEAK_CHECK", "1")

from PySide6.QtWidgets import QApplication
from vsg_qt.main_window import MainWindow

def main():
    """Initializes and runs the PyQt application."""
    app = QApplication(sys.argv)
    app.setApplicationName("Video Sync & Merge")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
