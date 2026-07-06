# vsg_core/analysis/correlation/dense_launcher.py
"""
Parent-side launcher for the dense-correlation subprocess.

Writes the (possibly source-separated / filtered) PCM arrays to ``.npy``
files, spawns ``dense_subprocess.py``, forwards its stdout to the log
callback verbatim, and reconstructs the typed ``ChunkResult`` list from
the result JSON. See ``dense_subprocess.py`` for the protocol and the
ROCm rationale.

Torch-free: this module must never import torch — GPU isolation is the
whole point.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import numpy as np

from ..types import ChunkResult

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ...models.settings import AppSettings

JSON_PREFIX = "__VSG_CORRELATION_JSON__ "


def chunk_result_to_dict(result: ChunkResult) -> dict[str, float | int | bool]:
    """Serialize one ChunkResult for the subprocess result JSON."""
    return {
        "delay_ms": result.delay_ms,
        "raw_delay_ms": result.raw_delay_ms,
        "match_pct": result.match_pct,
        "start_s": result.start_s,
        "accepted": result.accepted,
    }


def chunk_result_from_dict(data: dict[str, float | int | bool]) -> ChunkResult:
    """Rebuild one ChunkResult from the subprocess result JSON."""
    return ChunkResult(
        delay_ms=int(data["delay_ms"]),
        raw_delay_ms=float(data["raw_delay_ms"]),
        match_pct=float(data["match_pct"]),
        start_s=float(data["start_s"]),
        accepted=bool(data["accepted"]),
    )


def run_dense_correlation_subprocess(
    ref_pcm: np.ndarray,
    tgt_pcm: np.ndarray,
    sr: int,
    settings: AppSettings,
    *,
    use_source_separated: bool,
    multi_corr: bool,
    min_match: float,
    start_pct: float,
    end_pct: float,
    temp_dir: Path,
    tag: str,
    log: Callable[[str], None],
) -> list[ChunkResult]:
    """
    Run one dense-correlation job in an isolated subprocess.

    Returns the selected method's ``list[ChunkResult]`` (an empty list is
    valid — e.g. an all-silence scan range). Raises ``RuntimeError`` when
    the subprocess fails, mirroring how an in-process GPU exception would
    fail the job.
    """
    ref_path = temp_dir / f"corr_ref_{tag}.npy"
    tgt_path = temp_dir / f"corr_tgt_{tag}.npy"
    config_path = temp_dir / f"corr_config_{tag}.json"
    output_path = temp_dir / f"corr_result_{tag}.json"

    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        np.save(ref_path, ref_pcm)
        np.save(tgt_path, tgt_pcm)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(settings.model_dump(), f, indent=2, ensure_ascii=False)

        # NOTE: Use --flag=value syntax for numeric args to prevent argparse
        # from misinterpreting negative numbers as flags.
        cmd = [
            sys.executable,
            "-m",
            "vsg_core.analysis.correlation.dense_subprocess",
            "--ref-pcm",
            str(ref_path),
            "--tgt-pcm",
            str(tgt_path),
            f"--sample-rate={sr}",
            "--config-json",
            str(config_path),
            "--output-json",
            str(output_path),
            "--mode",
            "multi" if multi_corr else "single",
            f"--min-match={min_match}",
            f"--start-pct={start_pct}",
            f"--end-pct={end_pct}",
        ]
        if use_source_separated:
            cmd.append("--source-separated")

        # Pin the child to the discrete GPU (device 0); on dual-GPU ROCm
        # systems the iGPU otherwise SIGSEGVs on first kernel launch.
        env = {**os.environ}
        env.setdefault("HIP_VISIBLE_DEVICES", "0")

        json_payload = None
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
        except Exception as exc:
            raise RuntimeError(f"Correlation subprocess launch failed: {exc}") from exc

        # Forward stdout (log messages + JSON result marker). Empty lines
        # are forwarded too — the dense summary relies on them for spacing.
        if process.stdout:
            for line in process.stdout:
                line = line.rstrip("\n")
                if line.startswith(JSON_PREFIX):
                    try:
                        json_payload = json.loads(line.split(JSON_PREFIX, 1)[1])
                    except json.JSONDecodeError:
                        json_payload = None
                else:
                    log(line)

        return_code = process.wait()

        # Log any stderr (filter noise from model libraries)
        if process.stderr:
            for line in process.stderr:
                line = line.rstrip("\n")
                if line:
                    log(f"[Correlation] stderr: {line}")

        if return_code != 0:
            error_detail = None
            if json_payload and not json_payload.get("success"):
                error_detail = json_payload.get("error")
            log(f"[Correlation] ERROR: Subprocess failed (code {return_code})")
            if error_detail:
                log(f"[Correlation] ERROR: {error_detail}")
            raise RuntimeError(
                f"Correlation subprocess failed: "
                f"{error_detail or f'exit code {return_code}'}"
            )

        if not json_payload or not json_payload.get("success"):
            log("[Correlation] ERROR: Subprocess returned no result")
            raise RuntimeError("Correlation subprocess returned no result")

        with open(output_path, encoding="utf-8") as f:
            result = json.load(f)

        selected = result["selected_method"]
        return [
            chunk_result_from_dict(d) for d in result["results_by_method"][selected]
        ]
    finally:
        # The PCM files are the big ones (up to ~1.4 GB per pair) — remove
        # them immediately rather than waiting for the job's temp-dir sweep.
        for path in (ref_path, tgt_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
