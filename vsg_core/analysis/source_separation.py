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
import time
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

# Model quality database with SDR scores, rankings, and use-case recommendations
# Based on the audio-separator project recommendations and community testing
MODEL_QUALITY_DATABASE = {
    # BS-Roformer models - Best for vocals/instrumental separation
    'model_bs_roformer_ep_317_sdr_12.9755.ckpt': {
        'quality_tier': 'S-Tier',
        'rank': 1,
        'sdr_vocals': 12.9,
        'sdr_instrumental': 17.0,
        'use_cases': ['Instrumental', 'Vocals', 'General Purpose'],
        'recommended': True,
        'description_override': 'Highest quality vocals/instrumental separation. Best overall performance. SLOW: 2-5 min for 3-min audio.',
    },
    'model_bs_roformer_ep_368_sdr_12.9628.ckpt': {
        'quality_tier': 'S-Tier',
        'rank': 2,
        'sdr_vocals': 12.9,
        'sdr_instrumental': 17.0,
        'use_cases': ['Instrumental', 'Vocals', 'General Purpose'],
        'recommended': True,
        'description_override': 'Excellent vocals/instrumental separation. Very close to ep_317. SLOW: 2-5 min for 3-min audio.',
    },
    'deverb_bs_roformer_8_384dim_10depth.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 10,
        'use_cases': ['Reverb Removal', 'Cleanup'],
        'description_override': 'Specialized model for removing reverb from audio.',
    },

    # MelBand Roformer models
    'mel_band_roformer_kim_ft_unwa.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 5,
        'sdr_vocals': 12.4,
        'use_cases': ['Vocals'],
        'description_override': 'Excellent vocals extraction with good instrumental preservation.',
    },
    'vocals_mel_band_roformer.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 6,
        'sdr_vocals': 12.6,
        'use_cases': ['Vocals'],
        'description_override': 'Strong vocals separation model.',
    },
    'mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 11,
        'sdr_vocals': 10.1,
        'use_cases': ['Karaoke', 'Backing Vocals'],
        'description_override': 'Specialized for karaoke - separates lead vocals from backing vocals.',
    },
    'model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 4,
        'sdr_vocals': 11.4,
        'use_cases': ['Vocals', 'Dialogue'],
        'description_override': 'High-quality separation, good for dialogue extraction.',
    },
    'denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt': {
        'quality_tier': 'S-Tier',
        'rank': 9,
        'sdr_vocals': 27.9,
        'use_cases': ['Denoise', 'Cleanup'],
        'description_override': 'Exceptional denoise model with very high SDR.',
    },

    # MDX-Net models
    'MDX23C-8KFFT-InstVoc_HQ_2.ckpt': {
        'quality_tier': 'A-Tier',
        'rank': 3,
        'use_cases': ['Instrumental', 'General Purpose'],
        'recommended': True,
        'description_override': 'High-quality MDX model for instrumental/vocals separation.',
    },
    'UVR-MDX-NET-Inst_HQ_4.onnx': {
        'quality_tier': 'A-Tier',
        'rank': 7,
        'use_cases': ['Instrumental'],
        'description_override': 'Reliable instrumental separation with good performance.',
    },
    'UVR_MDXNET_KARA_2.onnx': {
        'quality_tier': 'B-Tier',
        'rank': 12,
        'use_cases': ['Karaoke'],
        'description_override': 'Karaoke-specific model for backing track creation.',
    },

    # VR Architecture models - Fast but lower quality
    'Kim_Vocal_2.onnx': {
        'quality_tier': 'B-Tier',
        'rank': 13,
        'use_cases': ['Vocals', 'Fast Processing'],
        'description_override': 'Fast vocals extraction, lower quality than Roformer models.',
    },
    'kuielab_a_vocals.onnx': {
        'quality_tier': 'B-Tier',
        'rank': 14,
        'use_cases': ['Vocals', 'Fast Processing'],
        'description_override': 'Quick vocals separation, suitable for batch processing.',
    },
    '4_HP-Vocal-UVR.pth': {
        'quality_tier': 'B-Tier',
        'rank': 15,
        'use_cases': ['Vocals', 'Fast Processing'],
        'description_override': 'Fast VR model for vocals extraction.',
    },
    '2_HP-UVR.pth': {
        'quality_tier': 'B-Tier',
        'rank': 8,
        'use_cases': ['Instrumental', 'Fast Processing'],
        'recommended': True,
        'description_override': 'Fastest instrumental separation. FAST: ~20 sec for 3-min audio. Good speed/quality balance.',
    },
    '6_HP-Karaoke-UVR.pth': {
        'quality_tier': 'B-Tier',
        'rank': 16,
        'use_cases': ['Karaoke', 'Fast Processing'],
        'description_override': 'Fast karaoke model for quick backing track creation.',
    },
    'kuielab_a_bass.onnx': {
        'quality_tier': 'B-Tier',
        'rank': 17,
        'use_cases': ['Bass', 'Multi-Instrument'],
        'description_override': 'Specialized bass extraction model.',
    },
    'kuielab_a_drums.onnx': {
        'quality_tier': 'B-Tier',
        'rank': 18,
        'use_cases': ['Drums', 'Multi-Instrument'],
        'description_override': 'Specialized drums extraction model.',
    },

    # Demucs models - Multi-stem separation
    'htdemucs': {
        'quality_tier': 'A-Tier',
        'rank': 19,
        'use_cases': ['Multi-Instrument', '4-Stem', 'General Purpose'],
        'recommended': True,
        'sdr_vocals': 7.0,  # Approximate, varies by stem
        'description_override': 'Best all-around 4-stem separation (drums/bass/other/vocals). MEDIUM: ~30-60 sec for 3-min audio.',
    },
    'htdemucs_ft': {
        'quality_tier': 'A-Tier',
        'rank': 20,
        'use_cases': ['Multi-Instrument', '4-Stem'],
        'sdr_vocals': 7.2,  # Approximate, fine-tuned version
        'description_override': 'Fine-tuned version of htdemucs with slightly better performance. MEDIUM: ~30-60 sec for 3-min audio.',
    },
    'htdemucs_6s': {
        'quality_tier': 'A-Tier',
        'rank': 21,
        'use_cases': ['Multi-Instrument', '6-Stem', 'Advanced'],
        'sdr_vocals': 6.8,  # Approximate
        'description_override': '6-stem separation including drums/bass/other/vocals/guitar/piano. MEDIUM: ~30-60 sec for 3-min audio.',
    },
    'htdemucs.yaml': {
        'quality_tier': 'A-Tier',
        'rank': 19,
        'use_cases': ['Multi-Instrument', '4-Stem', 'General Purpose'],
        'recommended': True,
        'sdr_vocals': 7.0,
        'description_override': 'Best all-around 4-stem separation (drums/bass/other/vocals). MEDIUM: ~30-60 sec for 3-min audio.',
    },
    'htdemucs_ft.yaml': {
        'quality_tier': 'A-Tier',
        'rank': 20,
        'use_cases': ['Multi-Instrument', '4-Stem'],
        'sdr_vocals': 7.2,
        'description_override': 'Fine-tuned version of htdemucs with slightly better performance. MEDIUM: ~30-60 sec for 3-min audio.',
    },
    'htdemucs_6s.yaml': {
        'quality_tier': 'A-Tier',
        'rank': 21,
        'use_cases': ['Multi-Instrument', '6-Stem', 'Advanced'],
        'sdr_vocals': 6.8,
        'description_override': '6-stem separation including drums/bass/other/vocals/guitar/piano. MEDIUM: ~30-60 sec for 3-min audio.',
    },
}

