# vsg_core/orchestrator/steps.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any

# Core utilities you already have
from vsg_core.process import CommandRunner
from vsg_core import analysis as core_analysis
from vsg_core import mkv_utils
from vsg_core import subtitle_utils

# New modular models / builder you added earlier
from vsg_core.models.settings import AppSettings
from vsg_core.models.jobs import MergePlan, PlanItem, Delays
from vsg_core.models.media import Track, StreamProps
from vsg_core.models.enums import SourceRole, TrackType
from vsg_core.mux.options_builder import MkvmergeOptionsBuilder


# -------------------------------------------------------------------------------------------------
# Context shared by all steps
# -------------------------------------------------------------------------------------------------
@dataclass
class Context:
    # Provided by Orchestrator entry
    settings: AppSettings                  # typed settings
    settings_dict: Dict[str, Any]          # raw dict (needed by core functions that expect dict)
    tool_paths: Dict[str, Optional[str]]
    log: Callable[[str], None]
    progress: Callable[[float], None]
    output_dir: str
    temp_dir: Path                         # per-job temporary workspace (created by orchestrator)
    ref_file: str
    sec_file: Optional[str] = None
    ter_file: Optional[str] = None
    and_merge: bool = False
    manual_layout: List[Dict[str, Any]] = field(default_factory=list)

    # Filled along the pipeline
    delays: Optional[Delays] = None
    extracted_items: Optional[List[PlanItem]] = None
    chapters_xml: Optional[str] = None
    attachments: Optional[List[str]] = None

    # Results/summaries
    out_file: Optional[str] = None
    delay_sec_val: Optional[int] = None
    delay_ter_val: Optional[int] = None

    # NEW: mkvmerge @opts tokens produced by MuxStep (surgical tweak)
    tokens: Optional[List[str]] = None


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------
def _best_from_results(results: List[Dict[str, Any]], min_match_pct: float) -> Optional[Dict[str, Any]]:
    """
    Mirrors the stable selection logic from the original pipeline:
      - filter by match > min_match_pct
      - pick the delay value with the highest frequency
      - tie-break among that delay by max match percentage
      - then pick overall best by match
    """
    if not results:
        return None
    valid = [r for r in results if r.get('match', 0.0) > float(min_match_pct)]
    if not valid:
        return None
    from collections import Counter
    counts = Counter(r['delay'] for r in valid)
    max_freq = counts.most_common(1)[0][1]
    contenders = [d for d, f in counts.items() if f == max_freq]
    best_of_each = [
        max((r for r in valid if r['delay'] == d), key=lambda x: x['match'])
        for d in contenders
    ]
    return max(best_of_each, key=lambda x: x['match'])


def _role_tag_for(path: Optional[str]) -> str:
    return 'sec' if path else 'ter'


