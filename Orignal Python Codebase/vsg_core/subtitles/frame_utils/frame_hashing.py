# vsg_core/subtitles/frame_utils/frame_hashing.py
# -*- coding: utf-8 -*-
"""
Frame hashing and comparison functions for video sync verification.

Contains:
- Perceptual hash computation (phash, dhash, average_hash, whash)
- SSIM (Structural Similarity Index) comparison
- MSE (Mean Squared Error) comparison
- Unified frame comparison interface
"""
from __future__ import annotations
from typing import Any, Optional
import gc
import io


def compute_perceptual_hash(image_data: bytes, runner, algorithm: str = 'dhash', hash_size: int = 8) -> Optional[str]:
    """
    Compute perceptual hash from image data.

    Supports multiple algorithms with different tolerance levels:
    - dhash: Difference hash - good for compression artifacts (default)
    - phash: Perceptual hash - best for heavy re-encoding, color grading
    - average_hash: Simple averaging - fast but less accurate
    - whash: Wavelet hash - very robust but slower

    Args:
        image_data: PNG/JPEG image data as bytes
        runner: CommandRunner for logging
        algorithm: Hash algorithm to use (dhash, phash, average_hash, whash)
        hash_size: Hash size (4, 8, 16) - larger = more precise but less tolerant

    Returns:
        Hexadecimal hash string, or None on error
    """
    try:
        from PIL import Image
        import imagehash

        img = Image.open(io.BytesIO(image_data))

        # Select hash algorithm
        if algorithm == 'phash':
            hash_obj = imagehash.phash(img, hash_size=hash_size)
        elif algorithm == 'average_hash':
            hash_obj = imagehash.average_hash(img, hash_size=hash_size)
        elif algorithm == 'whash':
            hash_obj = imagehash.whash(img, hash_size=hash_size)
        else:  # dhash (default)
            hash_obj = imagehash.dhash(img, hash_size=hash_size)

        del img
        gc.collect()

        return str(hash_obj)

    except ImportError:
        runner._log_message("[Perceptual Hash] WARNING: imagehash library not installed")
        runner._log_message("[Perceptual Hash] Install with: pip install imagehash")
        return None
    except Exception as e:
        runner._log_message(f"[Perceptual Hash] ERROR: Failed to compute hash: {e}")
        return None


def compute_frame_hash(frame: 'Image.Image', hash_size: int = 8, method: str = 'phash') -> Optional[Any]:
    """
    Compute perceptual hash of a frame.

    Args:
        frame: PIL Image object
        hash_size: Hash size (8x8 = 64 bits, 16x16 = 256 bits)
        method: Hash method ('phash', 'dhash', 'average_hash', 'whash')

    Returns:
        ImageHash object, or None on failure
    """
    try:
        import imagehash

        if method == 'dhash':
            return imagehash.dhash(frame, hash_size=hash_size)
        elif method == 'average_hash':
            return imagehash.average_hash(frame, hash_size=hash_size)
        elif method == 'whash':
            return imagehash.whash(frame, hash_size=hash_size)
        else:  # 'phash' or default
            return imagehash.phash(frame, hash_size=hash_size)

    except ImportError:
        return None
    except Exception:
        return None


def compute_hamming_distance(hash1, hash2) -> int:
    """
    Compute Hamming distance between two perceptual hashes.

    Args:
        hash1: First ImageHash object
        hash2: Second ImageHash object

    Returns:
        Hamming distance (number of differing bits). Lower = more similar.
        Returns 0 for identical frames, typically <5 for matching frames,
        and >10 for different frames.
    """
    # ImageHash objects support subtraction to get Hamming distance
    return hash1 - hash2


