# vsg_core/analysis/separation/registry.py
"""
Model discovery, downloading, and caching for audio source separation.
"""

from __future__ import annotations

import importlib.resources as resources
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .models import CURATED_MODELS, enrich_model_with_quality_data


def _get_venv_python() -> str:
    """
    Get the correct Python executable from the current virtual environment.

    When running from a properly activated venv, sys.executable already points
    to the venv Python, so we can just use it directly.

    As a backup, we also check for a .venv directory in the project root.
    """
    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        return sys.executable

    project_root = Path(__file__).resolve().parent.parent.parent.parent
    venv_python = project_root / ".venv" / "bin" / "python"
    if venv_python.is_file():
        return str(venv_python)

    return sys.executable


def _module_available_in_python(module: str, python_exe: str | None = None) -> bool:
    if not python_exe or python_exe == sys.executable:
        return importlib.util.find_spec(module) is not None

    try:
        result = subprocess.run(
            [
                python_exe,
                "-c",
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


def is_audio_separator_available() -> tuple[bool, str]:
    """
    Check if python-audio-separator is available.

    Returns:
        Tuple of (available: bool, message: str)
    """
    if _module_available_in_python("audio_separator"):
        return True, "audio-separator available"

    venv_python = _get_venv_python()
    if _module_available_in_python("audio_separator", venv_python):
        return True, f"audio-separator available via {venv_python}"

    return (
        False,
        'audio-separator not installed. Install with: pip install "audio-separator[gpu]"',
    )


def _load_model_data() -> object:
    try:
        root = resources.files("audio_separator")
    except Exception:
        return None

    candidates = []
    try:
        candidates.append(root / "models.json")
        candidates.extend(root.rglob("models.json"))
    except Exception:
        candidates = candidates or []

    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue

    return None


def _load_model_data_via_cli() -> object:
    import shutil

    cli_path = shutil.which("audio-separator")
    if cli_path:
        command = [cli_path, "-l", "--list_format=json"]
    else:
        command = [
            _get_venv_python(),
            "-m",
            "audio_separator",
            "-l",
            "--list_format=json",
        ]

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


def _collect_models_from_dict(model_data: dict, models: dict[str, str]) -> None:
    for key, value in model_data.items():
        if isinstance(value, dict):
            filename = (
                value.get("filename")
                if isinstance(value.get("filename"), str)
                else None
            )
            if filename and isinstance(key, str):
                models[key] = filename
                continue

            is_file_map = all(
                isinstance(k, str) and isinstance(v, str) for k, v in value.items()
            )
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


def _collect_models_from_list(model_list: list, models: dict[str, str]) -> None:
    for item in model_list:
        if isinstance(item, dict):
            name = (
                item.get("name") or item.get("display_name") or item.get("model_name")
            )
            filename = (
                item.get("filename") or item.get("model_filename") or item.get("file")
            )
            if name and filename:
                models[name] = filename
            else:
                _collect_models_from_dict(item, models)
        elif isinstance(item, list):
            _collect_models_from_list(item, models)


def _select_model_filename(file_map: dict) -> str | None:
    if not isinstance(file_map, dict):
        return None

    preferred_exts = (".ckpt", ".onnx", ".pth", ".pt", ".th")
    for ext in preferred_exts:
        for candidate in file_map.keys():
            if isinstance(candidate, str) and candidate.lower().endswith(ext):
                return candidate

    for candidate in file_map.keys():
        if isinstance(candidate, str) and candidate.lower().endswith((".yaml", ".yml")):
            return candidate

    for candidate in file_map.keys():
        if isinstance(candidate, str):
            return candidate

    return None


def get_installed_models_json_path(model_dir: str | None = None) -> Path:
    """Get path to installed_models.json file."""
    if model_dir:
        return Path(model_dir) / "installed_models.json"

    # Default to project .config/audio_separator_models directory
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    default_dir = project_root / ".config" / "audio_separator_models"
    return default_dir / "installed_models.json"


def get_installed_models(model_dir: str | None = None) -> list[dict[str, Any]]:
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
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("models", [])
    except (json.JSONDecodeError, OSError):
        return []


def update_installed_models_json(
    models: list[dict], model_dir: str | None = None
) -> bool:
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
            "version": "1.0",
            "last_updated": json.dumps(None),  # Will be timestamp
            "models": models,
        }

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return True
    except (OSError, json.JSONEncodeError):
        return False


def get_all_available_models_from_registry() -> list[dict]:
    """
    Query audio-separator for the complete model list with metadata.

    Returns:
        List of model dictionaries with all available info from registry.
        Returns empty list if query fails.
    """
    import shutil

    # Method 1: Try using audio-separator CLI
    cli_path = shutil.which("audio-separator")
    if cli_path:
        print(f"[get_all_available_models] Using audio-separator CLI: {cli_path}")
        command = [cli_path, "--list_models", "--list_format=json"]

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )

            print(
                f"[get_all_available_models] Command completed with return code: {result.returncode}"
            )
            output = result.stdout.strip()

            if output:
                model_data = json.loads(output)
                models: list[dict] = []
                _extract_models_from_registry(model_data, models)
                print(
                    f"[get_all_available_models] Extracted {len(models)} models from CLI"
                )
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
            print(
                f"[get_all_available_models] Extracted {len(models)} models from library"
            )
            return models
    except Exception as e:
        print(f"[get_all_available_models] Library import method failed: {e}")

    # Method 3: Try using the CLI via the venv Python's Scripts directory
    python_exe = _get_venv_python()
    venv_scripts = Path(python_exe).parent / "audio-separator"
    if venv_scripts.exists():
        print(
            f"[get_all_available_models] Found audio-separator in venv scripts: {venv_scripts}"
        )
        command = [str(venv_scripts), "--list_models", "--list_format=json"]

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
                print(
                    f"[get_all_available_models] Extracted {len(models)} models from venv script"
                )
                return models

        except Exception as e:
            print(f"[get_all_available_models] Venv script method failed: {e}")

    print("[get_all_available_models] ERROR: All methods failed to load models")
    return []


