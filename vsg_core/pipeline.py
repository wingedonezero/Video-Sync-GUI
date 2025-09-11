# vsg_core/pipeline.py
# -*- coding: utf-8 -*-
import json
import shutil
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from .io.runner import CommandRunner
from .orchestrator.pipeline import Orchestrator

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

    def run_job(
        self,
        sources: Dict[str, str],
        and_merge: bool,
        output_dir_str: str,
        manual_layout: Optional[List[Dict]] = None,
        attachment_sources: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        source1_file = sources.get("Source 1")
        if not source1_file:
            raise ValueError("Job is missing Source 1 (Reference).")

        output_dir = Path(output_dir_str)
        output_dir.mkdir(parents=True, exist_ok=True)

        log_path = output_dir / f"{Path(source1_file).stem}.log"
        logger = logging.getLogger(f'job_{Path(source1_file).stem}')
        logger.setLevel(logging.INFO)
        for handler in logger.handlers[:]: logger.removeHandler(handler)
        handler = logging.FileHandler(log_path, mode='w', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        logger.propagate = False

        def log_to_all(message: str):
            logger.info(message.strip())
            self.gui_log_callback(message)

        runner = CommandRunner(self.config, log_to_all)

        try:
            self._find_required_tools()
        except FileNotFoundError as e:
            log_to_all(f'[ERROR] {e}')
            return {'status': 'Failed', 'error': str(e), 'name': Path(source1_file).name}

        log_to_all(f'=== Starting Job: {Path(source1_file).name} ===')
        self.progress(0.0)

        if and_merge and manual_layout is None:
            err_msg = 'Manual layout required for merge.'
            log_to_all(f'[ERROR] {err_msg}')
            return {'status': 'Failed', 'error': err_msg, 'name': Path(source1_file).name}

        job_temp = Path(self.config['temp_root']) / f'job_{Path(source1_file).stem}_{int(time.time())}'
        job_temp.mkdir(parents=True, exist_ok=True)

        ctx_temp_dir: Optional[Path] = None
        try:
            orch = Orchestrator()
            ctx = orch.run(
                settings_dict=self.config, tool_paths=self.tool_paths, log=log_to_all, progress=self.progress,
                sources=sources, and_merge=and_merge,
                output_dir=str(output_dir),
                manual_layout=manual_layout or [],
                attachment_sources=attachment_sources or []
            )
            ctx_temp_dir = getattr(ctx, 'temp_dir', None)

            if not and_merge:
                log_to_all('--- Analysis Complete (No Merge) ---')
                self.progress(1.0)
                return {
                    'status': 'Analyzed',
                    'delays': ctx.delays.source_delays_ms if ctx.delays else {},
                    'name': Path(source1_file).name
                }

            self.progress(0.8)
            if not ctx.tokens:
                raise RuntimeError('Internal error: mkvmerge tokens were not generated.')

            opts_path = self._write_mkvmerge_opts(ctx.tokens, job_temp, runner)
            merge_ok = runner.run(['mkvmerge', f'@{opts_path}'], self.tool_paths) is not None
            if not merge_ok:
                raise RuntimeError('mkvmerge execution failed.')

            out_file = ctx.out_file or (Path(output_dir) / Path(source1_file).name)
            log_to_all(f'[SUCCESS] Output file created: {out_file}')
            self.progress(1.0)
            return {
                'status': 'Merged', 'output': str(out_file),
                'delays': ctx.delays.source_delays_ms if ctx.delays else {},
                'name': Path(source1_file).name
            }

        except Exception as e:
            log_to_all(f'[FATAL ERROR] Job failed: {e}')
            return {'status': 'Failed', 'error': str(e), 'name': Path(source1_file).name}
        finally:
            if ctx_temp_dir and ctx_temp_dir.exists():
                shutil.rmtree(ctx_temp_dir, ignore_errors=True)
            shutil.rmtree(job_temp, ignore_errors=True)
            log_to_all('=== Job Finished ===')
            handler.close()
            logger.removeHandler(handler)

    def _write_mkvmerge_opts(self, tokens, temp_dir: Path, runner: CommandRunner) -> str:
        opts_path = temp_dir / 'opts.json'
        try:
            opts_path.write_text(json.dumps(tokens, ensure_ascii=False), encoding='utf-8')
            runner._log_message(f'mkvmerge options file written to: {opts_path}')
            if self.config.get('log_show_options_json'):
                runner._log_message('--- mkvmerge options (json) ---\n' + json.dumps(tokens, indent=2, ensure_ascii=False) + '\n-------------------------------')
            if self.config.get('log_show_options_pretty'):
                pretty_path = temp_dir / 'opts.pretty.txt'
                pretty_path.write_text(' \\\n  '.join(tokens), encoding='utf-8')
                runner._log_message(f'--- mkvmerge options (pretty) ---\n{pretty_path.read_text()}\n-------------------------------')
            return str(opts_path)
        except Exception as e:
            raise IOError(f"Failed to write mkvmerge options file: {e}")
