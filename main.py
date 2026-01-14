#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Video/Audio Sync & Merge — PyQt6/PySide6 Edition
Main application entry point.
"""

import sys
from PySide6.QtWidgets import QApplication
from vsg_qt.main_window import MainWindow

def main():
    """Initializes and runs the PyQt application."""
    # Log GPU environment for debugging
    try:
        from vsg_core.system.gpu_env import log_gpu_environment
        print("\n" + "="*60)
        print("Video Sync GUI - Startup Diagnostics")
        print("="*60)
        log_gpu_environment(print)
        print("="*60 + "\n")
    except Exception as e:
        print(f"[GPU] Warning: Could not detect GPU environment: {e}")

    app = QApplication(sys.argv)
    app.setApplicationName("Video Sync & Merge")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
