# vsg_core/analysis/source_separation.py
# -*- coding: utf-8 -*-
"""
Audio source separation using python-audio-separator for cross-language correlation.

This module runs separation in a subprocess to ensure complete memory cleanup
after processing. When the subprocess exits, all GPU/CPU memory is freed
by the OS - solving common PyTorch/ONNX memory leak issues.
"""

from __future__ import annotations

import importlib.resources as resources
import importlib.util
import json
import os
import re
import shutil
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
if importlib.util.find_spec('vsg_core.system.gpu_env'):
    from vsg_core.system.gpu_env import get_subprocess_environment
else:
    def get_subprocess_environment():
        return os.environ.copy()


# Separation modes available in the UI
SEPARATION_MODES = {
    'none': None,
    'instrumental': 'Instrumental',
    'vocals': 'Vocals',
}

DEFAULT_MODEL = 'default'

# Curated list of best-performing models for UI selection.
# These are intentionally limited to avoid overwhelming users with large lists.
CURATED_MODELS: List[Dict[str, str]] = [
    {
        'name': 'Demucs v4: htdemucs',
        'filename': 'htdemucs.yaml',
        'description': 'Best all-round 4-stem separation with strong balance across vocals and instruments.',
    },
    {
        'name': 'Roformer: BandSplit SDR 1053 (Viperx)',
        'filename': 'config_bs_roformer_ep_937_sdr_10.5309.yaml',
        'description': 'High-quality Roformer model with excellent overall stem clarity (vocals + instruments).',
    },
    {
        'name': 'MDX23C: InstVoc HQ',
        'filename': 'model_2_stem_full_band_8k.yaml',
        'description': 'Focused 2-stem instrumental/vocals model; strong for dialogue and music split.',
    },
    {
        'name': 'MDX-Net: Kim Vocal 2',
        'filename': 'Kim_Vocal_2.onnx',
        'description': 'Reliable vocals-only extraction for speech-heavy content.',
    },
    {
        'name': 'Bandit v2: Cinematic Multilang',
        'filename': 'config_dnr_bandit_v2_mus64.yaml',
        'description': 'Dialogue-friendly model for noisy mixes and multilingual sources.',
    },
]


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


