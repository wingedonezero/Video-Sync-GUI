# vsg_core/analysis/source_separation.py
# -*- coding: utf-8 -*-
"""
Audio source separation using Demucs for cross-language correlation.

This module runs Demucs in a subprocess to ensure complete memory cleanup
after processing. When the subprocess exits, all GPU/CPU memory is freed
by the OS - solving the common PyTorch memory leak issue.

Use case: When correlating Japanese and English audio, the vocal tracks
differ completely. By separating and removing vocals, we can correlate
on music/effects which should be identical between releases.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import numpy as np

# Import GPU environment support
try:
    from vsg_core.system.gpu_env import get_subprocess_environment
except ImportError:
    def get_subprocess_environment():
        return os.environ.copy()

# Separation modes available in the UI
SEPARATION_MODES = {
    'None (Use Original Audio)': None,
    'Demucs - Music/Effects (Strip Vocals)': 'no_vocals',
    'Demucs - Vocals Only': 'vocals_only',
}


def _get_venv_python():
    """
    Get the correct Python executable from the current virtual environment.

    When running from a properly activated venv, sys.executable already points
    to the venv Python, so we can just use it directly.

    As a backup, we also check for a .venv directory in the project root.
    """
    # First priority: if we're running from a venv, sys.executable is correct
    # Check if we're in a virtual environment
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        # We're in a venv - sys.executable should point to it
        return sys.executable

    # Backup: Look for .venv in the project directory
    # (In case the app was launched without properly activating the venv)
    project_root = Path(__file__).resolve().parent.parent.parent
    venv_python = project_root / '.venv' / 'bin' / 'python'
    if venv_python.is_file():
        return str(venv_python)

    # Last resort: use whatever Python we're running with
    return sys.executable


def is_demucs_available() -> Tuple[bool, str]:
    """
    Check if Demucs and its dependencies are available.

    Returns:
        Tuple of (available: bool, message: str)
    """
    try:
        import torch
        torch_version = torch.__version__

        # Check for GPU support (works for both CUDA and ROCm)
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            # Check if this is ROCm (HIP) or CUDA
            hip_version = getattr(torch.version, 'hip', None)
            if hip_version:
                gpu_info = f"ROCm GPU: {device_name}"
            else:
                gpu_info = f"CUDA GPU: {device_name}"
        else:
            gpu_info = "CPU only (no CUDA/ROCm detected)"

    except ImportError:
        return False, "PyTorch not installed. Install with: pip install torch"

    try:
        import demucs
        demucs_version = getattr(demucs, '__version__', 'unknown')
    except ImportError:
        return False, f"Demucs not installed (torch {torch_version} found). Install with: pip install demucs"

    return True, f"Demucs {demucs_version}, torch {torch_version}, {gpu_info}"


# --- Subprocess Worker Script ---
# This script runs in a separate process to ensure memory cleanup

_WORKER_SCRIPT = '''
import sys
import json
import numpy as np
from scipy.signal import resample_poly
from math import gcd

def resample_audio(audio_np, orig_sr, target_sr):
    """Resample audio using scipy (no torchaudio needed)."""
    if orig_sr == target_sr:
        return audio_np
    # Use rational resampling for better quality
    g = gcd(orig_sr, target_sr)
    up = target_sr // g
    down = orig_sr // g
    return resample_poly(audio_np, up, down).astype(np.float32)

def run_separation(input_path, output_path, mode, sample_rate, device_preference):
    """Run Demucs separation in isolated process."""
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    # Load audio from temp file
    audio = np.load(input_path)

    # Determine device
    if device_preference == 'cpu':
        device = torch.device('cpu')
    elif torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        device = torch.device('cpu')

    print(f"Using device: {device}", file=sys.stderr)

    # Load model (htdemucs is good balance of quality/speed)
    model = get_model('htdemucs')
    model.to(device)
    model.eval()

    # Resample to 44100 Hz if needed (Demucs expects 44100 Hz)
    if sample_rate != 44100:
        audio = resample_audio(audio, sample_rate, 44100)

    # Prepare audio tensor: (batch, channels, samples)
    # Input is mono float32, convert to stereo for Demucs
    audio_tensor = torch.from_numpy(audio).float()
    if audio_tensor.dim() == 1:
        audio_tensor = audio_tensor.unsqueeze(0).repeat(2, 1)  # mono -> stereo
    audio_tensor = audio_tensor.unsqueeze(0)  # add batch dim
    audio_tensor = audio_tensor.to(device)

    # Apply model
    with torch.no_grad():
        sources = apply_model(model, audio_tensor, device=device)

    # sources shape: (batch, num_sources, channels, samples)
    # htdemucs sources: drums, bass, other, vocals (indices 0,1,2,3)
    sources = sources.squeeze(0)  # remove batch dim

    if mode == 'no_vocals':
        # Combine drums + bass + other (exclude vocals at index 3)
        result = sources[0] + sources[1] + sources[2]
    elif mode == 'vocals_only':
        result = sources[3]
    else:
        # Fallback: return original
        result = sources.sum(dim=0)

    # Convert back to mono
    result = result.mean(dim=0)  # stereo -> mono

    # Move to CPU and convert to numpy
    result_np = result.cpu().numpy().astype(np.float32)

    # Resample back to original sample rate if needed
    if sample_rate != 44100:
        result_np = resample_audio(result_np, 44100, sample_rate)

    # Save result
    np.save(output_path, result_np)

    # Explicit cleanup
    del model, sources, audio_tensor, result
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return True

if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    try:
        run_separation(
            args['input_path'],
            args['output_path'],
            args['mode'],
            args['sample_rate'],
            args['device']
        )
        print(json.dumps({'success': True}))
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
'''


def separate_audio(
    pcm_data: np.ndarray,
    sample_rate: int,
    mode: str,
    log_func: Optional[Callable[[str], None]] = None,
    device: str = 'auto',
    timeout_seconds: int = 300
) -> Optional[np.ndarray]:
    """
    Separate audio using Demucs in an isolated subprocess.

    This function spawns a separate Python process to run Demucs,
    ensuring complete memory cleanup when separation is done.

    Args:
        pcm_data: Input audio as float32 numpy array
        sample_rate: Sample rate of the audio (e.g., 48000)
        mode: Separation mode ('no_vocals' or 'vocals_only')
        log_func: Optional logging function
        device: 'auto', 'cuda', 'rocm', or 'cpu'
        timeout_seconds: Maximum time to wait for separation

    Returns:
        Separated audio as float32 numpy array, or None on failure
    """
    log = log_func or (lambda x: None)

    if mode not in ('no_vocals', 'vocals_only'):
        log(f"[SOURCE SEPARATION] Unknown mode '{mode}', returning original audio")
        return pcm_data

    # Check availability first
    available, msg = is_demucs_available()
    if not available:
        log(f"[SOURCE SEPARATION] Demucs not available: {msg}")
        return None

    log(f"[SOURCE SEPARATION] Starting Demucs separation (mode={mode})...")
    log(f"[SOURCE SEPARATION] {msg}")

    # Create temp files for IPC
    with tempfile.TemporaryDirectory(prefix='demucs_') as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / 'input.npy'
        output_path = temp_path / 'output.npy'
        script_path = temp_path / 'worker.py'

        # Save input audio
        np.save(input_path, pcm_data)

        # Write worker script
        script_path.write_text(_WORKER_SCRIPT)

        # Prepare arguments
        args = {
            'input_path': str(input_path),
            'output_path': str(output_path),
            'mode': mode,
            'sample_rate': sample_rate,
            'device': 'cpu' if device == 'cpu' else 'auto'
        }

        # Run subprocess with venv Python and GPU environment
        python_exe = _get_venv_python()
        log(f"[SOURCE SEPARATION] Using Python: {python_exe}")

        # Get environment with GPU support
        env = get_subprocess_environment()

        try:
            result = subprocess.run(
                [python_exe, str(script_path), json.dumps(args)],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=env  # Pass environment with ROCm variables
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                stdout = result.stdout.strip()
                log(f"[SOURCE SEPARATION] Subprocess failed with code {result.returncode}")
                log(f"[SOURCE SEPARATION] Python executable: {python_exe}")
                log(f"[SOURCE SEPARATION] sys.executable: {sys.executable}")
                if stderr:
                    log(f"[SOURCE SEPARATION] STDERR: {stderr}")
                if stdout:
                    log(f"[SOURCE SEPARATION] STDOUT: {stdout}")
                return None

            # Parse result
            try:
                response = json.loads(result.stdout.strip())
                if not response.get('success'):
                    log(f"[SOURCE SEPARATION] Separation failed: {response.get('error', 'unknown error')}")
                    return None
            except json.JSONDecodeError:
                # Some output but not JSON - might be warnings, check if output exists
                if not output_path.exists():
                    log(f"[SOURCE SEPARATION] No output produced. stdout: {result.stdout[:200]}")
                    return None

            # Load result
            if output_path.exists():
                separated = np.load(output_path)
                log(f"[SOURCE SEPARATION] Separation complete. Output length: {len(separated)} samples")
                return separated
            else:
                log("[SOURCE SEPARATION] Output file not created")
                return None

        except subprocess.TimeoutExpired:
            log(f"[SOURCE SEPARATION] Timeout after {timeout_seconds}s")
            return None
        except Exception as e:
            log(f"[SOURCE SEPARATION] Error: {e}")
            return None


def apply_source_separation(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sample_rate: int,
    config: Dict,
    log_func: Optional[Callable[[str], None]] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply source separation to both reference and target audio.

    This is the main entry point called from audio_corr.py.
    If separation fails or is disabled, returns original audio unchanged.

    Args:
        ref_pcm: Reference audio (float32 numpy array)
        tgt_pcm: Target audio (float32 numpy array)
        sample_rate: Sample rate (e.g., 48000)
        config: Configuration dictionary
        log_func: Optional logging function

    Returns:
        Tuple of (processed_ref, processed_tgt)
    """
    log = log_func or (lambda x: None)

    separation_model = config.get('source_separation_model', 'None (Use Original Audio)')

    # Check if separation is enabled
    mode = SEPARATION_MODES.get(separation_model)
    if mode is None:
        return ref_pcm, tgt_pcm

    device = config.get('source_separation_device', 'auto')
    timeout = config.get('source_separation_timeout', 300)

    log(f"[SOURCE SEPARATION] Mode: {separation_model}")

    # Process reference audio
    log("[SOURCE SEPARATION] Processing reference audio...")
    ref_separated = separate_audio(ref_pcm, sample_rate, mode, log, device, timeout)
    if ref_separated is None:
        log("[SOURCE SEPARATION] Reference separation failed, using original audio")
        return ref_pcm, tgt_pcm

    # Process target audio
    log("[SOURCE SEPARATION] Processing target audio...")
    tgt_separated = separate_audio(tgt_pcm, sample_rate, mode, log, device, timeout)
    if tgt_separated is None:
        log("[SOURCE SEPARATION] Target separation failed, using original audio")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Both sources processed successfully")
    return ref_separated, tgt_separated
