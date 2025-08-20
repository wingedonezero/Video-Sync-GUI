"""Chapter utilities: extract from REF, rename, and snap to keyframes."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import subprocess

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.tools import ABS, _resolve_tool  # ABS may contain ffprobe

NS = "http://mkvtoolnix.matroska.org/chapters/1"

@dataclass
class SnapCfg:
    enabled: bool
    mode: str  # previous|next|nearest
    threshold_ms: int
    starts_only: bool
    verbose: bool

def _extract_chapters_xml(ref_path: Path) -> Optional[str]:
    """Extract chapters XML from a Matroska file using mkvextract (stdout)."""
    mkvextract = ABS.get("mkvextract") or _resolve_tool("mkvextract") or "mkvextract"
    try:
        proc = subprocess.run([mkvextract, "chapters", str(ref_path)], check=True, capture_output=True, text=True)
        xml = proc.stdout.strip()
        if xml and xml.lstrip().startswith("<?xml") or "Chapters" in xml:
            return xml
        return None
    except Exception as e:
        _log(f"[chapters] mkvextract failed: {e}")
        return None

def _get_keyframes_ns(video_path: Path) -> List[int]:
    """Return keyframe pts times in nanoseconds using ffprobe (skip non-key)."""
    ffprobe = ABS.get("ffprobe") or _resolve_tool("ffprobe") or "ffprobe"
    cmd = [
        ffprobe,
        "-v","error",
        "-select_streams","v:0",
        "-skip_frame","nokey",
        "-show_entries","frame=pts_time",
        "-of","csv=p=0",
        str(video_path),
    ]
    out = ""
    try:
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        out = proc.stdout.strip()
    except Exception as e:
        _log(f"[chapters] ffprobe keyframes failed: {e}")
        return []
    key_ns: List[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            t_sec = float(line)
            key_ns.append(int(round(t_sec * 1e9)))
        except Exception:
            continue
    key_ns.sort()
    return key_ns

def _time_str_to_ns(ts: str) -> int:
    # format HH:MM:SS.nnnnnnnnn
    hms, _, frac = ts.partition(".")
    h, m, s = map(int, hms.split(":"))
    ns = ((h*3600 + m*60 + s) * 1_000_000_000)
    if frac:
        # pad or trim to 9 digits
        if len(frac) > 9: frac = frac[:9]
        ns += int(frac.ljust(9, "0"))
    return ns

def _ns_to_time_str(ns: int) -> str:
    if ns < 0: ns = 0
    s, n = divmod(ns, 1_000_000_000)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}.{n:09d}"

def _rename_consecutive(root: ET.Element) -> None:
    idx = 1
    for ed in root.findall(f".//{{{NS}}}EditionEntry"):
        for chap in ed.findall(f".//{{{NS}}}ChapterAtom"):
            disp = chap.find(f".//{{{NS}}}ChapterDisplay/{{{NS}}}ChapterString")
            if disp is None:
                # create display structure
                cd = ET.SubElement(chap, f"{{{NS}}}ChapterDisplay")
                disp = ET.SubElement(cd, f"{{{NS}}}ChapterString")
            disp.text = f"Chapter {idx:02d}"
            idx += 1

def _snap_value(ns: int, keys: List[int], mode: str, threshold: int) -> int:
    # simple binary search
    import bisect
    i = bisect.bisect_left(keys, ns)
    prev_k = keys[i-1] if i > 0 else None
    next_k = keys[i] if i < len(keys) else None
    cand = ns
    if mode == "previous" and prev_k is not None and ns - prev_k <= threshold*1_000_000:
        cand = prev_k
    elif mode == "next" and next_k is not None and next_k - ns <= threshold*1_000_000:
        cand = next_k
    elif mode == "nearest":
        best = None
        if prev_k is not None: best = (abs(ns - prev_k), prev_k)
        if next_k is not None:
            d = abs(next_k - ns)
            if best is None or d < best[0]: best = (d, next_k)
        if best and best[0] <= threshold*1_000_000:
            cand = best[1]
    return cand

def _snap_chapters(root: ET.Element, keys: List[int], cfg: SnapCfg) -> int:
    """Snap chapter start times in-place. Returns count snapped."""
    snapped = 0
    for chap in root.findall(f".//{{{NS}}}ChapterAtom"):
        starts = chap.findall(f"./{{{NS}}}ChapterTimeStart")
        ends = chap.findall(f"./{{{NS}}}ChapterTimeEnd")
        if not starts:
            continue
        s_el = starts[0]
        s_ns = _time_str_to_ns(s_el.text or "00:00:00.000000000")
        new_s = _snap_value(s_ns, keys, cfg.mode, cfg.threshold_ms) if cfg.enabled else s_ns
        if new_s != s_ns:
            s_el.text = _ns_to_time_str(new_s)
            snapped += 1
        if not cfg.starts_only and ends:
            e_el = ends[0]
            e_ns = _time_str_to_ns(e_el.text or "00:00:00.000000000")
            new_e = _snap_value(e_ns, keys, cfg.mode, cfg.threshold_ms) if cfg.enabled else e_ns
            if new_e != e_ns:
                e_el.text = _ns_to_time_str(new_e)
    return snapped

def prepare_chapters_for_ref(ref_mkv: Path, temp_dir: Path) -> Optional[Path]:
    """If chapters exist and renaming/snap is enabled, produce an XML and return its path."""
    xml = _extract_chapters_xml(ref_mkv)
    if not xml:
        _log("[chapters] No chapters found in REF or extraction failed.")
        return None
    try:
        root = ET.fromstring(xml)
    except Exception as e:
        _log(f"[chapters] Invalid chapter XML: {e}")
        return None

    # rename?
    if CONFIG.get("rename_chapters", False):
        _rename_consecutive(root)

    # snap?
    snap_cfg = SnapCfg(
        enabled=bool(CONFIG.get("snap_chapters", False)),
        mode=str(CONFIG.get("snap_mode", "previous")),
        threshold_ms=int(CONFIG.get("snap_threshold_ms", 250)),
        starts_only=bool(CONFIG.get("snap_starts_only", True)),
        verbose=bool(CONFIG.get("chapter_snap_verbose", False)),
    )

    if snap_cfg.enabled:
        keys = _get_keyframes_ns(ref_mkv)
        if not keys:
            _log("[chapters] No keyframes detected; snap skipped.")
        else:
            n = _snap_chapters(root, keys, snap_cfg)
            _log(f"[chapters] Snapped {n} chapter boundaries to keyframes (mode={snap_cfg.mode}).")

    # write XML
    out = temp_dir / "chapters.final.xml"
    ET.register_namespace('', NS)
    tree = ET.ElementTree(root)
    try:
        tree.write(out, encoding="utf-8", xml_declaration=True)
        _log(f"[chapters] Wrote chapters XML: {out}")
        return out
    except Exception as e:
        _log(f"[chapters] Failed to write chapters XML: {e}")
        return None
