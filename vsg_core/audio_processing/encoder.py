# vsg_core/audio_processing/encoder.py
"""Execute an edit plan with one streaming ffmpeg pass straight into FLAC.

Every take is an exact-sample ``atrim`` of the decoded source, every silence an
exact-length run of digital zeros, joined with ``concat`` and capped by the end
trim. All branches are pinned to one integer sample format so nothing is ever
converted to floating point on the way.

FLAC settings: the highest ffmpeg compression level, with the predictor order
capped at 12 so the file stays inside the FLAC streamable subset (level 12
alone goes to order 32, which hardware decoders may reject).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from .types import EditPlan, Silence, SourceFormat, Take

if TYPE_CHECKING:
    from pathlib import Path

    from vsg_core.io.runner import CommandRunner

# FLAC's own channel orders (RFC 9639 section 9.1.3). Layouts outside this
# table are stored with a WAVEFORMATEXTENSIBLE_CHANNEL_MASK tag instead.
FLAC_NATIVE_LAYOUTS: dict[int, tuple[str, ...]] = {
    1: ("mono",),
    2: ("stereo",),
    3: ("3.0",),
    4: ("quad",),
    5: ("5.0", "5.0(side)"),
    6: ("5.1", "5.1(side)"),
    7: ("6.1",),
    8: ("7.1",),
}
SUPPORTED_BITS = (16, 20, 24)
FLAC_ENCODER_ARGS = (
    "-c:a",
    "flac",
    "-compression_level",
    "12",
    "-max_prediction_order",
    "12",
)
# Every decode of a source or of our own FLAC output. By default ffmpeg drops a
# frame that fails to decode (or a DTS-HD MA frame falls back to its lossy core)
# and still exits 0; the verifier's source scan would contain the same damage
# and agree with it. Strict decoding turns that into a failed track instead:
# explode makes the decoder report the error, -xerror makes ffmpeg exit on it,
# crccheck enables the CRCs that are off by default (FLAC frames).
STRICT_DECODE_ARGS = ("-err_detect", "+crccheck+explode", "-xerror")


def default_layout(channels: int) -> str:
    """The layout FLAC (and players) assume for an unnamed stream of ``channels``."""
    if channels not in FLAC_NATIVE_LAYOUTS:
        raise ValueError(f"FLAC has no default layout for {channels} channels")
    return FLAC_NATIVE_LAYOUTS[channels][0]


def is_native_layout(layout: str, channels: int) -> bool:
    return layout in FLAC_NATIVE_LAYOUTS.get(channels, ())


def output_layout(fmt: SourceFormat) -> str:
    return fmt.channel_layout or default_layout(fmt.channels)


def probe_source_format(
    path: Path,
    stream_index: int,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> SourceFormat:
    """Exact decoded format of audio stream ``stream_index`` of ``path``."""
    out = runner.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            f"a:{stream_index}",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,channel_layout,"
            "bits_per_raw_sample,bits_per_sample",
            "-of",
            "json",
            str(path),
        ],
        tool_paths,
    )
    if not isinstance(out, str):
        raise RuntimeError(f"ffprobe failed on {path}")
    streams = json.loads(out).get("streams") or []
    if not streams:
        raise RuntimeError(f"no audio stream {stream_index} in {path}")
    st = streams[0]
    bits = 0
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        try:
            bits = int(st.get(key) or 0)
        except (TypeError, ValueError):
            bits = 0
        if bits:
            break
    layout = st.get("channel_layout")
    if layout in (None, "", "unknown"):
        layout = None
    return SourceFormat(
        codec_name=str(st.get("codec_name") or ""),
        sample_rate=int(st["sample_rate"]),
        channels=int(st["channels"]),
        channel_layout=layout,
        bits=bits,
    )


def build_filter_graph(stream_index: int, fmt: SourceFormat, plan: EditPlan) -> str:
    """``-filter_complex`` graph for ``plan``; the result is labelled ``[out]``."""
    sample_fmt = fmt.flac_sample_fmt
    layout = output_layout(fmt)
    pin = f"aformat=sample_fmts={sample_fmt}:channel_layouts={layout}"
    chains: list[str] = []
    for i, op in enumerate(plan.ops):
        if isinstance(op, Take):
            trim = f"atrim=start_sample={op.start}"
            if op.end is not None:
                trim += f":end_sample={op.end}"
            chains.append(
                f"[0:a:{stream_index}]{trim},asetpts=PTS-STARTPTS,{pin}[p{i}]"
            )
        else:
            assert isinstance(op, Silence)
            chains.append(
                f"anullsrc=r={fmt.sample_rate}:cl={layout},{pin},"
                f"atrim=end_sample={op.samples}[p{i}]"
            )
    joined = "".join(f"[p{i}]" for i in range(len(plan.ops)))
    tail = f"concat=n={len(plan.ops)}:v=0:a=1"
    if plan.max_output_samples is not None:
        tail += f",atrim=end_sample={plan.max_output_samples}"
    chains.append(f"{joined}{tail}[out]")
    return ";".join(chains)


def build_encode_command(
    source: Path,
    stream_index: int,
    fmt: SourceFormat,
    plan: EditPlan,
    tags: dict[str, str],
    out: Path,
) -> list[str]:
    if fmt.bits not in SUPPORTED_BITS:
        raise ValueError(f"unsupported bit depth {fmt.bits}")
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-nostdin",
        *STRICT_DECODE_ARGS,
        "-i",
        str(source),
        "-filter_complex",
        build_filter_graph(stream_index, fmt, plan),
        "-map",
        "[out]",
        *FLAC_ENCODER_ARGS,
        "-sample_fmt",
        fmt.flac_sample_fmt,
    ]
    if fmt.bits != 16:
        cmd += ["-bits_per_raw_sample", str(fmt.bits)]
    # Drop the source's tags; the file describes itself with ours only.
    cmd += ["-map_metadata", "-1", "-fflags", "+bitexact"]
    for key, value in tags.items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd.append(str(out))  # a seekable file, so STREAMINFO total + MD5 get written
    return cmd


def encode(
    source: Path,
    stream_index: int,
    fmt: SourceFormat,
    plan: EditPlan,
    tags: dict[str, str],
    out: Path,
    runner: CommandRunner,
    tool_paths: dict[str, str | None],
) -> bool:
    cmd = build_encode_command(source, stream_index, fmt, plan, tags, out)
    ok = runner.run(cmd, tool_paths) is not None
    return ok and out.exists() and out.stat().st_size > 0
