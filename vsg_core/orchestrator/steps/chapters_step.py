# vsg_core/orchestrator/steps/chapters_step.py
from __future__ import annotations

from typing import TYPE_CHECKING

from vsg_core.chapters.compat import is_donor_compatible, quick_probe
from vsg_core.chapters.process import process_chapters

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


def _resolve_donor_offset_ms(
    ctx: Context,
    runner: CommandRunner,
    donor_source: str,
    source1_file: str,
) -> tuple[float, str]:
    """
    Pick the best available donor → Source 1 offset for chapter shifting.

    Priority:
      1. ``ctx.video_verified_sources[donor]`` (already populated when the
         donor contributed subs that ran through video-verified).
      2. Run video-verified for the donor *now* — but ONLY when the user
         has chosen video-verified sync mode. This handles the
         chapter-only donor case (donor file contributes only chapters,
         no subs, so video-verified didn't run for it).
      3. Fall back to ``raw_source_delays_ms[donor]`` (audio correlation).

    Returns ``(offset_ms, label)`` where ``label`` is a short tag like
    "video-verified", "video-verified (chapter donor)", or
    "audio correlation" used purely for logging.
    """
    # 1. Pre-computed video-verified result wins.
    cached = ctx.video_verified_sources.get(donor_source)
    if cached:
        corrected = cached.get("corrected_delay_ms")
        if corrected is not None:
            label = (
                "video-verified (cached)"
                if not cached.get("fallback")
                else "audio correlation (video-verified fell back)"
            )
            return float(corrected), label

    # 2. Live video-verified pass for the donor — gated to video-verified
    #    *subtitle* sync mode (settings.subtitle_sync_mode) so we don't
    #    surprise correlation-only users with an extra ~100s of analysis
    #    time. Note this is NOT ctx.sync_mode (which is the *audio
    #    timing* mode: positive_only / allow_negative / preserve_existing).
    subtitle_sync_mode = getattr(ctx.settings, "subtitle_sync_mode", "") or ""
    if subtitle_sync_mode == "video-verified":
        donor_video = ctx.sources.get(donor_source)
        if donor_video:
            try:
                # Imported lazily so the chapter step doesn't pull in the
                # video-verified plugin chain unless we actually need it.
                from vsg_core.subtitles.sync_mode_plugins.video_verified.preprocessing import (
                    _calculate_offset_for_method,
                )

                # Audio-correlation seed: the sliding window matcher uses
                # this as the "we expect roughly this offset" anchor and
                # searches around it. We pass the existing source delay
                # if there is one, else 0.
                seed_total_delay_ms: float = 0.0
                global_shift_ms: float = 0.0
                if ctx.delays is not None:
                    seed_total_delay_ms = ctx.delays.raw_source_delays_ms.get(
                        donor_source, 0.0
                    )
                    global_shift_ms = ctx.delays.raw_global_shift_ms

                runner._log_message(
                    f"[Chapters] Running video-verified pass for donor "
                    f"'{donor_source}' (chapter-only donor, no cached "
                    f"result). Seed offset: {seed_total_delay_ms:+.3f}ms."
                )

                corrected_delay_ms, details = _calculate_offset_for_method(
                    source_video=str(donor_video),
                    target_video=str(source1_file),
                    total_delay_ms=seed_total_delay_ms,
                    global_shift_ms=global_shift_ms,
                    source_key=donor_source,
                    ctx=ctx,
                    runner=runner,
                )

                if corrected_delay_ms is not None:
                    # Cache the result so later audits / re-reads see it,
                    # mirroring run_per_source_preprocessing's contract.
                    ctx.video_verified_sources[donor_source] = {
                        "original_delay_ms": seed_total_delay_ms,
                        "corrected_delay_ms": corrected_delay_ms,
                        "details": details,
                        "fallback": False,
                    }
                    return float(corrected_delay_ms), "video-verified (chapter donor)"

                runner._log_message(
                    f"[Chapters] video-verified produced no offset for "
                    f"donor '{donor_source}'. Falling back to audio "
                    f"correlation."
                )
            except Exception as e:
                runner._log_message(
                    f"[Chapters][WARN] video-verified for donor "
                    f"'{donor_source}' failed: {e}. Falling back to audio "
                    f"correlation."
                )

    # 3. Audio correlation fallback (today's behavior).
    raw_offset_ms: float = 0.0
    if ctx.delays is not None:
        raw_offset_ms = ctx.delays.raw_source_delays_ms.get(donor_source, 0.0)
    return raw_offset_ms, "audio correlation"


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

        # Track what was requested vs what we end up using. Only persisted
        # to ctx when the user picked something other than the default
        # ("Source 1") so we don't generate noise for unaltered jobs.
        requested_source = chapter_source

        # Explicit opt-out: produce no chapters at all.
        if chapter_source == "None":
            runner._log_message(
                "[Chapters] chapter_source = None — skipping chapters entirely."
            )
            ctx.chapters_xml = None
            ctx.chapter_source_outcome = {
                "requested": "None",
                "actual": "None",
                "reason": "",
                "fallback": False,
            }
            return ctx

        # Resolve donor file + verify compatibility. Any failure path falls
        # back to Source 1 with a warning so we never break a job over
        # this feature.
        donor_file: str = source1_file
        donor_offset_ns: int = 0
        fallback_reason: str = ""

        if chapter_source != "Source 1":
            candidate = ctx.sources.get(chapter_source)
            if not candidate:
                fallback_reason = (
                    f"donor '{chapter_source}' not present in this job's sources"
                )
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
                    fallback_reason = reason or "incompatible donor"
                    runner._log_message(
                        f"[Chapters][WARN] Donor '{chapter_source}' is "
                        f"incompatible: {reason}. Falling back to Source 1's "
                        f"chapters."
                    )
                    chapter_source = "Source 1"
                else:
                    donor_file = candidate
                    # Donor → Source 1 video-time offset. Prefer
                    # video-verified frame alignment when available
                    # (cached or live); fall back to audio correlation.
                    # Audio correlation can have a ~1 frame systematic
                    # offset from video alignment when audio masters
                    # differ between donor and Source 1 (e.g. broadcast
                    # vs. Bluray) — chapters are anchored to video
                    # scenes, not to audio, so video alignment is the
                    # right input here.
                    raw_offset_ms, offset_source = _resolve_donor_offset_ms(
                        ctx, runner, chapter_source, source1_file
                    )
                    donor_offset_ns = int(round(raw_offset_ms * 1_000_000))
                    runner._log_message(
                        f"[Chapters] Using donor '{chapter_source}' "
                        f"({candidate}) for chapters."
                    )
                    runner._log_message(
                        f"[Chapters] Donor offset: {raw_offset_ms:+.3f}ms "
                        f"({donor_offset_ns:+d}ns) via {offset_source} — "
                        f"donor → Source 1 video time."
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
                # Donor was accepted by the gate but had no chapters of its
                # own. Try Source 1 as a last resort and record this as a
                # fallback so the auditor surfaces it.
                fallback_reason = f"donor '{chapter_source}' has no chapters"
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
                # The path we ended up using is Source 1, regardless of
                # whether it had chapters or not.
                chapter_source = "Source 1"
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

        # Record the outcome ONLY when the user picked something other than
        # the default. Default ("Source 1" requested + "Source 1" used) is
        # the unmodified path — no need to surface anything.
        if requested_source != "Source 1":
            ctx.chapter_source_outcome = {
                "requested": requested_source,
                "actual": chapter_source,
                "reason": fallback_reason,
                "fallback": requested_source != chapter_source,
            }

        return ctx
