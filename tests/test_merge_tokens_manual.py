# tests/test_merge_tokens_manual.py
from pathlib import Path

def test_manual_merge_builds_expected_tokens(tmp_repo, base_config, fake_tools, fake_runner, capture_log, run_pipeline_and_capture_tokens):
    logs, log_cb = capture_log

    # Manual layout:
    #   - REF video id=0
    #   - SEC audio id=0 (AC3, default)
    #   - TER subs id=0 (SRT->ASS, rescale, 1.3x, forced, default)
    manual_layout = [
        {'source': 'REF', 'id': 0, 'type': 'video', 'apply_track_name': True},
        {'source': 'SEC', 'id': 0, 'type': 'audio', 'is_default': True, 'apply_track_name': True},
        {'source': 'TER', 'id': 0, 'type': 'subtitles', 'is_default': True, 'is_forced_display': True,
         'convert_to_ass': True, 'rescale': True, 'size_multiplier': 1.3, 'apply_track_name': True},
    ]

    tokens_holder, run_fn = run_pipeline_and_capture_tokens
    tokens_holder, result = run_fn(
        base_config, tmp_repo['ref'], tmp_repo['sec'], tmp_repo['ter'], log_cb, lambda v: None, manual_layout
    )

    assert result['status'] == 'Merged'

    tokens = tokens_holder['tokens']
    assert tokens is not None, "Pipeline did not write mkvmerge tokens"

    # --- basic structure ---
    assert '--output' in tokens
    # chapters should be present
    assert '--chapters' in tokens

    # track order like "0:0,1:0,2:0" for three inputs
    assert '--track-order' in tokens
    order = tokens[tokens.index('--track-order') + 1]
    assert order == '0:0,1:0,2:0'

    # --- per-track assertions via small helpers ---
    # Split into groups (language/sync/default/compression/(path))
    # Each track contributes a block ending with ')'
    groups = []
    acc = []
    for t in tokens:
        acc.append(t)
        if t == ')':
            groups.append(acc.copy())
            acc.clear()
    assert len(groups) == 3, f"Expected 3 tracks, found {len(groups)}"

    # Map expected delays:
    # SEC=+120ms, TER=-80ms → global_shift=+80
    # ref video delay = +80
    # sec audio delay = +80 + 120 = +200
    # ter subs delay = +80 - 80 = 0
    expected_sync = [ '0:80', '0:200', '0:0' ]

    # Check each group has the sync we expect in the same order manual_layout was given
    for i, g in enumerate(groups):
        assert '--language' in g
        assert '--sync' in g and expected_sync[i] in g[g.index('--sync')+1]
        # compression guard
        assert '--compression' in g and g[g.index('--compression')+1] == '0:none'

    # AC3 dialog norm removal should be present for SEC audio if enabled
    # It appears in the same per-track group
    g_audio = groups[1]
    assert '--remove-dialog-normalization-gain' in g_audio

    # Forced-display flag for TER subs present
    g_subs = groups[2]
    assert '--forced-display-flag' in g_subs and g_subs[g_subs.index('--forced-display-flag')+1] == '0:yes'
