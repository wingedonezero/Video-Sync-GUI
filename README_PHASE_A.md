# Video Sync GUI — Modularization Phase A (Move-only: settings/logging/tools)

This bundle moves **settings**, **log bus**, and **tool runner** implementations into `vsg/`,
then monkeypatches the existing `video_sync_gui.py` so the GUI uses the moved code.

## Run
```bash
python3 app_mod.py
```

## Modules
- `vsg/settings.py`: CONFIG, SETTINGS_PATH, load/save/apply/sync functions
- `vsg/logbus.py`: LOG_Q, _log, pump_logs
- `vsg/tools.py`: find_required_tools, run_command

Next steps: move analysis/plan/mux/jobs functions into `vsg/*` and remove monkeypatching.
