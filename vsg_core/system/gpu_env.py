# vsg_core/system/gpu_env.py
# -*- coding: utf-8 -*-
"""
GPU and hardware acceleration environment setup.

Provides environment variables for subprocesses. PyTorch-specific setup
is handled by the subprocess that actually imports torch (e.g., source separation).

IMPORTANT: GPU detection results are cached to avoid repeated subprocess calls.
After heavy GPU work (like source separation), repeatedly calling rocm-smi
can cause driver state issues leading to segfaults.
"""

import os
import subprocess
from typing import Dict, Optional


# Cache for GPU detection results - prevents repeated rocm-smi/lspci calls
# which can cause issues after heavy GPU work (e.g., source separation)
_gpu_detection_cache: Dict[str, Optional[Dict[str, str]]] = {}
_rocm_env_cache: Optional[Dict[str, str]] = None


def clear_gpu_caches() -> None:
    """
    Clear all cached GPU detection results.

    Call this if you need to force re-detection of GPU information,
    for example after changing hardware or for testing purposes.
    """
    global _gpu_detection_cache, _rocm_env_cache
    _gpu_detection_cache.clear()
    _rocm_env_cache = None


def detect_amd_gpu(use_cache: bool = True) -> Optional[Dict[str, str]]:
    """
    Detect AMD GPU and determine appropriate gfx architecture.

    Results are cached by default to avoid repeated subprocess calls to rocm-smi
    and lspci, which can cause driver state issues after heavy GPU work.

    Args:
        use_cache: If True (default), return cached results if available.
                   Set to False to force re-detection.

    Returns:
        Dict with 'name', 'gfx_version', 'hsa_version' if AMD GPU found, None otherwise
    """
    global _gpu_detection_cache

    cache_key = 'amd_gpu'
    if use_cache and cache_key in _gpu_detection_cache:
        return _gpu_detection_cache[cache_key]

    result = _detect_amd_gpu_impl()
    _gpu_detection_cache[cache_key] = result
    return result


