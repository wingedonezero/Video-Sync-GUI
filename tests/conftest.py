# tests/conftest.py
import json
from pathlib import Path
import pytest

# We import the product modules only after we monkeypatch CommandRunner in each test
# to avoid pulling the real one too early.

@pytest.fixture
def tmp_repo(tmp_path: Path):
    """Create a simulated workspace with REF/SEC/TER filenames (no media)."""
    root = tmp_path
    (root / "REF.mkv").write_bytes(b"")  # filenames only; no content needed
    (root / "SEC.mkv").write_bytes(b"")
    (root / "TER.mkv").write_bytes(b"")
    out = root / "out"; out.mkdir()
    temp = root / "temp"; temp.mkdir()
    return {
        "root": root,
        "ref": str(root / "REF.mkv"),
        "sec": str(root / "SEC.mkv"),
        "ter": str(root / "TER.mkv"),
        "outdir": str(out),
        "tempdir": str(temp),
    }

@pytest.fixture
def base_config(tmp_repo):
    """Minimal config dict matching AppConfig keys used by pipeline."""
    return {
        'output_folder': tmp_repo['outdir'],
        'temp_root': tmp_repo['tempdir'],
        'videodiff_path': '',                    # unused; tool_paths will be stubbed
        'analysis_mode': 'VideoDiff',            # avoid librosa/scipy work
        'analysis_lang_ref': '',
        'analysis_lang_sec': '',
        'analysis_lang_ter': '',
        'scan_chunk_count': 3,
        'scan_chunk_duration': 5,
        'min_match_pct': 5.0,
        'videodiff_error_min': 0.0,
        'videodiff_error_max': 100.0,
        'rename_chapters': True,
        'apply_dialog_norm_gain': True,
        'snap_chapters': True,
        'snap_mode': 'previous',
        'snap_threshold_ms': 250,
        'snap_starts_only': True,
        'log_compact': True,
        'log_autoscroll': True,
        'log_error_tail': 20,
        'log_tail_lines': 0,
        'log_progress_step': 20,
        'log_show_options_pretty': False,
        'log_show_options_json': False,
        'exclude_codecs': '',
        'disable_track_statistics_tags': True,
        'archive_logs': False,
        'auto_apply_strict': False,
        'merge_profile': []  # unused in Manual mode tests
    }

@pytest.fixture
def capture_log():
    lines = []
    def cb(msg: str):
        lines.append(msg)
    return lines, cb

@pytest.fixture
def fake_tools(monkeypatch):
    """Patch tool discovery to avoid PATH checks."""
    from vsg_core import pipeline as pl
    def _fake_find(self):
        self.tool_paths = {
            'ffmpeg': 'ffmpeg',
            'ffprobe': 'ffprobe',
            'mkvmerge': 'mkvmerge',
            'mkvextract': 'mkvextract',
            'videodiff': 'videodiff',
        }
    monkeypatch.setattr(pl.JobPipeline, "_find_required_tools", _fake_find)

@pytest.fixture
def fake_runner(monkeypatch):
    """Patch CommandRunner used by pipeline to our FakeCommandRunner."""
    from tests.fakes import FakeCommandRunner
    import vsg_core.pipeline as pl
    monkeypatch.setattr(pl, "CommandRunner", FakeCommandRunner)

@pytest.fixture
def run_pipeline_and_capture_tokens(monkeypatch):
    """
    Helper: replaces _write_mkvmerge_opts to capture the tokens list the pipeline builds.
    Returns (tokens_holder, run_func)
    """
    tokens_holder = {"tokens": None}

    def patch_writer():
        import vsg_core.pipeline as pl

        real_writer = pl.JobPipeline._write_mkvmerge_opts
        def spy(self, tokens, temp_dir, runner):
            tokens_holder["tokens"] = list(tokens)
            return real_writer(self, tokens, temp_dir, runner)
        monkeypatch.setattr(pl.JobPipeline, "_write_mkvmerge_opts", spy)

    def run(config, ref, sec, ter, log_cb, progress_cb, manual_layout):
        patch_writer()
        from vsg_core.pipeline import JobPipeline
        p = JobPipeline(config=config, log_callback=log_cb, progress_callback=progress_cb)
        return tokens_holder, p.run_job(ref, sec, ter, and_merge=True, output_dir_str=config['output_folder'], manual_layout=manual_layout)

    return tokens_holder, run

def _token_chunks(tokens: list[str]):
    """Yield per-input groupings (language/sync/flags/(path)). Helps assertions."""
    group, acc = [], []
    for t in tokens:
        acc.append(t)
        if t == ')':
            group.append(acc.copy())
            acc.clear()
    return group
