# tests/test_dialog_norm_toggle.py
def test_dialog_norm_toggle_off(tmp_repo, base_config, fake_tools, fake_runner, capture_log, run_pipeline_and_capture_tokens):
    logs, log_cb = capture_log
    cfg = dict(base_config)
    cfg['apply_dialog_norm_gain'] = False  # turn off

    manual_layout = [
        {'source': 'REF', 'id': 0, 'type': 'video'},
        {'source': 'SEC', 'id': 0, 'type': 'audio', 'is_default': True},
    ]

    tokens_holder, run_fn = run_pipeline_and_capture_tokens
    tokens_holder, result = run_fn(
        cfg, tmp_repo['ref'], tmp_repo['sec'], None, log_cb, lambda v: None, manual_layout
    )

    assert result['status'] == 'Merged'
    tokens = tokens_holder['tokens']
    assert tokens

    # ensure no '--remove-dialog-normalization-gain'
    assert all('--remove-dialog-normalization-gain' != t for t in tokens)
