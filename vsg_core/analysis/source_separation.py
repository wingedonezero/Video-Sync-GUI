# vsg_core/analysis/source_separation.py
# -*- coding: utf-8 -*-
"""
Audio source separation using python-audio-separator for cross-language correlation.

This module runs separation in a subprocess to ensure complete memory cleanup
after processing. When the subprocess exits, all GPU/CPU memory is freed
by the OS - solving common PyTorch/ONNX memory leak issues.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple, List

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly
from math import gcd

# Import GPU environment support
try:
    from vsg_core.system.gpu_env import get_subprocess_environment
except ImportError:
    def get_subprocess_environment():
        return os.environ.copy()


# Separation modes available in the UI
SEPARATION_MODES = {
    'none': None,
    'instrumental': 'Instrumental',
    'vocals': 'Vocals',
}

DEFAULT_MODEL = 'default'


def _get_venv_python() -> str:
    """
    Get the correct Python executable from the current virtual environment.

    When running from a properly activated venv, sys.executable already points
    to the venv Python, so we can just use it directly.

    As a backup, we also check for a .venv directory in the project root.
    """
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        return sys.executable

    project_root = Path(__file__).resolve().parent.parent.parent
    venv_python = project_root / '.venv' / 'bin' / 'python'
    if venv_python.is_file():
        return str(venv_python)

    return sys.executable


def is_audio_separator_available() -> Tuple[bool, str]:
    """
    Check if python-audio-separator is available.

    Returns:
        Tuple of (available: bool, message: str)
    """
    if importlib.util.find_spec('audio_separator') is None:
        return False, "audio-separator not installed. Install with: pip install \"audio-separator[gpu]\""

    return True, "audio-separator available"


def list_available_models() -> List[Tuple[str, str]]:
    """
    Get available model filenames from audio-separator's bundled model list.

    Returns:
        List of (friendly_name, filename) tuples.
    """
    try:
        import importlib.resources as resources

        with resources.open_text('audio_separator', 'models.json') as f:
            model_data = json.load(f)
    except Exception:
        return []

    models: Dict[str, str] = {}
    for group in model_data.values():
        if isinstance(group, dict):
            models.update(group)

    return sorted(models.items(), key=lambda item: item[0].lower())


def resample_audio(audio_np: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio using scipy (no torchaudio needed)."""
    if orig_sr == target_sr:
        return audio_np
    g = gcd(orig_sr, target_sr)
    up = target_sr // g
    down = orig_sr // g
    return resample_poly(audio_np, up, down).astype(np.float32)


_WORKER_SCRIPT = '''
import json
import sys
from audio_separator.separator import Separator

def run_separation(args):
    separator = Separator(
        output_dir=args['output_dir'],
        output_format='WAV',
        output_single_stem=args['target_stem'],
        sample_rate=args['sample_rate'],
    )

    model_filename = args.get('model_filename')
    if model_filename and model_filename != 'default':
        separator.load_model(model_filename=model_filename)
    else:
        separator.load_model()

    output_files = separator.separate(args['input_path'])
    if not output_files:
        raise RuntimeError('No output files produced by audio-separator')

    return output_files[0]

if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    try:
        output_path = run_separation(args)
        print(json.dumps({'success': True, 'output_path': output_path}))
    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))
        sys.exit(1)
'''


def _read_audio_file(path: Path) -> Tuple[int, np.ndarray]:
    """Read audio file and return (sample_rate, mono float32 array)."""
    sample_rate, data = wavfile.read(path)

    if data.dtype.kind in 'iu':
        max_val = np.iinfo(data.dtype).max
        data = data.astype(np.float32) / max_val
    else:
        data = data.astype(np.float32)

    if data.ndim > 1:
        data = data.mean(axis=1)

    return sample_rate, data


def _resolve_separation_settings(config: Dict) -> Tuple[str, str]:
    mode = config.get('source_separation_mode')
    model_filename = config.get('source_separation_model', DEFAULT_MODEL)

    if mode is None:
        legacy_value = config.get('source_separation_model', '')
        legacy_map = {
            'Demucs - Music/Effects (Strip Vocals)': 'instrumental',
            'Demucs - Vocals Only': 'vocals',
        }
        if legacy_value in legacy_map:
            mode = legacy_map[legacy_value]
            model_filename = DEFAULT_MODEL

    if mode not in SEPARATION_MODES:
        mode = 'none'

    return mode, model_filename


def is_separation_enabled(config: Dict) -> bool:
    mode, _ = _resolve_separation_settings(config)
    return SEPARATION_MODES.get(mode) is not None