def _module_available_in_python(module: str, python_exe: Optional[str] = None) -> bool:
    if not python_exe or python_exe == sys.executable:
        return importlib.util.find_spec(module) is not None

    try:
        result = subprocess.run(
            [
                python_exe,
                '-c',
                (
                    "import importlib.util, sys; "
                    f"sys.exit(0 if importlib.util.find_spec('{module}') else 1)"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


def is_audio_separator_available() -> Tuple[bool, str]:
    """
    Check if python-audio-separator is available.

    Returns:
        Tuple of (available: bool, message: str)
    """
    if _module_available_in_python('audio_separator'):
        return True, "audio-separator available"

    venv_python = _get_venv_python()
    if _module_available_in_python('audio_separator', venv_python):
        return True, f"audio-separator available via {venv_python}"

    return False, "audio-separator not installed. Install with: pip install \"audio-separator[gpu]\""


def _load_model_data() -> object:
    try:
        root = resources.files('audio_separator')
    except Exception:
        return None

    candidates = []
    try:
        candidates.append(root / 'models.json')
        candidates.extend(root.rglob('models.json'))
    except Exception:
        candidates = candidates or []

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            return json.loads(candidate.read_text(encoding='utf-8'))
        except Exception:
            continue

    return None


def _load_model_data_via_cli() -> object:
    cli_path = shutil.which('audio-separator')
    if cli_path:
        command = [cli_path, '-l', '--list_format=json']
    else:
        command = [_get_venv_python(), '-m', 'audio_separator', '-l', '--list_format=json']

    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    output = result.stdout.strip()
    if not output:
        return None

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _collect_models_from_dict(model_data: Dict, models: Dict[str, str]) -> None:
    for key, value in model_data.items():
        if isinstance(value, dict):
            filename = value.get('filename') if isinstance(value.get('filename'), str) else None
            if filename and isinstance(key, str):
                models[key] = filename
                continue

            is_file_map = all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
            if is_file_map and isinstance(key, str):
                selected = _select_model_filename(value)
                if selected:
                    models[key] = selected
                continue

            _collect_models_from_dict(value, models)
        elif isinstance(value, list):
            _collect_models_from_list(value, models)
        elif isinstance(value, str):
            if isinstance(key, str):
                models[key] = value


def _collect_models_from_list(model_list: List, models: Dict[str, str]) -> None:
    for item in model_list:
        if isinstance(item, dict):
            name = (
                item.get('name')
                or item.get('display_name')
                or item.get('model_name')
            )
            filename = (
                item.get('filename')
                or item.get('model_filename')
                or item.get('file')
            )
            if name and filename:
                models[name] = filename
            else:
                _collect_models_from_dict(item, models)
        elif isinstance(item, list):
            _collect_models_from_list(item, models)


def _select_model_filename(file_map: Dict) -> Optional[str]:
    if not isinstance(file_map, dict):
        return None

    preferred_exts = ('.ckpt', '.onnx', '.pth', '.pt', '.th')
    for ext in preferred_exts:
        for candidate in file_map.keys():
            if isinstance(candidate, str) and candidate.lower().endswith(ext):
                return candidate

    for candidate in file_map.keys():
        if isinstance(candidate, str) and candidate.lower().endswith(('.yaml', '.yml')):
            return candidate

    for candidate in file_map.keys():
        if isinstance(candidate, str):
            return candidate

    return None


def list_available_models() -> List[Tuple[str, str]]:
    """
    Get curated model filenames for audio-separator.

    Returns:
        List of (friendly_name, filename) tuples.
    """
    return [
        (f"{model['name']} — {model['description']}", model['filename'])
        for model in CURATED_MODELS
    ]


def _fallback_models() -> Dict[str, str]:
    return {model['name']: model['filename'] for model in CURATED_MODELS}


def resample_audio(audio_np: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio using scipy (no torchaudio needed)."""
    if not isinstance(orig_sr, int) or not isinstance(target_sr, int):
        raise TypeError(f"Sample rates must be integers, got orig_sr={type(orig_sr).__name__}, target_sr={type(target_sr).__name__}")

    if orig_sr <= 0 or target_sr <= 0:
        raise ValueError(f"Sample rates must be positive, got orig_sr={orig_sr}, target_sr={target_sr}")

    if orig_sr == target_sr:
        return audio_np

    g = gcd(orig_sr, target_sr)
    up = target_sr // g
    down = orig_sr // g
    return resample_poly(audio_np, up, down).astype(np.float32)


_WORKER_SCRIPT = '''
import json
import os
import sys
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from audio_separator.separator import Separator

def load_wav_file(path):
    """Load WAV file and return float32 mono audio."""
    sample_rate, data = wavfile.read(path)

    if data.dtype.kind in 'iu':
        max_val = np.iinfo(data.dtype).max
        data = data.astype(np.float32) / max_val
    else:
        data = data.astype(np.float32)

    if data.ndim > 1:
        data = data.mean(axis=1)

    return sample_rate, data

def run_separation(args):
    output_dir = Path(args['output_dir'])

    # Don't use output_single_stem - get all stems and select manually
    separator = Separator(
        output_dir=str(output_dir),
        output_format='WAV',
        sample_rate=args['sample_rate'],
        model_file_dir=args.get('model_dir') or "/tmp/audio-separator-models/",
    )

    model_filename = args.get('model_filename')
    if model_filename and model_filename != 'default':
        separator.load_model(model_filename=model_filename)
    else:
        separator.load_model()

    output_files = separator.separate(args['input_path'])

    # Convert all paths to absolute paths (separator might return relative paths)
    if output_files:
        abs_output_files = []
        for f in output_files:
            if f:
                f_path = Path(f)
                # If path is not absolute, join with output_dir
                if not f_path.is_absolute():
                    f_path = output_dir / f_path
                abs_output_files.append(str(f_path))
        output_files = abs_output_files

    # Debug: List all files in output directory
    all_files = []
    if output_dir.exists():
        all_files = list(output_dir.rglob('*.wav'))
        print(f"DEBUG: Found {len(all_files)} WAV files in {output_dir}", file=sys.stderr)
        for f in all_files:
            print(f"DEBUG: - {f.name}", file=sys.stderr)

    # Debug: What separator.separate() returned
    print(f"DEBUG: separator.separate() returned {len(output_files) if output_files else 0} files", file=sys.stderr)
    if output_files:
        for f in output_files:
            f_path = Path(f)
            exists = f_path.exists()
            print(f"DEBUG: - {f_path.name} (exists={exists})", file=sys.stderr)

    # If separator.separate() returned empty, try to find files manually
    if not output_files and all_files:
        output_files = [str(f) for f in all_files]
        print(f"DEBUG: Using manually discovered files instead", file=sys.stderr)

    if not output_files:
        raise RuntimeError('No output files produced by audio-separator')

    # Find the correct output file for the target stem
    target_stem = args['target_stem']
    selected_file = None

    # Try to find file matching the target stem (case-insensitive)
    for f in output_files:
        if isinstance(f, (str, Path)):
            f_path = Path(f)
            if f_path.exists():
                # Check if filename contains the target stem
                if target_stem.lower() in f_path.name.lower():
                    selected_file = str(f_path)
                    print(f"DEBUG: Selected {f_path.name} for stem {target_stem}", file=sys.stderr)
                    return selected_file

    # For instrumental, need to mix non-vocal stems together
    if not selected_file and target_stem.lower() == 'instrumental':
        # Look for files NOT containing 'vocal'
        non_vocal_files = [f for f in output_files if 'vocal' not in Path(f).name.lower()]

        if len(non_vocal_files) == 0:
            raise RuntimeError('No non-vocal stems found for instrumental mode')
        elif len(non_vocal_files) == 1:
            # Only one non-vocal file, use it directly
            selected_file = str(non_vocal_files[0])
            print(f"DEBUG: Using {Path(selected_file).name} as instrumental (only non-vocal file)", file=sys.stderr)
            return selected_file
        else:
            # Multiple non-vocal stems - need to mix them together (like old Demucs)
            print(f"DEBUG: Mixing {len(non_vocal_files)} non-vocal stems for instrumental", file=sys.stderr)

            mixed_audio = None
            sample_rate = None

            for stem_file in non_vocal_files:
                sr, audio = load_wav_file(Path(stem_file))
                print(f"DEBUG: - Loading {Path(stem_file).name}", file=sys.stderr)

                if sample_rate is None:
                    sample_rate = sr
                    mixed_audio = audio
                else:
                    if sr != sample_rate:
                        raise RuntimeError(f'Sample rate mismatch: {sr} vs {sample_rate}')
                    mixed_audio = mixed_audio + audio

            # Save mixed audio to a new file
            mixed_output = output_dir / 'mixed_instrumental.wav'
            wavfile.write(str(mixed_output), sample_rate, mixed_audio.astype(np.float32))
            print(f"DEBUG: Saved mixed instrumental to {mixed_output.name}", file=sys.stderr)

            return str(mixed_output)

    # For vocals, look for a file with 'vocal' in the name
    if not selected_file and target_stem.lower() == 'vocals':
        vocal_files = [f for f in output_files if 'vocal' in Path(f).name.lower()]
        if vocal_files:
            selected_file = str(vocal_files[0])
            print(f"DEBUG: Selected {Path(selected_file).name} for vocals", file=sys.stderr)
            return selected_file

    # If still no match, use the first file as fallback
    if not selected_file and output_files:
        selected_file = str(output_files[0])
        print(f"DEBUG: Falling back to first file: {Path(selected_file).name}", file=sys.stderr)

    if not selected_file:
        raise RuntimeError(f'Could not find output file for stem: {target_stem}')

    # Verify the file exists before returning
    if not Path(selected_file).exists():
        raise RuntimeError(f'Selected file does not exist: {selected_file}')

    return selected_file

if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    try:
        output_path = run_separation(args)
        print(json.dumps({'success': True, 'output_path': output_path}))
    except Exception as e:
        import traceback
        print(json.dumps({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}))
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


def _log_separator_stderr(log: Callable[[str], None], stderr: str) -> None:
    last_progress = -10
    # Fixed regex pattern: single backslash to match pipe character
    progress_pattern = re.compile(r'(\d{1,3})%\|')
    info_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} .* - INFO - ')
    warning_pattern = re.compile(r'^\d{4}-\d{2}-\d{2} .* - (WARNING|ERROR|CRITICAL) - ')
    miopen_pattern = re.compile(r'^MIOpen\(HIP\): Warning')
    for line in stderr.splitlines():
        if not line.strip():
            continue
        if miopen_pattern.match(line) or 'MIOpen(HIP): Warning' in line:
            continue
        # Always show DEBUG lines
        if 'DEBUG:' in line:
            log(f"[SOURCE SEPARATION] {line}")
            continue
        match = progress_pattern.search(line)
        if match:
            try:
                percent = int(match.group(1))
                if percent == 100 or percent - last_progress >= 10:
                    last_progress = percent
                    log(f"[SOURCE SEPARATION] {line}")
            except (ValueError, TypeError) as e:
                log(f"[SOURCE SEPARATION] Warning: Failed to parse progress from '{line}': {e}")
            continue
        if info_pattern.match(line) and not warning_pattern.match(line):
            continue
        log(f"[SOURCE SEPARATION] {line}")


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
    timeout_seconds: int = 300,
    model_dir: Optional[str] = None,
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
    if model_dir:
        log(f"[SOURCE SEPARATION] Model directory: {model_dir}")

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
            'model_dir': model_dir,
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
                    _log_separator_stderr(log, stderr)
                if stdout:
                    log(f"[SOURCE SEPARATION] STDOUT: {stdout}")
                return None

            if result.stderr:
                _log_separator_stderr(log, result.stderr)

            try:
                response = json.loads(result.stdout.strip())
            except json.JSONDecodeError:
                log(f"[SOURCE SEPARATION] Invalid JSON from worker: {result.stdout[:200]}")
                return None

            if not response.get('success'):
                error_msg = response.get('error', 'unknown error')
                log(f"[SOURCE SEPARATION] Separation failed: {error_msg}")
                if 'traceback' in response:
                    log(f"[SOURCE SEPARATION] Traceback:\n{response['traceback']}")
                return None

            output_path = response.get('output_path')
            if not output_path:
                log("[SOURCE SEPARATION] No output path provided")
                return None

            output_file = Path(output_path)
            if not output_file.exists():
                log(f"[SOURCE SEPARATION] Output file not found: {output_file}")
                return None

            try:
                output_sr, separated = _read_audio_file(output_file)
            except Exception as e:
                log(f"[SOURCE SEPARATION] Failed to read output file: {e}")
                return None

            if output_sr is None or separated is None:
                log(f"[SOURCE SEPARATION] Invalid audio data from output file")
                return None

            if not isinstance(output_sr, (int, float)) or output_sr <= 0:
                log(f"[SOURCE SEPARATION] Invalid sample rate from output file: {output_sr}")
                return None

            if output_sr != sample_rate:
                try:
                    separated = resample_audio(separated, int(output_sr), sample_rate)
                except Exception as e:
                    log(f"[SOURCE SEPARATION] Resampling failed: {e}")
                    return None

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
    model_dir = config.get('source_separation_model_dir') or None

    log(f"[SOURCE SEPARATION] Mode: {mode}")
    log(f"[SOURCE SEPARATION] Model: {model_filename}")

    log("[SOURCE SEPARATION] Processing reference audio...")
    ref_separated = separate_audio(ref_pcm, sample_rate, mode, model_filename, log, device, timeout, model_dir)
    if ref_separated is None:
        log("[SOURCE SEPARATION] Reference separation failed, using original audio")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Processing target audio...")
    tgt_separated = separate_audio(tgt_pcm, sample_rate, mode, model_filename, log, device, timeout, model_dir)
    if tgt_separated is None:
        log("[SOURCE SEPARATION] Target separation failed, using original audio")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Both sources processed successfully")
    return ref_separated, tgt_separated
