# vsg_core/pipeline.py

# -*- coding: utf-8 -*-
import json
import shutil
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional
from . import analysis, mkv_utils, subtitle_utils
from .process import CommandRunner

class JobPipeline:
    def __init__(self, config: dict, log_callback: Callable[[str], None], progress_callback: Callable[[float], None]):
        self.config = config
        self.gui_log_callback = log_callback
        self.progress = progress_callback
        self.tool_paths = {}

    def _find_required_tools(self):
        for tool in ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract']:
            self.tool_paths[tool] = shutil.which(tool)
            if not self.tool_paths[tool]:
                raise FileNotFoundError(f"Required tool '{tool}' not found in PATH.")
        self.tool_paths['videodiff'] = shutil.which('videodiff')

    def run_job(self, ref_file: str, sec_file: Optional[str], ter_file: Optional[str],
                and_merge: bool, output_dir_str: str, manual_layout: Optional[List[Dict]] = None) -> Dict[str, Any]:

        output_dir = Path(output_dir_str)
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
            return {'status': 'Failed', 'error': str(e), 'name': Path(ref_file).name}

        log_to_all(f'=== Starting Job: {Path(ref_file).name} ===')
        self.progress(0.0)

        # Manual-only guardrail: merging requires a manual layout
        if and_merge and manual_layout is None:
            log_to_all('[ERROR] Manual layout required for merge (Manual Selection is the only merge method).')
            return {'status': 'Failed', 'error': 'Manual layout required for merge', 'name': Path(ref_file).name}

        job_temp = Path(self.config['temp_root']) / f'job_{Path(ref_file).stem}_{int(time.time())}'
        job_temp.mkdir(parents=True, exist_ok=True)

        merge_ok = False
        try:
            log_to_all('--- Analysis Phase ---')
            delay_sec, delay_ter = self._run_analysis(ref_file, sec_file, ter_file, runner)

            if not and_merge:
                log_to_all('--- Analysis Complete (No Merge) ---')
                self.progress(1.0)
                return {'status': 'Analyzed', 'delay_sec': delay_sec, 'delay_ter': delay_ter, 'name': Path(ref_file).name}

            log_to_all('--- Merge Planning Phase ---')
            self.progress(0.25)

            delays = {'secondary_ms': delay_sec or 0, 'tertiary_ms': delay_ter or 0}
            present_delays = [0]
            if delay_sec is not None:
                present_delays.append(delay_sec)
            if delay_ter is not None:
                present_delays.append(delay_ter)
            min_delay = min(present_delays)
            global_shift = -min_delay if min_delay < 0 else 0
            delays['_global_shift'] = global_shift

            log_to_all(f'[Delay] Raw delays (ms): ref=0, sec={delays["secondary_ms"]}, ter={delays["tertiary_ms"]}')
            log_to_all(f'[Delay] Applying lossless global shift: +{global_shift} ms')

            log_to_all('--- Extraction Phase ---')
            self.progress(0.4)

            # Manual layout is required and provided at this point
            ref_ids = [t['id'] for t in manual_layout if t['source'] == 'REF']
            sec_ids = [t['id'] for t in manual_layout if t['source'] == 'SEC']
            ter_ids = [t['id'] for t in manual_layout if t['source'] == 'TER']
            log_to_all(f"Manual selection: preparing to extract {len(ref_ids)} REF, {len(sec_ids)} SEC, {len(ter_ids)} TER tracks.")

            ref_tracks_ext = mkv_utils.extract_tracks(ref_file, job_temp, runner, self.tool_paths, 'ref', specific_tracks=ref_ids)
            sec_tracks_ext = mkv_utils.extract_tracks(sec_file, job_temp, runner, self.tool_paths, 'sec', specific_tracks=sec_ids) if sec_file and sec_ids else []
            ter_tracks_ext = mkv_utils.extract_tracks(ter_file, job_temp, runner, self.tool_paths, 'ter', specific_tracks=ter_ids) if ter_file and ter_ids else []
            all_extracted_tracks = ref_tracks_ext + sec_tracks_ext + ter_tracks_ext
            extracted_map = {f"{t['source']}_{t['id']}": t for t in all_extracted_tracks}
            plan = self._build_plan_from_manual_layout(manual_layout, delays, extracted_map, log_to_all)

            log_to_all('--- Subtitle Processing Phase ---')
            for item in plan.get('plan', []):
                track = item['track']
                rule = item['rule']
                if track.get('type') == 'subtitles':
                    if rule.get('convert_to_ass'):
                        new_path = subtitle_utils.convert_srt_to_ass(track['path'], runner, self.tool_paths)
                        track['path'] = new_path
                    if rule.get('rescale'):
                        subtitle_utils.rescale_subtitle(track['path'], ref_file, runner, self.tool_paths)
                    size_multiplier = rule.get('size_multiplier', 1.0)
                    if size_multiplier != 1.0:
                        subtitle_utils.multiply_font_size(track['path'], size_multiplier, runner)

            ter_attachments = mkv_utils.extract_attachments(ter_file, job_temp, runner, self.tool_paths, 'ter') if ter_file else []
            chapters_xml = mkv_utils.process_chapters(ref_file, job_temp, runner, self.tool_paths, self.config, global_shift)

            log_to_all('--- Merge Execution Phase ---')
            self.progress(0.6)

            out_file = output_dir / Path(ref_file).name
            tokens = self._build_mkvmerge_tokens(plan, str(out_file), chapters_xml, ter_attachments)
            opts_path = self._write_mkvmerge_opts(tokens, job_temp, runner)
            self.progress(0.8)

            merge_ok = runner.run(['mkvmerge', f'@{opts_path}'], self.tool_paths) is not None
            if not merge_ok:
                raise RuntimeError('mkvmerge execution failed.')

            log_to_all(f'[SUCCESS] Output file created: {out_file}')
            self.progress(1.0)
            return {'status': 'Merged', 'output': str(out_file), 'delay_sec': delay_sec, 'delay_ter': delay_ter, 'name': Path(ref_file).name}

        except Exception as e:
            log_to_all(f'[FATAL ERROR] Job failed: {e}')
            return {'status': 'Failed', 'error': str(e), 'name': Path(ref_file).name}
        finally:
            if not and_merge or merge_ok:
                shutil.rmtree(job_temp, ignore_errors=True)
            log_to_all('=== Job Finished ===')
            handler.close()
            logger.removeHandler(handler)

    def _build_plan_from_manual_layout(self, manual_layout: List[Dict], delays: Dict, extracted_map: Dict, log_callback: Callable) -> Dict:
        log_callback(f"--- Building merge plan from {len(manual_layout)} manual selections ---")
        final_plan = []
        for selected_track in manual_layout:
            lookup_key = f"{selected_track['source']}_{selected_track['id']}"
            extracted_track_data = extracted_map.get(lookup_key)
            if not extracted_track_data:
                log_callback(f"[WARNING] Could not find extracted file for {lookup_key}. Skipping.")
                continue
            rule = {
                'is_default': selected_track.get('is_default', False),
                'is_forced_display': selected_track.get('is_forced_display', False),
                'apply_track_name': selected_track.get('apply_track_name', True),
                'convert_to_ass': selected_track.get('convert_to_ass', False),
                'rescale': selected_track.get('rescale', False),
                'size_multiplier': selected_track.get('size_multiplier', 1.0)
            }
            final_plan.append({'track': extracted_track_data, 'rule': rule})
        return {'plan': final_plan, 'delays': delays}

    def _run_analysis(self, ref_file, sec_file, ter_file, runner):
        delay_sec, delay_ter = None, None
        mode = self.config.get('analysis_mode', 'Audio Correlation')
        ref_lang = self.config.get('analysis_lang_ref') or None
        sec_lang = self.config.get('analysis_lang_sec') or None
        ter_lang = self.config.get('analysis_lang_ter') or None

        if sec_file:
            runner._log_message(f'Analyzing Secondary file ({mode})...')
            if mode == 'VideoDiff':
                delay_sec, err = analysis.run_videodiff(ref_file, sec_file, self.config, runner, self.tool_paths)
                if not (self.config['videodiff_error_min'] <= err <= self.config['videodiff_error_max']):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
            else:
                results = analysis.run_audio_correlation(
                    ref_file, sec_file, Path(self.config['temp_root']), self.config,
                    runner, self.tool_paths, ref_lang=ref_lang, target_lang=sec_lang, role_tag='sec'
                )
                best = self._best_from_results(results)
                if not best:
                    raise RuntimeError('Audio analysis for Secondary yielded no valid result.')
                delay_sec = best['delay']
            runner._log_message(f'Secondary delay determined: {delay_sec} ms')

        if ter_file:
            runner._log_message(f'Analyzing Tertiary file ({mode})...')
            if mode == 'VideoDiff':
                delay_ter, err = analysis.run_videodiff(ref_file, ter_file, self.config, runner, self.tool_paths)
                if not (self.config['videodiff_error_min'] <= err <= self.config['videodiff_error_max']):
                    raise RuntimeError(f"VideoDiff error ({err:.2f}) out of bounds.")
            else:
                results = analysis.run_audio_correlation(
                    ref_file, ter_file, Path(self.config['temp_root']), self.config,
                    runner, self.tool_paths, ref_lang=ref_lang, target_lang=ter_lang, role_tag='ter'
                )
                best = self._best_from_results(results)
                if not best:
                    raise RuntimeError('Audio analysis for Tertiary yielded no valid result.')
                delay_ter = best['delay']
            runner._log_message(f'Tertiary delay determined: {delay_ter} ms')

        return delay_sec, delay_ter

    def _best_from_results(self, results: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not results:
            return None
        min_pct = self.config.get('min_match_pct', 5.0)
        valid = [r for r in results if r['match'] > min_pct]
        if not valid:
            return None
        from collections import Counter
        counts = Counter(r['delay'] for r in valid)
        max_freq = counts.most_common(1)[0][1]
        contenders = [d for d, f in counts.items() if f == max_freq]
        best_of_each_contender = [max((r for r in valid if r['delay'] == d), key=lambda x: x['match']) for d in contenders]
        return max(best_of_each_contender, key=lambda x: x['match'])

    def _build_mkvmerge_tokens(self, plan_data: Dict, output_file: str, chapters_xml: Optional[str], attachments: List[str]) -> List[str]:
        # Harmless log-only guardrails
        plan_items = plan_data['plan']
        video_items = [it for it in plan_items if it['track'].get('type') == 'video']
        if video_items:
            if not any(it['track'].get('source', 'REF').upper() == 'REF' for it in video_items):
                self.gui_log_callback("[WARN] No REF video present in final plan. If this was intended (audio-only), ignore this warning.")
            if any(it['track'].get('source', 'REF').upper() != 'REF' for it in video_items):
                self.gui_log_callback("[WARN] Non-REF video detected in final plan (SEC/TER). The UI should prevent this; proceeding anyway.")

        tokens = ['--output', output_file]
        if chapters_xml:
            tokens.extend(['--chapters', chapters_xml])
        if self.config.get('disable_track_statistics_tags', False):
            tokens.append('--disable-track-statistics-tags')

        delays = plan_data['delays']
        global_shift = delays.get('_global_shift', 0)

        # Determine default/forced indices
        default_audio_track_id, default_sub_track_id, forced_display_sub_id = -1, -1, -1
        for i, item in enumerate(plan_items):
            if item['rule'].get('is_default'):
                if item['track']['type'] == 'audio' and default_audio_track_id == -1:
                    default_audio_track_id = i
                elif item['track']['type'] == 'subtitles' and default_sub_track_id == -1:
                    default_sub_track_id = i
            if item['rule'].get('is_forced_display') and item['track']['type'] == 'subtitles' and forced_display_sub_id == -1:
                forced_display_sub_id = i

        first_video_idx = next((i for i, item in enumerate(plan_items) if item['track'].get('type') == 'video'), -1)
        track_order_indices = []

        for i, item in enumerate(plan_items):
            track = item['track']
            rule = item['rule']
            source_path = track.get('path')
            if not source_path:
                raise KeyError(f"Track dictionary at index {i} is missing the 'path' key after planning phase.")
            role = track.get('source', 'REF').lower()
            delay = global_shift
            if role == 'sec':
                delay += delays.get('secondary_ms', 0)
            elif role == 'ter':
                delay += delays.get('tertiary_ms', 0)

            is_default = (i == first_video_idx) or (i == default_audio_track_id) or (i == default_sub_track_id)

            tokens.extend(['--language', f"0:{track.get('lang', 'und')}"])
            if rule.get('apply_track_name', False) and track.get('name'):
                tokens.extend(['--track-name', f"0:{track.get('name', '')}"])
            tokens.extend(['--sync', f'0:{delay}'])
            tokens.extend(['--default-track-flag', f"0:{'yes' if is_default else 'no'}"])
            if i == forced_display_sub_id:
                tokens.extend(['--forced-display-flag', '0:yes'])
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
