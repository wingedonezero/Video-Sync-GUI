#!/usr/bin/env python3
"""
Read-only audit: which subtitle/audio data extends past the END OF THE VIDEO.

Why this exists
---------------
"End of the video" is the presentation end of the *last encoded video frame* —
NOT the container/format duration. Container duration is the max end over ALL
tracks, so a subtitle that overflows inflates it (circular), and it is often
audio-dominated. This tool measures each track against the true last-frame end
(computed exactly on the CFR frame grid when the stream is CFR-from-0).

It MODIFIES NOTHING. It prints, per file:
  * video: fps, true last-frame end (frame-grid exact for CFR)
  * container duration and WHICH track defines it (video / audio / a subtitle)
  * audio tracks: end time + overhang past the last video frame
  * text subs (ASS/SRT): every line whose END is past the last frame, with the
    overflow in ms and a text preview
  * PGS: last composition/clear PTS (approximate display end; flagged if past)
  * a plain-language verdict, incl. whether the post-video tail (if any) is
    caused by AUDIO or by a SUBTITLE

Usage:
    python3 tools/overflow_audit.py [PATH ...]
    PATH may be a folder (audits every *.mkv inside) or individual .mkv files.
    Default: the Re Monster sync_output folder.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

DEFAULT_PATHS = [
    "/home/chaoz/Applications/Media Tools/My Programs/"
    "Video-Sync-GUI/sync_output/[BDMV] Re Monster [JPN]"
]

# A track end within this many ms of the container duration is treated as the
# track that "defines" the container (mkvmerge rounds; audio frames are coarse).
CONTAINER_DEFINE_TOL_MS = 60.0


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True).stdout


@dataclass(slots=True)
class StreamInfo:
    index: int
    codec_type: str
    codec_name: str


@dataclass(slots=True)
class SubOverflow:
    track_index: int
    codec: str
    line_count_overflow: int
    max_end_ms: float
    overflow_ms: float  # max_end - video_end
    examples: list[str] = field(default_factory=list)  # human-readable lines


@dataclass(slots=True)
class FileAudit:
    path: Path
    fps: Fraction | None
    is_cfr: bool
    video_end_ms: float | None
    container_ms: float | None
    audio_ends_ms: dict[int, float] = field(default_factory=dict)
    sub_overflows: list[SubOverflow] = field(default_factory=list)
    container_defined_by: str = "?"


def streams(path: Path) -> list[StreamInfo]:
    out = run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name", "-of", "csv", str(path)]
    )
    res: list[StreamInfo] = []
    for ln in out.strip().splitlines():
        p = ln.split(",")
        if len(p) >= 4:
            res.append(StreamInfo(int(p[1]), p[3], p[2]))
    return res


def container_ms(path: Path) -> float | None:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(path)])
    try:
        return float(json.loads(out)["format"]["duration"]) * 1000.0
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def video_fps(path: Path) -> tuple[Fraction | None, bool]:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=r_frame_rate,avg_frame_rate",
               "-of", "json", str(path)])
    try:
        st = json.loads(out)["streams"][0]
        r = Fraction(st["r_frame_rate"])
        a = Fraction(st.get("avg_frame_rate", st["r_frame_rate"]))
        return r, (r == a and r.numerator > 0)
    except (json.JSONDecodeError, KeyError, ValueError, ZeroDivisionError, IndexError):
        return None, False


def _tail_max_pts_ms(path: Path, selector: str, window_start_s: float,
                     window_len_s: float, add_dur: bool) -> float | None:
    entries = "packet=pts_time,duration_time" if add_dur else "packet=pts_time"
    out = run(["ffprobe", "-v", "error", "-select_streams", selector,
               "-show_entries", entries, "-read_intervals",
               f"{max(0.0, window_start_s):.3f}%+{window_len_s:.0f}",
               "-of", "csv", str(path)])
    mx: float | None = None
    for ln in out.strip().splitlines():
        p = ln.split(",")
        if len(p) >= 2 and p[1] not in ("", "N/A"):
            try:
                v = float(p[1]) * 1000.0
                if add_dur and len(p) >= 3 and p[2] not in ("", "N/A"):
                    v += float(p[2]) * 1000.0
                if mx is None or v > mx:
                    mx = v
            except ValueError:
                pass
    return mx


def true_video_end_ms(path: Path, fps: Fraction | None, is_cfr: bool,
                      cont_ms: float | None) -> float | None:
    """Presentation end of the last video frame.

    CFR-from-0: snap last-frame PTS to the exact frame grid, then add one
    frame period — pure rational arithmetic, no float drift.
    VFR / unknown fps: last_frame_pts + last_packet_duration.
    """
    win = ((cont_ms or 0) / 1000.0) - 12.0
    last_pts = _tail_max_pts_ms(path, "v:0", win, 15, add_dur=False)
    if last_pts is None:
        return None
    if is_cfr and fps:
        period = Fraction(fps.denominator, fps.numerator)  # seconds/frame
        idx = round((last_pts / 1000.0) / float(period))   # last frame index
        end_s = Fraction(idx + 1) * period                 # exact end of frame
        return float(end_s) * 1000.0
    last_end = _tail_max_pts_ms(path, "v:0", win, 15, add_dur=True)
    return last_end if last_end is not None else last_pts


def audio_end_ms(path: Path, sidx: int, cont_ms: float | None) -> float | None:
    win = ((cont_ms or 0) / 1000.0) - 12.0
    return _tail_max_pts_ms(path, str(sidx), win, 15, add_dur=True)


def _ass_time_to_ms(ts: str) -> float:
    h, m, s = ts.split(":")
    return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0


def _srt_time_to_ms(ts: str) -> float:
    ts = ts.replace(",", ".")
    h, m, s = ts.split(":")
    return (int(h) * 3600 + int(m) * 60 + float(s)) * 1000.0


def text_sub_overflow(path: Path, sidx: int, codec: str,
                      video_end_ms: float) -> SubOverflow | None:
    dst = Path("/tmp") / f"audit_{path.stem}_{sidx}.{('ass' if codec == 'ass' else 'srt')}"
    subprocess.run(["mkvextract", "tracks", str(path), f"{sidx}:{dst}"],
                   capture_output=True)
    if not dst.exists():
        return None
    over: list[tuple[float, float, str]] = []  # (end_ms, overflow_ms, preview)
    max_end = 0.0
    text = dst.read_text(encoding="utf-8", errors="replace")
    if codec == "ass":
        for ln in text.splitlines():
            if not ln.startswith("Dialogue:"):
                continue
            parts = ln.split(",", 9)
            if len(parts) < 10:
                continue
            end_ms = _ass_time_to_ms(parts[2].strip())
            start_ms = _ass_time_to_ms(parts[1].strip())
            max_end = max(max_end, end_ms)
            if end_ms > video_end_ms:
                body = parts[9].strip().replace("\n", " ")[:70]
                tag = "START-PAST-END!" if start_ms >= video_end_ms else ""
                over.append((end_ms, end_ms - video_end_ms,
                             f"{parts[1].strip()}->{parts[2].strip()} [{parts[3].strip()}] "
                             f"{tag} {body}"))
    else:  # srt
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if "-->" not in ln:
                continue
            a, _, b = ln.partition("-->")
            try:
                start_ms = _srt_time_to_ms(a.strip())
                end_ms = _srt_time_to_ms(b.strip().split()[0])
            except (ValueError, IndexError):
                continue
            max_end = max(max_end, end_ms)
            if end_ms > video_end_ms:
                body = (lines[i + 1].strip() if i + 1 < len(lines) else "")[:70]
                tag = "START-PAST-END!" if start_ms >= video_end_ms else ""
                over.append((end_ms, end_ms - video_end_ms,
                             f"{a.strip()}->{b.strip()} {tag} {body}"))
    if not over and max_end <= video_end_ms:
        return SubOverflow(sidx, codec, 0, max_end, max_end - video_end_ms)
    over.sort(reverse=True)
    return SubOverflow(
        sidx, codec, len(over), max_end,
        (max_end - video_end_ms),
        [f"+{o:.0f}ms  {prev}" for _, o, prev in over[:6]],
    )


def pgs_last_pts_ms(path: Path, sidx: int) -> float | None:
    out = run(["ffprobe", "-v", "error", "-select_streams", str(sidx),
               "-show_entries", "packet=pts_time", "-of", "csv", str(path)])
    mx: float | None = None
    for ln in out.strip().splitlines():
        p = ln.split(",")
        if len(p) >= 2 and p[1] not in ("", "N/A"):
            try:
                v = float(p[1]) * 1000.0
                if mx is None or v > mx:
                    mx = v
            except ValueError:
                pass
    return mx


def audit_file(path: Path) -> FileAudit:
    cont = container_ms(path)
    fps, is_cfr = video_fps(path)
    vend = true_video_end_ms(path, fps, is_cfr, cont)
    fa = FileAudit(path=path, fps=fps, is_cfr=is_cfr, video_end_ms=vend,
                   container_ms=cont)
    sm = streams(path)
    for s in sm:
        if s.codec_type == "audio":
            ae = audio_end_ms(path, s.index, cont)
            if ae is not None:
                fa.audio_ends_ms[s.index] = ae
        elif s.codec_type == "subtitle" and vend is not None:
            if s.codec_name in ("ass", "subrip"):
                so = text_sub_overflow(path, s.index,
                                       "ass" if s.codec_name == "ass" else "srt",
                                       vend)
                if so:
                    fa.sub_overflows.append(so)
            elif s.codec_name == "hdmv_pgs_subtitle":
                last = pgs_last_pts_ms(path, s.index)
                if last is not None:
                    fa.sub_overflows.append(
                        SubOverflow(s.index, "pgs",
                                    1 if last > vend else 0, last, last - vend,
                                    ["(PGS: last composition PTS, approx display end)"])
                    )
    # Decide what defines the container.
    if cont is not None:
        cand: list[tuple[str, float]] = []
        if vend is not None:
            cand.append(("video", vend))
        for idx, ae in fa.audio_ends_ms.items():
            cand.append((f"audio#{idx}", ae))
        for so in fa.sub_overflows:
            cand.append((f"sub#{so.track_index}({so.codec})", so.max_end_ms))
        near = [name for name, end in cand if abs(end - cont) <= CONTAINER_DEFINE_TOL_MS]
        fa.container_defined_by = ", ".join(near) if near else "?"
    return fa


def fmt_ms(x: float | None) -> str:
    return f"{x / 1000:.3f}s" if x is not None else "  --  "


def print_audit(fa: FileAudit) -> None:
    name = fa.path.name
    fps_s = (f"{fa.fps} ({float(fa.fps):.3f})" if fa.fps else "?")
    cfr_s = "CFR" if fa.is_cfr else "VFR/unknown"
    print(f"\n{'='*74}\n{name}   fps={fps_s} {cfr_s}")
    print(f"  video last-frame end : {fmt_ms(fa.video_end_ms)}")
    print(f"  container duration   : {fmt_ms(fa.container_ms)}   "
          f"(defined by: {fa.container_defined_by})")
    if fa.video_end_ms is None:
        print("  !! could not determine video end — skipping comparisons")
        return
    vend = fa.video_end_ms
    # Audio
    for idx, ae in sorted(fa.audio_ends_ms.items()):
        over = ae - vend
        flag = "  <-- PAST VIDEO" if over > 0 else ""
        print(f"  audio  s:{idx:<2} end {fmt_ms(ae)}  overhang {over:+.0f}ms{flag}")
    # Subs
    for so in fa.sub_overflows:
        if so.codec == "pgs":
            flag = "  <-- PAST VIDEO" if so.overflow_ms > 0 else "  (ok)"
            print(f"  PGS    s:{so.track_index:<2} last {fmt_ms(so.max_end_ms)}  "
                  f"{so.overflow_ms:+.0f}ms{flag}")
            continue
        if so.line_count_overflow == 0:
            print(f"  {so.codec.upper():<4} s:{so.track_index:<2} max-end {fmt_ms(so.max_end_ms)}  "
                  f"{so.overflow_ms:+.0f}ms  (ok, within video)")
        else:
            print(f"  {so.codec.upper():<4} s:{so.track_index:<2} *** {so.line_count_overflow} "
                  f"line(s) PAST VIDEO ***  worst +{so.overflow_ms:.0f}ms")
            for ex in so.examples:
                print(f"        {ex}")
    # Verdict on the post-video tail (answers the audio question).
    tail_end = fa.container_ms or vend
    tail_ms = (tail_end - vend) if tail_end else 0
    sub_in_tail = [so for so in fa.sub_overflows
                   if so.codec != "pgs" and so.line_count_overflow > 0]
    audio_in_tail = [i for i, ae in fa.audio_ends_ms.items() if ae - vend > 1.0]
    if tail_ms <= 1:
        print("  VERDICT: file ends with the video — no post-video tail.")
    else:
        cause = []
        if sub_in_tail:
            cause.append("a SUBTITLE")
        if audio_in_tail and (fa.container_ms or 0) - vend > 1.0 and not (
            sub_in_tail and max(s.max_end_ms for s in sub_in_tail) >= (fa.container_ms or 0) - 1
        ):
            cause.append("AUDIO")
        print(f"  VERDICT: ~{tail_ms:.0f}ms tail past the last video frame, caused by "
              f"{' and '.join(cause) if cause else 'container rounding'}.")


def collect(paths: list[str]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(pp.glob("*.mkv"),
                                key=lambda f: (len(f.stem), f.stem)))
        elif pp.is_file():
            files.append(pp)
    return files


def main() -> None:
    args = sys.argv[1:] or DEFAULT_PATHS
    files = collect(args)
    if not files:
        print("No .mkv files found.")
        return
    print(f"Auditing {len(files)} file(s). 'End of video' = last encoded frame "
          f"(frame-grid exact for CFR).")
    for f in files:
        print_audit(audit_file(f))


if __name__ == "__main__":
    main()