# -------------------------------------------------------------------------------------------------
# Steps
# -------------------------------------------------------------------------------------------------
class AnalysisStep:
    """
    Determines delays for Secondary and Tertiary using either Audio Correlation or VideoDiff,
    with the same guardrails and logs as the original pipeline.
    Also computes the global shift so that the minimum (possibly negative) delay is lifted.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        mode = ctx.settings.analysis_mode  # 'Audio Correlation' or 'VideoDiff'

        # Prepare language preferences (blank -> None maps to "first stream")
        ref_lang = ctx.settings.analysis_lang_ref or None
        sec_lang = ctx.settings.analysis_lang_sec or None
        ter_lang = ctx.settings.analysis_lang_ter or None

        delay_sec: Optional[int] = None
        delay_ter: Optional[int] = None

        # ---------- Secondary ----------
        if ctx.sec_file:
            runner._log_message(f'Analyzing Secondary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = core_analysis.run_videodiff(ctx.ref_file, ctx.sec_file, ctx.settings_dict, runner, ctx.tool_paths)
                # enforce error bounds
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
                delay_sec = delay_ms
            else:
                # Audio correlation on multiple chunks
                results = core_analysis.run_audio_correlation(
                    ctx.ref_file,
                    ctx.sec_file,
                    ctx.temp_dir,
                    ctx.settings_dict,
                    runner,
                    ctx.tool_paths,
                    ref_lang=ref_lang,
                    target_lang=sec_lang,
                    role_tag='sec'
                )
                best = _best_from_results(results, ctx.settings.min_match_pct)
                if not best:
                    raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
                delay_sec = int(best['delay'])
            runner._log_message(f'Secondary delay determined: {delay_sec} ms')

        # ---------- Tertiary ----------
        if ctx.ter_file:
            runner._log_message(f'Analyzing Tertiary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ms, err = core_analysis.run_videodiff(ctx.ref_file, ctx.ter_file, ctx.settings_dict, runner, ctx.tool_paths)
                if not (ctx.settings.videodiff_error_min <= err <= ctx.settings.videodiff_error_max):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
                delay_ter = delay_ms
            else:
                results = core_analysis.run_audio_correlation(
                    ctx.ref_file,
                    ctx.ter_file,
                    ctx.temp_dir,
                    ctx.settings_dict,
                    runner,
                    ctx.tool_paths,
                    ref_lang=ref_lang,
                    target_lang=ter_lang,
                    role_tag='ter'
                )
                best = _best_from_results(results, ctx.settings.min_match_pct)
                if not best:
                    raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
                delay_ter = int(best['delay'])
            runner._log_message(f'Tertiary delay determined: {delay_ter} ms')

        # Compute global shift (unchanged behavior from legacy pipeline)
        present = [0]
        if delay_sec is not None:
            present.append(delay_sec)
        if delay_ter is not None:
            present.append(delay_ter)
        min_delay = min(present)
        global_shift = -min_delay if min_delay < 0 else 0

        ctx.delay_sec_val = delay_sec
        ctx.delay_ter_val = delay_ter
        ctx.delays = Delays(
            secondary_ms=delay_sec if delay_sec is not None else 0,
            tertiary_ms=delay_ter if delay_ter is not None else 0,
            global_shift_ms=global_shift
        )

        # Helpful logs, mirroring originals
        sec_disp = delay_sec if delay_sec is not None else 0
        ter_disp = delay_ter if delay_ter is not None else 0
        runner._log_message(f'[Delay] Raw delays (ms): ref=0, sec={sec_disp}, ter={ter_disp}')
        runner._log_message(f'[Delay] Applying lossless global shift: +{global_shift} ms')

        return ctx


class ExtractStep:
    """
    Extracts the user-selected tracks from REF/SEC/TER using mkvextract/ffmpeg (through your mkv_utils).
    Builds a typed PlanItem list with rules from the manual layout for downstream steps.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            # Nothing to extract for analyze-only
            ctx.extracted_items = []
            return ctx

        # Separate selected IDs per source
        ref_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'REF']
        sec_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'SEC']
        ter_ids = [t['id'] for t in ctx.manual_layout if t.get('source', '').upper() == 'TER']

        runner._log_message(f"Manual selection: preparing to extract {len(ref_ids)} REF, {len(sec_ids)} SEC, {len(ter_ids)} TER tracks.")

        # Perform extraction; mkv_utils.extract_tracks returns info including path, codec_id, lang, name, type, id
        ref_tracks_ext = mkv_utils.extract_tracks(ctx.ref_file, ctx.temp_dir, runner, ctx.tool_paths, 'ref', specific_tracks=ref_ids)
        sec_tracks_ext = mkv_utils.extract_tracks(ctx.sec_file, ctx.temp_dir, runner, ctx.tool_paths, 'sec', specific_tracks=sec_ids) if (ctx.sec_file and sec_ids) else []
        ter_tracks_ext = mkv_utils.extract_tracks(ctx.ter_file, ctx.temp_dir, runner, ctx.tool_paths, 'ter', specific_tracks=ter_ids) if (ctx.ter_file and ter_ids) else []

        extracted_map: Dict[str, Dict[str, Any]] = {f"{t['source'].upper()}_{t['id']}": t for t in (ref_tracks_ext + sec_tracks_ext + ter_tracks_ext)}

        # Translate manual_layout (+ rules) to typed PlanItem list using extracted paths
        items: List[PlanItem] = []
        for sel in ctx.manual_layout:
            key = f"{sel.get('source','').upper()}_{sel['id']}"
            trk = extracted_map.get(key)
            if not trk:
                runner._log_message(f"[WARNING] Could not find extracted file for {key}. Skipping.")
                continue

            # Build Track model
            try:
                src_role = SourceRole[trk.get('source', 'REF').upper()]
            except Exception:
                src_role = SourceRole.REF
            try:
                ttype = TrackType(trk.get('type', 'video'))
            except Exception:
                ttype = TrackType.VIDEO

            track_model = Track(
                source=src_role,
                id=int(trk['id']),
                type=ttype,
                props=StreamProps(
                    codec_id=trk.get('codec_id', '') or '',
                    lang=trk.get('lang', 'und') or 'und',
                    name=trk.get('name', '') or ''
                )
            )

            items.append(
                PlanItem(
                    track=track_model,
                    extracted_path=Path(trk['path']),
                    is_default=bool(sel.get('is_default', False)),
                    is_forced_display=bool(sel.get('is_forced_display', False)),
                    apply_track_name=bool(sel.get('apply_track_name', True)),
                    convert_to_ass=bool(sel.get('convert_to_ass', False)),
                    rescale=bool(sel.get('rescale', False)),
                    size_multiplier=float(sel.get('size_multiplier', 1.0))
                )
            )

        ctx.extracted_items = items
        return ctx


