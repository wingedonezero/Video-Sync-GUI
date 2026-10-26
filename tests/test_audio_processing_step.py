# tests/test_audio_processing_step.py
"""AudioProcessingStep: FLAC-route eligibility, delay helpers, and an end-to-end
run of the step + mux options on synthetic tracks (needs ffmpeg).

Real-media checks live in the Tests harness (finisher_real_samples.py).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import numpy as np
import pytest

from vsg_core.audio_processing import FinishError
from vsg_core.audio_processing.passthrough import PassthroughError
from vsg_core.audio_processing.verify import read_streaminfo
from vsg_core.correction.stepping import AudioSegment
from vsg_core.correction.stepping.edit_plan import edl_to_edits, render_edits
from vsg_core.io.runner import CommandRunner
from vsg_core.models.jobs import Delays, MergePlan, PlanItem
from vsg_core.models.media import StreamProps, Track
from vsg_core.models.settings import AppSettings
from vsg_core.mux.options_builder import MkvmergeOptionsBuilder
from vsg_core.orchestrator.steps import audio_processing_step as aps
from vsg_core.orchestrator.steps.audio_processing_step import (
    AudioProcessingStep,
    eligibility_skip_reason,
    output_video_end_ms,
    source1_audio_offset_ms,
)
from vsg_core.orchestrator.steps.context import Context
from vsg_core.orchestrator.validation import StepValidator
from vsg_core.postprocess.auditors import (
    AudioPassthroughAuditor,
    DriftCorrectionAuditor,
)

if TYPE_CHECKING:
    from pathlib import Path


def _stream(
    codec_name: str = "pcm_s24le",
    profile: str | None = None,
    channels: int = 6,
    bits: int | None = 24,
) -> dict:
    stream: dict = {"codec_name": codec_name, "channels": channels}
    if bits is not None:
        stream["bits_per_raw_sample"] = bits
    if profile is not None:
        stream["profile"] = profile
    return stream


class TestEligibility:
    def test_pcm_is_eligible(self) -> None:
        assert eligibility_skip_reason("A_PCM/INT/LIT", _stream()) is None

    def test_ms_acm_extracted_wav_is_eligible(self) -> None:
        assert (
            eligibility_skip_reason("A_MS/ACM", _stream("pcm_s16le", bits=16)) is None
        )

    def test_plain_truehd_is_eligible(self) -> None:
        assert eligibility_skip_reason("A_TRUEHD", _stream("truehd")) is None

    def test_mlp_is_eligible(self) -> None:
        assert eligibility_skip_reason("A_MLP", _stream("mlp")) is None

    def test_existing_flac_is_eligible(self) -> None:
        assert eligibility_skip_reason("A_FLAC", _stream("flac", bits=16)) is None

    def test_truehd_atmos_is_skipped(self) -> None:
        reason = eligibility_skip_reason(
            "A_TRUEHD", _stream("truehd", profile="Dolby TrueHD + Dolby Atmos")
        )
        assert reason is not None and "object-based" in reason

    def test_dts_hd_ma_is_eligible(self) -> None:
        assert (
            eligibility_skip_reason("A_DTS", _stream("dts", profile="DTS-HD MA"))
            is None
        )

    def test_dts_x_is_skipped(self) -> None:
        reason = eligibility_skip_reason(
            "A_DTS", _stream("dts", profile="DTS-HD MA + DTS:X")
        )
        assert reason is not None and "object-based" in reason

    def test_lossy_dts_profiles_are_skipped(self) -> None:
        for profile in ("DTS", "DTS-ES", "DTS 96/24", "DTS-HD HRA", "DTS Express"):
            reason = eligibility_skip_reason("A_DTS", _stream("dts", profile=profile))
            assert reason is not None and "not lossless" in reason, profile

    def test_dts_without_profile_is_skipped(self) -> None:
        assert eligibility_skip_reason("A_DTS", _stream("dts")) is not None

    def test_lossy_codecs_are_skipped(self) -> None:
        for codec_id in ("A_AC3", "A_EAC3", "A_AAC", "A_OPUS", "A_VORBIS"):
            reason = eligibility_skip_reason(codec_id, _stream())
            assert reason is not None and "not lossless" in reason, codec_id

    def test_missing_probe_is_skipped(self) -> None:
        assert eligibility_skip_reason("A_PCM/INT/LIT", None) is not None

    def test_more_than_eight_channels_is_skipped(self) -> None:
        reason = eligibility_skip_reason("A_PCM/INT/LIT", _stream(channels=10))
        assert reason is not None and "channels" in reason

    def test_non_pcm_data_under_pcm_codec_id_is_skipped(self) -> None:
        assert eligibility_skip_reason("A_PCM/INT/LIT", _stream("ac3")) is not None

    def test_float_pcm_is_skipped(self) -> None:
        reason = eligibility_skip_reason(
            "A_PCM/FLOAT/IEEE", _stream("pcm_f32le", bits=32)
        )
        assert reason is not None and "floating-point" in reason

    def test_32_bit_integer_pcm_is_skipped(self) -> None:
        reason = eligibility_skip_reason("A_PCM/INT/LIT", _stream("pcm_s32le", bits=32))
        assert reason is not None and "32-bit" in reason

    def test_unknown_bit_depth_is_skipped(self) -> None:
        assert (
            eligibility_skip_reason("A_TRUEHD", _stream("truehd", bits=None))
            is not None
        )


class TestDelayHelpers:
    def test_source1_audio_offset_is_exact_and_video_relative(self) -> None:
        info = {
            "tracks": [
                {
                    "id": 0,
                    "type": "video",
                    "properties": {"minimum_timestamp": 41_708_000},
                },
                {
                    "id": 1,
                    "type": "audio",
                    "properties": {"minimum_timestamp": 50_042_333},
                },
                {"id": 2, "type": "audio", "properties": {}},
            ]
        }
        assert source1_audio_offset_ms(info, 1) == pytest.approx(8.334333)
        assert source1_audio_offset_ms(info, 2) == pytest.approx(-41.708)
        assert source1_audio_offset_ms(info, 9) == 0.0

    def test_output_video_end_starts_from_the_first_frame(self) -> None:
        # first frame at 1001 ms in the source; 3 frames of 41.708 ms
        times = (1001.0, 1042.708, 1084.416)
        assert output_video_end_ms(times, 0) == pytest.approx(125.124)
        assert output_video_end_ms(times, 50) == pytest.approx(175.124)
        with pytest.raises(ValueError):
            output_video_end_ms((5.0,), 0)


# --- end to end ------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    not (
        shutil.which("ffmpeg") and shutil.which("ffprobe") and shutil.which("mkvmerge")
    ),
    reason="ffmpeg/mkvmerge not installed",
)


def _synth(path: Path, codec: str, channels: int = 2, seconds: float = 2.0) -> None:
    layout = {2: "stereo", 6: "5.1(side)"}[channels]
    exprs = "|".join(f"0.3*sin({300 + 100 * c}*2*PI*t)" for c in range(channels))
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"aevalsrc={exprs}:s=48000:c={layout}:d={seconds}",
            "-c:a",
            codec,
            str(path),
        ],
        check=True,
    )


def _decode(path: Path) -> np.ndarray:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s32le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(out, dtype="<i4")


def _item(source: str, tid: int, codec_id: str, path: Path, convert: bool) -> PlanItem:
    item = PlanItem(
        track=Track(source, tid, "audio", StreamProps(codec_id)), extracted_path=path
    )
    item.convert_to_flac = convert
    return item


def _ctx(tmp_path: Path, items: list[PlanItem], raw_delay_ms: float) -> Context:
    ctx = Context(
        settings=AppSettings(),
        tool_paths={},
        log=lambda _m: None,
        progress=lambda _p: None,
        output_dir=str(tmp_path),
        temp_dir=tmp_path,
        and_merge=True,
    )
    ctx.delays = Delays(
        source_delays_ms={"Source 2": round(raw_delay_ms)},
        raw_source_delays_ms={"Source 2": raw_delay_ms},
    )
    ctx.extracted_items = items
    return ctx


@needs_ffmpeg
class TestStepEndToEnd:
    def test_routes_bake_and_mux_options(self, tmp_path: Path) -> None:
        pcm = tmp_path / "pcm.wav"
        ac3 = tmp_path / "ac3.ac3"
        flac_src = tmp_path / "src.flac"
        _synth(pcm, "pcm_s24le", 6)
        _synth(ac3, "ac3", 2)
        _synth(flac_src, "flac", 2)
        items = [
            _item("Source 2", 1, "A_PCM/INT/LIT", pcm, convert=True),
            _item(
                "Source 2", 2, "A_AC3", ac3, convert=True
            ),  # lossy: skipped, cut in its codec
            _item(
                "Source 2", 3, "A_FLAC", flac_src, convert=False
            ),  # auto: delay -> re-encode
        ]
        ctx = _ctx(tmp_path, items, raw_delay_ms=-10.834789)
        runner = CommandRunner(AppSettings(), lambda _m: None)
        ctx = AudioProcessingStep().run(ctx, runner)

        routes = [(r.route, r.ok) for r in ctx.audio_processing_results]
        assert routes == [("flac", True), ("passthrough", True), ("flac", True)]
        pcm_item, ac3_item, _flac_item = items
        assert pcm_item.delay_baked and pcm_item.track.props.codec_id == "A_FLAC"
        # AC-3 keeps its codec: the first 32 ms frame is dropped, the second
        # lands at 32 - 10.834789 = 21.165 ms -> --sync +21.
        assert not ac3_item.delay_baked and ac3_item.mux_sync_ms == 21
        assert (
            ac3_item.extracted_path != ac3 and ac3_item.original_extracted_path == ac3
        )
        ac3_cut = ctx.audio_processing_results[1].cut
        assert ac3_cut is not None and ac3_cut.dropped_start == 1
        assert ctx.flac_conversion_skips == [
            "Source 2 audio track 2: codec A_AC3 is not lossless"
        ]

        res = ctx.audio_processing_results[0]
        assert (res.samples_trimmed_start, res.silence_samples_added) == (520, 0)
        assert res.mkvmerge_delay_ms == -11
        source = _decode(pcm).reshape(-1, 6)
        assert pcm_item.extracted_path is not None
        assert np.array_equal(
            _decode(pcm_item.extracted_path).reshape(-1, 6), source[520:]
        )

        tokens = MkvmergeOptionsBuilder().build(
            MergePlan(items=items, delays=ctx.delays or Delays()), AppSettings()
        )
        syncs = [tokens[i + 1] for i, t in enumerate(tokens) if t == "--sync"]
        assert syncs == ["0:+0", "0:+21", "0:+0"]
        assert "--stop-after-video-ends" not in tokens

    def test_flac_with_nothing_to_change_is_left_alone(self, tmp_path: Path) -> None:
        flac_src = tmp_path / "src.flac"
        _synth(flac_src, "flac", 2)
        item = _item("Source 2", 1, "A_FLAC", flac_src, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=0.0)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        assert ctx.audio_processing_results[0].route == "untouched"
        assert item.extracted_path == flac_src and not item.delay_baked

    def test_positive_delay_adds_silence(self, tmp_path: Path) -> None:
        pcm = tmp_path / "pcm.wav"
        _synth(pcm, "pcm_s16le", 2)
        item = _item("Source 2", 1, "A_PCM/INT/LIT", pcm, convert=True)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=10.834789)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        res = ctx.audio_processing_results[0]
        assert res.ok and res.silence_samples_added == 520
        assert item.extracted_path is not None
        out = _decode(item.extracted_path).reshape(-1, 2)
        assert not out[:520].any()
        assert np.array_equal(out[520:], _decode(pcm).reshape(-1, 2))

    def test_damaged_source_keeps_the_original(self, tmp_path: Path) -> None:
        flac_src = tmp_path / "src.flac"
        _synth(flac_src, "flac", 2)
        data = bytearray(flac_src.read_bytes())
        data[len(data) * 3 // 5] ^= 0x10  # inside a frame, past the headers
        flac_src.write_bytes(data)
        item = _item("Source 2", 1, "A_FLAC", flac_src, convert=True)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-10.834789)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        res = ctx.audio_processing_results[0]
        assert (res.route, res.ok) == ("flac", False)
        assert "source does not decode cleanly" in res.problems[0]
        assert item.extracted_path == flac_src and not item.delay_baked
        assert ctx.flac_conversion_failures[0].startswith("Source 2 audio track 1: ")
        tokens = MkvmergeOptionsBuilder().build(
            MergePlan(items=[item], delays=ctx.delays or Delays()), AppSettings()
        )
        assert tokens[tokens.index("--sync") + 1] == "0:-11"

    def test_global_shift_uses_the_whole_ms_shift_the_video_got(
        self, tmp_path: Path
    ) -> None:
        # Raw -993.109 ms shifted by the raw +993.109 reads 0.0, but the video
        # moves by the whole-ms +993: the track belongs at -0.109 ms (5 samples).
        pcm = tmp_path / "pcm.wav"
        _synth(pcm, "pcm_s16le", 2)
        item = _item("Source 2", 1, "A_PCM/INT/LIT", pcm, convert=True)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=0.0)
        ctx.delays = Delays(
            source_delays_ms={"Source 2": 0},
            raw_source_delays_ms={"Source 2": 0.0},
            global_shift_ms=993,
            raw_global_shift_ms=993.109,
        )
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        res = ctx.audio_processing_results[0]
        assert res.ok and res.delay_raw_ms == pytest.approx(-0.109)
        assert (res.samples_trimmed_start, res.silence_samples_added) == (5, 0)


def _stepping_edl() -> list[AudioSegment]:
    # start -10.834789 ms, +500 ms step at 2 s (silence), -250 ms at 4 s (cut)
    return [
        AudioSegment(0.0, 0.0, -11, -10.834789),
        AudioSegment(2.0, 2.0, 489, 489.165211),
        AudioSegment(4.0, 4.0, 239, 239.165211),
    ]


@needs_ffmpeg
class TestSteppingRoute:
    def _run(
        self, tmp_path: Path, path: Path, codec_id: str
    ) -> tuple[Context, PlanItem]:
        item = _item("Source 2", 1, codec_id, path, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-10.834789)
        ctx.source1_audio_container_delay_ms = 1.5
        ctx.stepping_corrections["Source 2"] = _stepping_edl()
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        StepValidator.validate_audio_processing(ctx)
        return ctx, item

    def test_whole_edl_is_baked_exactly_at_source_depth(self, tmp_path: Path) -> None:
        pcm = tmp_path / "pcm.wav"
        _synth(pcm, "pcm_s16le", 2, seconds=6.0)
        ctx, item = self._run(tmp_path, pcm, "A_PCM/INT/LIT")

        res = ctx.audio_processing_results[0]
        assert (res.route, res.ok) == ("corrected", True)
        assert item.delay_baked and item.is_corrected
        assert item.extracted_path is not None and item.extracted_path != pcm
        edits = edl_to_edits(_stepping_edl(), 48000, 1.5, lambda _m: None)
        expected = render_edits(_decode(pcm), 2, edits.ops).reshape(-1, 2)
        assert np.array_equal(_decode(item.extracted_path).reshape(-1, 2), expected)
        assert read_streaminfo(item.extracted_path).bits == 16  # was 24 before

        # The original is kept as a preserved track, cut in its own codec
        # (never by mkvmerge); mux bakes nothing twice.
        preserved = [i for i in ctx.extracted_items or [] if i.is_preserved]
        assert [p.original_extracted_path for p in preserved] == [pcm]
        assert preserved[0].mux_sync_ms is not None and preserved[0].mux_sync_ms >= 0
        assert ctx.audio_processing_results[-1].preserved_original
        tokens = MkvmergeOptionsBuilder().build(
            MergePlan(items=[item], delays=ctx.delays or Delays()), AppSettings()
        )
        assert tokens[tokens.index("--sync") + 1] == "0:+0"
        tags = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags",
                "-of",
                "default=nw=1",
                str(item.extracted_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "TAG:VSG_EDIT_PLAN=T448-96000 S24000 T96000-192000 T204000-" in tags

    def test_lossy_track_becomes_24_bit(self, tmp_path: Path) -> None:
        ac3 = tmp_path / "a.ac3"
        _synth(ac3, "ac3", 2, seconds=6.0)
        ctx, item = self._run(tmp_path, ac3, "A_AC3")
        assert ctx.audio_processing_results[0].ok
        assert item.extracted_path is not None
        assert read_streaminfo(item.extracted_path).bits == 24

    def test_failure_keeps_the_original_and_reports(self, tmp_path: Path) -> None:
        flac_src = tmp_path / "src.flac"
        _synth(flac_src, "flac", 2, seconds=6.0)
        data = bytearray(flac_src.read_bytes())
        data[len(data) * 3 // 5] ^= 0x10
        flac_src.write_bytes(data)
        ctx, item = self._run(tmp_path, flac_src, "A_FLAC")

        res = ctx.audio_processing_results[0]
        assert (res.route, res.ok) == ("corrected", False)
        assert item.extracted_path == flac_src and not item.delay_baked
        assert ctx.flac_conversion_failures[0].startswith("Source 2 audio track 1: ")
        assert ctx.stepping_quality_issues[0]["issue_type"] == "correction_not_applied"


@needs_ffmpeg
class TestDisconnectedDrift:
    def test_pal_flag_is_logged_not_corrected(self, tmp_path: Path) -> None:
        pcm = tmp_path / "pcm.wav"
        _synth(pcm, "pcm_s16le", 2)
        item = _item("Source 2", 1, "A_PCM/INT/LIT", pcm, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-10.0)
        ctx.settings.stepping_enabled = True  # used to gate PAL / linear too
        ctx.pal_drift_flags["Source 2_1"] = {"rate": 40.96}
        lines: list[str] = []
        ctx = AudioProcessingStep().run(ctx, CommandRunner(AppSettings(), lines.append))
        StepValidator.validate_audio_processing(ctx)
        StepValidator.validate_correction(ctx)

        res = ctx.audio_processing_results[0]
        assert res.route == "passthrough" and res.cut is not None
        assert res.cut.dropped_start == 480 and item.mux_sync_ms == 0
        assert not item.is_corrected and item.original_extracted_path == pcm
        assert any("[Drift] PAL drift detected in Source 2" in ln for ln in lines)

    def test_audit_reports_drift_but_not_an_unverified_stepping_flag(
        self, tmp_path: Path
    ) -> None:
        ctx = _ctx(tmp_path, [], raw_delay_ms=0.0)
        ctx.linear_drift_flags["Source 2_1"] = {"rate": 1.0}
        ctx.segment_flags["Source 3_1"] = {
            "base_delay": 0,
            "subs_only": False,
        }  # no EDL
        lines: list[str] = []
        auditor = DriftCorrectionAuditor(
            ctx, CommandRunner(AppSettings(), lines.append)
        )
        assert auditor.run(tmp_path / "out.mkv", {}) == 1
        assert "Linear drift detected in Source 2" in auditor.issues[0].message
        assert any("no verified EDL" in ln for ln in lines)


@needs_ffmpeg
class TestPassthroughRoute:
    def test_refused_cut_falls_back_to_mkvmerge(self, tmp_path: Path) -> None:
        ac3 = tmp_path / "ac3.ac3"
        _synth(ac3, "ac3", 2)
        damaged = tmp_path / "damaged.ac3"
        damaged.write_bytes(
            b"\0\0\0" + ac3.read_bytes()
        )  # garbage before the first frame
        item = _item("Source 2", 1, "A_AC3", damaged, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-10.834789)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        StepValidator.validate_audio_processing(ctx)
        res = ctx.audio_processing_results[0]
        assert (res.route, res.ok) == ("passthrough", False)
        assert item.mux_sync_ms is None and item.extracted_path == damaged
        assert ctx.passthrough_cut_failures[0].startswith("Source 2 audio track 1:")
        tokens = MkvmergeOptionsBuilder().build(
            MergePlan(items=[item], delays=ctx.delays or Delays()), AppSettings()
        )
        assert tokens[tokens.index("--sync") + 1] == "0:-11"

    def test_cut_mkvmerge_cannot_read_falls_back(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ac3 = tmp_path / "ac3.ac3"
        _synth(ac3, "ac3", 2)
        item = _item("Source 2", 1, "A_AC3", ac3, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-100.0)

        def unreadable(*_args: object) -> None:
            raise PassthroughError("mkvmerge reads the cut file as nothing")

        monkeypatch.setattr(AudioProcessingStep, "_check_mkvmerge_reads", unreadable)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        res = ctx.audio_processing_results[0]
        assert not res.ok and item.extracted_path == ac3 and item.mux_sync_ms is None
        assert not (tmp_path / "ac3_cut.ac3").exists()

    def test_failed_flac_conversion_is_still_cut_in_its_codec(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pcm = tmp_path / "pcm.wav"
        _synth(pcm, "pcm_s16le", 2)
        item = _item("Source 2", 1, "A_PCM/INT/LIT", pcm, convert=True)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-10.0)

        def broken(*_args: object) -> None:
            raise FinishError("encoder failed")

        monkeypatch.setattr(aps, "finish", broken)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        StepValidator.validate_audio_processing(ctx)
        res = ctx.audio_processing_results[0]
        assert (res.route, res.ok) == ("flac", False)
        assert res.cut is not None and res.cut.dropped_start == 480
        assert item.mux_sync_ms == 0 and item.original_extracted_path == pcm
        assert ctx.flac_conversion_failures[0].startswith("Source 2 audio track 1:")

    def test_audit_compares_the_muxed_track_with_the_cut(self, tmp_path: Path) -> None:
        ac3 = tmp_path / "ac3.ac3"
        _synth(ac3, "ac3", 2)
        item = _item("Source 2", 1, "A_AC3", ac3, convert=False)
        ctx = _ctx(tmp_path, [item], raw_delay_ms=-100.0)
        runner = CommandRunner(AppSettings(), lambda _m: None)
        ctx = AudioProcessingStep().run(ctx, runner)
        assert item.extracted_path is not None and item.mux_sync_ms == 28

        def mux(audio: Path, sync: int) -> tuple[Path, dict]:
            out = tmp_path / f"out_{sync}_{audio.name}.mkv"
            subprocess.run(
                ["mkvmerge", "-q", "-o", str(out), "--sync", f"0:{sync}", str(audio)],
                check=True,
            )
            info = subprocess.run(
                ["mkvmerge", "-J", str(out)], capture_output=True, text=True, check=True
            ).stdout
            return out, json.loads(info)

        good, info = mux(item.extracted_path, 28)
        # Off (the default): only the first frame time, from mkvmerge -J.
        assert AudioPassthroughAuditor(ctx, runner).run(good, info) == 0
        late, late_info = mux(item.extracted_path, 29)
        assert AudioPassthroughAuditor(ctx, runner).run(late, late_info) == 1

        ctx.settings.verify_passthrough_frames = True
        auditor = AudioPassthroughAuditor(ctx, runner)
        assert auditor.run(good, info) == 0, [i.message for i in auditor.issues]
        late, info = mux(item.extracted_path, 29)  # one ms off
        assert AudioPassthroughAuditor(ctx, runner).run(late, info) == 1
        uncut, info = mux(ac3, 28)  # not the bytes the app wrote
        assert AudioPassthroughAuditor(ctx, runner).run(uncut, info) >= 1

    def test_preserved_original_is_cut_too(self, tmp_path: Path) -> None:
        ac3 = tmp_path / "ac3.ac3"
        _synth(ac3, "ac3", 2)
        main = _item("Source 2", 1, "A_AC3", ac3, convert=False)
        original = _item("Source 2", 1, "A_AC3", ac3, convert=False)
        original.is_preserved = True
        ctx = _ctx(tmp_path, [main, original], raw_delay_ms=-100.0)
        ctx = AudioProcessingStep().run(
            ctx, CommandRunner(AppSettings(), lambda _m: None)
        )
        StepValidator.validate_audio_processing(ctx)
        labels = [(r.label, r.preserved_original) for r in ctx.audio_processing_results]
        assert labels == [
            ("Source 2 audio track 1", False),
            ("Source 2 audio track 1 (preserved original)", True),
        ]
        assert original.mux_sync_ms == 28 and main.mux_sync_ms == 28  # 128 - 100 ms


def test_audit_reports_passthrough_failures_and_caveats(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, [], raw_delay_ms=0.0)
    ctx.passthrough_cut_failures.append("Source 2 audio track 1: truncated last frame")
    ctx.passthrough_warnings.append("Source 3 audio track 1: Opus is muxed with lacing")
    auditor = AudioPassthroughAuditor(
        ctx, CommandRunner(AppSettings(), lambda _m: None)
    )
    assert auditor.run(tmp_path / "out.mkv", {}) == 2
    assert [i.severity for i in auditor.issues] == ["warning", "warning"]
    assert "Opus is muxed with lacing" in auditor.issues[1].message
