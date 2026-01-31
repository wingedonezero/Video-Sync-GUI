# vsg_core/analysis/separation/core.py
"""
Core audio source separation logic using python-audio-separator.

This module runs separation in a subprocess to ensure complete memory cleanup
after processing. When the subprocess exits, all GPU/CPU memory is freed
by the OS - solving common PyTorch/ONNX memory leak issues.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from math import gcd
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

from .models import DEFAULT_MODEL, SEPARATION_MODES
from .registry import _get_venv_python, is_audio_separator_available

# Import GPU environment support
if importlib.util.find_spec("vsg_core.system.gpu_env"):
    from vsg_core.system.gpu_env import get_subprocess_environment
else:

    def get_subprocess_environment():
        return os.environ.copy()


def resample_audio(audio_np: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio using scipy (no torchaudio needed)."""
    if not isinstance(orig_sr, int) or not isinstance(target_sr, int):
        raise TypeError(
            f"Sample rates must be integers, got orig_sr={type(orig_sr).__name__}, target_sr={type(target_sr).__name__}"
        )

    if orig_sr <= 0 or target_sr <= 0:
        raise ValueError(
            f"Sample rates must be positive, got orig_sr={orig_sr}, target_sr={target_sr}"
        )

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

# Limit BLAS threads before numpy import to prevent threading issues
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

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


def _read_audio_file(path: Path) -> tuple[int, np.ndarray]:
    """Read audio file and return (sample_rate, mono float32 array).

    Returns a contiguous copy of the data to ensure no references to
    memory-mapped file data remain after the temp file is deleted.
    """
    sample_rate, data = wavfile.read(path)

    if data.dtype.kind in "iu":
        max_val = np.iinfo(data.dtype).max
        data = data.astype(np.float32) / max_val
    else:
        data = data.astype(np.float32)

    if data.ndim > 1:
        data = data.mean(axis=1)

    # Ensure we have a contiguous copy (not a view into memory-mapped file)
    return sample_rate, np.ascontiguousarray(data)


def _resolve_separation_settings(config: dict) -> tuple[str, str]:
    mode = config.get("source_separation_mode")
    model_filename = config.get("source_separation_model", DEFAULT_MODEL)

    if mode is None:
        legacy_value = config.get("source_separation_model", "")
        legacy_map = {
            "Demucs - Music/Effects (Strip Vocals)": "instrumental",
            "Demucs - Vocals Only": "vocals",
        }
        if legacy_value in legacy_map:
            mode = legacy_map[legacy_value]
            model_filename = DEFAULT_MODEL

    if mode not in SEPARATION_MODES:
        mode = "none"

    return mode, model_filename


def _log_separator_stderr(log: Callable[[str], None], stderr: str) -> None:
    last_progress = -10
    # Fixed regex pattern: single backslash to match pipe character
    progress_pattern = re.compile(r"(\d{1,3})%\|")
    info_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} .* - INFO - ")
    warning_pattern = re.compile(r"^\d{4}-\d{2}-\d{2} .* - (WARNING|ERROR|CRITICAL) - ")
    miopen_pattern = re.compile(r"^MIOpen\(HIP\): Warning")
    for line in stderr.splitlines():
        if not line.strip():
            continue
        if miopen_pattern.match(line) or "MIOpen(HIP): Warning" in line:
            continue
        # Always show DEBUG lines
        if "DEBUG:" in line:
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
                log(
                    f"[SOURCE SEPARATION] Warning: Failed to parse progress from '{line}': {e}"
                )
            continue
        if info_pattern.match(line) and not warning_pattern.match(line):
            continue
        log(f"[SOURCE SEPARATION] {line}")


def is_separation_enabled(config: dict) -> bool:
    mode, _ = _resolve_separation_settings(config)
    return SEPARATION_MODES.get(mode) is not None


