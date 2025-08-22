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
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
