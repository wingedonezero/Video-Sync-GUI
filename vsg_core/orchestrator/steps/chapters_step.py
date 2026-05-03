# vsg_core/orchestrator/steps/chapters_step.py
from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.chapters.compat import is_donor_compatible, quick_probe
from vsg_core.chapters.process import process_chapters

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class ChaptersStep:
    """
    Extracts/modifies chapter XML for the final mux.

    By default uses Source 1's chapters (existing behavior). When
    ``ctx.chapter_source`` names a donor source (e.g. "Source 3"),
    chapters are pulled from that file instead, shifted into Source 1's
    video timeline using ``raw_source_delays_ms[donor]``, snapped to
    Source 1's keyframes, then shifted to container time using the
    integer ``global_shift_ms`` (matches mkvmerge's video delay).

    Donor mode is gated on a tight compatibility check: both Source 1
    and the donor must be modern progressive video at the same fps.
    Any failure (fps mismatch, MPEG-2/DVD, interlaced, donor missing,
    donor has no chapters) falls back to Source 1's chapters with a
    warning. ``chapter_source == "None"`` skips chapters entirely.

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

        chapter_source = getattr(ctx, "chapter_source", "Source 1") or "Source 1"

        # Explicit opt-out: produce no chapters at all.
        if chapter_source == "None":
            runner._log_message(
                "[Chapters] chapter_source = None — skipping chapters entirely."
            )
            ctx.chapters_xml = None
            return ctx

        # Resolve donor file + verify compatibility. Any failure path falls
        # back to Source 1 with a warning so we never break a job over
        # this feature.
        donor_file: str = source1_file
        donor_offset_ns: int = 0

        if chapter_source != "Source 1":
            candidate = ctx.sources.get(chapter_source)
            if not candidate:
                runner._log_message(
                    f"[Chapters][WARN] chapter_source '{chapter_source}' "
                    f"not present in this job's sources. Falling back to "
                    f"Source 1's chapters."
                )
                chapter_source = "Source 1"
            else:
                s1_probe = quick_probe(source1_file)
                donor_probe = quick_probe(candidate)
                ok, reason = is_donor_compatible(s1_probe, donor_probe)
                if not ok:
                    runner._log_message(
                        f"[Chapters][WARN] Donor '{chapter_source}' is "
                        f"incompatible: {reason}. Falling back to Source 1's "
                        f"chapters."
                    )
                    chapter_source = "Source 1"
                else:
                    donor_file = candidate
                    # Donor → Source 1 video-time offset. Use the raw
                    # (unrounded) source delay so we keep sub-ms precision
                    # before snap. round to ns at the boundary.
                    raw_offset_ms: float = 0.0
                    if ctx.delays is not None:
                        raw_offset_ms = ctx.delays.raw_source_delays_ms.get(
                            chapter_source, 0.0
                        )
                    donor_offset_ns = int(round(raw_offset_ms * 1_000_000))
                    runner._log_message(
                        f"[Chapters] Using donor '{chapter_source}' "
                        f"({candidate}) for chapters."
                    )
                    runner._log_message(
                        f"[Chapters] Donor offset: {raw_offset_ms:+.3f}ms "
                        f"({donor_offset_ns:+d}ns) — donor → Source 1 video time."
                    )

        # CRITICAL: Chapters must be shifted by the SAME amount as video container delay
        # Video delay is rounded to integer ms by mkvmerge, so chapters must match exactly
        # to land on the correct keyframes in the final container
        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0

        if shift_ms != 0:
            runner._log_message(
                f"[Chapters] Applying global shift of +{shift_ms}ms to chapter timestamps"
            )
            runner._log_message(
                "[Chapters] This matches the video container delay for correct keyframe alignment"
            )
        elif donor_offset_ns == 0:
            runner._log_message("[Chapters] No global shift needed for chapters")

        try:
            xml_path = process_chapters(
                donor_file,
                ctx.temp_dir,
                runner,
                ctx.tool_paths,
                ctx.settings,
                shift_ms,
                keyframe_ref_mkv=source1_file,
                donor_offset_ns=donor_offset_ns,
            )

            if xml_path:
                ctx.chapters_xml = xml_path
                runner._log_message(
                    f"[Chapters] Successfully processed chapters: {xml_path}"
                )
            elif chapter_source != "Source 1":
                # Donor had no chapters — try Source 1 as a last resort.
                runner._log_message(
                    f"[Chapters][WARN] Donor '{chapter_source}' has no "
                    f"chapters. Falling back to Source 1's chapters."
                )
                xml_path = process_chapters(
                    source1_file,
                    ctx.temp_dir,
                    runner,
                    ctx.tool_paths,
                    ctx.settings,
                    shift_ms,
                )
                ctx.chapters_xml = xml_path
                if xml_path:
                    runner._log_message(
                        f"[Chapters] Successfully processed Source 1 "
                        f"chapters: {xml_path}"
                    )
                else:
                    runner._log_message(
                        "[Chapters] No chapters found in Source 1 either."
                    )
            else:
                ctx.chapters_xml = None
                runner._log_message("[Chapters] No chapters found in source file")

        except Exception as e:
            # Enhanced error logging but not fatal - chapters are optional
            runner._log_message(f"[ERROR] Chapter processing failed: {e}")
            runner._log_message("[INFO] Chapters will be omitted from the final file")
            runner._log_message(
                "[DEBUG] This is not a fatal error - the merge will continue without chapters"
            )

            # Check for specific error types to provide better guidance
            error_str = str(e)
            if "mkvextract" in error_str.lower():
                runner._log_message("[HINT] This may be caused by:")
                runner._log_message(
                    "       - mkvextract not being installed or in PATH"
                )
                runner._log_message("       - Corrupted chapter data in source file")
                runner._log_message(
                    "       - Insufficient permissions to read source file"
                )
            elif "xml" in error_str.lower() or "parse" in error_str.lower():
                runner._log_message("[HINT] This may be caused by:")
                runner._log_message("       - Malformed XML in chapter data")
                runner._log_message("       - Unsupported chapter format")
                runner._log_message("       - Character encoding issues")

            ctx.chapters_xml = None

        return ctx
