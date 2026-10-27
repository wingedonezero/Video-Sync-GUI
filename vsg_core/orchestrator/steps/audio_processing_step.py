# vsg_core/orchestrator/steps/audio_processing_step.py
"""
Audio Processing step: every change to audio before the mux happens here.

Order:
1. Stepping verifies its EDL first. PAL / linear drift is only logged:
   that correction is disconnected (docs/plans/drift-correction.md).
2. Every audio track gets exactly one route:
   - ``corrected`` (stepping): every audio track of a source with a verified
     EDL. One verified finisher encode applies the whole EDL (start delay,
     silence inserts, cuts) to the samples plus the end trim; mkvmerge then
     applies no delay. Lossy tracks are decoded and stored as 24-bit FLAC.
   - ``flac``: a lossless track the user asked to convert, or a track that is
     already FLAC and needs a change. One verified FLAC encode bakes the
     whole delay into the samples (start cut, or digital silence for a
     positive delay) and, when "trim converted audio to the video end" is on,
     cuts the end at the video end (never Source 1). mkvmerge then applies no
     delay to it.
   - ``passthrough``: every other track (lossy, object audio, lossless not
     converted) in a codec the app can cut: it stays in its codec, the app
     drops whole units before the delay point and, with the end trim on (not
     Source 1), after the video end; mkvmerge gets only the residual (>= 0).
     See ``vsg_core/audio_processing/passthrough.py``.
   - ``untouched``: a codec the app does not cut, or a refused cut; muxed as
     extracted with mkvmerge ``--sync`` exactly as before.

A FLAC request is never lost: if a correction was pending but produced
nothing (no EDL, QA failure), the track still takes the FLAC route here. Any failure keeps the
original track (untouched) and is reported, including a strict decode that
hits a damaged or lossy frame (see ``STRICT_DECODE_ARGS``).
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING

from vsg_core.audio_processing import (
    EditPlan,
    FinishError,
    bake_delay,
    delay_tags,
    edit_tags,
    end_cap_samples,
    finish,
    format_edit_plan,
    ms_to_ns,
    plan_for_delay,
)
from vsg_core.audio_processing.encoder import STRICT_DECODE_ARGS, SUPPORTED_BITS
from vsg_core.audio_processing.passthrough import (
    PassthroughCut,
    PassthroughError,
    cut_passthrough,
    passthrough_kind,
)
from vsg_core.correction.stepping import swap_in_corrected_track
from vsg_core.correction.stepping.edit_plan import edl_to_edits
from vsg_core.extraction.tracks import get_stream_info_with_delays
from vsg_core.models.audio_processing import AudioProcessingResult, AudioRouteStr
from vsg_core.models.media import StreamProps, Track
from vsg_core.orchestrator.steps.audio_correction_step import AudioCorrectionStep

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from vsg_core.audio_processing import DelayBake, FinishResult
    from vsg_core.correction.stepping import AudioSegment
    from vsg_core.io.runner import CommandRunner
    from vsg_core.models.jobs import PlanItem
    from vsg_core.orchestrator.steps.context import Context

# mkvmerge codec IDs whose decode is bit-exact. A_MS/ACM tracks are extracted
# to WAV by ExtractStep, so they are plain PCM by the time they get here.
_LOSSLESS_CODEC_PREFIXES = ("A_PCM", "A_MS/ACM", "A_TRUEHD", "A_MLP", "A_DTS", "A_FLAC")
_FLAC_MAX_CHANNELS = 8


def item_label(item: PlanItem) -> str:
    """Stable identifier used in logs, skip/failure records, and validation."""
    label = f"{item.track.source} audio track {item.track.id}"
    return f"{label} (preserved original)" if item.is_preserved else label


def stream_bits(stream: dict) -> int | None:
    """Effective bit depth of an ffprobe stream (raw bits win over container)."""
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            bits = int(stream.get(key) or 0)
        except (TypeError, ValueError):
            bits = 0
        if bits > 0:
            return bits
    return None


def eligibility_skip_reason(codec_id: str, stream: dict | None) -> str | None:
    """Why a track cannot take the FLAC route, or None if it can.

    ``stream`` is the ffprobe stream dict of the *extracted* file; its
    ``profile`` string is the authority for object-based extensions
    (mirrors AudioObjectBasedAuditor's detection).
    """
    cid = (codec_id or "").upper()
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
            return f"DTS profile '{profile or 'unknown'}' is not lossless (DTS-HD MA required)"

    codec_name = str(stream.get("codec_name") or "")
    if "A_PCM" in cid or "A_MS/ACM" in cid:
        if not codec_name.startswith("pcm_"):
            return f"expected PCM data, found '{codec_name or 'unknown'}'"
        if codec_name.startswith(("pcm_f", "pcm_lxf")):
            return f"floating-point PCM ({codec_name}) cannot be stored in FLAC"

    bits = stream_bits(stream)
    if bits not in SUPPORTED_BITS:
        return f"{bits or 'unknown'}-bit audio is not supported (16/20/24-bit only)"
    return None


def source1_audio_offset_ms(mkvmerge_info: dict, audio_track_id: int) -> float:
    """Source 1 audio start relative to its video, exact to the ns, from the
    ``minimum_timestamp`` values of ``mkvmerge -J`` (0 when absent)."""
    tracks = mkvmerge_info.get("tracks", [])

    def min_ts(track: dict) -> int:
        return int((track.get("properties") or {}).get("minimum_timestamp") or 0)

    video = next((t for t in tracks if t.get("type") == "video"), None)
    audio = next(
        (
            t
            for t in tracks
            if t.get("type") == "audio" and t.get("id") == audio_track_id
        ),
        None,
    )
    if audio is None:
        return 0.0
    return (min_ts(audio) - (min_ts(video) if video else 0)) / 1_000_000


def output_video_end_ms(
    frame_times_ms: tuple[float, ...], video_delay_ms: float
) -> float:
    """Where Source 1's video ends in the output: it is muxed from a raw stream,
    so it starts at 0 (+ its own delay) whatever its first timestamp was."""
    if len(frame_times_ms) < 2:
        raise ValueError("need at least two video frames")
    last_interval = frame_times_ms[-1] - frame_times_ms[-2]
    return frame_times_ms[-1] - frame_times_ms[0] + last_interval + video_delay_ms


def _log_disconnected_drift(ctx: Context, log: Callable[[str], None]) -> None:
    """PAL / linear drift is detected but no longer corrected; say so for every
    flagged source so the log shows why its audio may drift."""
    flags = [("PAL", ctx.pal_drift_flags), ("Linear", ctx.linear_drift_flags)]
    for kind, entries in flags:
        for analysis_key, info in entries.items():
            source_key = analysis_key.split("_")[0]
            log(
                f"[Drift] {kind} drift detected in {source_key} "
                f"({info.get('rate', 0.0):+.2f} ms/s); correction is disconnected "
                f"(switch {'on' if ctx.settings.drift_correction_enabled else 'off'}), "
                f"so its audio keeps the analysis delay and will drift. "
                f"See docs/plans/drift-correction.md."
            )


def _format_line(res: FinishResult) -> str:
    """Log line for the FLAC's format, noting non-native layouts and requantizing."""
    fmt = res.fmt
    layout = fmt.channel_layout or f"unnamed {fmt.channels}-channel (FLAC default)"
    line = f"  format: {fmt.sample_rate} Hz, {fmt.out_bits}-bit, {layout}"
    if fmt.requantized:
        line += (
            f" (decoded {fmt.sample_fmt or 'floating-point'} audio stored as "
            f"{fmt.out_bits}-bit)"
        )
    if not res.native_layout:
        line += (
            " — NOT a FLAC-native layout: stored with a channel-mask tag; "
            "players that ignore it would assume the default order"
        )
    return line


class AudioProcessingStep:
    """Corrections, FLAC conversion, delay baking and end trim for all audio."""

    def __init__(self) -> None:
        # Per-job caches, filled on first use.
        self._source1_info: dict | None = None
        self._video_end_ms: float | None = None
        self._video_end_checked = False

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            return ctx
        log = runner._log_message

        _log_disconnected_drift(ctx, log)
        if ctx.settings.stepping_enabled and ctx.segment_flags:
            # Local import: validation imports the steps package (cycle).
            from vsg_core.orchestrator.validation import StepValidator

            log("--- Advanced Audio Correction ---")
            ctx = AudioCorrectionStep().run(ctx, runner)
            StepValidator.validate_correction(ctx)

        audio_items = [
            item
            for item in (ctx.extracted_items or [])
            if item.track.type == "audio" and not item.is_preserved
        ]
        if not audio_items:
            return ctx

        log(
            "[AudioProcessing] FLAC conversions decode strictly "
            f"({' '.join(STRICT_DECODE_ARGS)}): a damaged or lossy frame fails "
            "that track and its original is kept."
        )
        for item in audio_items:
            result = self._process(ctx, item, runner)
            ctx.audio_processing_results.append(result)
        # Originals kept beside stepping-corrected tracks keep their codec;
        # they get the same cut, so mkvmerge never cuts them itself.
        for item in ctx.extracted_items or []:
            if item.track.type == "audio" and item.is_preserved:
                result = self._passthrough(
                    ctx, item, runner, "original kept beside the corrected track"
                )
                ctx.audio_processing_results.append(
                    dataclasses.replace(result, preserved_original=True)
                )

        results = ctx.audio_processing_results
        flac = [r for r in results if r.route == "flac" and r.ok]
        cut = [r for r in results if r.route == "passthrough" and r.ok]
        log(
            f"[AudioProcessing] Done: {len(flac)} track(s) baked into FLAC, "
            f"{len(cut)} cut in their codec, "
            f"{sum(r.route == 'untouched' or (r.route == 'passthrough' and not r.ok) for r in results)} "
            f"untouched, {sum(r.route == 'corrected' for r in results)} corrected."
        )
        return ctx

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------

    def _process(
        self, ctx: Context, item: PlanItem, runner: CommandRunner
    ) -> AudioProcessingResult:
        log = runner._log_message
        label = item_label(item)
        codec_id = item.track.props.codec_id or ""

        edl = ctx.stepping_corrections.get(item.track.source)
        if edl is not None and not item.is_corrected:
            return self._stepping(ctx, item, runner, edl)

        if item.is_corrected:
            detail = "already corrected (FLAC from a corrector)"
            if item.convert_to_flac:
                ctx.flac_conversion_skips.append(f"{label}: {detail}")
            log(f"[AudioProcessing] {label} ({codec_id}) -> corrected: {detail}")
            return AudioProcessingResult(label, "corrected", codec_id, True, detail)

        is_flac = "A_FLAC" in codec_id.upper()
        if not (item.convert_to_flac or is_flac):
            return self._passthrough(ctx, item, runner, "FLAC conversion not requested")

        stream = self._probe_stream(item.extracted_path, runner, ctx.tool_paths)
        reason = eligibility_skip_reason(codec_id, stream)
        if reason is not None:
            if item.convert_to_flac:
                ctx.flac_conversion_skips.append(f"{label}: {reason}")
            return self._passthrough(ctx, item, runner, reason)

        assert stream is not None
        delay_ms = self._baked_delay_ms(ctx, item, runner)
        rate = int(stream["sample_rate"])
        bake = bake_delay(ms_to_ns(delay_ms), rate)
        cap = self._end_cap(ctx, item, runner, rate)
        plan = plan_for_delay(bake, cap)

        if is_flac and not item.convert_to_flac and bake.samples == 0 and cap is None:
            return self._untouched(ctx, item, runner, "already FLAC, nothing to change")

        return self._to_flac(ctx, item, runner, delay_ms, bake, plan)

    def _untouched(
        self, ctx: Context, item: PlanItem, runner: CommandRunner, reason: str
    ) -> AudioProcessingResult:
        label = item_label(item)
        codec_id = item.track.props.codec_id or ""
        runner._log_message(
            f"[AudioProcessing] {label} ({codec_id}) -> untouched: {reason}"
        )
        return AudioProcessingResult(label, "untouched", codec_id, True, reason)

    # ------------------------------------------------------------------
    # passthrough route
    # ------------------------------------------------------------------

    def _passthrough(
        self, ctx: Context, item: PlanItem, runner: CommandRunner, reason: str
    ) -> AudioProcessingResult:
        """Keep the codec; cut whole units at the start and (trim on) the end."""
        log = runner._log_message
        label = item_label(item)
        codec_id = item.track.props.codec_id or ""
        src = item.extracted_path
        if "A_VORBIS" in codec_id.upper():
            if self._mkvmerge_delay_ms(ctx, item) < 0:
                self._warn(
                    ctx,
                    log,
                    f"{label}: Vorbis is cut by mkvmerge; muxed with lacing, "
                    "FFmpeg-based players place a cut Vorbis track up to 9.33 ms "
                    "early (measured)",
                )
            return self._untouched(
                ctx,
                item,
                runner,
                f"{reason}; Vorbis is cut by mkvmerge, its end is not trimmed",
            )
        kind = passthrough_kind(codec_id)
        if kind is None or src is None:
            mkvmerge_ms = self._mkvmerge_delay_ms(ctx, item)
            if mkvmerge_ms < 0:
                self._warn(
                    ctx,
                    log,
                    f"{label}: {codec_id or 'this codec'} is not cut by the app; "
                    f"mkvmerge cuts it with --sync {mkvmerge_ms:+d}",
                )
            return self._untouched(
                ctx,
                item,
                runner,
                f"{reason}; the app does not cut {codec_id or 'this codec'}",
            )

        delay_ms = self._baked_delay_ms(ctx, item, runner)
        mkvmerge_ms = self._mkvmerge_delay_ms(ctx, item)
        video_end_ms = self._passthrough_video_end_ms(ctx, item, runner)
        dialnorm = ctx.settings.apply_dialog_norm_gain and kind == "ac3"
        if dialnorm and self._is_eac3_atmos(codec_id, src, runner, ctx.tool_paths):
            dialnorm = False
            item.keep_dialnorm = True
        dst = ctx.temp_dir / f"{src.stem}_cut{src.suffix}"
        try:
            cut = cut_passthrough(
                kind,
                src,
                ms_to_ns(delay_ms),
                None if video_end_ms is None else ms_to_ns(video_end_ms),
                dst,
                dialnorm,
            )
            if cut.output is not None:
                self._check_mkvmerge_reads(src, cut.output, runner, ctx.tool_paths)
        except (PassthroughError, OSError, ValueError) as e:
            problem = str(e)
            log(
                f"[WARNING] [AudioProcessing] {label} ({codec_id}): not cut by the app "
                f"({problem}). mkvmerge gets --sync {mkvmerge_ms:+d} as before."
            )
            ctx.passthrough_cut_failures.append(f"{label}: {problem}")
            dst.unlink(missing_ok=True)
            return AudioProcessingResult(
                label,
                "passthrough",
                codec_id,
                False,
                "not cut, mkvmerge --sync as before",
                delay_raw_ms=delay_ms,
                mkvmerge_delay_ms=mkvmerge_ms,
                problems=(problem,),
            )

        item.mux_sync_ms = cut.sync_ms
        item.dialnorm_removed = dialnorm
        if kind == "opus":
            self._warn(
                ctx,
                log,
                f"{label}: Opus is muxed with lacing; FFmpeg decodes variable-size "
                "Opus packets in a lace slightly differently from unlaced ones "
                "(measured, with or without a cut)",
            )
        if cut.output is not None:
            item.original_extracted_path = src
            item.extracted_path = cut.output
        self._log_cut(
            log, label, codec_id, reason, delay_ms, mkvmerge_ms, cut, video_end_ms
        )
        if item.keep_dialnorm:
            log(
                "  dialnorm: kept: E-AC-3 Atmos (receivers play it as plain DD+ "
                "after the edit)"
            )
        if ctx.audit:
            ctx.audit.append_event(
                "milestone",
                f"Audio processing (passthrough cut): {label}",
                {
                    "codec": codec_id,
                    "original_file": str(src),
                    "muxed_file": str(item.extracted_path),
                    "delay_raw_ms": delay_ms,
                    "mkvmerge_delay_ms": cut.sync_ms,
                    "units_total": cut.units_total,
                    "units_dropped_start": cut.dropped_start,
                    "units_dropped_end": cut.dropped_end,
                    "end_overrun_ns": cut.end_overrun_ns,
                    "dialnorm_frames": cut.dialnorm_frames,
                },
            )
        return AudioProcessingResult(
            label,
            "passthrough",
            codec_id,
            True,
            "cut in its codec" if cut.output is not None else "nothing to cut",
            delay_raw_ms=delay_ms,
            mkvmerge_delay_ms=cut.sync_ms,
            sample_rate=cut.rate,
            cut=cut,
        )

    def _is_eac3_atmos(
        self,
        codec_id: str,
        src: Path,
        runner: CommandRunner,
        tool_paths: dict[str, str | None],
    ) -> bool:
        """E-AC-3 with Atmos (JOC): FFmpeg reports it from the frame header's
        extension-type-A flag, the one MediaInfo and receivers go by."""
        if "EAC3" not in codec_id.upper():
            return False
        stream = self._probe_stream(src, runner, tool_paths)
        return stream is not None and "atmos" in str(stream.get("profile", "")).lower()

    @staticmethod
    def _warn(ctx: Context, log: Callable[[str], None], message: str) -> None:
        """Log a passthrough caveat and keep it for the final audit."""
        log(f"[WARNING] [AudioProcessing] {message}")
        ctx.passthrough_warnings.append(message)

    @staticmethod
    def _check_mkvmerge_reads(
        src: Path,
        cut: Path,
        runner: CommandRunner,
        tool_paths: dict[str, str | None],
    ) -> None:
        """mkvmerge must identify the cut file exactly as it identifies the
        extraction (one audio track, same codec, channels and rate): a file it
        can't read would fail the whole mux."""

        def identify(path: Path) -> list[tuple[str, str, object, object]]:
            out = runner.run(["mkvmerge", "-J", str(path)], tool_paths)
            try:
                info = json.loads(out) if isinstance(out, str) and out else {}
            except json.JSONDecodeError:
                info = {}
            return [
                (
                    str(t.get("type")),
                    str(t.get("codec")),
                    (t.get("properties") or {}).get("audio_channels"),
                    (t.get("properties") or {}).get("audio_sampling_frequency"),
                )
                for t in info.get("tracks") or []
            ]

        before, after = identify(src), identify(cut)
        if len(after) != 1 or after != before:
            raise PassthroughError(
                f"mkvmerge reads the cut file as {after or 'nothing'}, the extraction as {before}"
            )

    @staticmethod
    def _log_cut(
        log: Callable[[str], None],
        label: str,
        codec_id: str,
        reason: str,
        delay_ms: float,
        mkvmerge_ms: int,
        cut: PassthroughCut,
        video_end_ms: float | None,
    ) -> None:
        units = cut.unit_name
        unit_ms = cut.longest_unit_ns / 1e6
        log(
            f"[AudioProcessing] {label} ({codec_id}) -> passthrough: kept in its "
            f"codec ({reason}); the app cuts whole {units} ({unit_ms:.3f} ms each)"
        )
        log(
            f"  delay:  raw {delay_ms:+.6f} ms (mkvmerge alone would have used {mkvmerge_ms:+d} ms)"
        )
        if cut.dropped_start:
            log(
                f"  start:  dropped {cut.dropped_start} {units}; the first kept one "
                f"lands at {cut.first_kept_ns / 1e6:+.6f} ms -> --sync {cut.sync_ms:+d}"
            )
        else:
            log(f"  start:  nothing dropped -> --sync {cut.sync_ms:+d}")
        if cut.end_overrun_ns is not None:
            log(
                f"  end:    dropped {cut.dropped_end} {units} after the video end "
                f"({video_end_ms:.3f} ms); the audio ends "
                f"{cut.end_overrun_ns / 1e6:.3f} ms after it"
            )
        if cut.dialnorm_frames:
            log(
                f"  dialnorm: set to 31 (no attenuation) in {cut.dialnorm_frames} frames "
                "by the app, the same edit as mkvmerge's"
            )
        kept = cut.units_total - cut.dropped_start - cut.dropped_end
        if cut.output is None:
            log(
                f"  verify: nothing to cut; the extraction is muxed unchanged with --sync {cut.sync_ms:+d}"
            )
        else:
            log(
                f"  verify: {kept} {units} re-read from the cut file, identical to the "
                f"source{' apart from dialnorm and checksums' if cut.dialnorm_frames else ''}; "
                f"mkvmerge gets --sync {cut.sync_ms:+d}"
            )

    def _passthrough_video_end_ms(
        self, ctx: Context, item: PlanItem, runner: CommandRunner
    ) -> float | None:
        """The video end to trim at, or None (trim off, or Source 1)."""
        if not ctx.settings.trim_audio_to_video_duration:
            return None
        if item.track.source == "Source 1":
            return None
        return self._output_video_end_ms(ctx, runner)

    # ------------------------------------------------------------------
    # FLAC route
    # ------------------------------------------------------------------

    def _to_flac(
        self,
        ctx: Context,
        item: PlanItem,
        runner: CommandRunner,
        delay_ms: float,
        bake: DelayBake,
        plan: EditPlan,
    ) -> AudioProcessingResult:
        log = runner._log_message
        label = item_label(item)
        codec_id = item.track.props.codec_id or ""
        src = item.extracted_path
        assert src is not None
        out = ctx.temp_dir / f"{src.stem}_processed.flac"
        mkvmerge_ms = self._mkvmerge_delay_ms(ctx, item)

        log(
            f"[AudioProcessing] {label} ({codec_id}, {src.name}) -> FLAC with the delay baked in"
        )
        try:
            res = finish(
                src,
                0,
                plan,
                out,
                delay_tags(delay_ms, bake, plan, codec_id),
                runner,
                ctx.tool_paths,
            )
        except FinishError as e:
            return self._flac_failed(
                ctx, runner, item, delay_ms, mkvmerge_ms, [str(e)], "not processed"
            )
        fmt = res.fmt
        trimmed_end = int(res.tags.get("VSG_SAMPLES_TRIMMED_END", "0"))

        log(
            f"  delay:  raw {delay_ms:+.6f} ms (mkvmerge would have used {mkvmerge_ms:+d} ms)"
        )
        if bake.samples > 0:
            start = f"added {bake.silence_added} samples of digital silence"
        elif bake.samples < 0:
            start = f"cut {bake.trimmed_start} samples"
        else:
            start = "no change"
        log(
            f"  start:  {start} ({abs(bake.samples) * 1000 / fmt.sample_rate:.6f} ms), "
            f"residual {bake.residual_ns / 1e6:+.6f} ms"
        )
        if plan.max_output_samples is not None:
            log(
                f"  end:    trimmed {trimmed_end} samples "
                f"({trimmed_end * 1000 / fmt.sample_rate:.3f} ms) at the video end"
            )
        log(_format_line(res))

        if not res.ok:
            problems = list(res.check.problems) if res.check else ["FLAC encode failed"]
            return self._flac_failed(
                ctx,
                runner,
                item,
                delay_ms,
                mkvmerge_ms,
                problems,
                "verification failed",
            )

        log(
            f"  verify: {res.expected.output_samples} samples identical to the source plan; "
            f"STREAMINFO total + MD5 OK; mkvmerge gets --sync 0"
        )

        # Swap the item to the FLAC; keep the original path for auditing.
        item.original_extracted_path = src
        item.extracted_path = out
        item.flac_converted = True
        item.delay_baked = True
        original_props = item.track.props
        item.track = Track(
            source=item.track.source,
            id=item.track.id,
            type=item.track.type,
            props=StreamProps(
                codec_id="A_FLAC", lang=original_props.lang, name=original_props.name
            ),
        )
        ctx.flac_conversions.append(label)
        if ctx.audit:
            ctx.audit.append_event(
                "milestone",
                f"Audio processing (FLAC, delay baked): {label}",
                {
                    "original_codec": codec_id,
                    "original_file": str(src),
                    "flac_file": str(out),
                    "delay_raw_ms": delay_ms,
                    "mkvmerge_delay_ms": mkvmerge_ms,
                    "tags": res.tags,
                    "sample_rate": fmt.sample_rate,
                    "bits": fmt.out_bits,
                    "channel_layout": fmt.channel_layout,
                },
            )
        return AudioProcessingResult(
            label,
            "flac",
            codec_id,
            True,
            "converted, delay baked",
            delay_raw_ms=delay_ms,
            mkvmerge_delay_ms=mkvmerge_ms,
            samples_trimmed_start=bake.trimmed_start,
            silence_samples_added=bake.silence_added,
            samples_trimmed_end=trimmed_end,
            residual_ns=bake.residual_ns,
            output_samples=res.expected.output_samples,
            sample_rate=fmt.sample_rate,
            channel_layout=fmt.channel_layout or "",
            native_layout=res.native_layout,
        )

    def _flac_failed(
        self,
        ctx: Context,
        runner: CommandRunner,
        item: PlanItem,
        delay_ms: float,
        mkvmerge_ms: int,
        problems: list[str],
        what: str,
        route: AudioRouteStr = "flac",
    ) -> AudioProcessingResult:
        """Keep the original track in its codec, cut by the passthrough route
        (so mkvmerge never cuts it), and report why."""
        label = item_label(item)
        runner._log_message(
            f"[ERROR] [AudioProcessing] {label}: {'; '.join(problems)}. Keeping the original track."
        )
        ctx.flac_conversion_failures.append(f"{label}: {'; '.join(problems)}")
        kept = self._passthrough(ctx, item, runner, f"{what}, original kept")
        return AudioProcessingResult(
            label,
            route,
            item.track.props.codec_id or "",
            False,
            f"{what}, original kept" + (" and cut in its codec" if kept.cut else ""),
            delay_raw_ms=delay_ms,
            mkvmerge_delay_ms=item.mux_sync_ms if kept.cut else mkvmerge_ms,
            problems=tuple(problems),
            cut=kept.cut,
        )

    # ------------------------------------------------------------------
    # stepping route
    # ------------------------------------------------------------------

    def _stepping(
        self,
        ctx: Context,
        item: PlanItem,
        runner: CommandRunner,
        edl: list[AudioSegment],
    ) -> AudioProcessingResult:
        """Apply a verified stepping EDL to this track in one finisher encode."""
        log = runner._log_message
        label = item_label(item)
        codec_id = item.track.props.codec_id or ""
        src = item.extracted_path
        assert src is not None
        # The EDL is on Source 1's audio-content timeline; that audio sits at
        # its container offset from the video, and the video is moved by the
        # whole-ms global shift.
        offset_ms = ctx.source1_audio_container_delay_ms + (
            ctx.delays.global_shift_ms if ctx.delays else 0
        )
        mkvmerge_ms = round(ctx.source1_audio_container_delay_ms)

        def failed(problems: list[str], what: str) -> AudioProcessingResult:
            ctx.stepping_quality_issues.append(
                {
                    "source": item.track.source,
                    "issue_type": "correction_not_applied",
                    "severity": "high",
                    "message": (
                        f"Stepping correction failed for {label} "
                        f"({'; '.join(problems)}); the original track is muxed "
                        f"with the first segment's delay"
                    ),
                    "details": {},
                }
            )
            return self._flac_failed(
                ctx,
                runner,
                item,
                offset_ms + edl[0].delay_raw,
                mkvmerge_ms,
                problems,
                what,
                route="corrected",
            )

        log(
            f"[AudioProcessing] {label} ({codec_id}, {src.name}) -> corrected: "
            f"stepping EDL ({len(edl)} segments), one verified encode"
        )
        stream = self._probe_stream(src, runner, ctx.tool_paths)
        if stream is None:
            return failed(
                ["ffprobe could not read the extracted track"], "not processed"
            )
        channels = int(stream.get("channels") or 0)
        if channels > _FLAC_MAX_CHANNELS:
            return failed(
                [f"{channels} channels exceed FLAC's limit of {_FLAC_MAX_CHANNELS}"],
                "not processed",
            )
        profile = str(stream.get("profile") or "")
        if "atmos" in profile.lower() or "DTS:X" in profile.upper():
            log(
                f"  note:   object audio ({profile}): only its {channels}-channel bed "
                f"is kept (stepping edits decoded audio)"
            )
        rate = int(stream["sample_rate"])

        try:
            edits = edl_to_edits(edl, rate, offset_ms, log)
            plan = EditPlan(edits.ops, self._end_cap(ctx, item, runner, rate))
        except ValueError as e:
            return failed([str(e)], "not processed")
        out = ctx.temp_dir / f"corrected_{src.stem}.flac"
        try:
            res = finish(
                src,
                0,
                plan,
                out,
                edit_tags(edits.start_delay_ms, plan, codec_id),
                runner,
                ctx.tool_paths,
            )
        except FinishError as e:
            return failed([str(e)], "not processed")

        trimmed_end = int(res.tags.get("VSG_SAMPLES_TRIMMED_END", "0"))
        log(
            f"  delay:  start {edits.start_delay_ms:+.6f} ms "
            f"(mkvmerge used to get {mkvmerge_ms:+d} ms for this track)"
        )
        log(f"  edits:  {format_edit_plan(plan)}")
        if edits.ignored_steps:
            log(
                "  note:   ignored step(s) <= 10 ms: "
                + ", ".join(
                    f"+{s.step_ms:.3f} ms @ {s.at_s:.3f}s" for s in edits.ignored_steps
                )
            )
        if plan.max_output_samples is not None:
            log(
                f"  end:    trimmed {trimmed_end} samples "
                f"({trimmed_end * 1000 / rate:.3f} ms) at the video end"
            )
        log(_format_line(res))
        if not res.ok:
            problems = list(res.check.problems) if res.check else ["FLAC encode failed"]
            return failed(problems, "verification failed")
        log(
            f"  verify: {res.expected.output_samples} samples identical to the edited "
            f"source; STREAMINFO total + MD5 OK; mkvmerge gets --sync 0"
        )

        swap_in_corrected_track(ctx, item, out, ctx.settings, log)
        if ctx.audit:
            ctx.audit.append_event(
                "milestone",
                f"Audio processing (stepping, delay baked): {label}",
                {
                    "original_codec": codec_id,
                    "original_file": str(src),
                    "flac_file": str(out),
                    "start_delay_ms": edits.start_delay_ms,
                    "tags": res.tags,
                    "sample_rate": rate,
                    "bits": res.fmt.out_bits,
                    "channel_layout": res.fmt.channel_layout,
                },
            )
        return AudioProcessingResult(
            label,
            "corrected",
            codec_id,
            True,
            "stepping corrected, delay baked",
            delay_raw_ms=edits.start_delay_ms,
            mkvmerge_delay_ms=mkvmerge_ms,
            samples_trimmed_start=max(-edits.start_samples, 0),
            silence_samples_added=plan.silence_samples,
            samples_trimmed_end=trimmed_end,
            output_samples=res.expected.output_samples,
            sample_rate=rate,
            channel_layout=res.fmt.channel_layout or "",
            native_layout=res.native_layout,
        )

    def _end_cap(
        self, ctx: Context, item: PlanItem, runner: CommandRunner, rate: int
    ) -> int | None:
        """Output samples before the video end, when the end trim applies."""
        if not ctx.settings.trim_audio_to_video_duration:
            return None
        if item.track.source == "Source 1":
            return None
        video_end_ms = self._output_video_end_ms(ctx, runner)
        if video_end_ms is None:
            return None
        return end_cap_samples(ms_to_ns(video_end_ms), rate)

    # ------------------------------------------------------------------
    # delays and the video end
    # ------------------------------------------------------------------

    def _baked_delay_ms(
        self, ctx: Context, item: PlanItem, runner: CommandRunner
    ) -> float:
        """The track's delay as mkvmerge would apply it, but unrounded."""
        delays = ctx.delays
        global_shift = delays.global_shift_ms if delays else 0
        if item.track.source == "Source 1":
            if self._source1_info is None:
                src1 = ctx.sources.get("Source 1")
                self._source1_info = (
                    get_stream_info_with_delays(str(src1), runner, ctx.tool_paths)
                    if src1
                    else None
                ) or {}
            # Source 1 video only gets the (whole-ms) global shift, so its audio
            # follows the video's real position: exact offset + that shift.
            return (
                source1_audio_offset_ms(self._source1_info, item.track.id)
                + global_shift
            )
        sync_key = (
            item.sync_to if item.track.source == "External" else item.track.source
        )
        if not delays or sync_key is None:
            return 0.0
        if sync_key in delays.raw_source_delays_ms:
            # The raw delay carries the raw (fractional) global shift, but the
            # video is moved by the whole-ms shift: swap one for the other.
            return (
                delays.raw_source_delays_ms[sync_key]
                - delays.raw_global_shift_ms
                + global_shift
            )
        return float(delays.source_delays_ms.get(sync_key, 0))

    def _mkvmerge_delay_ms(self, ctx: Context, item: PlanItem) -> int:
        """What --sync would have been (whole ms), for the log."""
        delays = ctx.delays
        global_shift = delays.global_shift_ms if delays else 0
        if item.track.source == "Source 1":
            return round(item.container_delay_ms) + global_shift
        sync_key = (
            item.sync_to if item.track.source == "External" else item.track.source
        )
        return int(delays.source_delays_ms.get(sync_key or "", 0)) if delays else 0

    def _output_video_end_ms(self, ctx: Context, runner: CommandRunner) -> float | None:
        if self._video_end_checked:
            return self._video_end_ms
        self._video_end_checked = True
        from vsg_core.subtitles.frame_grids import frame_table_for

        log = runner._log_message
        src1 = ctx.sources.get("Source 1")
        table = frame_table_for(ctx, str(src1), log) if src1 else None
        if table is None:
            log(
                "[WARNING] [AudioProcessing] Could not read Source 1's real frame "
                "timestamps — no audio track is trimmed to the video end (FLAC or "
                "cut in its codec)."
            )
            return None
        video_delay = ctx.delays.global_shift_ms if ctx.delays else 0
        self._video_end_ms = output_video_end_ms(table.times_ms, video_delay)
        log(
            f"[AudioProcessing] Video end for trimming: {self._video_end_ms:.3f} ms "
            f"({table.num_frames} frames, from {table.origin}; container timestamps are whole ms)"
        )
        return self._video_end_ms

    # ------------------------------------------------------------------

    def _probe_stream(
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
        out = runner.run(
            [
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
            ],
            tool_paths,
        )
        if not out or not isinstance(out, str):
            return None
        try:
            streams = json.loads(out).get("streams") or []
        except json.JSONDecodeError:
            return None
        return streams[0] if streams else None
