# -*- coding: utf-8 -*-

"""
Handles the discovery of jobs for batch processing.
"""

from pathlib import Path
from typing import List, Tuple, Optional

def discover_jobs(ref_path_str: str, sec_path_str: Optional[str], ter_path_str: Optional[str]) -> List[Tuple[str, Optional[str], Optional[str]]]:
    """
    Discovers jobs based on input paths.
    If the reference is a file, it's a single job.
    If the reference is a folder, it finds matching files in other folders.
    """
    if not ref_path_str:
        raise ValueError("Reference path cannot be empty.")

    ref_path = Path(ref_path_str)
    if not ref_path.exists():
        raise FileNotFoundError(f"Reference path does not exist: {ref_path}")

    sec_path = Path(sec_path_str) if sec_path_str else None
    ter_path = Path(ter_path_str) if ter_path_str else None

    # --- Single File Mode ---
    if ref_path.is_file():
        sec_file = str(sec_path) if sec_path and sec_path.is_file() else None
        ter_file = str(ter_path) if ter_path and ter_path.is_file() else None
        return [(str(ref_path), sec_file, ter_file)]

    # --- Batch (Folder) Mode ---
    if ref_path.is_dir():
        if (sec_path and sec_path.is_file()) or (ter_path and ter_path.is_file()):
            raise ValueError("If Reference is a folder, Secondary and Tertiary must also be folders or empty.")

        jobs = []
        for ref_file in sorted(ref_path.iterdir()):
            if ref_file.is_file() and ref_file.suffix.lower() in ['.mkv', '.mp4', '.m4v']:

                sec_file_match = sec_path / ref_file.name if sec_path else None
                ter_file_match = ter_path / ref_file.name if ter_path else None

                valid_sec = str(sec_file_match) if sec_file_match and sec_file_match.is_file() else None
                valid_ter = str(ter_file_match) if ter_file_match and ter_file_match.is_file() else None

                if valid_sec or valid_ter:
                    jobs.append((str(ref_file), valid_sec, valid_ter))

        if not jobs:
            raise FileNotFoundError("No matching files found for batch processing in the specified folders.")

        return jobs

    raise ValueError("Reference path is not a valid file or directory.")
