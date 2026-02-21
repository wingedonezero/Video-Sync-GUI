# vsg_core/correction/stepping/data_io.py
"""
Serialize / deserialize dense analysis data for the stepping correction pipeline.

When the analysis step detects stepping, it saves the full ``list[ChunkResult]``
and cluster diagnostics to a JSON file in the job's temp directory.  The stepping
correction step reads this file instead of re-scanning from scratch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ...analysis.types import ChunkResult, ClusterDiagnostic
from ...audit.trail import NumpyJSONEncoder
from .types import SteppingData

if TYPE_CHECKING:
    from ...analysis.types import SteppingDiagnosis


def save_stepping_data(
    temp_dir: Path,
    source_key: str,
    track_id: int,
    chunk_results: list[ChunkResult],
    diagnosis: SteppingDiagnosis,
) -> Path:
    """Persist dense analysis data to ``{temp_dir}/stepping_data/{source}_{track}.json``."""
    out_dir = temp_dir / "stepping_data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Sanitise source_key for file-name safety (spaces → underscores)
    safe_source = source_key.replace(" ", "_")
    out_path = out_dir / f"{safe_source}_{track_id}.json"

    payload = {
        "source_key": source_key,
        "track_id": track_id,
        "windows": [
            {
                "delay_ms": r.delay_ms,
                "raw_delay_ms": r.raw_delay_ms,
                "match_pct": r.match_pct,
                "start_s": r.start_s,
                "accepted": r.accepted,
            }
            for r in chunk_results
        ],
        "clusters": [
            {
                "cluster_id": c.cluster_id,
                "mean_delay_ms": c.mean_delay_ms,
                "std_delay_ms": c.std_delay_ms,
                "chunk_count": c.chunk_count,
                "chunk_numbers": c.chunk_numbers,
                "raw_delays": list(c.raw_delays),
                "time_range": list(c.time_range),
                "mean_match_pct": c.mean_match_pct,
                "min_match_pct": c.min_match_pct,
            }
            for c in diagnosis.cluster_details
        ],
    }

    out_path.write_text(json.dumps(payload, indent=2, cls=NumpyJSONEncoder), encoding="utf-8")
    return out_path


def load_stepping_data(path: str | Path) -> SteppingData:
    """Read a previously-saved JSON and reconstitute typed objects."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    windows = [
        ChunkResult(
            delay_ms=w["delay_ms"],
            raw_delay_ms=w["raw_delay_ms"],
            match_pct=w["match_pct"],
            start_s=w["start_s"],
            accepted=w["accepted"],
        )
        for w in raw["windows"]
    ]

    clusters = [
        ClusterDiagnostic(
            cluster_id=c["cluster_id"],
            mean_delay_ms=c["mean_delay_ms"],
            std_delay_ms=c["std_delay_ms"],
            chunk_count=c["chunk_count"],
            chunk_numbers=c["chunk_numbers"],
            raw_delays=tuple(c["raw_delays"]),
            time_range=tuple(c["time_range"]),
            mean_match_pct=c["mean_match_pct"],
            min_match_pct=c["min_match_pct"],
        )
        for c in raw["clusters"]
    ]

    return SteppingData(
        source_key=raw["source_key"],
        track_id=raw["track_id"],
        windows=windows,
        clusters=clusters,
    )
