# vsg_core/system/gpu_env.py
# -*- coding: utf-8 -*-
"""
GPU and hardware acceleration environment setup.

Automatically detects AMD ROCm GPUs and sets necessary environment variables
for PyTorch, PyAV, and other GPU-accelerated libraries.
"""

import os
import subprocess
from typing import Dict, Optional


def detect_amd_gpu() -> Optional[Dict[str, str]]:
    """
    Detect AMD GPU and determine appropriate gfx architecture.

    Returns:
        Dict with 'name', 'gfx_version', 'hsa_version' if AMD GPU found, None otherwise
    """
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


def get_rocm_environment() -> Dict[str, str]:
    """
    Get environment variables needed for ROCm GPU support.

    Detects AMD GPU and returns appropriate environment variables for:
    - PyTorch ROCm GPU detection
    - PyAV/FFmpeg GPU access
    - Fixing common ROCm issues (missing amdgpu.ids, etc.)

    Returns:
        Dict of environment variables to set
    """
    env = {}

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

    if not existing_ids_path or not os.path.exists(existing_ids_path):
        env['AMDGPU_IDS_PATH'] = amdgpu_ids_path
    if not existing_libdrm_path or not os.path.exists(existing_libdrm_path):
        env['LIBDRM_AMDGPU_IDS_PATH'] = amdgpu_ids_path

    # Detect AMD GPU
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

        # PyTorch 2.9+ AMD variant provider variables
        if not os.environ.get('AMD_VARIANT_PROVIDER_FORCE_GFX_ARCH'):
            env['AMD_VARIANT_PROVIDER_FORCE_GFX_ARCH'] = gpu_info['gfx_version']

        if not os.environ.get('AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'):
            # Extract ROCm version from torch if available
            try:
                import torch
                if hasattr(torch.version, 'hip'):
                    hip_version = torch.version.hip
                    if hip_version:
                        # Extract major.minor from version string like "6.4.41134"
                        rocm_version = '.'.join(hip_version.split('.')[:2])
                        env['AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'] = rocm_version
                    else:
                        env['AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'] = '6.4'
                else:
                    env['AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'] = '6.4'
            except ImportError:
                env['AMD_VARIANT_PROVIDER_FORCE_ROCM_VERSION'] = '6.4'

        # Workaround for missing amdgpu.ids file (known ROCm bug)
        # Set to empty to disable file lookup that causes errors
        if not os.environ.get('AMD_TEE_LOG_PATH'):
            env['AMD_TEE_LOG_PATH'] = '/dev/null'

    return env


def get_subprocess_environment() -> Dict[str, str]:
    """
    Get complete environment for subprocesses with GPU support.

    Returns a copy of current environment with ROCm variables added.
    Safe to pass to subprocess.run(env=...) or subprocess.Popen(env=...).

    Returns:
        Complete environment dict
    """
    env = os.environ.copy()
    rocm_env = get_rocm_environment()
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

    # Check if PyTorch can see GPU
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            hip_version = getattr(torch.version, 'hip', None)
            if hip_version:
                log(f"[GPU] PyTorch ROCm {hip_version}: {device_name}")
            else:
                log(f"[GPU] PyTorch CUDA: {device_name}")
        else:
            log("[GPU] PyTorch: CPU only (no CUDA/ROCm)")
    except ImportError:
        log("[GPU] PyTorch not installed")
