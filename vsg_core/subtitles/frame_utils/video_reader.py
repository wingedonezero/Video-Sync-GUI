# vsg_core/subtitles/frame_utils/video_reader.py
"""
FFMS2 index cache path generation.

One cached ``.ffindex`` per video per job, shared by the sliding matcher,
the real-timestamp frame tables and visual verification.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def _get_ffms2_cache_path(video_path: str, temp_dir: Path | None) -> Path:
    """
    Generate cache path for FFMS2 index in job's temp directory.

    Cache key: parent_dir + filename + size + mtime (unique per file path)
    Location: {job_temp_dir}/ffindex/{cache_key}.ffindex

    The index is created in the job's temp folder so it can be:
    1. Easily identified by filename and source
    2. Reused within the job (multiple sync operations on same video)
    3. Cleaned up automatically when job completes
    4. Avoid collisions when different sources have same episode numbers
    """
    import hashlib
    import os

    video_path_obj = Path(video_path)

    # Get file metadata for cache invalidation
    stat = os.stat(video_path)
    file_size = stat.st_size
    mtime = int(stat.st_mtime)

    # Include parent directory to distinguish between sources
    # E.g., "source1/1.mkv" vs "source2/1.mkv" get different indexes
    parent_dir = video_path_obj.parent.name

    # If parent is empty/root, use path hash instead
    if not parent_dir or parent_dir == ".":
        path_hash = hashlib.md5(str(video_path_obj.resolve()).encode()).hexdigest()[:8]
        cache_key = f"{video_path_obj.stem}_{path_hash}_{file_size}_{mtime}"
    else:
        cache_key = f"{parent_dir}_{video_path_obj.stem}_{file_size}_{mtime}"

    # ALWAYS use job's temp_dir for index storage (for cleanup)
    if temp_dir:
        cache_dir = temp_dir / "ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Fallback: use system temp (but warn - won't be cleaned up)
        cache_dir = Path(tempfile.gettempdir()) / "vsg_ffindex"
        cache_dir.mkdir(parents=True, exist_ok=True)

    return cache_dir / f"{cache_key}.ffindex"
