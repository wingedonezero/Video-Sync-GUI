# tests/test_chapters_snap.py
from pathlib import Path

def test_chapters_present_and_written(tmp_repo, base_config, fake_tools, fake_runner, capture_log, run_pipeline_and_capture_tokens):
    logs, log_cb = capture_log

    manual_layout = [
        {'source': 'REF', 'id': 0, 'type': 'video'},
    ]

    tokens_holder, run_fn = run_pipeline_and_capture_tokens
    tokens_holder, result = run_fn(
        base_config, tmp_repo['ref'], None, None, log_cb, lambda v: None, manual_layout
    )

    assert result['status'] == 'Merged'
    tokens = tokens_holder['tokens']

    # find chapters xml path in tokens and verify the file exists
    assert '--chapters' in tokens
    chapters_path = Path(tokens[tokens.index('--chapters') + 1])
    assert chapters_path.exists()
    text = chapters_path.read_text(encoding='utf-8')

    # sanity checks: renamed, normalized/snap run left some traces
    assert 'Chapter' in text  # renamed titles
    # ensure at least one ChapterTimeEnd exists after normalization
    assert 'ChapterTimeEnd' in text
