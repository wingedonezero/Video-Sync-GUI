# vsg_core/subtitles/frame_utils/video_filters.py
"""
VapourSynth video filters for deinterlacing, IVTC, and decimation.

Standalone functions that take a VapourSynth clip + core and return a
processed clip. Used by VideoReader during initialization.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FilterResult:
    """Result of applying a video filter chain."""

    clip: object  # vs.VideoNode (not typed to avoid import)
    deinterlace_applied: bool = False
    ivtc_applied: bool = False
    vfm_applied: bool = False
    decimate_applied: bool = False
    original_fps: float | None = None


def apply_deinterlace_filter(
    clip,
    core,
    method: str,
    field_order: str,
    runner,
) -> tuple[object, bool]:
    """
    Apply deinterlace filter to VapourSynth clip.

    Args:
        clip: VapourSynth clip
        core: VapourSynth core
        method: Deinterlace method ('yadif', 'yadifmod', 'bob', 'bwdif')
        field_order: Field order ('tff' or 'bff')
        runner: CommandRunner for logging

    Returns:
        Tuple of (processed clip, whether deinterlace was applied)
    """
    if field_order not in ("tff", "bff"):
        field_order = "tff"

    tff = field_order == "tff"

    runner._log_message(
        f"[FrameUtils] Applying deinterlace: {method} (field order: {'TFF' if tff else 'BFF'})"
    )

    try:
        # Force the correct field order on the clip via _FieldBased frame property.
        # Bwdif/Yadif read _FieldBased from each frame and OVERRIDE the field/order
        # parameter when it is set. FFMS2 sets _FieldBased per-frame based on
        # FFmpeg's AV_FRAME_FLAG_INTERLACED, which is often wrong or inconsistent
        # for MPEG-2 DVD content. Without this, two encodes of the same content
        # can get different _FieldBased values from FFMS2, causing bwdif to
        # deinterlace them with different field orders -> completely different
        # progressive output -> frame comparison fails (avg_dist 40+).
        clip = core.std.SetFieldBased(clip, 2 if tff else 1)
        if method == "yadif":
            # YADIF - Yet Another DeInterlacing Filter
            # Mode 0 = output one frame per frame (not bob)
            # Order: 1 = TFF, 0 = BFF
            if hasattr(core, "yadifmod"):
                # Prefer yadifmod if available (better edge handling)
                clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
            elif hasattr(core, "yadif"):
                clip = core.yadif.Yadif(clip, order=1 if tff else 0, mode=0)
            else:
                # Fallback to standard VapourSynth functions
                runner._log_message(
                    "[FrameUtils] YADIF plugin not found, using std.SeparateFields + DoubleWeave"
                )
                clip = _deinterlace_fallback(clip, core, tff)

        elif method == "yadifmod":
            # YADIFmod - improved edge handling
            if hasattr(core, "yadifmod"):
                clip = core.yadifmod.Yadifmod(clip, order=1 if tff else 0, mode=0)
            else:
                runner._log_message(
                    "[FrameUtils] YADIFmod not available, falling back to YADIF"
                )
                return apply_deinterlace_filter(
                    clip, core, "yadif", field_order, runner
                )

        elif method == "bob":
            # Bob - doubles framerate by outputting each field as frame
            clip = core.std.SeparateFields(clip, tff=tff)
            clip = core.resize.Spline36(clip, height=clip.height * 2)

        elif method == "bwdif":
            # BWDIF - motion adaptive deinterlacer
            if hasattr(core, "bwdif"):
                clip = core.bwdif.Bwdif(clip, field=1 if tff else 0)
            else:
                runner._log_message(
                    "[FrameUtils] BWDIF not available, falling back to YADIF"
                )
                return apply_deinterlace_filter(
                    clip, core, "yadif", field_order, runner
                )

        else:
            runner._log_message(
                f"[FrameUtils] Unknown deinterlace method: {method}, using YADIF"
            )
            return apply_deinterlace_filter(clip, core, "yadif", field_order, runner)

        runner._log_message("[FrameUtils] Deinterlace filter applied successfully")
        return clip, True

    except Exception as e:
        runner._log_message(f"[FrameUtils] Deinterlace failed: {e}, using raw frames")
        return clip, False


def _deinterlace_fallback(clip, core, tff: bool):
    """Fallback deinterlacing using standard VapourSynth functions."""
    clip = core.std.SeparateFields(clip, tff=tff)
    clip = core.std.DoubleWeave(clip, tff=tff)
    clip = core.std.SelectEvery(clip, 2, 0)
    return clip


def apply_ivtc_filter(
    clip,
    core,
    field_order: str,
    skip_decimate: bool,
    runner,
) -> FilterResult:
    """
    Apply Inverse Telecine (IVTC) to recover progressive frames from telecine.

    Uses VIVTC (VFM + VDecimate) to:
    1. VFM: Field match to find original progressive frames
    2. VDecimate: Remove duplicate frames (30fps -> 24fps)

    This converts 29.97i telecine content back to ~23.976p progressive.

    Args:
        clip: VapourSynth clip (interlaced telecine)
        core: VapourSynth core
        field_order: Field order ('tff' or 'bff')
        skip_decimate: If True, apply VFM only (no VDecimate)
        runner: CommandRunner for logging

    Returns:
        FilterResult with processed clip and flags
    """
    if field_order not in ("tff", "bff"):
        field_order = "tff"

    tff = field_order == "tff"

    runner._log_message(
        f"[FrameUtils] Applying IVTC (field order: {'TFF' if tff else 'BFF'})"
    )

    original_fps = clip.fps_num / clip.fps_den

    # Normalize telecine timebase before IVTC when FFMS2 exposes odd VFR-ish
    # rates (e.g. 29.778). This stabilizes VDecimate output cadence.
    if 29.0 < original_fps < 31.0 and abs(original_fps - 30000 / 1001) > 0.01:
        clip = core.std.AssumeFPS(clip, fpsnum=30000, fpsden=1001)
        runner._log_message(
            f"[FrameUtils] Normalized pre-IVTC FPS ({original_fps:.3f} -> 29.970)"
        )

    try:
        # Force correct field order in frame properties (same reason as
        # apply_deinterlace_filter -- FFMS2's per-frame _FieldBased can be
        # wrong for MPEG-2, and VFM reads it to override the order param).
        clip = core.std.SetFieldBased(clip, 2 if tff else 1)

        # Check if VIVTC is available
        if hasattr(core, "vivtc"):
            # VFM: Field matching - recovers progressive frames
            clip = core.vivtc.VFM(clip, order=1 if tff else 0)

            if skip_decimate:
                runner._log_message(
                    f"[FrameUtils] VFM-only applied with VIVTC "
                    f"({original_fps:.3f}fps, VDecimate skipped)"
                )
                return FilterResult(
                    clip=clip,
                    vfm_applied=True,
                    original_fps=original_fps,
                )

            # VDecimate: Remove duplicates (5 frames -> 4 frames)
            clip = core.vivtc.VDecimate(clip)

            # Force canonical film rate after IVTC for stable downstream
            # frame-index math across DVD telecine sources.
            clip = core.std.AssumeFPS(clip, fpsnum=24000, fpsden=1001)

            runner._log_message(
                f"[FrameUtils] IVTC applied with VIVTC "
                f"({original_fps:.3f}fps -> {clip.fps_num / clip.fps_den:.3f}fps)"
            )
            return FilterResult(
                clip=clip,
                ivtc_applied=True,
                original_fps=original_fps,
            )

        # Fallback: Try TIVTC if VIVTC not available
        elif hasattr(core, "tivtc"):
            clip = core.tivtc.TFM(clip, order=1 if tff else 0)

            if skip_decimate:
                runner._log_message(
                    f"[FrameUtils] VFM-only applied with TIVTC "
                    f"({original_fps:.3f}fps, TDecimate skipped)"
                )
                return FilterResult(
                    clip=clip,
                    vfm_applied=True,
                    original_fps=original_fps,
                )

            clip = core.tivtc.TDecimate(clip, mode=1)

            # Force canonical film rate after IVTC
            clip = core.std.AssumeFPS(clip, fpsnum=24000, fpsden=1001)

            runner._log_message(
                f"[FrameUtils] IVTC applied with TIVTC "
                f"({original_fps:.3f}fps -> {clip.fps_num / clip.fps_den:.3f}fps)"
            )
            return FilterResult(
                clip=clip,
                ivtc_applied=True,
                original_fps=original_fps,
            )

        else:
            runner._log_message(
                "[FrameUtils] WARNING: No IVTC plugin available (vivtc or tivtc)"
            )
            runner._log_message("[FrameUtils] Install vivtc plugin for VapourSynth")
            runner._log_message(
                "[FrameUtils] Falling back to deinterlacing (may cause frame count mismatch)"
            )
            # Fall back to regular deinterlacing
            clip, applied = apply_deinterlace_filter(
                clip, core, "bwdif", field_order, runner
            )
            return FilterResult(
                clip=clip,
                deinterlace_applied=applied,
                original_fps=original_fps,
            )

    except Exception as e:
        runner._log_message(f"[FrameUtils] IVTC failed: {e}")
        runner._log_message("[FrameUtils] Falling back to deinterlacing")
        clip, applied = apply_deinterlace_filter(
            clip, core, "bwdif", field_order, runner
        )
        return FilterResult(
            clip=clip,
            deinterlace_applied=applied,
            original_fps=original_fps,
        )


def apply_decimate_filter(clip, core, runner) -> FilterResult:
    """
    Apply VDecimate only (no VFM) for progressive content with duplicate frames.

    For progressive content with 2:3 pulldown (soft telecine), the frames are
    already progressive but contain duplicates from the pulldown pattern.
    VDecimate detects and removes these duplicates, converting ~30fps to ~24fps.

    Args:
        clip: VapourSynth clip (progressive with duplicate frames)
        core: VapourSynth core
        runner: CommandRunner for logging

    Returns:
        FilterResult with processed clip and flags
    """
    original_fps = clip.fps_num / clip.fps_den

    runner._log_message(
        f"[FrameUtils] Applying VDecimate for progressive-with-pulldown "
        f"({original_fps:.3f}fps)"
    )

    try:
        if hasattr(core, "vivtc"):
            clip = core.vivtc.VDecimate(clip)
            new_fps = clip.fps_num / clip.fps_den
            runner._log_message(
                f"[FrameUtils] VDecimate applied "
                f"({original_fps:.3f}fps -> {new_fps:.3f}fps)"
            )
            return FilterResult(
                clip=clip,
                decimate_applied=True,
                original_fps=original_fps,
            )

        elif hasattr(core, "tivtc"):
            clip = core.tivtc.TDecimate(clip, mode=1)
            new_fps = clip.fps_num / clip.fps_den
            runner._log_message(
                f"[FrameUtils] TDecimate applied "
                f"({original_fps:.3f}fps -> {new_fps:.3f}fps)"
            )
            return FilterResult(
                clip=clip,
                decimate_applied=True,
                original_fps=original_fps,
            )

        else:
            runner._log_message(
                "[FrameUtils] WARNING: No decimation plugin available (vivtc or tivtc)"
            )
            runner._log_message(
                "[FrameUtils] Duplicate frames will remain (~30fps instead of ~24fps)"
            )
            return FilterResult(clip=clip, original_fps=original_fps)

    except Exception as e:
        runner._log_message(f"[FrameUtils] Decimation failed: {e}")
        return FilterResult(clip=clip, original_fps=original_fps)
