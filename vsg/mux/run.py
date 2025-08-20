# Clean manual copy — mux.run
from __future__ import annotations
from typing import Any, Dict, List
import json, subprocess, logging, os
from vsg.logbus import _log

def write_mkvmerge_json_options(plan: Dict[str, Any], path: str) -> None:
    """Write mkvmerge options JSON file."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2)
        _log(f"Wrote mkvmerge options to {path}")
    except Exception as e:
        _log(f"write_mkvmerge_json_options failed: {e}")

def run_mkvmerge_with_json(opts_path: str, output_path: str) -> int:
    """Run mkvmerge with a given JSON opts file."""
    try:
        cmd = ["mkvmerge", "--output", output_path, f"@{opts_path}"]
        _log("$ " + " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            _log(proc.stderr)
        else:
            _log(proc.stdout)
        return proc.returncode
    except Exception as e:
        _log(f"run_mkvmerge_with_json failed: {e}")
        return 1
