# Video Sync GUI — Modularization (First Bundle)

This bundle introduces a package layout **without changing behavior**.
All modules are *thin wrappers* that re-export functions from the current monolith `video_sync_gui.py`.

```
vsg/
  __init__.py
  settings.py           # CONFIG, load/save/apply/sync
  logbus.py             # LOG_Q, _log, pump_logs
  tools.py              # runners and probes
  analysis/
    videodiff.py        # run_videodiff(), format_delay_ms()
    audio_xcorr.py      # correlation pipeline (getattr-safe)
  plan/
    build.py            # build_plan(), summarize_plan()
  mux/
    tokens.py           # mkvmerge token builders
    run.py              # opts.json write + mkvmerge run
  jobs/
    discover.py         # discover_jobs()
    merge_job.py        # merge_job()
```

## How to use now

- **Run the GUI exactly as before**:
  ```bash
  python3 app.py
  ```
  This simply calls `build_ui()` from the existing `video_sync_gui.py`.

- **Start importing from modules** (no behavior change):
  ```python
  from vsg.settings import CONFIG, load_settings
  from vsg.analysis.videodiff import run_videodiff
  from vsg.plan.build import build_plan
  ```

## Next step (move-only)
In the next PR, we will *move implementations* from `video_sync_gui.py`
into the corresponding `vsg/*` modules and update imports in the GUI,
guarded by a parity test that compares `opts.json` and the "Merge Summary".