def compute_ssim(frame1: 'Image.Image', frame2: 'Image.Image') -> float:
    """
    Compute Structural Similarity Index (SSIM) between two frames.

    SSIM compares structural patterns and is more accurate than perceptual
    hashing for detecting subtle differences.

    Args:
        frame1: First PIL Image object
        frame2: Second PIL Image object

    Returns:
        SSIM value from 0.0 to 1.0. Higher = more similar.
        1.0 = identical, >0.95 = very similar, <0.8 = noticeably different
    """
    try:
        import numpy as np

        # Convert to grayscale numpy arrays
        arr1 = np.array(frame1.convert('L'))
        arr2 = np.array(frame2.convert('L'))

        # Resize to match if needed
        if arr1.shape != arr2.shape:
            from PIL import Image as PILImage
            # Resize frame2 to match frame1
            frame2_resized = frame2.resize(frame1.size, PILImage.Resampling.LANCZOS)
            arr2 = np.array(frame2_resized.convert('L'))

        # Try scikit-image SSIM first (most accurate)
        try:
            from skimage.metrics import structural_similarity
            ssim_value = structural_similarity(arr1, arr2, data_range=255)
            return float(ssim_value)
        except ImportError:
            pass

        # Fallback: simplified SSIM calculation
        # Using the formula: SSIM = (2*mu1*mu2 + C1)(2*sigma12 + C2) / ((mu1^2 + mu2^2 + C1)(sigma1^2 + sigma2^2 + C2))
        C1 = (0.01 * 255) ** 2
        C2 = (0.03 * 255) ** 2

        mu1 = arr1.mean()
        mu2 = arr2.mean()
        sigma1_sq = arr1.var()
        sigma2_sq = arr2.var()
        sigma12 = ((arr1 - mu1) * (arr2 - mu2)).mean()

        ssim = ((2 * mu1 * mu2 + C1) * (2 * sigma12 + C2)) / \
               ((mu1 ** 2 + mu2 ** 2 + C1) * (sigma1_sq + sigma2_sq + C2))

        return float(ssim)

    except Exception:
        return 0.0


def compute_mse(frame1: 'Image.Image', frame2: 'Image.Image') -> float:
    """
    Compute Mean Squared Error between two frames.

    Lower MSE = more similar. 0 = identical.

    Args:
        frame1: First PIL Image object
        frame2: Second PIL Image object

    Returns:
        MSE value. Lower = more similar.
    """
    try:
        import numpy as np

        arr1 = np.array(frame1.convert('L'), dtype=np.float64)
        arr2 = np.array(frame2.convert('L'), dtype=np.float64)

        # Resize to match if needed
        if arr1.shape != arr2.shape:
            from PIL import Image as PILImage
            frame2_resized = frame2.resize(frame1.size, PILImage.Resampling.LANCZOS)
            arr2 = np.array(frame2_resized.convert('L'), dtype=np.float64)

        mse = np.mean((arr1 - arr2) ** 2)
        return float(mse)

    except Exception:
        return float('inf')


def compare_frames(
    frame1: 'Image.Image',
    frame2: 'Image.Image',
    method: str = 'hash',
    hash_algorithm: str = 'dhash',
    hash_size: int = 8
) -> tuple:
    """
    Compare two frames using the specified method.

    Args:
        frame1: First PIL Image object
        frame2: Second PIL Image object
        method: Comparison method ('hash', 'ssim', 'mse')
        hash_algorithm: Hash algorithm when method='hash'
        hash_size: Hash size when method='hash'

    Returns:
        Tuple of (distance, is_match):
        - distance: Similarity metric (interpretation depends on method)
        - is_match: Boolean indicating if frames are considered matching

    Distance interpretation:
    - hash: Hamming distance (0=identical, <5=match, >10=different)
    - ssim: 1.0 - SSIM (0=identical, <0.05=match, >0.2=different)
    - mse: Normalized MSE (0=identical, <100=match, >500=different)
    """
    if method == 'ssim':
        ssim = compute_ssim(frame1, frame2)
        # Convert to distance (0 = identical, higher = more different)
        distance = (1.0 - ssim) * 100  # Scale to ~0-100 range
        is_match = ssim > 0.90  # 90% similarity threshold
        return (distance, is_match)

    elif method == 'mse':
        mse = compute_mse(frame1, frame2)
        # Normalize to ~0-100 range (assuming 8-bit images)
        distance = min(mse / 100, 100)  # Cap at 100
        is_match = mse < 500  # Empirical threshold
        return (distance, is_match)

    else:  # 'hash' (default)
        hash1 = compute_frame_hash(frame1, hash_size, hash_algorithm)
        hash2 = compute_frame_hash(frame2, hash_size, hash_algorithm)

        if hash1 is None or hash2 is None:
            return (999, False)

        distance = compute_hamming_distance(hash1, hash2)
        is_match = distance <= 5  # Default threshold
        return (distance, is_match)
