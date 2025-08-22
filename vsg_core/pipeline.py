# -*- coding: utf-8 -*-

"""
The main processing pipeline that orchestrates the analysis and merge workflow.
"""

import json
import shutil
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from . import analysis, mkv_utils
from .process import CommandRunner

class JobPipeline:
    """Orchestrates a single analysis or merge job from start to finish."""

    def __init__(self, config: dict, log_callback: Callable[[str], None], progress_callback: Callable[[float], None]):
        self.config = config
        self.gui_log_callback = log_callback
        self.progress = progress_callback
        self.tool_paths = {}

    def _find_required_tools(self):
        """Ensures all required command-line tools are found in the system PATH."""
        for tool in ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract']:
            self.tool_paths[tool] = shutil.which(tool)
            if not self.tool_paths[tool]:
                raise FileNotFoundError(f"Required tool '{tool}' not found in PATH.")

        self.tool_paths['videodiff'] = shutil.which('videodiff')

    def run_job(self, ref_file: str, sec_file: Optional[str], ter_file: Optional[str], and_merge: bool) -> Dict[str, Any]:
        """
        Executes the full analysis and optional merge pipeline.
        """
        output_dir = Path(self.config['output_folder'])
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / f"{Path(ref_file).stem}.log"

        logger = logging.getLogger(f'job_{Path(ref_file).stem}')
        logger.setLevel(logging.INFO)
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)

        def log_to_all(message: str):
            logger.info(message.strip())
            self.gui_log_callback(message)

        runner = CommandRunner(self.config, log_to_all)

        try:
            self._find_required_tools()
        except FileNotFoundError as e:
            log_to_all(f'[ERROR] {e}')
            return {'status': 'Failed', 'error': str(e)}

        log_to_all(f'=== Starting Job: {Path(ref_file).name} ===')
        self.progress(0.0)

        job_temp = Path(self.config['temp_root']) / f'job_{Path(ref_file).stem}_{int(time.time())}'
        job_temp.mkdir(parents=True, exist_ok=True)

        merge_ok = False
        try:
            log_to_all('--- Analysis Phase ---')
            delay_sec, delay_ter = self._run_analysis(ref_file, sec_file, ter_file, runner)

            if not and_merge:
                log_to_all('--- Analysis Complete (No Merge) ---')
                self.progress(1.0)
                return {'status': 'Analyzed', 'delay_sec': delay_sec, 'delay_ter': delay_ter}

            log_to_all('--- Merge Planning Phase ---')
            self.progress(0.25)

            delays = {'secondary_ms': delay_sec or 0, 'tertiary_ms': delay_ter or 0}

            present_delays = [0]
            if delay_sec is not None: present_delays.append(delay_sec)
            if delay_ter is not None: present_delays.append(delay_ter)
            min_delay = min(present_delays)
            global_shift = -min_delay if min_delay < 0 else 0
            delays['_global_shift'] = global_shift

            log_to_all(f'[Delay] Raw delays (ms): ref=0, sec={delays["secondary_ms"]}, ter={delays["tertiary_ms"]}')
            log_to_all(f'[Delay] Applying lossless global shift: +{global_shift} ms')

            log_to_all('--- Extraction Phase ---')
            self.progress(0.4)

            ref_tracks = mkv_utils.extract_tracks(ref_file, job_temp, runner, self.tool_paths, 'ref', all_tracks=True)
            sec_tracks = mkv_utils.extract_tracks(sec_file, job_temp, runner, self.tool_paths, 'sec', audio=True, subs=True) if sec_file else []
            ter_tracks = mkv_utils.extract_tracks(ter_file, job_temp, runner, self.tool_paths, 'ter', audio=False, subs=True) if ter_file else []
            ter_attachments = mkv_utils.extract_attachments(ter_file, job_temp, runner, self.tool_paths, 'ter') if ter_file else []

            # *** FIX: Implement subtitle swap logic ***
            if self.config.get('swap_subtitle_order', False) and sec_tracks:
                subs_in_sec = [t for t in sec_tracks if t['type'] == 'subtitles']
                if len(subs_in_sec) >= 2:
                    log_to_all('[Info] Swapping first two Secondary subtitle tracks.')
                    t1_original_index = sec_tracks.index(subs_in_sec[0])
                    t2_original_index = sec_tracks.index(subs_in_sec[1])
                    sec_tracks[t1_original_index], sec_tracks[t2_original_index] = sec_tracks[t2_original_index], sec_tracks[t1_original_index]

            chapters_xml = mkv_utils.process_chapters(ref_file, job_temp, runner, self.tool_paths, self.config, global_shift)

            log_to_all('--- Merge Execution Phase ---')
            self.progress(0.6)

            plan = self._build_plan(ref_tracks, sec_tracks, ter_tracks, delays)
            out_file = output_dir / Path(ref_file).name

            tokens = self._build_mkvmerge_tokens(plan, str(out_file), chapters_xml, ter_attachments)
            opts_path = self._write_mkvmerge_opts(tokens, job_temp, runner)

            self.progress(0.8)
            merge_ok = runner.run(['mkvmerge', f'@{opts_path}'], self.tool_paths) is not None

            if not merge_ok:
                raise RuntimeError('mkvmerge execution failed.')

            log_to_all(f'[SUCCESS] Output file created: {out_file}')
            self.progress(1.0)
            return {'status': 'Merged', 'output': str(out_file), 'delay_sec': delay_sec, 'delay_ter': delay_ter}

        except Exception as e:
            log_to_all(f'[FATAL ERROR] Job failed: {e}')
            return {'status': 'Failed', 'error': str(e)}
        finally:
            if not and_merge or merge_ok:
                 shutil.rmtree(job_temp, ignore_errors=True)
            log_to_all('=== Job Finished ===')
            handler.close()
            logger.removeHandler(handler)

    def _run_analysis(self, ref_file, sec_file, ter_file, runner):
        delay_sec, delay_ter = None, None
        mode = self.config.get('analysis_mode', 'Audio Correlation')

        if sec_file:
            runner._log_message(f'Analyzing Secondary file ({mode})...')
            if mode == 'VideoDiff':
                delay_sec, err = analysis.run_videodiff(ref_file, sec_file, self.config, runner, self.tool_paths)
                if not (self.config['videodiff_error_min'] <= err <= self.config['videodiff_error_max']):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
            else:
                lang = 'jpn' if self.config.get('match_jpn_secondary') else None
                results = analysis.run_audio_correlation(ref_file, sec_file, Path(self.config['temp_root']), self.config, runner, self.tool_paths, lang, 'sec')
                best = self._best_from_results(results)
                if not best: raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
                delay_sec = best['delay']
            runner._log_message(f'Secondary delay determined: {delay_sec} ms')

        if ter_file:
            runner._log_message(f'Analyzing Tertiary file ({mode})...')
            if mode == 'VideoDiff':
                 delay_ter, err = analysis.run_videodiff(ref_file, ter_file, self.config, runner, self.tool_paths)
                 if not (self.config['videodiff_error_min'] <= err <= self.config['videodiff_error_max']):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
            else:
                lang = 'jpn' if self.config.get('match_jpn_tertiary') else None
                results = analysis.run_audio_correlation(ref_file, ter_file, Path(self.config['temp_root']), self.config, runner, self.tool_paths, lang, 'ter')
                best = self._best_from_results(results)
                if not best: raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
                delay_ter = best['delay']
            runner._log_message(f'Tertiary delay determined: {delay_ter} ms')

        return delay_sec, delay_ter

    def _best_from_results(self, results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not results: return None
        min_pct = self.config.get('min_match_pct', 5.0)
        valid = [r for r in results if r['match'] > min_pct]
        if not valid: return None

        from collections import Counter
        counts = Counter(r['delay'] for r in valid)
        max_freq = counts.most_common(1)[0][1]

        contenders = [d for d, f in counts.items() if f == max_freq]
        best_of_each_contender = [max((r for r in valid if r['delay'] == d), key=lambda x: x['match']) for d in contenders]

        return max(best_of_each_contender, key=lambda x: x['match'])

    def _build_plan(self, ref_tracks, sec_tracks, ter_tracks, delays):
        plan = []
        plan.extend(t for t in ref_tracks if t['type'] == 'video')
        plan.extend(t for t in sec_tracks if t['type'] == 'audio')
        plan.extend(t for t in ref_tracks if t['type'] == 'audio')
        plan.extend(t for t in ter_tracks if t['type'] == 'subtitles')
        plan.extend(t for t in sec_tracks if t['type'] == 'subtitles')
        plan.extend(t for t in ref_tracks if t['type'] not in ('video', 'audio'))
        return {'plan': plan, 'delays': delays}

    def _build_mkvmerge_tokens(self, plan_data, output_file, chapters_xml, attachments):
        tokens = ['--output', output_file]
        if chapters_xml:
            tokens.extend(['--chapters', chapters_xml])

        plan = plan_data['plan']
        delays = plan_data['delays']
        global_shift = delays.get('_global_shift', 0)

        video_indices = [i for i, t in enumerate(plan) if t.get('type') == 'video']
        audio_indices = [i for i, t in enumerate(plan) if t.get('type') == 'audio']
        sub_indices = [i for i, t in enumerate(plan) if t.get('type') == 'subtitles']

        first_video_idx = video_indices[0] if video_indices else -1
        first_audio_idx = audio_indices[0] if audio_indices else -1
        default_sub_idx = -1

        if self.config.get('first_sub_default', True) and sub_indices:
            signs_keys = ('sign', 'signs', 'song', 'songs', 'ops', 'eds', 'karaoke', 'titles')
            for i in sub_indices:
                if any(k in (plan[i].get('name') or '').lower() for k in signs_keys):
                    default_sub_idx = i
                    break
            if default_sub_idx == -1:
                default_sub_idx = sub_indices[0]

        track_order_indices = []
        for i, track in enumerate(plan):
            source_path = track.get('path')
            if not source_path:
                raise KeyError(f"Track dictionary at index {i} is missing the 'path' key.")

            role = 'ref'
            if 'sec_track' in Path(source_path).name: role = 'sec'
            elif 'ter_track' in Path(source_path).name: role = 'ter'

            delay = global_shift
            if role == 'sec': delay += delays.get('secondary_ms', 0)
            elif role == 'ter': delay += delays.get('tertiary_ms', 0)

            is_default = (i == first_video_idx) or (i == first_audio_idx) or (i == default_sub_idx)

            tokens.extend(['--language', f"0:{track.get('lang', 'und')}"])
            tokens.extend(['--track-name', f"0:{track.get('name', '')}"])
            tokens.extend(['--sync', f'0:{delay}'])
            tokens.extend(['--default-track-flag', f"0:{'yes' if is_default else 'no'}"])
            tokens.extend(['--compression', '0:none'])

            if self.config.get('apply_dialog_norm_gain') and track['type'] == 'audio':
                 codec = (track.get('codec_id') or '').upper()
                 if 'AC3' in codec or 'EAC3' in codec:
                     tokens.extend(['--remove-dialog-normalization-gain', '0'])

            tokens.extend(['(', str(source_path), ')'])
            track_order_indices.append(f'{i}:0')

        for a in attachments or []:
            tokens.extend(['--attach-file', str(a)])

        if track_order_indices:
            tokens.extend(['--track-order', ','.join(track_order_indices)])

        return tokens

    def _write_mkvmerge_opts(self, tokens, temp_dir, runner):
        opts_path = temp_dir / 'opts.json'
        try:
            opts_path.write_text(json.dumps(tokens, ensure_ascii=False), encoding='utf-8')
            runner._log_message(f'mkvmerge options file written to: {opts_path}')

            if self.config.get('log_show_options_pretty'):
                pretty_path = temp_dir / 'opts.pretty.txt'
                pretty_path.write_text(' \\\n  '.join(tokens), encoding='utf-8')
                runner._log_message(f'--- mkvmerge options (pretty) ---\n{pretty_path.read_text()}\n-------------------------------')

            return str(opts_path)
        except Exception as e:
            raise IOError(f"Failed to write mkvmerge options file: {e}")
