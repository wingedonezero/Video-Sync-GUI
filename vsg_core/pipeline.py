# vsg_core/pipeline.py
# -*- coding: utf-8 -*-
"""
Job pipeline orchestrator.

Coordinates sync job execution using modular components for improved
maintainability and testability.
"""

import shutil
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional

from .io.runner import CommandRunner
from .pipeline_components import (
    ToolValidator,
    LogManager,
    OutputWriter,
    SyncExecutor,
    SyncPlanner,
    ResultAuditor,
)


class JobPipeline:
    """
    Orchestrates video sync job execution.

    Coordinates tool validation, sync planning, merge execution, and output
    validation using modular components.
    """

    def __init__(
        self,
        config: dict,
        log_callback: Callable[[str], None],
        progress_callback: Callable[[float], None]
    ):
        """
        Initializes the job pipeline.

        Args:
            config: Configuration dictionary
            log_callback: Callback for GUI log messages
            progress_callback: Callback for progress updates
        """
        self.config = config
        self.gui_log_callback = log_callback
        self.progress = progress_callback
        self.tool_paths = {}

    def run_job(
        self,
        sources: Dict[str, str],
        and_merge: bool,
        output_dir_str: str,
        manual_layout: Optional[List[Dict]] = None,
        attachment_sources: Optional[List[str]] = None,
        source_settings: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Runs a complete sync job.

        Args:
            sources: Dictionary mapping source names to file paths
            and_merge: Whether to perform merge (vs. analyze-only)
            output_dir_str: Output directory path
            manual_layout: Manual layout configuration
            attachment_sources: List of attachment source paths
            source_settings: Per-source correlation settings, e.g.:
                {'Source 1': {'correlation_ref_track': 0}, 'Source 2': {'correlation_source_track': 1, 'use_source_separation': True}}

        Returns:
            Dictionary containing:
            - status: 'Analyzed', 'Merged', or 'Failed'
            - delays: Sync delays (if successful)
            - output: Output file path (if merged)
            - error: Error message (if failed)
            - name: Job name
            - issues: Number of audit issues found
            - stepping_sources: Sources with stepping detected
            - stepping_detected_disabled: Sources with stepping detection disabled
        """
        # --- 1. Input Validation ---
        source1_file = sources.get("Source 1")
        if not source1_file:
            raise ValueError("Job is missing Source 1 (Reference).")

        output_dir = Path(output_dir_str)
        output_dir.mkdir(parents=True, exist_ok=True)

        job_name = Path(source1_file).stem

        # --- 2. Setup Logging ---
        logger, handler, log_to_all = LogManager.setup_job_log(
            job_name, output_dir, self.gui_log_callback
        )

        runner = CommandRunner(self.config, log_to_all)

        # --- 3. Validate Tools ---
        try:
            self.tool_paths = ToolValidator.validate_tools()
        except FileNotFoundError as e:
            log_to_all(f'[ERROR] {e}')
            return {
                'status': 'Failed',
                'error': str(e),
                'name': Path(source1_file).name
            }

        log_to_all(f'=== Starting Job: {Path(source1_file).name} ===')
        self.progress(0.0)

        # --- 4. Validate Merge Requirements ---
        if and_merge and manual_layout is None:
            err_msg = 'Manual layout required for merge.'
            log_to_all(f'[ERROR] {err_msg}')
            return {
                'status': 'Failed',
                'error': err_msg,
                'name': Path(source1_file).name
            }

        ctx_temp_dir: Optional[Path] = None

        try:
            # --- 5. Plan Sync ---
            ctx = SyncPlanner.plan_sync(
                config=self.config,
                tool_paths=self.tool_paths,
                log_callback=log_to_all,
                progress_callback=self.progress,
                sources=sources,
                and_merge=and_merge,
                output_dir=str(output_dir),
                manual_layout=manual_layout or [],
                attachment_sources=attachment_sources or [],
                source_settings=source_settings or {}
            )
            ctx_temp_dir = getattr(ctx, 'temp_dir', None)

            # --- 6. Return Early if Analysis Only ---
            if not and_merge:
                log_to_all('--- Analysis Complete (No Merge) ---')
                self.progress(1.0)
                return {
                    'status': 'Analyzed',
                    'delays': ctx.delays.source_delays_ms if ctx.delays else {},
                    'name': Path(source1_file).name,
                    'issues': 0,
                    'stepping_sources': getattr(ctx, 'stepping_sources', []),
                    'stepping_detected_disabled': getattr(ctx, 'stepping_detected_disabled', [])
                }

            # --- 7. Validate Merge Tokens ---
            if not ctx.tokens:
                raise RuntimeError('Internal error: mkvmerge tokens were not generated.')

            # --- 8. Prepare Output Paths ---
            final_output_path = OutputWriter.prepare_output_path(output_dir, Path(source1_file).name)
            mkvmerge_output_path = ctx.temp_dir / f"temp_{final_output_path.name}"

            # --- 9. Add Output Flag to Tokens ---
            ctx.tokens.insert(0, str(mkvmerge_output_path))
            ctx.tokens.insert(0, '--output')

            # --- 10. Write mkvmerge Options ---
            opts_path = OutputWriter.write_mkvmerge_options(
                ctx.tokens, ctx.temp_dir, self.config, runner
            )

            # --- 11. Execute Merge ---
            merge_ok = SyncExecutor.execute_merge(opts_path, self.tool_paths, runner)
            if not merge_ok:
                raise RuntimeError('mkvmerge execution failed.')

            # --- 12. Finalize Output ---
            SyncExecutor.finalize_output(
                mkvmerge_output_path,
                final_output_path,
                self.config,
                self.tool_paths,
                runner
            )

            log_to_all(f'[SUCCESS] Output file created: {final_output_path}')

            # --- 13. Audit Output ---
            issues = ResultAuditor.audit_output(
                final_output_path, ctx, runner, log_to_all
            )

            # --- 14. Success ---
            self.progress(1.0)
            return {
                'status': 'Merged',
                'output': str(final_output_path),
                'delays': ctx.delays.source_delays_ms if ctx.delays else {},
                'name': Path(source1_file).name,
                'issues': issues,
                'stepping_sources': getattr(ctx, 'stepping_sources', []),
                'stepping_detected_disabled': getattr(ctx, 'stepping_detected_disabled', [])
            }

        except Exception as e:
            log_to_all(f'[FATAL ERROR] Job failed: {e}')
            return {
                'status': 'Failed',
                'error': str(e),
                'name': Path(source1_file).name,
                'issues': 0,
                'stepping_sources': [],
                'stepping_detected_disabled': []
            }

        finally:
            # --- 15. Cleanup ---
            if ctx_temp_dir and ctx_temp_dir.exists():
                shutil.rmtree(ctx_temp_dir, ignore_errors=True)

            # Clear VFR cache after each job to release VideoTimestamps instances
            try:
                from vsg_core.subtitles.frame_utils import clear_vfr_cache
                clear_vfr_cache()
            except ImportError:
                pass  # Module might not be loaded

            log_to_all('=== Job Finished ===')
            LogManager.cleanup_log(logger, handler)