class SubtitlesStep:
    """
    Applies optional subtitle transforms:
      - Convert SRT to ASS
      - Rescale ASS/SSA PlayResX/Y to match reference video resolution
      - Multiply font size in ASS/SSA styles
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.extracted_items:
            return ctx

        for i, item in enumerate(ctx.extracted_items):
            if item.track.type != TrackType.SUBTITLES:
                continue

            # Convert SRT -> ASS if requested
            if item.convert_to_ass:
                new_path = subtitle_utils.convert_srt_to_ass(str(item.extracted_path), runner, ctx.tool_paths)
                item.extracted_path = Path(new_path)

            # Rescale PlayResX/Y to match video resolution if requested
            if item.rescale:
                subtitle_utils.rescale_subtitle(str(item.extracted_path), ctx.ref_file, runner, ctx.tool_paths)

            # Multiply style font size if requested and multiplier != 1.0
            try:
                if abs(float(item.size_multiplier) - 1.0) > 1e-6:
                    subtitle_utils.multiply_font_size(str(item.extracted_path), float(item.size_multiplier), runner)
            except Exception:
                # Non-fatal; already logged inside helper when it fails
                pass

        return ctx


class ChaptersStep:
    """
    Extracts/renames/snaps/shifts chapter XML from the reference and writes a modified XML,
    honoring settings (rename_chapters, snap_chapters, threshold, etc.) and global shift.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge:
            ctx.chapters_xml = None
            return ctx

        shift_ms = ctx.delays.global_shift_ms if ctx.delays else 0
        xml_path = mkv_utils.process_chapters(
            ctx.ref_file,
            ctx.temp_dir,
            runner,
            ctx.tool_paths,
            ctx.settings_dict,
            shift_ms
        )
        ctx.chapters_xml = xml_path
        return ctx


class AttachmentsStep:
    """
    Extracts attachments from TER only (mirrors original behavior).
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        files: List[str] = []
        if ctx.and_merge and ctx.ter_file:
            files = mkv_utils.extract_attachments(ctx.ter_file, ctx.temp_dir, runner, ctx.tool_paths, 'ter') or []
        ctx.attachments = files
        return ctx


class MuxStep:
    """
    Builds mkvmerge tokens and stores them on the context (surgical tweak).
    The final @opts execution remains the caller’s (pipeline) responsibility.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        # Decide output target (unchanged: same basename as REF inside output_dir)
        out_path = Path(ctx.output_dir) / Path(ctx.ref_file).name

        # Ensure we have a Delays object
        delays = ctx.delays or Delays(
            secondary_ms=0,
            tertiary_ms=0,
            global_shift_ms=0
        )

        # Build the plan from what previous steps produced
        plan = MergePlan(
            items=ctx.extracted_items or [],
            delays=delays,
            chapters_xml=Path(ctx.chapters_xml) if ctx.chapters_xml else None,
            attachments=[Path(a) for a in (ctx.attachments or [])]
        )

        # Delegate token construction to the builder (stable behavior)
        builder = MkvmergeOptionsBuilder()
        tokens = builder.build(plan, ctx.settings, out_path)

        # Store for the caller (pipeline) to write @opts and invoke mkvmerge
        ctx.out_file = str(out_path)
        ctx.tokens = tokens
        return ctx
