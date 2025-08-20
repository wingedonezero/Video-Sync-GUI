# Video Sync GUI — Full Bundle (Fix 1)

This bundle consolidates all fixes to date and cleans up formatting (Black-compatible).

## Run
```bash
python3 app_mod_c.py
```

## Notes
- **Tools discovery**: `vsg/tools.py` now resolves from PATH, current folder (e.g., `./videodiff`), or settings overrides like `videodiff_path`.
- **Logging**: `vsg/settings.py` uses `_log(...)` (no direct `LOG_Q.put(...)`), preventing NameError in threads.
- **Formatting**: Files are Black-compatible; a `pyproject.toml` is included (run `black .` locally if you wish).
