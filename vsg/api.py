from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .analysis.audio import analyze_audio_offset
from .analysis.video import analyze_video_offset
from .plan import PositiveOnlyDelayPlan, build_positive_only_delays
from .opts import build_mkvmerge_tokens, pretty_print_tokens
from .mux.mkvmerge import run_mkvmerge_with_tokens
from .chapters import load_chapters, shift_chapters, snap_chapters
from .language import infer_language_code
from .attachments import collect_font_attachments
from .settings import AppSettings
from .utils.proc import run_command
from .utils.fs import ensure_dir

def analyze(
    ref_path: Path,
    sec_path: Optional[Path] = None,
    ter_path: Optional[Path] = None,
    mode: str = "audio",
    settings: Optional[AppSettings] = None,
) -> Dict[str, int]:
    """Analyze offsets vs. the reference.

    Returns a dict of measured delays in milliseconds (positive => behind REF).
    Keys: "ref" (always 0), "sec" (or None), "ter" (or None).
    """
    delays = {"ref": 0, "sec": None, "ter": None}
    if sec_path is not None:
        delays["sec"] = (
            analyze_audio_offset(ref_path, sec_path, settings) if mode == "audio"
            else analyze_video_offset(ref_path, sec_path, settings)
        )
    if ter_path is not None:
        delays["ter"] = (
            analyze_audio_offset(ref_path, ter_path, settings) if mode == "audio"
            else analyze_video_offset(ref_path, ter_path, settings)
        )
    return delays

def analyze_and_plan(
    ref_path: Path,
    sec_path: Optional[Path],
    ter_path: Optional[Path],
    mode: str,
    settings: Optional[AppSettings] = None,
) -> PositiveOnlyDelayPlan:
    """Analyze then normalize into a positive-only delay plan."""
    measured = analyze(ref_path, sec_path, ter_path, mode=mode, settings=settings)
    return build_positive_only_delays(measured)

def merge_with_plan(
    output_path: Path,
    ref_path: Path,
    sec_path: Optional[Path],
    ter_path: Optional[Path],
    plan: PositiveOnlyDelayPlan,
    settings: Optional[AppSettings] = None,
) -> Path:
    """Build mkvmerge tokens from a plan and execute mkvmerge.

    Writes:
      - opts.json (token array)
      - opts.pretty.txt (human summary)

    Returns the output MKV path.
    """
    ensure_dir(output_path.parent)
    # Chapters (optional)
    ch_xml = None
    if settings and settings.chapters.enabled:
        ch = load_chapters(settings.chapters.source or ref_path)
        ch = shift_chapters(ch, plan.global_anchor_ms)
        if settings.chapters.snap_mode != "off":
            ch = snap_chapters(ch, settings.chapters.snap_mode, settings.chapters.snap_tolerance_ms)
        ch_xml = (output_path.parent / "chapters_mod.xml").resolve()

    tokens = build_mkvmerge_tokens(
        output_path=output_path,
        ref_path=ref_path,
        sec_path=sec_path,
        ter_path=ter_path,
        plan=plan,
        chapters_xml=ch_xml,
        settings=settings,
    )
    pretty = pretty_print_tokens(tokens)
    (output_path.parent / "opts.pretty.txt").write_text(pretty, encoding="utf-8")
    (output_path.parent / "opts.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    run_mkvmerge_with_tokens(tokens)
    return output_path