# Curated list of best-performing models for UI selection.
# These are intentionally limited to avoid overwhelming users with large lists.
CURATED_MODELS: List[Dict[str, str]] = [
    {
        'name': 'Demucs v4: htdemucs',
        'filename': 'htdemucs',
        'description': 'Best all-round 4-stem separation (drums/bass/other/vocals) with strong balance.',
    },
    {
        'name': 'BS-Roformer Viperx 1297 (Highest Quality)',
        'filename': 'model_bs_roformer_ep_317_sdr_12.9755.ckpt',
        'description': 'Top quality 2-stem (vocals SDR 12.9, instrumental SDR 17.0). Best overall performance.',
    },
    {
        'name': 'BS-Roformer Viperx 1296',
        'filename': 'model_bs_roformer_ep_368_sdr_12.9628.ckpt',
        'description': 'High quality 2-stem (vocals SDR 12.9, instrumental SDR 17.0). Alternative to 1297.',
    },
    {
        'name': 'MDX23C: InstVoc HQ',
        'filename': 'model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt',
        'description': 'High-quality 2-stem instrumental/vocals separation. Good for dialogue extraction.',
    },
    {
        'name': 'MelBand Roformer Kim',
        'filename': 'mel_band_roformer_kim_ft_unwa.ckpt',
        'description': 'Reliable vocals extraction with good instrumental preservation (SDR 12.4).',
    },
]


