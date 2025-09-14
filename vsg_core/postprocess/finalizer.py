# vsg_core/postprocess/finalizer.py
# -*- coding: utf-8 -*-
import shutil
from pathlib import Path
from ..io.runner import CommandRunner
from .chapter_backup import extract_chapters_xml, inject_chapters


def finalize_merged_file(temp_output_path: Path, final_output_path: Path, runner: CommandRunner, config: dict, tool_paths: dict):
    """
    Post-merge finalization with chapter language preservation.

    Since FFmpeg's avoid_negative_ts only affects media streams (not chapter metadata),
    we backup chapters before FFmpeg processing and restore them after to preserve languages.
    """
    log = runner._log_message
    log("--- Post-Merge: Finalizing File ---")

    # Step 1: Backup chapters before FFmpeg processing
    # FFmpeg doesn't change chapter timestamps, but it may affect language metadata
    log("[Finalize] Backing up chapter languages...")
    original_chapters_xml = extract_chapters_xml(temp_output_path, runner, tool_paths)

    # Step 2: FFmpeg timestamp normalization (affects media streams only)
    ffmpeg_input = str(temp_output_path)
    ffmpeg_temp_output = str(temp_output_path.with_suffix('.normalized.mkv'))

    log("[Finalize] Step 1/2: Rebasing timestamps with FFmpeg...")
    ffmpeg_cmd = [
        'ffmpeg', '-y', '-i', ffmpeg_input,
        '-c', 'copy', '-map', '0',
        '-fflags', '+genpts',
        '-avoid_negative_ts', 'make_zero',
        ffmpeg_temp_output
    ]
    ffmpeg_ok = runner.run(ffmpeg_cmd, tool_paths) is not None

    if not ffmpeg_ok:
        log("[WARNING] Timestamp normalization with FFmpeg failed. The original merged file will be used.")
        shutil.move(ffmpeg_input, str(final_output_path))
        return

    # Replace the original with the normalized version
    Path(ffmpeg_input).unlink()
    Path(ffmpeg_temp_output).rename(temp_output_path)
    log("Timestamp normalization successful.")

    # Step 3: Restore original chapters (preserves keyframe alignment and languages)
    if original_chapters_xml:
        log("[Finalize] Restoring original chapters...")
        inject_chapters(temp_output_path, original_chapters_xml, runner, tool_paths)

    # Step 4: Optional tag stripping
    if config.get('post_mux_strip_tags', False):
        log("[Finalize] Step 2/2: Stripping ENCODER tag with mkvpropedit...")
        propedit_cmd = ['mkvpropedit', str(temp_output_path), '--tags', 'all:']
        runner.run(propedit_cmd, tool_paths)
        log("Stripped ENCODER tag successfully.")

    # Step 5: Move to final output location
    shutil.move(str(temp_output_path), str(final_output_path))
    log("[Finalize] Post-merge finalization complete.")
