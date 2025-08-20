# Video Sync GUI — 1.0.0-rc

This is the first fully modular release candidate.
- GUI imports **vsg.*** directly (no monkeypatching)
- Core: settings (defaults+merge), logging, tool discovery
- Features: VideoDiff analysis, Audio XCorr, chapters rename + snap-to-I-frames
- Mux: mkvmerge JSON opts writer + runner

## Run
    python3 app_direct.py

## Parity checks
    python3 tests/parity/diff_opts.py    /path/to/before/opts.json  ./after/opts.json
    python3 tests/parity/diff_summary.py /path/to/before/summary.txt ./after/summary.txt

## Formatting
    pip install black pre-commit
    pre-commit install
    black .
