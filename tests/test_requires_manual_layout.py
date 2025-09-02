# tests/test_requires_manual_layout.py
from pathlib import Path

def test_requires_manual_layout(tmp_repo, base_config, fake_tools, fake_runner, capture_log):
    """
    If and_merge=True and manual_layout=None, the pipeline must fail fast.
    This locks in the manual-only merge contract (profile path removed).
    """
    logs, log_cb = capture_log

    from vsg_core.pipeline import JobPipeline
    p = JobPipeline(config=base_config, log_callback=log_cb, progress_callback=lambda v: None)

    result = p.run_job(
        ref_file=tmp_repo['ref'],
        sec_file=None,
        ter_file=None,
        and_merge=True,
        output_dir_str=tmp_repo['outdir'],
        manual_layout=None
    )

    assert result['status'] == 'Failed'
    assert 'Manual layout required' in (result.get('error') or '')
