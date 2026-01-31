#!/usr/bin/env python3

"""
Video/Audio Sync & Merge — PyQt6/PySide6 Edition
Main application entry point.
"""

# Enable faulthandler FIRST to catch segfaults and print tracebacks
# This helps diagnose crashes in native code (numpy, scipy, torch, etc.)
import faulthandler
import os
import sys

faulthandler.enable()

# Limit BLAS/OpenBLAS threads to prevent threading issues with scipy/numpy
# This MUST be set before numpy is imported anywhere
# Helps prevent segfaults when running multiple source separation jobs
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

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

    exit_code = app.exec()

    # Final cleanup before Python shutdown to prevent nanobind leaks
    # This runs after Qt cleanup but before Python's module teardown
    try:
        from vsg_core.subtitles.frame_utils import clear_vfr_cache

        clear_vfr_cache()
    except ImportError:
        pass

    # Force final garbage collection before exit
    import gc

    gc.collect()
    gc.collect()  # Run twice for good measure

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
