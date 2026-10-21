# tests/test_audio_processing.py
"""Audio finisher: exact sample maths, edit plans, ffmpeg graph/args, FLAC
header + MD5 helpers, and an end-to-end run on synthetic audio (needs ffmpeg).

Real-media checks (TrueHD, DTS-HD MA, BD PCM, channel layouts) live in the
Tests harness, per the repo convention.
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from vsg_core.audio_processing import (
    EditPlan,
    FinishError,
    Silence,
    SourceFormat,
    Take,
    bake_delay,
    delay_tags,
    end_cap_samples,
    expected_output_samples,
    finish,
    ms_to_ns,
    ns_to_samples,
    plan_for_delay,
    trimmed_end_samples,
)
from vsg_core.audio_processing.encoder import (
    STRICT_DECODE_ARGS,
    build_encode_command,
    build_filter_graph,
    default_layout,
    is_native_layout,
)
from vsg_core.audio_processing.verify import (
    _decode_cmd,
    _FrameReader,
    canonical_bytes,
    check_output,
    read_streaminfo,
    scan_expected,
)
from vsg_core.io.runner import CommandRunner
from vsg_core.models.settings import AppSettings

# --- sample maths -------------------------------------------------------------


class TestNsToSamples:
    def test_measured_delay_rounds_to_nearest_sample(self) -> None:
        # -10.834789 ms at 48 kHz = -520.07 samples
        assert ns_to_samples(ms_to_ns(-10.834789), 48000) == -520
        assert ns_to_samples(ms_to_ns(10.834789), 48000) == 520

    def test_whole_ms_is_exact(self) -> None:
        assert ns_to_samples(ms_to_ns(-517), 48000) == -24816
        assert ns_to_samples(ms_to_ns(1001), 44100) == 44144  # 44144.1

    def test_ties_round_away_from_zero(self) -> None:
        # 8 kHz: one sample = 125000 ns, so 62500 ns is exactly half a sample
        assert ns_to_samples(62_500, 8000) == 1
        assert ns_to_samples(-62_500, 8000) == -1
        assert ns_to_samples(62_499, 8000) == 0

    def test_zero(self) -> None:
        assert ns_to_samples(0, 48000) == 0

    @pytest.mark.parametrize("rate", [44100, 48000, 88200, 96000, 192000])
    def test_residual_never_exceeds_half_a_sample(self, rate: int) -> None:
        half_sample_ns = Fraction(10**9, 2 * rate)
        for ns in range(-3_000_000, 3_000_000, 7919):  # prime step: many phases
            bake = bake_delay(ns, rate)
            exact = Fraction(bake.samples * 10**9, rate) - ns
            assert abs(exact) <= half_sample_ns, (ns, rate)


class TestDelayBake:
    def test_negative_delay_cuts(self) -> None:
        bake = bake_delay(ms_to_ns(-10.834789), 48000)
        assert (bake.trimmed_start, bake.silence_added) == (520, 0)
        assert bake.residual_ns == pytest.approx(1455.7, abs=0.1)

    def test_positive_delay_adds_silence(self) -> None:
        bake = bake_delay(ms_to_ns(10.834789), 48000)
        assert (bake.trimmed_start, bake.silence_added) == (0, 520)

    def test_end_cap(self) -> None:
        assert end_cap_samples(ms_to_ns(45678), 48000) == 2_192_544
        with pytest.raises(ValueError):
            end_cap_samples(0, 48000)


# --- edit plans ---------------------------------------------------------------


class TestEditPlan:
    def test_plan_for_negative_delay(self) -> None:
        plan = plan_for_delay(bake_delay(ms_to_ns(-1), 48000))
        assert plan.ops == (Take(48),)

    def test_plan_for_positive_delay(self) -> None:
        plan = plan_for_delay(bake_delay(ms_to_ns(1), 48000), max_output_samples=1000)
        assert plan.ops == (Silence(48), Take(0))
        assert plan.max_output_samples == 1000

    def test_plan_for_zero_delay(self) -> None:
        assert plan_for_delay(bake_delay(0, 48000)).ops == (Take(0),)

    @pytest.mark.parametrize(
        "ops",
        [
            (),
            (Take(100, 50),),
            (Take(0, 100), Take(50, 200)),  # overlapping
            (Take(0), Take(500)),  # take after an open-ended take
            (Silence(0), Take(0)),
        ],
    )
    def test_invalid_plans_rejected(self, ops: tuple) -> None:
        with pytest.raises(ValueError):
            EditPlan(ops=ops)

    def test_expected_lengths(self) -> None:
        plan = EditPlan(
            ops=(Take(0, 100), Silence(10), Take(150)), max_output_samples=None
        )
        assert expected_output_samples(plan, 1000) == 100 + 10 + 850
        capped = EditPlan(ops=plan.ops, max_output_samples=500)
        assert expected_output_samples(capped, 1000) == 500
        assert trimmed_end_samples(capped, 1000) == 460


# --- ffmpeg graph / args -------------------------------------------------------

FMT_51 = SourceFormat("truehd", 48000, 6, "5.1(side)", 24)


class TestEncoderCommand:
    def test_graph_for_stepping_style_plan(self) -> None:
        plan = EditPlan(
            ops=(Take(0, 100), Silence(10), Take(150)), max_output_samples=500
        )
        graph = build_filter_graph(1, FMT_51, plan)
        pin = "aformat=sample_fmts=s32:channel_layouts=5.1(side)"
        assert graph == (
            f"[0:a:1]atrim=start_sample=0:end_sample=100,asetpts=PTS-STARTPTS,{pin}[p0];"
            f"anullsrc=r=48000:cl=5.1(side),{pin},atrim=end_sample=10[p1];"
            f"[0:a:1]atrim=start_sample=150,asetpts=PTS-STARTPTS,{pin}[p2];"
            "[p0][p1][p2]concat=n=3:v=0:a=1,atrim=end_sample=500[out]"
        )

    def test_unnamed_layout_gets_flac_default(self) -> None:
        fmt = SourceFormat("pcm_s16le", 48000, 2, None, 16)
        graph = build_filter_graph(0, fmt, EditPlan(ops=(Take(0),)))
        assert "aformat=sample_fmts=s16:channel_layouts=stereo" in graph

    def test_encode_args_stay_in_flac_subset(self) -> None:
        cmd = build_encode_command(
            Path("in.thd"),
            0,
            FMT_51,
            EditPlan(ops=(Take(0),)),
            {"K": "V"},
            Path("o.flac"),
        )
        joined = " ".join(cmd)
        assert "-compression_level 12 -max_prediction_order 12" in joined
        assert "-sample_fmt s32 -bits_per_raw_sample 24" in joined
        assert "-metadata K=V" in joined
        assert cmd[-1] == "o.flac"

    def test_sixteen_bit_needs_no_raw_bits(self) -> None:
        fmt = SourceFormat("pcm_s16le", 48000, 2, "stereo", 16)
        cmd = build_encode_command(
            Path("i.wav"), 0, fmt, EditPlan(ops=(Take(0),)), {}, Path("o.flac")
        )
        assert "-sample_fmt" in cmd and cmd[cmd.index("-sample_fmt") + 1] == "s16"
        assert "-bits_per_raw_sample" not in cmd

    def test_unsupported_bit_depth_rejected(self) -> None:
        fmt = SourceFormat("pcm_s32le", 48000, 2, "stereo", 32)
        with pytest.raises(ValueError):
            build_encode_command(
                Path("i.wav"), 0, fmt, EditPlan(ops=(Take(0),)), {}, Path("o.flac")
            )

    def test_every_decode_is_strict(self) -> None:
        encode = build_encode_command(
            Path("in.thd"), 0, FMT_51, EditPlan(ops=(Take(0),)), {}, Path("o.flac")
        )
        for cmd in (encode, _decode_cmd(Path("in.thd"), 0)):
            at = cmd.index("-i")
            # Input options only apply to the input that follows them.
            assert tuple(cmd[at - len(STRICT_DECODE_ARGS) : at]) == STRICT_DECODE_ARGS

    def test_layout_tables(self) -> None:
        assert default_layout(6) == "5.1"
        assert is_native_layout("5.1(side)", 6)
        assert not is_native_layout("4.0", 4)
        with pytest.raises(ValueError):
            default_layout(9)


# --- FLAC header / MD5 helpers / stream reader ---------------------------------


def _streaminfo_header(
    rate: int, channels: int, bits: int, total: int, md5: bytes
) -> bytes:
    packed = (rate << 44) | ((channels - 1) << 41) | ((bits - 1) << 36) | total
    body = struct.pack(">HH", 4608, 4608) + bytes(6) + packed.to_bytes(8, "big") + md5
    return b"fLaC" + bytes([0x80]) + len(body).to_bytes(3, "big") + body


class TestFlacHelpers:
    def test_read_streaminfo(self, tmp_path: Path) -> None:
        f = tmp_path / "h.flac"
        md5 = bytes(range(16))
        f.write_bytes(_streaminfo_header(96000, 8, 24, 123_456_789, md5))
        info = read_streaminfo(f)
        assert (info.sample_rate, info.channels, info.bits) == (96000, 8, 24)
        assert info.total_samples == 123_456_789 and info.md5 == md5

    def test_canonical_bytes(self) -> None:
        s16 = np.array([1, -2], dtype=np.int32) << 16
        assert (
            canonical_bytes(s16.astype("<i4").tobytes(), 16)
            == np.array([1, -2], "<i2").tobytes()
        )
        s24 = np.array([0x123456, -1], dtype=np.int32) << 8
        assert canonical_bytes(s24.astype("<i4").tobytes(), 24) == bytes(
            [0x56, 0x34, 0x12, 0xFF, 0xFF, 0xFF]
        )

    def test_frame_reader_handles_chunks_split_mid_frame(self) -> None:
        frames = bytes(range(24)) * 5  # 120 bytes = 10 frames of 12 bytes
        chunks = iter([frames[:5], frames[5:50], frames[50:]])
        r = _FrameReader(chunks, frame_bytes=12)
        assert b"".join(r.read(3)) == frames[:36]
        assert b"".join(r.read(None)) == frames[36:]
        assert r.position == 10


# --- end to end on synthetic audio ---------------------------------------------

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
    reason="ffmpeg not installed",
)


def _make_wav(path: Path, layout: str, bits: int, seconds: float = 2.0) -> None:
    """Different tone per channel so channel swaps would be visible."""
    channels = {"stereo": 2, "5.1(side)": 6}[layout]
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
            f"pcm_s{bits}le",
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


def _Runner() -> CommandRunner:
    """Real subprocesses with default app settings, log discarded."""
    return CommandRunner(AppSettings(), lambda _m: None)


@needs_ffmpeg
class TestEndToEnd:
    @pytest.mark.parametrize(("layout", "bits"), [("stereo", 16), ("5.1(side)", 24)])
    @pytest.mark.parametrize("delay_ms", [-517.0, -10.834789, 0.0, 10.834789])
    def test_finish_is_exact(
        self, tmp_path: Path, layout: str, bits: int, delay_ms: float
    ) -> None:
        src = tmp_path / "src.wav"
        _make_wav(src, layout, bits)
        bake = bake_delay(ms_to_ns(delay_ms), 48000)
        plan = plan_for_delay(
            bake, max_output_samples=end_cap_samples(ms_to_ns(1500.0), 48000)
        )
        out = tmp_path / "out.flac"
        res = finish(
            src, 0, plan, out, delay_tags(delay_ms, bake, plan, "A_PCM"), _Runner(), {}
        )
        assert res.ok, res.check
        ch = res.fmt.channels
        source = _decode(src).reshape(-1, ch)
        expected = np.concatenate(
            [np.zeros((bake.silence_added, ch), np.int32), source[bake.trimmed_start :]]
        )[:72000]
        assert np.array_equal(_decode(out).reshape(-1, ch), expected)
        assert res.tags["VSG_SAMPLES_TRIMMED_START"] == str(bake.trimmed_start)
        assert int(res.tags["VSG_SAMPLES_TRIMMED_END"]) == trimmed_end_samples(
            plan, 96000
        )

    def test_verifier_catches_a_wrong_output(self, tmp_path: Path) -> None:
        src = tmp_path / "src.wav"
        _make_wav(src, "stereo", 16)
        runner = _Runner()
        fmt = SourceFormat("pcm_s16le", 48000, 2, "stereo", 16)
        good = plan_for_delay(bake_delay(ms_to_ns(-10), 48000))
        res = finish(src, 0, good, tmp_path / "o.flac", lambda _e: {}, runner, {})
        assert res.ok
        # Expected output for a plan one sample off must not match this file.
        off = EditPlan(ops=(Take(481),))
        wrong = scan_expected(src, 0, fmt, off, runner, {})
        check = check_output(tmp_path / "o.flac", wrong, fmt, runner, {})
        assert not check.ok
        assert any("differ" in p for p in check.problems)

    def test_delay_removing_everything_is_refused(self, tmp_path: Path) -> None:
        src = tmp_path / "src.wav"
        _make_wav(src, "stereo", 16, seconds=0.05)
        bake = bake_delay(ms_to_ns(-517), 48000)
        plan = plan_for_delay(bake)
        out = tmp_path / "o.flac"
        res = finish(src, 0, plan, out, lambda _e: {}, _Runner(), {})
        assert not res.ok
        assert res.check is not None and "no audio" in res.check.problems[0]
        assert not out.exists()

    def test_damaged_source_fails_instead_of_matching_itself(
        self, tmp_path: Path
    ) -> None:
        src = tmp_path / "src.flac"
        _make_wav(tmp_path / "src.wav", "stereo", 16)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(tmp_path / "src.wav"), str(src)],
            check=True,
        )
        data = bytearray(src.read_bytes())
        data[len(data) * 3 // 5] ^= 0x10  # inside a frame, past the headers
        src.write_bytes(data)
        # A normal decode accepts the damage silently, so a non-strict source
        # scan and output check would both see it and agree.
        lax = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(src), "-f", "null", "-"],
            capture_output=True,
            check=False,
        )
        assert lax.returncode == 0
        out = tmp_path / "o.flac"
        plan = plan_for_delay(bake_delay(ms_to_ns(-10), 48000))
        with pytest.raises(FinishError, match="source does not decode cleanly"):
            finish(src, 0, plan, out, lambda _e: {}, _Runner(), {})
        assert not out.exists()

    def test_failed_stream_names_the_first_stderr_line(self) -> None:
        cmd = [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('root cause\\nmore\\n'); sys.exit(3)",
        ]
        with pytest.raises(RuntimeError, match=r"exit code 3: root cause$"):
            list(_Runner().stream_binary(cmd, {}))

    def test_tags_survive_and_hash_matches_flac_md5(self, tmp_path: Path) -> None:
        src = tmp_path / "src.wav"
        _make_wav(src, "5.1(side)", 24)
        bake = bake_delay(ms_to_ns(10.834789), 48000)
        plan = plan_for_delay(bake)
        out = tmp_path / "o.flac"
        res = finish(
            src, 0, plan, out, delay_tags(10.834789, bake, plan, "A_PCM"), _Runner(), {}
        )
        assert res.ok
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format_tags",
                "-of",
                "default=nw=1",
                str(out),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "VSG_SILENCE_SAMPLES_ADDED=520" in probe
        md5 = hashlib.md5(canonical_bytes(_decode(out).tobytes(), 24)).digest()
        assert read_streaminfo(out).md5 == md5
