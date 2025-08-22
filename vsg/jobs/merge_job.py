"""Moved implementations for jobs.merge_job (full-move RC)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from vsg.logbus import _log
from vsg.settings import CONFIG
from vsg.analysis.audio_xcorr import run_audio_correlation_workflow, best_from_results
from vsg.analysis.videodiff import run_videodiff


# Hook: chapters


def merge_job(ref_file: str, sec_file: Optional[str], ter_file: Optional[str], out_dir: str, logger,
              videodiff_path: Path):
    Path(CONFIG['temp_root']).mkdir(parents=True, exist_ok=True)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    delays = {'secondary_ms': 0, 'tertiary_ms': 0}
    set_status('Analyzing…')
    set_progress(0.0)
    delay_sec = None
    delay_ter = None
    if sec_file:
        if CONFIG['analysis_mode'] == 'VideoDiff':
            delay_sec, err_sec = run_videodiff(ref_file, sec_file, logger, videodiff_path)
            if err_sec < float(CONFIG.get('videodiff_error_min', 0.0)) or err_sec > float(
                    CONFIG.get('videodiff_error_max', 100.0)):
                raise RuntimeError(
                    f"VideoDiff confidence out of bounds: error={err_sec:.2f} (allowed {CONFIG.get('videodiff_error_min')}..{CONFIG.get('videodiff_error_max')})")
        else:
            lang = 'jpn' if CONFIG['match_jpn_secondary'] else None
            results = run_audio_correlation_workflow(ref_file, sec_file, logger, CONFIG['scan_chunk_count'],
                                                     CONFIG['scan_chunk_duration'], lang, role_tag='sec')
            best = best_from_results(results, CONFIG['min_match_pct'])
            if not best:
                raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
            delay_sec = best['delay']
        _log(logger, f'Secondary delay: {delay_sec} ms')
    if ter_file:
        if CONFIG['analysis_mode'] == 'VideoDiff':
            delay_ter, err_ter = run_videodiff(ref_file, ter_file, logger, videodiff_path)
            if err_ter < float(CONFIG.get('videodiff_error_min', 0.0)) or err_ter > float(
                    CONFIG.get('videodiff_error_max', 100.0)):
                raise RuntimeError(
                    f"VideoDiff confidence out of bounds: error={err_ter:.2f} (allowed {CONFIG.get('videodiff_error_min')}..{CONFIG.get('videodiff_error_max')})")
        else:
            lang = 'jpn' if CONFIG['match_jpn_tertiary'] else None
            results = run_audio_correlation_workflow(ref_file, ter_file, logger, CONFIG['scan_chunk_count'],
                                                     CONFIG['scan_chunk_duration'], lang, role_tag='ter')
            best = best_from_results(results, CONFIG['min_match_pct'])
            if not best:
                raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
            delay_ter = best['delay']
        _log(logger, f'Tertiary delay: {delay_ter} ms')
    if CONFIG['workflow'] == 'Analyze Only':
        set_status('Analysis complete (no merge).')
        set_progress(1.0)
        return {'status': 'Analyzed', 'delay_sec': delay_sec, 'delay_ter': delay_ter}
    delays['secondary_ms'] = int(delay_sec or 0)
    delays['tertiary_ms'] = int(delay_ter or 0)
    present = [0]
    if sec_file is not None and delay_sec is not None:
        present.append(int(delay_sec))
    if ter_file is not None and delay_ter is not None:
        present.append(int(delay_ter))
    min_delay = min(present) if present else 0
    global_shift = -min_delay if min_delay < 0 else 0
    delays['_global_shift'] = int(global_shift)
    _log(logger, f'[Delay] Raw group delays (ms): ref=0, sec={int(delay_sec or 0)}, ter={int(delay_ter or 0)}')
    _log(logger, f'[Delay] Lossless global shift: +{int(global_shift)} ms')
    job_temp = Path(CONFIG['temp_root']) / f'job_{Path(ref_file).stem}_{int(time.time())}'
    job_temp.mkdir(parents=True, exist_ok=True)
    merge_ok = False
    try:
        set_status('Preparing merge…')
        set_progress(0.05)
        chapters_xml = None
        if CONFIG['rename_chapters']:
            chapters_xml = rename_chapters_xml(ref_file, str(job_temp), logger,
                                               shift_ms=int(delays.get('_global_shift', 0)))
        ref_tracks = extract_tracks(ref_file, str(job_temp), logger, role='ref', all_tracks=True)
        sec_tracks = extract_tracks(sec_file, str(job_temp), logger, role='sec', audio=True,
                                    subs=True) if sec_file else []
        ter_tracks = extract_tracks(ter_file, str(job_temp), logger, role='ter', audio=False,
                                    subs=True) if ter_file else []
        ter_atts = extract_attachments(ter_file, str(job_temp), logger, role='ter') if ter_file else []
        if CONFIG['swap_subtitle_order'] and sec_tracks:
            only_subs = [t for t in sec_tracks if t['type'] == 'subtitles']
            if len(only_subs) >= 2:
                i0, i1 = (sec_tracks.index(only_subs[0]), sec_tracks.index(only_subs[1]))
                sec_tracks[i0], sec_tracks[i1] = (sec_tracks[i1], sec_tracks[i0])
        if not sec_tracks and (not ter_tracks):
            raise RuntimeError('No tracks to merge from Secondary/Tertiary.')
        plan = build_plan(ref_tracks, sec_tracks, ter_tracks, delays)
        out_file = str(Path(out_dir) / Path(ref_file).name)
        track_order_str, summary_lines = summarize_plan(plan, out_file, chapters_xml, ter_atts)
        for ln in summary_lines:
            _log(logger, ln)
        tokens = build_mkvmerge_tokens(plan, out_file, chapters_xml, ter_atts, track_order_str=track_order_str)
        json_opts = write_mkvmerge_json_options(tokens, job_temp / 'opts.json', logger)
        set_status('Merging…')
        set_progress(0.5)
        merge_ok = run_mkvmerge_with_json(json_opts, logger)
        if not merge_ok:
            raise RuntimeError('mkvmerge failed.')
        set_status('Merge complete.')
        set_progress(1.0)
        _log(logger, f'[OK] Output: {out_file}')
        return {'status': 'Merged', 'output': out_file, 'delay_sec': delay_sec, 'delay_ter': delay_ter}
    finally:
        if merge_ok or CONFIG['workflow'] == 'Analyze Only':
            try:
                shutil.rmtree(job_temp, ignore_errors=True)
            except Exception:
                pass