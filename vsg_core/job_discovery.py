# vsg_core/job_discovery.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Optional


def _find_matching_subtitle_folder(video_file_path: Path, subtitle_base_path: Path) -> Optional[Path]:
    """
    Find a subtitle folder matching the video file name.
    Matches folder name to video file stem (filename without extension).

    Args:
        video_file_path: Path to the video file
        subtitle_base_path: Base path containing subtitle subfolders

    Returns:
        Path to matching subtitle folder if found, None otherwise
    """
    video_stem = video_file_path.stem  # filename without extension
    potential_folder = subtitle_base_path / video_stem

    if potential_folder.exists() and potential_folder.is_dir():
        return potential_folder

    return None


def discover_jobs(sources: Dict[str, str], subtitle_folder_path: str = None, subtitle_folder_sync_source: str = "Source 1") -> List[Dict[str, Dict[str, str]]]:
    """
    Discovers jobs based on a dictionary of source paths.
    'Source 1' is the reference for filename matching.
    Returns a list of job dictionaries, each with a 'sources' key.

    NEW: Supports single-source (Source 1 only) for remux-only mode.
    NEW: Supports subtitle folder matching - matches folder names to video file stems.

    Args:
        sources: Dict of source paths ("Source 1", "Source 2", etc.)
        subtitle_folder_path: Optional path to folder containing subtitle subfolders
        subtitle_folder_sync_source: Which source to sync subtitle delays to (default "Source 1")
    """
    source1_path_str = sources.get("Source 1")
    if not source1_path_str:
        raise ValueError("Source 1 (Reference) path cannot be empty.")

    source1_path = Path(source1_path_str)
    if not source1_path.exists():
        raise FileNotFoundError(f"Source 1 path does not exist: {source1_path}")

    other_source_paths = {key: Path(path) for key, path in sources.items() if key != "Source 1" and path}

    # Parse subtitle folder path if provided
    subtitle_base_path = None
    if subtitle_folder_path:
        subtitle_base_path = Path(subtitle_folder_path)
        if not subtitle_base_path.exists():
            raise FileNotFoundError(f"Subtitle folder path does not exist: {subtitle_base_path}")
        if not subtitle_base_path.is_dir():
            raise ValueError(f"Subtitle folder path must be a directory: {subtitle_base_path}")

    # --- Single File Mode ---
    if source1_path.is_file():
        job_sources = {"Source 1": str(source1_path)}
        has_other_sources = False
        for key, path in other_source_paths.items():
            if path.is_file():
                job_sources[key] = str(path)
                has_other_sources = True

        # Check for matching subtitle folder
        job_data = {'sources': job_sources}
        if subtitle_base_path:
            matched_sub_folder = _find_matching_subtitle_folder(source1_path, subtitle_base_path)
            if matched_sub_folder:
                job_data['subtitle_folder_path'] = str(matched_sub_folder)
                job_data['subtitle_folder_sync_source'] = subtitle_folder_sync_source

        # CHANGE: Always return the job, even with only Source 1
        # This enables remux-only mode for processing a single file
        return [job_data]

    # --- Batch (Folder) Mode ---
    if source1_path.is_dir():
        for key, path in other_source_paths.items():
            if path.is_file():
                raise ValueError(f"If Source 1 is a folder, all other sources must also be folders or empty.")

        jobs = []
        for ref_file in sorted(ref_file for ref_file in source1_path.iterdir() if ref_file.is_file() and ref_file.suffix.lower() in ['.mkv', '.mp4', '.m4v']):
            job_sources = {"Source 1": str(ref_file)}
            has_other_sources = False
            for key, path in other_source_paths.items():
                match_file = path / ref_file.name
                if match_file.is_file():
                    job_sources[key] = str(match_file)
                    has_other_sources = True

            # Check for matching subtitle folder
            job_data = {'sources': job_sources}
            if subtitle_base_path:
                matched_sub_folder = _find_matching_subtitle_folder(ref_file, subtitle_base_path)
                if matched_sub_folder:
                    job_data['subtitle_folder_path'] = str(matched_sub_folder)
                    job_data['subtitle_folder_sync_source'] = subtitle_folder_sync_source

            # CHANGE: Allow single-source batch jobs (remux-only mode)
            # Always include the job, even if no matching files in other sources
            jobs.append(job_data)

        return jobs

    raise ValueError("Source 1 path is not a valid file or directory.")
