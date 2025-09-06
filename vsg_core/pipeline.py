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
    """
    Lean pipeline that delegates all step logic to the orchestrator.
    Public API and return payloads remain unchanged.
    """

    def __init__(self, config: dict, log_callback: Callable[[str], None], progress_callback: Callable[[float], None]):
        self.config = config
        self.gui_log_callback = log_callback
        self.progress = progress_callback
        self.tool_paths = {}

    # --------------------------------------------------------------------------------------------
    # Tool discovery (unchanged behavior)
    # --------------------------------------------------------------------------------------------
    def _find_required_tools(self):
        for tool in ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract']:
            self.tool_paths[tool] = shutil.which(tool)
            if not self.tool_paths[tool]:
                raise FileNotFoundError(f"Required tool '{tool}' not found in PATH.")
        self.tool_paths['videodiff'] = shutil.which('videodiff')  # optional

    # --------------------------------------------------------------------------------------------
    # Public entry: identical return contract as before
    # --------------------------------------------------------------------------------------------
    def run_job(
        self,
        ref_file: str,
        sec_file: Optional[str],
        ter_file: Optional[str],
        and_merge: bool,
        output_dir_str: str,
        manual_layout: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:

        output_dir = Path(output_dir_str)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Per-job file logger (unchanged)
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

        # Guardrail: merges require manual layout (unchanged)
        if and_merge and manual_layout is None:
            log_to_all('[ERROR] Manual layout required for merge (Manual Selection is the only merge method).')
            return {'status': 'Failed', 'error': 'Manual layout required for merge', 'name': Path(ref_file).name}

        # Our own small temp just for @opts.json
        job_temp = Path(self.config['temp_root']) / f'job_{Path(ref_file).stem}_{int(time.time())}'
        job_temp.mkdir(parents=True, exist_ok=True)

        merge_ok = False
        ctx_temp_dir: Optional[Path] = None  # orchestrator temp to clean later
        try:
            log_to_all('--- Initializing Job ---')
            self.progress(0.0)

            # Delegate to orchestrator: analysis (+ extraction/subs/chapters/attachments/tokens if merging)
            orch = Orchestrator()
            ctx = orch.run(
                settings_dict=self.config,
                tool_paths=self.tool_paths,
                log=log_to_all,
                progress=self.progress,
                ref_file=ref_file,
                sec_file=sec_file,
                ter_file=ter_file,
                and_merge=and_merge,
                output_dir=str(output_dir),
                manual_layout=manual_layout or []
            )

            # Keep a handle to orchestrator temp so we can clean it AFTER mkvmerge
            try:
                ctx_temp_dir = Path(getattr(ctx, 'temp_dir', None)) if getattr(ctx, 'temp_dir', None) else None
            except Exception:
                ctx_temp_dir = None

            # Analyze-only: return delays (unchanged)
            if not and_merge:
                log_to_all('--- Analysis Complete (No Merge) ---')
                self.progress(1.0)
                return {
                    'status': 'Analyzed',
                    'delay_sec': ctx.delay_sec_val,
                    'delay_ter': ctx.delay_ter_val,
                    'name': Path(ref_file).name
                }

            # Merge: tokens were already built by MuxStep in the orchestrator
            self.progress(0.8)

            if not ctx.tokens:
                raise RuntimeError('Internal error: mkvmerge tokens were not generated.')

            # Write @opts.json and execute mkvmerge
            opts_path = self._write_mkvmerge_opts(ctx.tokens, job_temp, runner)

            merge_ok = runner.run(['mkvmerge', f'@{opts_path}'], self.tool_paths) is not None
            if not merge_ok:
                raise RuntimeError('mkvmerge execution failed.')

            out_file = ctx.out_file or (Path(output_dir) / Path(ref_file).name)
            log_to_all(f'[SUCCESS] Output file created: {out_file}')
            self.progress(1.0)
            return {
                'status': 'Merged',
                'output': str(out_file),
                'delay_sec': ctx.delay_sec_val,
                'delay_ter': ctx.delay_ter_val,
                'name': Path(ref_file).name
            }

        except Exception as e:
            log_to_all(f'[FATAL ERROR] Job failed: {e}')
            return {'status': 'Failed', 'error': str(e), 'name': Path(ref_file).name}
        finally:
            # Clean both temps AFTER mkvmerge/analysis completes
            try:
                if ctx_temp_dir and ctx_temp_dir.exists():
                    shutil.rmtree(ctx_temp_dir, ignore_errors=True)
            except Exception:
                pass
            try:
                shutil.rmtree(job_temp, ignore_errors=True)
            except Exception:
                pass
            log_to_all('=== Job Finished ===')
            handler.close()
            logger.removeHandler(handler)

    # --------------------------------------------------------------------------------------------
    # opts.json writer (unchanged behavior)
    # --------------------------------------------------------------------------------------------
    def _write_mkvmerge_opts(self, tokens, temp_dir: Path, runner: CommandRunner) -> str:
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