def _extract_sdr_from_filename(filename: str) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract SDR scores from model filename if embedded.

    Many models have SDR scores in their filenames like:
    - model_bs_roformer_ep_317_sdr_12.9755.ckpt -> SDR 12.9755
    - mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt -> SDR 10.1956

    Returns:
        Tuple of (sdr_vocals, sdr_instrumental) if found, (None, None) otherwise.
    """
    # Look for "sdr_XX.XXXX" pattern in filename
    sdr_pattern = r'sdr[_-]?(\d+\.?\d*)'
    match = re.search(sdr_pattern, filename.lower())

    if match:
        sdr_value = float(match.group(1))
        # For 2-stem models, the SDR is typically vocals SDR
        # Instrumental SDR is usually higher (approximate as +4)
        return (sdr_value, sdr_value + 4.0)

    return (None, None)


def _enrich_model_with_quality_data(model: Dict) -> Dict:
    """
    Enrich model metadata with quality database information.

    Adds:
    - Quality tier (S-Tier, A-Tier, B-Tier)
    - Ranking (1 = best)
    - Use case recommendations
    - SDR scores (from database or filename)
    - Better descriptions

    Args:
        model: Model dict with basic info

    Returns:
        Enhanced model dict with quality metadata
    """
    filename = model.get('filename', '')

    # Check if we have quality data for this model
    quality_data = MODEL_QUALITY_DATABASE.get(filename, {})

    # If we have quality data, merge it
    if quality_data:
        # Override SDR if provided in quality database
        if 'sdr_vocals' in quality_data:
            model['sdr_vocals'] = quality_data['sdr_vocals']
        if 'sdr_instrumental' in quality_data:
            model['sdr_instrumental'] = quality_data['sdr_instrumental']

        # Add quality metadata
        model['quality_tier'] = quality_data.get('quality_tier', 'C-Tier')
        model['rank'] = quality_data.get('rank', 999)
        model['use_cases'] = quality_data.get('use_cases', [])
        model['recommended'] = quality_data.get('recommended', False)

        # Override description if provided
        if 'description_override' in quality_data:
            model['description'] = quality_data['description_override']

    # If no SDR data yet, try to extract from filename
    if not model.get('sdr_vocals'):
        sdr_vocals, sdr_instrumental = _extract_sdr_from_filename(filename)
        if sdr_vocals:
            model['sdr_vocals'] = sdr_vocals
        if sdr_instrumental and not model.get('sdr_instrumental'):
            model['sdr_instrumental'] = sdr_instrumental

    # Set default quality tier if not set
    if 'quality_tier' not in model:
        model['quality_tier'] = 'C-Tier'
        model['rank'] = 999

    return model


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


def get_installed_models_json_path(model_dir: Optional[str] = None) -> Path:
    """Get path to installed_models.json file."""
    if model_dir:
        return Path(model_dir) / 'installed_models.json'

    # Default to project .audio_separator_models directory
    project_root = Path(__file__).resolve().parent.parent.parent
    default_dir = project_root / '.audio_separator_models'
    return default_dir / 'installed_models.json'


def get_installed_models(model_dir: Optional[str] = None) -> List[Dict[str, any]]:
    """
    Read installed models from local JSON cache.

    Returns:
        List of model dictionaries with metadata:
        [{'name': ..., 'filename': ..., 'sdr_vocals': ..., 'sdr_instrumental': ...,
          'stems': ..., 'type': ..., 'size_mb': ..., 'description': ...}]
    """
    json_path = get_installed_models_json_path(model_dir)

    if not json_path.exists():
        return []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('models', [])
    except (json.JSONDecodeError, OSError):
        return []


def update_installed_models_json(models: List[Dict], model_dir: Optional[str] = None) -> bool:
    """
    Write/update the installed_models.json file.

    Args:
        models: List of model dictionaries
        model_dir: Model directory path

    Returns:
        True on success, False on failure
    """
    json_path = get_installed_models_json_path(model_dir)

    # Create directory if it doesn't exist
    json_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = {
            'version': '1.0',
            'last_updated': json.dumps(None),  # Will be timestamp
            'models': models
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True
    except (OSError, json.JSONEncodeError):
        return False


def get_all_available_models_from_registry() -> List[Dict]:
    """
    Query audio-separator for the complete model list with metadata.

    Returns:
        List of model dictionaries with all available info from registry.
        Returns empty list if query fails.
    """
    # Method 1: Try using audio-separator CLI
    cli_path = shutil.which('audio-separator')
    if cli_path:
        print(f"[get_all_available_models] Using audio-separator CLI: {cli_path}")
        command = [cli_path, '--list_models', '--list_format=json']

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            print(f"[get_all_available_models] Command completed with return code: {result.returncode}")
            output = result.stdout.strip()

            if output:
                model_data = json.loads(output)
                models = []
                _extract_models_from_registry(model_data, models)
                print(f"[get_all_available_models] Extracted {len(models)} models from CLI")
                return models

        except Exception as e:
            print(f"[get_all_available_models] CLI method failed: {e}")

    # Method 2: Try importing audio-separator directly and loading models.json
    print("[get_all_available_models] Trying to import audio-separator library...")
    try:
        model_data = _load_model_data()
        if model_data:
            print("[get_all_available_models] Loaded models.json from library")
            models = []
            _extract_models_from_registry(model_data, models)
            print(f"[get_all_available_models] Extracted {len(models)} models from library")
            return models
    except Exception as e:
        print(f"[get_all_available_models] Library import method failed: {e}")

    # Method 3: Try using the CLI via the venv Python's Scripts directory
    python_exe = _get_venv_python()
    venv_scripts = Path(python_exe).parent / 'audio-separator'
    if venv_scripts.exists():
        print(f"[get_all_available_models] Found audio-separator in venv scripts: {venv_scripts}")
        command = [str(venv_scripts), '--list_models', '--list_format=json']

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            output = result.stdout.strip()
            if output:
                model_data = json.loads(output)
                models = []
                _extract_models_from_registry(model_data, models)
                print(f"[get_all_available_models] Extracted {len(models)} models from venv script")
                return models

        except Exception as e:
            print(f"[get_all_available_models] Venv script method failed: {e}")

    print("[get_all_available_models] ERROR: All methods failed to load models")
    return []


def _extract_models_from_registry(data: any, models: List[Dict]) -> None:
    """Recursively extract model info from audio-separator's nested JSON structure."""
    if isinstance(data, dict):
        # Check if this looks like a model entry
        if 'filename' in data or 'model_filename' in data:
            filename = data.get('filename') or data.get('model_filename')
            name = data.get('name') or data.get('display_name') or data.get('model_name') or filename

            # Extract SDR scores if available
            sdr_vocals = None
            sdr_instrumental = None
            if 'sdr' in data:
                if isinstance(data['sdr'], dict):
                    sdr_vocals = data['sdr'].get('vocals')
                    sdr_instrumental = data['sdr'].get('instrumental') or data['sdr'].get('other')
                elif isinstance(data['sdr'], (int, float)):
                    sdr_vocals = data['sdr']

            # Determine model type from filename
            model_type = 'Unknown'
            stems = 'Unknown'
            if 'demucs' in filename.lower() and 'htdemucs' in filename.lower():
                model_type = 'Demucs v4'
                stems = '4-stem (Drums/Bass/Other/Vocals)'
            elif 'bs_roformer' in filename.lower() or 'bs-roformer' in filename.lower():
                model_type = 'BS-Roformer'
                stems = '2-stem (Vocals/Instrumental)'
            elif 'mel_band_roformer' in filename.lower() or 'melband' in filename.lower():
                model_type = 'MelBand Roformer'
                stems = '2-stem (Vocals/Instrumental)'
            elif 'mdx' in filename.lower():
                model_type = 'MDX-Net'
                stems = '2-stem (Vocals/Instrumental)'
            elif 'vr' in filename.lower():
                model_type = 'VR Arch'
                stems = '2-stem'

            # Create base model dict
            model = {
                'name': name,
                'filename': filename,
                'sdr_vocals': sdr_vocals,
                'sdr_instrumental': sdr_instrumental,
                'type': model_type,
                'stems': stems,
                'description': data.get('description', ''),
            }

            # Enrich with quality database information and extract SDR from filename
            model = _enrich_model_with_quality_data(model)

            models.append(model)
        else:
            # Recurse into nested structures
            for value in data.values():
                _extract_models_from_registry(value, models)
    elif isinstance(data, list):
        for item in data:
            _extract_models_from_registry(item, models)


