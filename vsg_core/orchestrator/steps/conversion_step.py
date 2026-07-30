# vsg_core/orchestrator/steps/conversion_step.py
"""
Post-extraction step: losslessly convert flagged audio tracks to FLAC.

Runs right after ExtractStep, before audio correction. Each converted track
replaces its extracted file in place (same PlanItem, same mux order), so
every later stage — delays, trimming, muxing — is unaffected.

Safety model:
- Only lossless sources are converted (PCM/WAV, TrueHD, DTS-HD MA).
  Object-based audio (Atmos, DTS:X) is skipped: decoding would silently
  discard the object/height data.
- Tracks from a source with pending audio correction are skipped — the
  corrector produces its own FLAC and preserves the original track, so a
  pre-conversion would just be thrown away.
- Every conversion is verified bit-identical: both files are decoded to the
  same raw PCM format and their MD5s must match, plus channel count,
  sample rate, and bit depth are compared.
- Any failure keeps the original extracted track and is recorded in
  ``ctx.flac_conversion_failures`` for the final report.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from vsg_core.models.media import StreamProps, Track

if TYPE_CHECKING:
    from pathlib import Path

    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.context_types import DriftFlagsEntry, SegmentFlagsEntry
    from vsg_core.models.jobs import PlanItem
    from vsg_core.orchestrator.steps.context import Context

# mkvmerge codec IDs whose decoded audio is bit-exact (lossless), making a
# FLAC conversion transparent. A_MS/ACM tracks are extracted to WAV by
# ExtractStep, so they are plain PCM by the time this step sees them.
_LOSSLESS_CODEC_PREFIXES = ("A_PCM", "A_MS/ACM", "A_TRUEHD", "A_DTS")

# FLAC's container limit.
_FLAC_MAX_CHANNELS = 8


def item_label(item: PlanItem) -> str:
    """Stable identifier used in logs, skip/failure records, and validation."""
    return f"{item.track.source} audio track {item.track.id}"


def eligibility_skip_reason(codec_id: str, stream: dict | None) -> str | None:
    """Why a track cannot be converted, or None if it is eligible.

    ``stream`` is the ffprobe stream dict of the *extracted* file; its
    ``profile`` string is the authority for object-based extensions
    (mirrors AudioObjectBasedAuditor's detection).
    """
    cid = (codec_id or "").upper()

    if "A_FLAC" in cid:
        return "already FLAC"

    if not any(prefix in cid for prefix in _LOSSLESS_CODEC_PREFIXES):
        return f"codec {codec_id or 'unknown'} is not lossless"

    if stream is None:
        return "ffprobe could not read the extracted track"

    profile = str(stream.get("profile") or "")
    if "atmos" in profile.lower():
        return f"object-based audio ({profile})"

    try:
        channels = int(stream.get("channels") or 0)
    except (TypeError, ValueError):
        channels = 0
    if channels > _FLAC_MAX_CHANNELS:
        return f"{channels} channels exceed FLAC's limit of {_FLAC_MAX_CHANNELS}"

    if "A_DTS" in cid:
        profile_upper = profile.upper()
        if "DTS:X" in profile_upper:
            return f"object-based audio ({profile})"
        if not profile_upper.startswith("DTS-HD MA"):
            return (
                f"DTS profile '{profile or 'unknown'}' is not lossless "
                "(DTS-HD MA required)"
            )
        return None

    if "A_TRUEHD" in cid:
        return None

    # PCM family (A_PCM*, A_MS/ACM extracted to WAV)
    codec_name = str(stream.get("codec_name") or "")
    if not codec_name.startswith("pcm_"):
        return f"expected PCM data, found '{codec_name or 'unknown'}'"
    return None


def correction_skip_reason(
    source: str,
    stepping_enabled: bool,
    segment_flags: dict[str, SegmentFlagsEntry],
    pal_drift_flags: dict[str, DriftFlagsEntry],
    linear_drift_flags: dict[str, DriftFlagsEntry],
) -> str | None:
    """Why conversion should defer to a pending audio correction, or None.

    Correction flag keys are "{source}_{track_id}". Audio correction targets
    every audio track from the flagged source, outputs its own FLAC, and
    preserves the original — converting first would be wasted work whose
    result gets discarded. Subs-only stepping never touches audio, so it
    does not block conversion.
    """
    if not stepping_enabled:
        return None

    for key, flag_info in segment_flags.items():
        if key.split("_")[0] == source and not flag_info.get("subs_only", False):
            return (
                "stepping correction pending for this source "
                "(it outputs FLAC and preserves the original track)"
            )
    if any(key.split("_")[0] == source for key in pal_drift_flags):
        return (
            "PAL drift correction pending for this source "
            "(it outputs FLAC and preserves the original track)"
        )
    if any(key.split("_")[0] == source for key in linear_drift_flags):
        return (
            "linear drift correction pending for this source "
            "(it outputs FLAC and preserves the original track)"
        )
    return None


def _stream_bits(stream: dict) -> int | None:
    """Effective bit depth of an ffprobe stream (raw bits win over container)."""
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            bits = int(stream.get(key) or 0)
        except (TypeError, ValueError):
            bits = 0
        if bits > 0:
            return bits
    return None


class ConversionStep:
    """Converts eligible flagged audio tracks to FLAC, verified bit-identical."""

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            return ctx

        candidates = [
            item
            for item in (ctx.extracted_items or [])
            if item.track.type == "audio"
            and item.convert_to_flac
            and not item.is_preserved
        ]
        if not candidates:
            return ctx

        runner._log_message(
            f"[FLAC Convert] {len(candidates)} audio track(s) flagged for conversion."
        )

        for item in candidates:
            label = item_label(item)

            reason = correction_skip_reason(
                item.track.source,
                ctx.settings.stepping_enabled,
                ctx.segment_flags,
                ctx.pal_drift_flags,
                ctx.linear_drift_flags,
            )
            stream: dict | None = None
            if reason is None:
                stream = self._probe_audio_stream(
                    item.extracted_path, runner, ctx.tool_paths
                )
                reason = eligibility_skip_reason(item.track.props.codec_id, stream)

            if reason is not None:
                runner._log_message(f"[FLAC Convert] Skipping {label}: {reason}")
                ctx.flac_conversion_skips.append(f"{label}: {reason}")
                continue

            assert stream is not None  # eligibility passed, so the probe succeeded
            error = self._convert_and_verify(ctx, item, stream, runner)
            if error is not None:
                runner._log_message(
                    f"[ERROR] [FLAC Convert] {label}: {error}. "
                    "Keeping the original track."
                )
                ctx.flac_conversion_failures.append(f"{label}: {error}")
            else:
                ctx.flac_conversions.append(label)

        return ctx

    def _probe_audio_stream(
        self,
        path: Path | None,
        runner: CommandRunner,
        tool_paths: dict[str, str | None],
    ) -> dict | None:
        """First audio stream of ``path`` per ffprobe, or None."""
        if path is None or not path.exists():
            return None
        # Raw TrueHD/DTS elementary streams need a generous probe window for
        # reliable profile (Atmos/DTS:X/MA) detection.
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-analyzeduration",
            "10M",
            "-probesize",
            "50M",
            "-print_format",
            "json",
            "-show_streams",
            "-select_streams",
            "a:0",
            str(path),
        ]
        out = runner.run(cmd, tool_paths)
        if not out or not isinstance(out, str):
            return None
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None
        streams = data.get("streams") or []
        return streams[0] if streams else None

    def _convert_and_verify(
        self,
        ctx: Context,
        item: PlanItem,
        source_stream: dict,
        runner: CommandRunner,
    ) -> str | None:
        """Convert one track and prove it lossless. Returns an error, or None.

        On any error the partial output is removed and ``item`` is left
        untouched, so the original extracted track flows through the rest
        of the pipeline exactly as if conversion was never requested.
        """
        log = runner._log_message
        src = item.extracted_path
        if src is None or not src.exists():
            return f"extracted file missing at {src}"

        label = item_label(item)
        out = ctx.temp_dir / f"{src.stem}_converted.flac"
        log(
            f"[FLAC Convert] Converting {label} "
            f"({item.track.props.codec_id}, {src.name})..."
        )

        encode_cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-nostats",
            "-i",
            str(src),
            "-map",
            "0:a:0",
            "-c:a",
            "flac",
            "-compression_level",
            "12",
            str(out),
        ]
        if runner.run(encode_cmd, ctx.tool_paths) is None:
            out.unlink(missing_ok=True)
            return "ffmpeg FLAC encode failed"
        if not out.exists() or out.stat().st_size == 0:
            out.unlink(missing_ok=True)
            return "ffmpeg produced no FLAC output"

        # --- Verification 1: stream properties must be unchanged ---
        flac_stream = self._probe_audio_stream(out, runner, ctx.tool_paths)
        if flac_stream is None:
            out.unlink(missing_ok=True)
            return "could not probe the converted FLAC"

        for prop in ("channels", "sample_rate"):
            src_val = str(source_stream.get(prop) or "")
            flac_val = str(flac_stream.get(prop) or "")
            if src_val != flac_val:
                out.unlink(missing_ok=True)
                return f"{prop} changed ({src_val} -> {flac_val})"

        src_bits = _stream_bits(source_stream)
        flac_bits = _stream_bits(flac_stream)
        if src_bits is not None and flac_bits is not None and src_bits != flac_bits:
            out.unlink(missing_ok=True)
            return f"bit depth changed ({src_bits}-bit -> {flac_bits}-bit)"

        # --- Verification 2: decoded samples must be bit-identical ---
        src_md5 = self._decoded_md5(src, ctx, runner, tag="orig")
        flac_md5 = self._decoded_md5(out, ctx, runner, tag="flac")
        if not src_md5 or not flac_md5:
            out.unlink(missing_ok=True)
            return "could not compute decoded-audio MD5 for verification"
        if src_md5 != flac_md5:
            out.unlink(missing_ok=True)
            return "decoded audio MD5 mismatch (conversion is not bit-identical)"

        # --- Success: swap the item to the FLAC, keep the original path ---
        orig_size = src.stat().st_size
        flac_size = out.stat().st_size
        pct = (flac_size / orig_size * 100.0) if orig_size else 0.0
        log(
            f"[FLAC Convert] ✓ {label} verified bit-identical "
            f"(decoded MD5 {src_md5[:8]}…): "
            f"{orig_size / 1_048_576:.1f} MB -> {flac_size / 1_048_576:.1f} MB "
            f"({pct:.0f}%)"
        )

        item.original_extracted_path = src
        item.extracted_path = out
        item.flac_converted = True
        original_props = item.track.props
        item.track = Track(
            source=item.track.source,
            id=item.track.id,
            type=item.track.type,
            props=StreamProps(
                codec_id="A_FLAC",
                lang=original_props.lang,
                name=original_props.name,
            ),
        )

        if ctx.audit:
            ctx.audit.append_event(
                "milestone",
                f"FLAC conversion: {label}",
                {
                    "original_codec": original_props.codec_id,
                    "original_file": str(src),
                    "flac_file": str(out),
                    "decoded_md5": src_md5,
                    "channels": source_stream.get("channels"),
                    "sample_rate": source_stream.get("sample_rate"),
                    "bit_depth": src_bits,
                },
            )
        return None

    def _decoded_md5(
        self, path: Path, ctx: Context, runner: CommandRunner, tag: str
    ) -> str | None:
        """MD5 of ``path`` decoded to canonical raw PCM (s32le).

        Both the original and the FLAC are normalized to the same sample
        format, so equal digests prove sample-exact conversion. The digest
        is written to a file because CommandRunner merges stderr into the
        captured stdout.
        """
        md5_path = ctx.temp_dir / f"{path.stem}_{tag}.md5"
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-nostats",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-c:a",
            "pcm_s32le",
            "-f",
            "md5",
            str(md5_path),
        ]
        try:
            if runner.run(cmd, ctx.tool_paths) is None:
                return None
            try:
                text = md5_path.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            digest = text.removeprefix("MD5=").strip()
            return digest or None
        finally:
            md5_path.unlink(missing_ok=True)