def separate_audio(
    pcm_data: np.ndarray,
    sample_rate: int,
    mode: str,
    model_filename: str,
    log_func: Optional[Callable[[str], None]] = None,
    device: str = 'auto',
    timeout_seconds: int = 300
) -> Optional[np.ndarray]:
    """
    Separate audio using python-audio-separator in an isolated subprocess.

    Args:
        pcm_data: Input audio as float32 numpy array
        sample_rate: Sample rate of the audio (e.g., 48000)
        mode: Separation mode ('instrumental' or 'vocals')
        model_filename: Model filename to use (or 'default')
        log_func: Optional logging function
        device: 'auto', 'cpu', 'cuda', 'rocm', or 'mps'
        timeout_seconds: Maximum time to wait for separation

    Returns:
        Separated audio as float32 numpy array, or None on failure
    """
    log = log_func or (lambda x: None)

    target_stem = SEPARATION_MODES.get(mode)
    if target_stem is None:
        log(f"[SOURCE SEPARATION] Mode '{mode}' disabled, returning original audio")
        return pcm_data

    available, msg = is_audio_separator_available()
    if not available:
        log(f"[SOURCE SEPARATION] Audio-separator not available: {msg}")
        return None

    log(f"[SOURCE SEPARATION] Starting audio-separator (mode={mode}, model={model_filename})...")
    log(f"[SOURCE SEPARATION] {msg}")

    with tempfile.TemporaryDirectory(prefix='audio_sep_') as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / 'input.wav'
        script_path = temp_path / 'worker.py'
        output_dir = temp_path / 'output'

        wavfile.write(input_path, sample_rate, pcm_data.astype(np.float32))
        script_path.write_text(_WORKER_SCRIPT)

        args = {
            'input_path': str(input_path),
            'output_dir': str(output_dir),
            'target_stem': target_stem,
            'sample_rate': sample_rate,
            'model_filename': model_filename,
        }

        python_exe = _get_venv_python()
        log(f"[SOURCE SEPARATION] Using Python: {python_exe}")

        env = get_subprocess_environment()
        if device == 'cpu':
            env['CUDA_VISIBLE_DEVICES'] = ''
            env['ROCR_VISIBLE_DEVICES'] = ''
            env['HIP_VISIBLE_DEVICES'] = ''

        try:
            timeout = None if timeout_seconds <= 0 else timeout_seconds
            result = subprocess.run(
                [python_exe, str(script_path), json.dumps(args)],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
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

            if result.stderr:
                for line in result.stderr.splitlines():
                    log(f"[SOURCE SEPARATION] {line}")

            try:
                response = json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                log(f"[SOURCE SEPARATION] Invalid JSON from worker: {result.stdout[:200]}")
                return None

            if not response.get('success'):
                log(f"[SOURCE SEPARATION] Separation failed: {response.get('error', 'unknown error')}")
                return None

            output_path = response.get('output_path')
            if not output_path:
                log("[SOURCE SEPARATION] No output path provided")
                return None

            output_file = Path(output_path)
            if not output_file.exists():
                log(f"[SOURCE SEPARATION] Output file not found: {output_file}")
                return None

            output_sr, separated = _read_audio_file(output_file)
            if output_sr != sample_rate:
                separated = resample_audio(separated, output_sr, sample_rate)

            log(f"[SOURCE SEPARATION] Separation complete. Output length: {len(separated)} samples")
            return separated

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
    """
    log = log_func or (lambda x: None)

    mode, model_filename = _resolve_separation_settings(config)

    target_stem = SEPARATION_MODES.get(mode)
    if target_stem is None:
        return ref_pcm, tgt_pcm

    device = config.get('source_separation_device', 'auto')
    timeout = config.get('source_separation_timeout', 300)

    log(f"[SOURCE SEPARATION] Mode: {mode}")
    log(f"[SOURCE SEPARATION] Model: {model_filename}")

    log("[SOURCE SEPARATION] Processing reference audio...")
    ref_separated = separate_audio(ref_pcm, sample_rate, mode, model_filename, log, device, timeout)
    if ref_separated is None:
        log("[SOURCE SEPARATION] Reference separation failed, using original audio")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Processing target audio...")
    tgt_separated = separate_audio(tgt_pcm, sample_rate, mode, model_filename, log, device, timeout)
    if tgt_separated is None:
        log("[SOURCE SEPARATION] Target separation failed, using original audio")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Both sources processed successfully")
    return ref_separated, tgt_separated
