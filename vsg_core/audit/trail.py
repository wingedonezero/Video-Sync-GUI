# vsg_core/audit/trail.py
"""
Pipeline audit trail for debugging timing issues.

Creates a JSON file in the job's temp folder that records EVERY timing-related
value at each pipeline step. Never overwrites - only appends/adds new keys.

Design principles:
1. Atomic writes - use temp file + rename to prevent corruption
2. Append-only - never delete or overwrite existing data (merge instead)
3. Hierarchical - organized by pipeline step then by track
4. Human-readable - formatted JSON with meaningful key names
5. Complete - captures raw values before any rounding
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class NumpyJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types and Path objects."""

    def default(self, obj):
        # Try numpy types
        try:
            import numpy as np

            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.bool_):
                return bool(obj)
        except ImportError:
            pass

        # Handle Path objects
        if isinstance(obj, Path):
            return str(obj)

        return super().default(obj)


class AuditTrail:
    """
    Manages the pipeline audit trail JSON file.

    Usage:
        audit = AuditTrail(temp_dir, job_name)
        audit.record('analysis.correlations.Source 2.raw_chunks', chunk_data)
        audit.record('mux.track_delays', delay_list)

    All paths are dot-separated (e.g., 'analysis.correlations.Source 2').
    Missing intermediate keys are created automatically.
    """

    VERSION = "1.0"
    FILENAME = "pipeline_audit_trail.json"

    def __init__(self, temp_dir: Path | str, job_name: str):
        """
        Initialize audit trail.

        Args:
            temp_dir: Job's temporary directory
            job_name: Name of the job (for metadata)
        """
        self.temp_dir = Path(temp_dir)
        self.job_name = job_name
        self.file_path = self.temp_dir / self.FILENAME

        # Initialize structure
        self._data: dict[str, Any] = {
            "_metadata": {
                "version": self.VERSION,
                "created_at": datetime.now().isoformat(),
                "job_name": job_name,
                "temp_dir": str(temp_dir),
                "output_file": None,
            },
            "sources": {},
            "analysis": {
                "correlations": {},
                "container_delays": {},
                "delay_calculations": {},
                "global_shift": {},
                "final_delays": {},
            },
            "extraction": {"tracks": []},
            "stepping": {},
            "subtitle_processing": {},
            "mux": {"track_delays": [], "tokens": []},
            "events": [],
        }

        # Write initial file
        self._write()

    def record(self, path: str, value: Any, merge: bool = False) -> None:
        """
        Record a value at the specified path.

        Args:
            path: Dot-separated path (e.g., 'analysis.correlations.Source 2')
            value: Value to store (must be JSON-serializable)
            merge: If True and both existing and new values are dicts, merge them
                   If False (default), replace existing value

        Raises:
            ValueError: If path is invalid or would overwrite a non-dict with a dict path
        """
        parts = path.split(".")
        target = self._data

        # Navigate to parent, creating intermediate dicts as needed
        for i, part in enumerate(parts[:-1]):
            if part not in target:
                target[part] = {}
            elif not isinstance(target[part], dict):
                # Can't traverse through a non-dict
                raise ValueError(
                    f"Cannot set '{path}': '{'.'.join(parts[: i + 1])}' is not a dict"
                )
            target = target[part]

        # Set the value
        final_key = parts[-1]
        if (
            merge
            and isinstance(target.get(final_key), dict)
            and isinstance(value, dict)
        ):
            target[final_key].update(value)
        else:
            target[final_key] = value

        # Write immediately
        self._write()

    def append(self, path: str, value: Any) -> None:
        """
        Append a value to a list at the specified path.

        Creates the list if it doesn't exist.

        Args:
            path: Dot-separated path to a list
            value: Value to append
        """
        parts = path.split(".")
        target = self._data

        # Navigate to parent, creating intermediate dicts as needed
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]

        # Get or create list and append
        final_key = parts[-1]
        if final_key not in target:
            target[final_key] = []
        elif not isinstance(target[final_key], list):
            # Convert to list if not already
            target[final_key] = [target[final_key]]

        target[final_key].append(value)
        self._write()

    def append_event(
        self, event_type: str, message: str, data: dict | None = None
    ) -> None:
        """
        Append a timestamped event to the events log.

        Args:
            event_type: Type of event (e.g., 'warning', 'error', 'milestone', 'debug')
            message: Human-readable message
            data: Optional additional data
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            "message": message,
        }
        if data:
            event["data"] = data

        self._data["events"].append(event)
        self._write()

    def record_source(self, source_key: str, file_path: str, **kwargs) -> None:
        """
        Record source file information.

        Args:
            source_key: Source identifier (e.g., 'Source 1', 'Source 2')
            file_path: Path to source file
            **kwargs: Additional metadata (fps, tracks, etc.)
        """
        source_data = {
            "file_path": str(file_path),
            "recorded_at": datetime.now().isoformat(),
            **kwargs,
        }
        self.record(f"sources.{source_key}", source_data, merge=True)

    def record_correlation_chunk(
        self,
        source_key: str,
        chunk_idx: int,
        start_s: float,
        delay_ms: int,
        raw_delay_ms: float,
        match_pct: float,
        accepted: bool,
    ) -> None:
        """
        Record a single correlation chunk result.

        Args:
            source_key: Source being correlated (e.g., 'Source 2')
            chunk_idx: Index of this chunk
            start_s: Start time in seconds
            delay_ms: Rounded delay in milliseconds
            raw_delay_ms: Raw (unrounded) delay in milliseconds
            match_pct: Match percentage
            accepted: Whether chunk was accepted
        """
        chunk_data = {
            "chunk_idx": chunk_idx,
            "start_s": round(start_s, 3),
            "delay_ms": delay_ms,
            "raw_delay_ms": round(raw_delay_ms, 6),
            "match_pct": round(match_pct, 4),
            "accepted": accepted,
        }
        self.append(f"analysis.correlations.{source_key}.chunks", chunk_data)

    def record_delay_calculation(
        self,
        source_key: str,
        correlation_raw_ms: float,
        correlation_rounded_ms: int,
        container_delay_ms: float,
        final_raw_ms: float,
        final_rounded_ms: int,
        selection_method: str,
        accepted_chunks: int,
        total_chunks: int,
    ) -> None:
        """
        Record the delay calculation chain for a source.

        This captures the full calculation: correlation -> container adjustment -> final
        """
        self.record(
            f"analysis.delay_calculations.{source_key}",
            {
                "correlation": {
                    "raw_ms": round(correlation_raw_ms, 6),
                    "rounded_ms": correlation_rounded_ms,
                    "selection_method": selection_method,
                    "accepted_chunks": accepted_chunks,
                    "total_chunks": total_chunks,
                },
                "container_delay_ms": round(container_delay_ms, 6),
                "before_global_shift": {
                    "raw_ms": round(final_raw_ms, 6),
                    "rounded_ms": final_rounded_ms,
                },
            },
        )

    def record_global_shift(
        self,
        most_negative_raw_ms: float,
        most_negative_rounded_ms: int,
        shift_raw_ms: float,
        shift_rounded_ms: int,
        sync_mode: str,
    ) -> None:
        """
        Record global shift calculation.
        """
        self.record(
            "analysis.global_shift",
            {
                "sync_mode": sync_mode,
                "most_negative_delay": {
                    "raw_ms": round(most_negative_raw_ms, 6),
                    "rounded_ms": most_negative_rounded_ms,
                },
                "calculated_shift": {
                    "raw_ms": round(shift_raw_ms, 6),
                    "rounded_ms": shift_rounded_ms,
                },
            },
        )

    def record_final_delay(
        self,
        source_key: str,
        raw_ms: float,
        rounded_ms: int,
        includes_global_shift: bool,
    ) -> None:
        """
        Record final delay for a source (after global shift applied).
        """
        self.record(
            f"analysis.final_delays.{source_key}",
            {
                "raw_ms": round(raw_ms, 6),
                "rounded_ms": rounded_ms,
                "includes_global_shift": includes_global_shift,
            },
        )

    def record_subtitle_track(
        self, track_key: str, source: str, track_id: int, **kwargs
    ) -> None:
        """
        Record or update subtitle track processing data.

        Args:
            track_key: Unique key for this track (e.g., 'track_3')
            source: Source name (e.g., 'Source 2', 'External')
            track_id: Track ID
            **kwargs: Additional data to merge
        """
        track_path = f"subtitle_processing.{track_key}"

        # Get existing data or create new
        existing = self._get_nested(track_path) or {}

        # Update with core fields
        existing["source"] = source
        existing["track_id"] = track_id
        existing["updated_at"] = datetime.now().isoformat()

        # Merge additional data
        for key, value in kwargs.items():
            if isinstance(value, dict) and isinstance(existing.get(key), dict):
                existing[key].update(value)
            else:
                existing[key] = value

        self.record(track_path, existing)

    def record_subtitle_parsed(
        self,
        track_key: str,
        event_count: int,
        first_event_start_ms: float,
        last_event_end_ms: float,
        style_count: int,
        source_path: str,
    ) -> None:
        """
        Record parsed subtitle info.
        """
        self.record(
            f"subtitle_processing.{track_key}.parsed",
            {
                "source_path": str(source_path),
                "event_count": event_count,
                "first_event_start_ms": round(first_event_start_ms, 3),
                "last_event_end_ms": round(last_event_end_ms, 3),
                "style_count": style_count,
            },
        )

    def record_subtitle_sync(
        self,
        track_key: str,
        sync_mode: str,
        delay_from_context_raw_ms: float,
        delay_from_context_rounded_ms: int,
        global_shift_raw_ms: float,
        source_key: str,
        plugin_name: str,
        events_modified: int,
        stepping_adjusted_before: bool,
        stepping_adjusted_after: bool,
        frame_adjusted_before: bool,
        frame_adjusted_after: bool,
    ) -> None:
        """
        Record subtitle sync operation details.
        """
        self.record(
            f"subtitle_processing.{track_key}.sync",
            {
                "sync_mode": sync_mode,
                "delay_from_context": {
                    "source_key": source_key,
                    "raw_ms": round(delay_from_context_raw_ms, 6),
                    "rounded_ms": delay_from_context_rounded_ms,
                    "global_shift_raw_ms": round(global_shift_raw_ms, 6),
                },
                "plugin": {"name": plugin_name, "events_modified": events_modified},
                "flags": {
                    "stepping_adjusted": {
                        "before": stepping_adjusted_before,
                        "after": stepping_adjusted_after,
                    },
                    "frame_adjusted": {
                        "before": frame_adjusted_before,
                        "after": frame_adjusted_after,
                    },
                },
            },
        )

    def record_mux_track_delay(
        self,
        track_idx: int,
        source: str,
        track_type: str,
        track_id: int,
        final_delay_ms: int,
        reason: str,
        raw_delay_available_ms: float | None = None,
        stepping_adjusted: bool = False,
        frame_adjusted: bool = False,
        sync_key: str | None = None,
    ) -> None:
        """
        Record the final delay calculation for a track in mux.
        """
        entry = {
            "track_idx": track_idx,
            "source": source,
            "track_type": track_type,
            "track_id": track_id,
            "final_delay_ms": final_delay_ms,
            "reason": reason,
            "sync_key": sync_key,
            "flags": {
                "stepping_adjusted": stepping_adjusted,
                "frame_adjusted": frame_adjusted,
            },
        }
        if raw_delay_available_ms is not None:
            entry["raw_delay_available_ms"] = round(raw_delay_available_ms, 6)

        self.append("mux.track_delays", entry)

    def record_mux_tokens(self, tokens: list[str]) -> None:
        """
        Record the final mkvmerge tokens.
        """
        self.record("mux.tokens", tokens)
        self.record(
            "mux.command_preview",
            " ".join(tokens[:20]) + ("..." if len(tokens) > 20 else ""),
        )

    def _get_nested(self, path: str) -> Any | None:
        """Get value at nested path, or None if not found."""
        parts = path.split(".")
        target = self._data
        for part in parts:
            if not isinstance(target, dict) or part not in target:
                return None
            target = target[part]
        return target

    def _write(self) -> None:
        """
        Write audit trail to disk using atomic write pattern.

        Uses temp file + rename to prevent corruption if write is interrupted.
        """
        # Ensure directory exists
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Create temp file in same directory (ensures same filesystem for rename)
        fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", prefix="audit_", dir=self.temp_dir
        )

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    self._data, f, indent=2, ensure_ascii=False, cls=NumpyJSONEncoder
                )

            # Atomic rename
            shutil.move(temp_path, self.file_path)
        except Exception:
            # Clean up temp file on error
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def get_path(self) -> Path:
        """Return path to the audit trail file."""
        return self.file_path

    def finalize(self, output_file: str | None = None, success: bool = True) -> None:
        """
        Finalize the audit trail.

        Args:
            output_file: Path to final output file
            success: Whether the job completed successfully
        """
        self._data["_metadata"]["finalized_at"] = datetime.now().isoformat()
        self._data["_metadata"]["success"] = success
        if output_file:
            self._data["_metadata"]["output_file"] = str(output_file)
        self._write()

    def to_dict(self) -> dict[str, Any]:
        """Return copy of the audit data."""
        return dict(self._data)