def _extract_models_from_registry(data: Any, models: list[dict]) -> None:
    """Recursively extract model info from audio-separator's nested JSON structure."""
    if isinstance(data, dict):
        # Check if this looks like a model entry
        if "filename" in data or "model_filename" in data:
            filename = data.get("filename") or data.get("model_filename")
            name = (
                data.get("name")
                or data.get("display_name")
                or data.get("model_name")
                or filename
            )

            # Extract SDR scores if available
            sdr_vocals = None
            sdr_instrumental = None
            if "sdr" in data:
                if isinstance(data["sdr"], dict):
                    sdr_vocals = data["sdr"].get("vocals")
                    sdr_instrumental = data["sdr"].get("instrumental") or data[
                        "sdr"
                    ].get("other")
                elif isinstance(data["sdr"], (int, float)):
                    sdr_vocals = data["sdr"]

            # Determine model type from filename
            model_type = "Unknown"
            stems = "Unknown"
            if "demucs" in filename.lower() and "htdemucs" in filename.lower():
                model_type = "Demucs v4"
                stems = "4-stem (Drums/Bass/Other/Vocals)"
            elif "bs_roformer" in filename.lower() or "bs-roformer" in filename.lower():
                model_type = "BS-Roformer"
                stems = "2-stem (Vocals/Instrumental)"
            elif (
                "mel_band_roformer" in filename.lower() or "melband" in filename.lower()
            ):
                model_type = "MelBand Roformer"
                stems = "2-stem (Vocals/Instrumental)"
            elif "mdx" in filename.lower():
                model_type = "MDX-Net"
                stems = "2-stem (Vocals/Instrumental)"
            elif "vr" in filename.lower():
                model_type = "VR Arch"
                stems = "2-stem"

            # Create base model dict
            model = {
                "name": name,
                "filename": filename,
                "sdr_vocals": sdr_vocals,
                "sdr_instrumental": sdr_instrumental,
                "type": model_type,
                "stems": stems,
                "description": data.get("description", ""),
            }

            # Enrich with quality database information and extract SDR from filename
            model = enrich_model_with_quality_data(model)

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
    progress_callback: Callable[[int, str], None] | None = None,
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
    if not _module_available_in_python("audio_separator", python_exe):
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
        print("[download_model] Importing audio_separator...")

        # Build a Python script to run in subprocess
        download_script = f"""
import sys
sys.path.insert(0, r"{Path(__file__).parent.parent.parent.parent}")
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
"""

        print("[download_model] Running download script...")
        # Redirect stderr to stdout to prevent deadlock from filled stderr buffer
        process = subprocess.Popen(
            [python_exe, "-c", download_script],
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
            error_output = "\n".join(output_lines[-10:])  # Last 10 lines
            print(f"[download_model] FAILED with return code {process.returncode}")
            print(f"[download_model] Error output:\n{error_output}")
            if progress_callback:
                progress_callback(
                    0, f"Download failed (exit code {process.returncode})"
                )
            return False

    except Exception as e:
        print(f"[download_model] EXCEPTION: {e}")
        import traceback

        traceback.print_exc()
        if progress_callback:
            progress_callback(0, f"Download failed: {e!s}")
        return False


def list_available_models() -> list[tuple[str, str]]:
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
            (f"{model['name']} — {model['description']}", model["filename"])
            for model in CURATED_MODELS
        ]

    # Build friendly names with metadata
    result = []
    for model in installed:
        name_parts = [model["name"]]

        # Add SDR info if available
        if model.get("sdr_vocals"):
            name_parts.append(f"SDR {model['sdr_vocals']}")

        name_parts.append(f"({model['filename']})")
        friendly_name = " ".join(name_parts)

        result.append((friendly_name, model["filename"]))

    return result


def fallback_models() -> dict[str, str]:
    return {model["name"]: model["filename"] for model in CURATED_MODELS}