def download_model(
    model_filename: str,
    model_dir: str,
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> bool:
    """
    Download a model using audio-separator.

    Args:
        model_filename: The model filename to download
        model_dir: Directory to download to
        progress_callback: Optional callback(percent, message)

    Returns:
        True on success, False on failure
    """
    print(f"[download_model] Attempting to download {model_filename} to {model_dir}")

    # Check if audio-separator is available
    python_exe = _get_venv_python()
    if not _module_available_in_python('audio_separator', python_exe):
        error_msg = (
            "audio-separator is not installed.\n\n"
            "To use model downloading, install it with:\n"
            "  pip install audio-separator\n\n"
            "Or for GPU support:\n"
            "  pip install 'audio-separator[gpu]'"
        )
        print(f"[download_model] ERROR: {error_msg}")
        if progress_callback:
            progress_callback(0, "audio-separator not installed")
        return False

    # Create model directory if it doesn't exist
    Path(model_dir).mkdir(parents=True, exist_ok=True)

    try:
        if progress_callback:
            progress_callback(0, f"Starting download of {model_filename}...")

        # Use the Python API to download the model
        # The Separator class automatically downloads models on initialization
        print(f"[download_model] Importing audio_separator...")

        # Build a Python script to run in subprocess
        download_script = f'''
import sys
sys.path.insert(0, r"{Path(__file__).parent.parent.parent}")
from audio_separator.separator import Separator

# Initialize separator with config
print("[download_model] Creating Separator instance...")
separator = Separator(
    model_file_dir=r"{model_dir}",
    output_dir=r"{model_dir}",
)

# Load the model - this triggers download if not present
print("[download_model] Loading model {model_filename}...")
separator.load_model(model_filename="{model_filename}")
print("[download_model] Model downloaded successfully")
sys.exit(0)
'''

        print(f"[download_model] Running download script...")
        # Redirect stderr to stdout to prevent deadlock from filled stderr buffer
        process = subprocess.Popen(
            [python_exe, '-c', download_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout to prevent deadlock
            text=True,
        )

        # Monitor output for progress
        output_lines = []

        # Read all output line by line (non-blocking since stderr is merged)
        for line in process.stdout:
            line = line.strip()
            if line:
                output_lines.append(line)
                print(f"[download_model] {line}")

            if progress_callback:
                progress_callback(50, "Downloading...")

        # Wait for process to complete
        process.wait()

        if process.returncode == 0:
            if progress_callback:
                progress_callback(100, "Download complete")
            print(f"[download_model] SUCCESS: Model {model_filename} downloaded")
            return True
        else:
            error_output = '\n'.join(output_lines[-10:])  # Last 10 lines
            print(f"[download_model] FAILED with return code {process.returncode}")
            print(f"[download_model] Error output:\n{error_output}")
            if progress_callback:
                progress_callback(0, f"Download failed (exit code {process.returncode})")
            return False

    except Exception as e:
        print(f"[download_model] EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        if progress_callback:
            progress_callback(0, f"Download failed: {str(e)}")
        return False


def list_available_models() -> List[Tuple[str, str]]:
    """
    Get installed models from local JSON cache.
    Falls back to curated list if no local cache exists.

    Returns:
        List of (friendly_name, filename) tuples.
    """
    installed = get_installed_models()

    if not installed:
        # Fallback to curated list
        return [
            (f"{model['name']} — {model['description']}", model['filename'])
            for model in CURATED_MODELS
        ]

    # Build friendly names with metadata
    result = []
    for model in installed:
        name_parts = [model['name']]

        # Add SDR info if available
        if model.get('sdr_vocals'):
            name_parts.append(f"SDR {model['sdr_vocals']}")

        name_parts.append(f"({model['filename']})")
        friendly_name = ' '.join(name_parts)

        result.append((friendly_name, model['filename']))

    return result


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

def cleanup_gpu():
    """Release GPU resources before subprocess exits."""
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass  # torch not available or no GPU

if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    try:
        output_path = run_separation(args)
        print(json.dumps({'success': True, 'output_path': output_path}))
    except Exception as e:
        import traceback
        print(json.dumps({'success': False, 'error': str(e), 'traceback': traceback.format_exc()}))
        cleanup_gpu()
        sys.exit(1)
    finally:
        cleanup_gpu()
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
    timeout_seconds: int = 900,
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
        timeout_seconds: Maximum time to wait for separation (default 900s = 15 min)
                        High-quality models like BS-Roformer can take 5-10 minutes
                        Fast models like Demucs/VR typically take 30-60 seconds

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
            # Enforce reasonable timeout bounds to prevent infinite hangs
            # 0 or negative means "use max timeout" (2 hours), not "no timeout"
            if timeout_seconds <= 0:
                timeout = 7200  # 2 hours max
                log(f"[SOURCE SEPARATION] Using maximum timeout of 2 hours")
            else:
                timeout = min(timeout_seconds, 7200)  # Cap at 2 hours

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

        except subprocess.TimeoutExpired as e:
            log(f"[SOURCE SEPARATION] Timeout after {timeout}s (high-quality models may need more time)")
            log(f"[SOURCE SEPARATION] Consider using a faster model or increasing the timeout in settings")
            # subprocess.run() automatically kills the process on timeout
            # Log that the process was terminated
            log(f"[SOURCE SEPARATION] Subprocess was terminated due to timeout")
            return None
        except Exception as e:
            log(f"[SOURCE SEPARATION] Error: {e}")
            return None


def apply_source_separation(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sample_rate: int,
    config: Dict,
    log_func: Optional[Callable[[str], None]] = None,
    role_tag: str = "Source 2"
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply source separation to both reference and target audio, or neither.

    This is the main entry point called from audio_corr.py.
    If separation fails or is disabled, returns original audio unchanged.

    Selection logic:
    - 'all' → Always separate both sides
    - 'source_2' → Only separate when comparing Source 1 vs Source 2
    - 'source_3' → Only separate when comparing Source 1 vs Source 3

    IMPORTANT: Both sides must be treated the same (both separated OR both original)
    for correlation to work properly. Can't compare separated vs original audio.

    Args:
        ref_pcm: Reference audio (typically Source 1)
        tgt_pcm: Target audio (typically Source 2, Source 3, etc.)
        sample_rate: Sample rate
        config: Configuration dict
        log_func: Optional logging function
        role_tag: Which target is being processed (e.g., "Source 2", "Source 3", "QA")

    Returns:
        Tuple of (ref_pcm, tgt_pcm) - both separated or both original
    """
    log = log_func or (lambda x: None)

    mode, model_filename = _resolve_separation_settings(config)

    target_stem = SEPARATION_MODES.get(mode)
    if target_stem is None:
        return ref_pcm, tgt_pcm

    device = config.get('source_separation_device', 'auto')
    timeout = config.get('source_separation_timeout', 900)
    model_dir = config.get('source_separation_model_dir') or None

    # Check which source was selected
    apply_to = config.get('source_separation_apply_to', 'all').lower()

    # Normalize role_tag to compare (e.g., "Source 2" -> "source_2")
    role_normalized = role_tag.lower().replace(' ', '_')

    # Determine if we should separate for this comparison
    # Logic: Separate BOTH sides if 'all' OR if this comparison involves the selected source
    should_separate = (apply_to == 'all') or (apply_to == role_normalized)

    if not should_separate:
        log(f"[SOURCE SEPARATION] Skipping separation for Source 1 vs {role_tag} (selected: {apply_to})")
        return ref_pcm, tgt_pcm

    log(f"[SOURCE SEPARATION] Mode: {mode}")
    log(f"[SOURCE SEPARATION] Model: {model_filename}")
    log(f"[SOURCE SEPARATION] Applying to Source 1 vs {role_tag} comparison")

    # Separate reference (Source 1)
    log("[SOURCE SEPARATION] Processing reference audio (Source 1)...")
    ref_separated = separate_audio(ref_pcm, sample_rate, mode, model_filename, log, device, timeout, model_dir)
    if ref_separated is None:
        log("[SOURCE SEPARATION] Reference separation failed, using original audio for both")
        return ref_pcm, tgt_pcm

    # Separate target
    log(f"[SOURCE SEPARATION] Processing target audio ({role_tag})...")
    tgt_separated = separate_audio(tgt_pcm, sample_rate, mode, model_filename, log, device, timeout, model_dir)
    if tgt_separated is None:
        log("[SOURCE SEPARATION] Target separation failed, using original audio for both")
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Both sources processed successfully")
    return ref_separated, tgt_separated