def _detect_amd_gpu_impl() -> Optional[Dict[str, str]]:
    """Internal implementation of AMD GPU detection (uncached)."""
    try:
        # Try rocm-smi first (most reliable)
        result = subprocess.run(
            ['rocm-smi', '--showproductname'],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            gpu_name = None
            for line in result.stdout.splitlines():
                if 'Card Series' in line:
                    gpu_name = line.split('Card Series', 1)[-1]
                    gpu_name = gpu_name.split(':', 1)[-1].strip()
                    break
            if not gpu_name:
                gpu_name = result.stdout.strip()

            if gpu_name:
                # Map common AMD GPUs to gfx architecture
                gfx_map = {
                    'Radeon RX 7900': ('gfx1100', '11.0.0'),
                    'Radeon RX 7800': ('gfx1100', '11.0.0'),
                    'Radeon RX 7700': ('gfx1100', '11.0.0'),
                    'Radeon RX 7600': ('gfx1100', '11.0.0'),
                    'Radeon RX 6900': ('gfx1030', '10.3.0'),
                    'Radeon RX 6800': ('gfx1030', '10.3.0'),
                    'Radeon RX 6700': ('gfx1030', '10.3.0'),
                    'Radeon RX 6600': ('gfx1030', '10.3.0'),
                    'Radeon 890M': ('gfx1151', '11.5.1'),  # Strix Halo
                    'Radeon 780M': ('gfx1103', '11.0.3'),  # Phoenix
                }

                for pattern, (gfx, hsa) in gfx_map.items():
                    if pattern in gpu_name:
                        return {
                            'name': gpu_name,
                            'gfx_version': gfx,
                            'hsa_version': hsa
                        }

                # Generic Radeon detection - use safe defaults
                if 'Radeon' in gpu_name:
                    return {
                        'name': gpu_name,
                        'gfx_version': 'gfx1100',  # Most common modern AMD
                        'hsa_version': '11.0.0'
                    }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: Try lspci
    try:
        result = subprocess.run(
            ['lspci', '-nn'],
            capture_output=True,
            text=True,
            timeout=2
        )

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if 'VGA' in line or 'Display' in line:
                    if 'AMD' in line or 'Radeon' in line:
                        # Extract GPU name from lspci output
                        parts = line.split(':')
                        if len(parts) >= 3:
                            gpu_name = parts[2].strip().split('[')[0].strip()
                            return {
                                'name': gpu_name,
                                'gfx_version': 'gfx1100',
                                'hsa_version': '11.0.0'
                            }
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def get_rocm_environment(use_cache: bool = True) -> Dict[str, str]:
    """
    Get environment variables needed for ROCm GPU support.

    Sets minimal environment variables to prevent warnings/errors.
    PyTorch-specific variables (AMD_VARIANT_PROVIDER_*) are set to safe defaults;
    the subprocess that imports torch will configure itself properly.

    Results are cached by default to avoid repeated GPU detection.

    Args:
        use_cache: If True (default), return cached results if available.

    Returns:
        Dict of environment variables to set
    """
    global _rocm_env_cache

    if use_cache and _rocm_env_cache is not None:
        return _rocm_env_cache.copy()

    env = _get_rocm_environment_impl()

    # Cache the result
    _rocm_env_cache = env.copy()
    return env


def _get_rocm_environment_impl() -> Dict[str, str]:
    """Internal implementation of ROCm environment detection (uncached)."""
    env = {}

    # Find amdgpu.ids path to prevent libdrm warnings
    amdgpu_ids_path = None
    existing_ids_path = os.environ.get('AMDGPU_IDS_PATH')
    existing_libdrm_path = os.environ.get('LIBDRM_AMDGPU_IDS_PATH')
    if existing_ids_path and os.path.exists(existing_ids_path):
        amdgpu_ids_path = existing_ids_path
    elif existing_libdrm_path and os.path.exists(existing_libdrm_path):
        amdgpu_ids_path = existing_libdrm_path
    else:
        for candidate in (
            '/opt/amdgpu/share/libdrm/amdgpu.ids',
            '/usr/share/libdrm/amdgpu.ids',
        ):
            if os.path.exists(candidate):
                amdgpu_ids_path = candidate
                break
        if not amdgpu_ids_path:
            amdgpu_ids_path = '/dev/null'

    env['AMDGPU_IDS_PATH'] = amdgpu_ids_path
    env['LIBDRM_AMDGPU_IDS_PATH'] = amdgpu_ids_path

    # Detect AMD GPU for architecture settings
    gpu_info = detect_amd_gpu()

    if gpu_info:
        # Core ROCm variables
        if not os.environ.get('ROCR_VISIBLE_DEVICES'):
            env['ROCR_VISIBLE_DEVICES'] = '0'

        if not os.environ.get('HIP_VISIBLE_DEVICES'):
            env['HIP_VISIBLE_DEVICES'] = '0'

        # GPU architecture override (needed for newer GPUs not officially supported)
        if not os.environ.get('HSA_OVERRIDE_GFX_VERSION'):
            env['HSA_OVERRIDE_GFX_VERSION'] = gpu_info['hsa_version']

        # PyTorch 2.9+ AMD variant provider variables - use safe defaults
        # The subprocess that imports torch will configure these properly if needed
        if not os.environ.get('AMD_VARIANT_PROVIDER_FORCE_GFX_ARCH'):
            env['AMD_VARIANT_PROVIDER_FORCE_GFX_ARCH'] = gpu_info['gfx_version']

        if not os.environ.get('AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'):
            # Use safe default; subprocess with torch will set correct version
            env['AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'] = '6.4'

        # Workaround for missing amdgpu.ids file (known ROCm bug)
        if not os.environ.get('AMD_TEE_LOG_PATH'):
            env['AMD_TEE_LOG_PATH'] = '/dev/null'

    return env


def get_subprocess_environment(use_cache: bool = True) -> Dict[str, str]:
    """
    Get complete environment for subprocesses with GPU support.

    Returns a copy of current environment with ROCm variables added.
    Safe to pass to subprocess.run(env=...) or subprocess.Popen(env=...).

    Results are cached by default. The cache is based on the ROCm environment
    variables (which are static for the session), combined with a fresh copy
    of os.environ each time (in case environment variables change).

    IMPORTANT: Caching prevents repeated calls to rocm-smi/lspci which can
    cause driver state issues after heavy GPU work (like source separation).

    Args:
        use_cache: If True (default), use cached ROCm environment.

    Returns:
        Complete environment dict
    """
    # Always get a fresh copy of the base environment
    env = os.environ.copy()
    # Get ROCm vars (cached by default to avoid repeated GPU detection)
    rocm_env = get_rocm_environment(use_cache=use_cache)
    env.update(rocm_env)
    return env


def log_gpu_environment(log_func=None):
    """
    Log detected GPU and environment variables for debugging.

    Args:
        log_func: Optional logging function, uses print if None
    """
    log = log_func or print

    gpu_info = detect_amd_gpu()

    if gpu_info:
        log(f"[GPU] Detected: {gpu_info['name']}")
        log(f"[GPU] Architecture: {gpu_info['gfx_version']} (HSA {gpu_info['hsa_version']})")

        rocm_env = get_rocm_environment()
        if rocm_env:
            log("[GPU] ROCm environment variables:")
            for key, value in rocm_env.items():
                log(f"[GPU]   {key}={value}")
    else:
        log("[GPU] No AMD GPU detected, using CPU only")

    # Check if PyTorch can see GPU (only if already imported)
    import sys
    if 'torch' in sys.modules:
        torch = sys.modules['torch']
        try:
            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                hip_version = getattr(torch.version, 'hip', None)
                if hip_version:
                    log(f"[GPU] PyTorch ROCm {hip_version}: {device_name}")
                else:
                    log(f"[GPU] PyTorch CUDA: {device_name}")
            else:
                log("[GPU] PyTorch: CPU only (no CUDA/ROCm)")
        except Exception as e:
            log(f"[GPU] PyTorch GPU check failed: {e}")
    else:
        log("[GPU] PyTorch not loaded in this process")
