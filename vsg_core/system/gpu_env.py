# vsg_core/system/gpu_env.py
# -*- coding: utf-8 -*-
"""
GPU and hardware acceleration environment setup.

SIMPLIFIED: Just returns os.environ.copy() for subprocesses.
The source separation subprocess handles its own PyTorch/GPU setup internally.
ffprobe/ffmpeg/mkvmerge don't need any special GPU environment variables.
"""

import os
from typing import Dict


def get_subprocess_environment() -> Dict[str, str]:
    """
    Get environment for subprocesses.

    Simply returns a copy of the current environment. Subprocesses that need
    GPU support (like source separation) handle their own setup internally.

    Returns:
        Copy of current environment dict
    """
    return os.environ.copy()
