"""Moved implementations for jobs.discover (full-move RC)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import os, re, json, math, logging, subprocess, tempfile, pathlib
from pathlib import Path

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.tools import run_command, find_required_tools
def discover_jobs(ref_path, sec_path, ter_path):
    ref = Path(ref_path) if ref_path else None
    sec = Path(sec_path) if sec_path else None
    ter = Path(ter_path) if ter_path else None
    if not ref or not ref.exists():
        raise RuntimeError('Reference path must exist.')
    if ref.is_file():
        return [(str(ref), str(sec) if sec and sec.is_file() else None, str(ter) if ter and ter.is_file() else None)]
    if sec and sec.is_file() or (ter and ter.is_file()):
        raise RuntimeError('If Reference is a folder, Secondary/Tertiary must be folders too.')
    jobs = []
    for f in sorted(ref.iterdir()):
        if f.is_file():
            s = sec / f.name if sec else None
            t = ter / f.name if ter else None
            s_ok = str(s) if s and s.exists() and s.is_file() else None
            t_ok = str(t) if t and t.exists() and t.is_file() else None
            if s_ok or t_ok:
                jobs.append((str(f), s_ok, t_ok))
    return jobs

