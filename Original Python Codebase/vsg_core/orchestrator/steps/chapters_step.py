# vsg_core/orchestrator/steps/chapters_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.chapters.process import process_chapters


class ChaptersStep:
    """
    Extracts/modifies chapter XML from Source 1.
    Applies global shift to keep chapters in sync with shifted audio tracks.
    Enhanced with better error handling - failures are logged but non-fatal.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        # Ensure ctx is not None
        if ctx is None:
            runner._log_message("[ERROR] Context is None in ChaptersStep")
            raise RuntimeError("Context is None in ChaptersStep")

        if not ctx.and_merge:
            ctx.chapters_xml = None
            return ctx

        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            # Not fatal - chapters are optional
            runner._log_message("[WARN] No Source 1 file found for chapter processing.")
            runner._log_message("[INFO] Chapters will be omitted from the final file.")
            ctx.chapters_xml = None
            return ctx

        # CRITICAL: Chapters must be shifted by the SAME amount as video container delay
        # Video delay is rounded to integer ms by mkvmerge, so chapters must match exactly
        # to land on the correct keyframes in the final container
        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0

        if shift_ms != 0:
            runner._log_message(f"[Chapters] Applying global shift of +{shift_ms}ms to chapter timestamps")
            runner._log_message(f"[Chapters] This matches the video container delay for correct keyframe alignment")
        else:
            runner._log_message("[Chapters] No global shift needed for chapters")

        try:
            xml_path = process_chapters(
                source1_file, ctx.temp_dir, runner, ctx.tool_paths,
                ctx.settings_dict, shift_ms
            )

            if xml_path:
                ctx.chapters_xml = xml_path
                runner._log_message(f"[Chapters] Successfully processed chapters: {xml_path}")
            else:
                ctx.chapters_xml = None
                runner._log_message(f"[Chapters] No chapters found in source file")

        except Exception as e:
            # Enhanced error logging but not fatal - chapters are optional
            runner._log_message(f"[ERROR] Chapter processing failed: {e}")
            runner._log_message(f"[INFO] Chapters will be omitted from the final file")
            runner._log_message(f"[DEBUG] This is not a fatal error - the merge will continue without chapters")

            # Check for specific error types to provide better guidance
            error_str = str(e)
            if "mkvextract" in error_str.lower():
                runner._log_message(f"[HINT] This may be caused by:")
                runner._log_message(f"       - mkvextract not being installed or in PATH")
                runner._log_message(f"       - Corrupted chapter data in source file")
                runner._log_message(f"       - Insufficient permissions to read source file")
            elif "xml" in error_str.lower() or "parse" in error_str.lower():
                runner._log_message(f"[HINT] This may be caused by:")
                runner._log_message(f"       - Malformed XML in chapter data")
                runner._log_message(f"       - Unsupported chapter format")
                runner._log_message(f"       - Character encoding issues")

            ctx.chapters_xml = None

        return ctx
