# vsg_core/postprocess/finalizer.py
# -*- coding: utf-8 -*-
import shutil
from pathlib import Path
from ..io.runner import CommandRunner
from .chapter_backup import extract_chapters_xml, inject_chapters

def check_if_rebasing_is_needed(mkv_path: Path, runner: CommandRunner, tool_paths: dict) -> bool:
    """
    Uses ffprobe to check if the first video packet's timestamp is non-zero.
    Returns True if the file needs to be rebased.
    """
    runner._log_message("[Finalize] Checking if timestamp rebasing is necessary...")
    cmd = [
        'ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'packet=pts_time',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-read_intervals', '%+#1', # Read only the first packet
        str(mkv_path)
    ]
    out = runner.run(cmd, tool_paths)
    try:
        # Check if the first video frame's timestamp is greater than a small tolerance
        if out and float(out.strip()) > 0.01:
            runner._log_message(f"[Finalize] First video timestamp is {float(out.strip()):.3f}s. Rebasing is required.")
            return True
    except (ValueError, IndexError):
        # Fallback or error, assume it's not needed
        pass

    runner._log_message("[Finalize] Video timestamps already start at zero. Rebasing is not required.")
    return False

def finalize_merged_file(temp_output_path: Path, final_output_path: Path, runner: CommandRunner, config: dict, tool_paths: dict):
    """
    Post-merge finalization with chapter language preservation.
    """
    log = runner._log_message
    log("--- Post-Merge: Finalizing File ---")

    # Step 1: Backup chapters before FFmpeg processing
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
