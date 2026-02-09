# vsg_core/subtitles/ocr/wrapper.py
"""
OCR coordination wrapper for subtitle processing step.

Handles OCR execution (in-process or subprocess) and creates preserved
copies of original image-based subtitles.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context
    from vsg_core.subtitles.data import SubtitleData

from vsg_core.models.media import StreamProps, Track


def process_ocr_with_preservation(
    item, ctx: Context, runner: CommandRunner, items_to_add: list
) -> SubtitleData | None:
    """
    Process OCR for a track and create preserved copy of original.

    Returns:
        - SubtitleData if OCR succeeded
        - None if OCR failed/skipped

    Side effects:
        - Adds preserved copy of original to items_to_add
        - Updates item.extracted_path to .ass
        - Updates item.track codec to S_TEXT/ASS
    """
    from vsg_core.subtitles.ocr import run_ocr_unified

    ocr_work_dir = ctx.temp_dir / "ocr"
    logs_dir = Path(ctx.settings.logs_folder or ctx.temp_dir)

    # Determine debug output directory - use debug_paths if available, fallback to logs_dir
    debug_output_dir = logs_dir
    if ctx.debug_paths and ctx.debug_paths.ocr_debug_dir:
        debug_output_dir = ctx.debug_paths.ocr_debug_dir

    # Run OCR (subprocess or in-process)
    if ctx.settings.ocr_run_in_subprocess:
        subtitle_data = _run_ocr_subprocess(
            item=item,
            ctx=ctx,
            runner=runner,
            ocr_work_dir=ocr_work_dir,
            logs_dir=logs_dir,
            debug_output_dir=debug_output_dir,
        )
    else:
        subtitle_data = run_ocr_unified(
            str(item.extracted_path.with_suffix(".idx")),
            item.track.props.lang,
            runner,
            ctx.tool_paths,
            ctx.settings,
            work_dir=ocr_work_dir,
            logs_dir=logs_dir,
            debug_output_dir=debug_output_dir,
            track_id=item.track.id,
        )

    # Check OCR result
    if subtitle_data is None:
        runner._log_message(f"[OCR] ERROR: OCR failed for track {item.track.id}")
        runner._log_message("[OCR] Keeping original image-based subtitle")
        item.perform_ocr = False
        return None

    if not subtitle_data.events:
        runner._log_message(
            f"[OCR] WARNING: OCR produced no events for track {item.track.id}"
        )
        item.perform_ocr = False
        return None

    # OCR succeeded - create preserved copy of original
    preserved_item = copy.deepcopy(item)
    preserved_item.is_preserved = True
    original_props = preserved_item.track.props
    preserved_item.track = Track(
        source=preserved_item.track.source,
        id=preserved_item.track.id,
        type=preserved_item.track.type,
        props=StreamProps(
            codec_id=original_props.codec_id,
            lang=original_props.lang,
            name=f"{original_props.name} (Original)"
            if original_props.name
            else "Original",
        ),
    )
    items_to_add.append(preserved_item)

    # Update item to reflect OCR output
    item.extracted_path = item.extracted_path.with_suffix(".ass")
    item.track = Track(
        source=item.track.source,
        id=item.track.id,
        type=item.track.type,
        props=StreamProps(
            codec_id="S_TEXT/ASS",
            lang=original_props.lang,
            name=original_props.name,
        ),
    )

    return subtitle_data


def _run_ocr_subprocess(
    item,
    ctx: Context,
    runner: CommandRunner,
    ocr_work_dir: Path,
    logs_dir: Path,
    debug_output_dir: Path,
) -> SubtitleData | None:
    """
    Run OCR in subprocess and return SubtitleData.

    Uses unified_subprocess.py to isolate OCR from main process.
    """
    from vsg_core.subtitles.data import SubtitleData

    config_path = ctx.temp_dir / f"ocr_config_track_{item.track.id}.json"
    output_json = ctx.temp_dir / f"subtitle_data_track_{item.track.id}.json"

    # Write config for subprocess
    try:
        with open(config_path, "w", encoding="utf-8") as config_file:
            json.dump(ctx.settings.to_dict(), config_file, indent=2, ensure_ascii=False)
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: Failed to write OCR config: {e}")
        return None

    # Build subprocess command
    cmd = [
        sys.executable,
        "-m",
        "vsg_core.subtitles.ocr.unified_subprocess",
        "--subtitle-path",
        str(item.extracted_path.with_suffix(".idx")),
        "--lang",
        item.track.props.lang,
        "--config-json",
        str(config_path),
        "--output-json",
        str(output_json),
        "--work-dir",
        str(ocr_work_dir),
        "--logs-dir",
        str(logs_dir),
        "--debug-output-dir",
        str(debug_output_dir),
        "--track-id",
        str(item.track.id),
    ]

    runner._log_message(f"[OCR] Running OCR in subprocess for track {item.track.id}...")

    # Start subprocess
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: Failed to start OCR subprocess: {e}")
        return None

    # Parse subprocess output
    json_payload = None
    json_prefix = "__VSG_UNIFIED_OCR_JSON__ "

    if process.stdout:
        for line in process.stdout:
            line = line.rstrip("\n")
            if line.startswith(json_prefix):
                try:
                    json_payload = json.loads(line.split(json_prefix, 1)[1])
                except json.JSONDecodeError:
                    json_payload = None
            elif line:
                runner._log_message(line)

    return_code = process.wait()

    # Log stderr (filter out C++ tracebacks and noise)
    if process.stderr:
        skip_traceback = False
        for line in process.stderr:
            line = line.rstrip("\n")
            if not line:
                continue

            # Skip PaddleOCR internal spam
            if any(
                skip in line
                for skip in [
                    "Model files already exist",
                    "Creating model:",
                    "Checking connectivity",
                    "which: no ccache",
                    "UserWarning:",
                    "warnings.warn",
                    "[32m",  # ANSI green
                    "[33m",  # ANSI yellow
                    "[0m",  # ANSI reset
                ]
            ):
                continue

            # Skip C++ traceback blocks (paddle crashes)
            if "C++ Traceback" in line or "------" in line:
                skip_traceback = True
                continue
            if skip_traceback and (
                "Error Message Summary" in line or line.startswith("  ")
            ):
                continue
            if skip_traceback and not line.startswith("["):
                continue  # Skip traceback lines
            skip_traceback = False

            # Log meaningful errors only
            if any(
                marker in line
                for marker in ["ERROR", "WARNING", "WARN", "Error", "[OCR]"]
            ):
                runner._log_message(f"[OCR] {line}")

    # Check result
    if return_code != 0:
        error_detail = None
        if json_payload and not json_payload.get("success"):
            error_detail = json_payload.get("error")
        runner._log_message(f"[OCR] ERROR: OCR subprocess failed (code {return_code})")
        if error_detail:
            runner._log_message(f"[OCR] ERROR: {error_detail}")
        return None

    if not json_payload or not json_payload.get("success"):
        runner._log_message("[OCR] ERROR: OCR subprocess returned no result")
        return None

    json_path = json_payload.get("json_path")
    if not json_path:
        runner._log_message("[OCR] ERROR: OCR subprocess returned no JSON path")
        return None

    # Load SubtitleData from JSON
    try:
        return SubtitleData.from_json(json_path)
    except Exception as e:
        runner._log_message(f"[OCR] ERROR: Failed to load SubtitleData JSON: {e}")
        return None
