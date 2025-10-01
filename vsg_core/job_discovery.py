# vsg_core/job_discovery.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from typing import List, Dict

def discover_jobs(sources: Dict[str, str]) -> List[Dict[str, Dict[str, str]]]:
    """
    Discovers jobs based on a dictionary of source paths.
    'Source 1' is the reference for filename matching.
    Returns a list of job dictionaries, each with a 'sources' key.

    NEW: Supports single-source (Source 1 only) for remux-only mode.
    """
    source1_path_str = sources.get("Source 1")
    if not source1_path_str:
        raise ValueError("Source 1 (Reference) path cannot be empty.")

    source1_path = Path(source1_path_str)
    if not source1_path.exists():
        raise FileNotFoundError(f"Source 1 path does not exist: {source1_path}")

    other_source_paths = {key: Path(path) for key, path in sources.items() if key != "Source 1" and path}

    # --- Single File Mode ---
    if source1_path.is_file():
        job_sources = {"Source 1": str(source1_path)}
        has_other_sources = False
        for key, path in other_source_paths.items():
            if path.is_file():
                job_sources[key] = str(path)
                has_other_sources = True

        # CHANGE: Always return the job, even with only Source 1
        # This enables remux-only mode for processing a single file
        return [{'sources': job_sources}]

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

            # CHANGE: Allow single-source batch jobs (remux-only mode)
            # Always include the job, even if no matching files in other sources
            jobs.append({'sources': job_sources})

        return jobs

    raise ValueError("Source 1 path is not a valid file or directory.")