def separate_audio(
    pcm_data: np.ndarray,
    sample_rate: int,
    mode: str,
    model_filename: str,
    log_func: Callable[[str], None] | None = None,
    device: str = "auto",
    timeout_seconds: int = 900,
    model_dir: str | None = None,
) -> np.ndarray | None:
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
    # CRITICAL: Set up log function early to ensure we can log any issues
    log = log_func if log_func is not None else (lambda x: None)

    # DIAGNOSTIC: First thing we do - log entry to help debug crashes
    log("[SOURCE SEPARATION] DEBUG: Entered separate_audio()")

    # Flush outputs to ensure we see the log before any potential crash
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass  # Don't fail on flush errors

    # SAFETY: Early validation using only basic Python operations
    # Avoid touching numpy internals until we've validated the basic object
    log("[SOURCE SEPARATION] DEBUG: Validating input...")
    if pcm_data is None:
        log("[SOURCE SEPARATION] ERROR: pcm_data is None")
        return None

    # Check type using string comparison first (safer than isinstance for corrupted objects)
    try:
        type_name = type(pcm_data).__name__
        if type_name != "ndarray":
            log(
                f"[SOURCE SEPARATION] ERROR: pcm_data type is {type_name}, expected ndarray"
            )
            return None
    except Exception as e:
        log(f"[SOURCE SEPARATION] ERROR: Failed to check type: {e}")
        return None

    # SAFETY: Validate array before accessing flags (which touches C memory)
    try:
        # First check basic attributes exist
        if not hasattr(pcm_data, "flags") or not hasattr(pcm_data, "dtype"):
            log("[SOURCE SEPARATION] ERROR: pcm_data missing required array attributes")
            return None

        # Check dtype before flags (dtype is safer to access)
        if pcm_data.dtype != np.float32:
            log(
                f"[SOURCE SEPARATION] DEBUG: Converting dtype from {pcm_data.dtype} to float32"
            )
            pcm_data = pcm_data.astype(np.float32)

        # Now check contiguity and make a copy if needed
        # Making a copy is ALWAYS safer as it ensures we own the memory
        log("[SOURCE SEPARATION] DEBUG: Creating safe array copy...")
        pcm_data = np.array(pcm_data, dtype=np.float32, copy=True, order="C")
        log(
            f"[SOURCE SEPARATION] DEBUG: Array validated - shape={pcm_data.shape}, size={pcm_data.nbytes} bytes"
        )
    except Exception as e:
        log(f"[SOURCE SEPARATION] ERROR: Failed during array validation: {e}")
        return None

    target_stem = SEPARATION_MODES.get(mode)
    if target_stem is None:
        log(f"[SOURCE SEPARATION] Mode '{mode}' disabled, returning original audio")
        return pcm_data

    # Check availability with try/except to catch any potential crashes
    try:
        available, msg = is_audio_separator_available()
    except Exception as e:
        log(
            f"[SOURCE SEPARATION] ERROR: Failed to check audio-separator availability: {e}"
        )
        return None

    if not available:
        log(f"[SOURCE SEPARATION] Audio-separator not available: {msg}")
        return None

    log(
        f"[SOURCE SEPARATION] Starting audio-separator (mode={mode}, model={model_filename})..."
    )
    log(f"[SOURCE SEPARATION] {msg}")
    if model_dir:
        log(f"[SOURCE SEPARATION] Model directory: {model_dir}")

    with tempfile.TemporaryDirectory(prefix="audio_sep_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.wav"
        script_path = temp_path / "worker.py"
        output_dir = temp_path / "output"

        wavfile.write(input_path, sample_rate, pcm_data.astype(np.float32))
        script_path.write_text(_WORKER_SCRIPT)

        args = {
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "target_stem": target_stem,
            "sample_rate": sample_rate,
            "model_filename": model_filename,
            "model_dir": model_dir,
        }

        python_exe = _get_venv_python()
        log(f"[SOURCE SEPARATION] Using Python: {python_exe}")

        env = get_subprocess_environment()
        if device == "cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
            env["ROCR_VISIBLE_DEVICES"] = ""
            env["HIP_VISIBLE_DEVICES"] = ""

        try:
            # Enforce reasonable timeout bounds to prevent infinite hangs
            # 0 or negative means "use max timeout" (2 hours), not "no timeout"
            if timeout_seconds <= 0:
                timeout = 7200  # 2 hours max
                log("[SOURCE SEPARATION] Using maximum timeout of 2 hours")
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
                log(
                    f"[SOURCE SEPARATION] Subprocess failed with code {result.returncode}"
                )
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
                log(
                    f"[SOURCE SEPARATION] Invalid JSON from worker: {result.stdout[:200]}"
                )
                return None

            if not response.get("success"):
                error_msg = response.get("error", "unknown error")
                log(f"[SOURCE SEPARATION] Separation failed: {error_msg}")
                if "traceback" in response:
                    log(f"[SOURCE SEPARATION] Traceback:\n{response['traceback']}")
                return None

            output_path = response.get("output_path")
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
                log("[SOURCE SEPARATION] Invalid audio data from output file")
                return None

            if not isinstance(output_sr, (int, float)) or output_sr <= 0:
                log(
                    f"[SOURCE SEPARATION] Invalid sample rate from output file: {output_sr}"
                )
                return None

            if output_sr != sample_rate:
                try:
                    separated = resample_audio(separated, int(output_sr), sample_rate)
                except Exception as e:
                    log(f"[SOURCE SEPARATION] Resampling failed: {e}")
                    return None

            log(
                f"[SOURCE SEPARATION] Separation complete. Output length: {len(separated)} samples"
            )
            return separated

        except subprocess.TimeoutExpired:
            log(
                f"[SOURCE SEPARATION] Timeout after {timeout}s (high-quality models may need more time)"
            )
            log(
                "[SOURCE SEPARATION] Consider using a faster model or increasing the timeout in settings"
            )
            # subprocess.run() automatically kills the process on timeout
            # Log that the process was terminated
            log("[SOURCE SEPARATION] Subprocess was terminated due to timeout")
            return None
        except Exception as e:
            log(f"[SOURCE SEPARATION] Error: {e}")
            return None


def apply_source_separation(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sample_rate: int,
    config: dict,
    log_func: Callable[[str], None] | None = None,
    role_tag: str = "Source 2",
) -> tuple[np.ndarray, np.ndarray]:
    """
    Apply source separation to both reference and target audio, or neither.

    This is the main entry point called from audio_corr.py.
    If separation fails or is disabled, returns original audio unchanged.

    NOTE: The decision to use source separation is made at the analysis step level
    based on per-source settings (use_source_separation flag in job layout).
    This function is only called when separation has been determined to be needed.

    IMPORTANT: Both sides must be treated the same (both separated OR both original)
    for correlation to work properly. Can't compare separated vs original audio.

    Args:
        ref_pcm: Reference audio (typically Source 1)
        tgt_pcm: Target audio (typically Source 2, Source 3, etc.)
        sample_rate: Sample rate
        config: Configuration dict (contains separation mode, model, device settings)
        log_func: Optional logging function
        role_tag: Which target is being processed (e.g., "Source 2", "Source 3", "QA")

    Returns:
        Tuple of (ref_pcm, tgt_pcm) - both separated or both original
    """
    log = log_func or (lambda x: None)

    log("[SOURCE SEPARATION] DEBUG: Entered apply_source_separation()")

    mode, model_filename = _resolve_separation_settings(config)

    target_stem = SEPARATION_MODES.get(mode)
    if target_stem is None:
        return ref_pcm, tgt_pcm

    device = config.get("source_separation_device", "auto")
    timeout = config.get("source_separation_timeout", 900)
    model_dir = config.get("source_separation_model_dir") or None

    log(f"[SOURCE SEPARATION] Mode: {mode}")
    log(f"[SOURCE SEPARATION] Model: {model_filename}")
    log(f"[SOURCE SEPARATION] Applying to Source 1 vs {role_tag} comparison")

    # SAFETY: Validate inputs before any numpy operations
    log("[SOURCE SEPARATION] DEBUG: Validating input arrays...")
    try:
        if ref_pcm is None or tgt_pcm is None:
            log("[SOURCE SEPARATION] ERROR: Input array is None")
            return ref_pcm, tgt_pcm

        # Quick sanity check on shapes
        ref_shape = ref_pcm.shape
        tgt_shape = tgt_pcm.shape
        log(
            f"[SOURCE SEPARATION] DEBUG: ref_pcm shape={ref_shape}, tgt_pcm shape={tgt_shape}"
        )
    except Exception as e:
        log(f"[SOURCE SEPARATION] ERROR: Failed to validate inputs: {e}")
        return ref_pcm, tgt_pcm

    # CRITICAL: Create defensive copies FIRST, before ANY gc operations.
    # This ensures we have clean, owned memory before triggering any cleanup.
    log("[SOURCE SEPARATION] DEBUG: Creating defensive copies...")
    try:
        ref_pcm_copy = np.array(ref_pcm, dtype=np.float32, copy=True, order="C")
        tgt_pcm_copy = np.array(tgt_pcm, dtype=np.float32, copy=True, order="C")
        log(
            f"[SOURCE SEPARATION] DEBUG: Copies created - ref={ref_pcm_copy.nbytes} bytes, tgt={tgt_pcm_copy.nbytes} bytes"
        )
    except Exception as e:
        log(f"[SOURCE SEPARATION] ERROR: Failed to create copies: {e}")
        return ref_pcm, tgt_pcm

    # Flush before any operations that might crash
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    # NOTE: We deliberately avoid gc.collect() here as it can trigger buggy
    # C extension destructors that corrupt memory state.

    # Separate reference (Source 1)
    log("[SOURCE SEPARATION] Processing reference audio (Source 1)...")
    ref_separated = separate_audio(
        ref_pcm_copy, sample_rate, mode, model_filename, log, device, timeout, model_dir
    )
    if ref_separated is None:
        log(
            "[SOURCE SEPARATION] Reference separation failed, using original audio for both"
        )
        # Just return originals - let Python handle cleanup naturally
        return ref_pcm, tgt_pcm

    # Release ref copy memory - but do NOT gc.collect() yet
    del ref_pcm_copy

    # Small delay between separations to allow subprocess cleanup to complete.
    # This is safer than gc.collect() which can trigger problematic destructors.
    time.sleep(0.2)

    # Separate target
    log(f"[SOURCE SEPARATION] Processing target audio ({role_tag})...")
    log(
        f"[SOURCE SEPARATION] DEBUG: tgt_pcm_copy shape={tgt_pcm_copy.shape}, dtype={tgt_pcm_copy.dtype}"
    )

    # Flush before second separation
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    tgt_separated = separate_audio(
        tgt_pcm_copy, sample_rate, mode, model_filename, log, device, timeout, model_dir
    )

    # Release tgt copy memory
    del tgt_pcm_copy

    if tgt_separated is None:
        log(
            "[SOURCE SEPARATION] Target separation failed, using original audio for both"
        )
        # Return originals - separation failed
        return ref_pcm, tgt_pcm

    log("[SOURCE SEPARATION] Both sources processed successfully")

    # Only do gc at the very end, after all operations are complete
    # and we have valid results to return
    gc.collect()

    return ref_separated, tgt_separated
