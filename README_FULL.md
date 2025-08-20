# Video Sync GUI — Full Modular Bundle (Consolidated)

This bundle includes all earlier phases + fixes:
- Clean `vsg/logbus.py` (robust logging & pump_logs)
- `vsg/settings.py` patched to log via `_log` and import `LOG_Q`
- Robust `vsg/tools.py` that resolves tools from PATH, CWD, or settings overrides
- `vsg/mux/tokens.py` delegates to monolith to avoid extraction errors
- All Phase B/C modules present (videodiff, plan.build, audio_xcorr, mux.run, jobs.*)
- Entrypoint: `app_mod_c.py` (monkeypatches monolith to use moved modules)

## Run
```bash
python3 app_mod_c.py
```

## Notes
- Place optional `videodiff` binary in PATH or the current folder, or set `videodiff_path` in settings.
- Required tools: `ffmpeg`, `ffprobe`, `mkvmerge`, `mkvextract`.
- If status shows "Missing tools", check the log lines printed by `find_required_tools()`.
