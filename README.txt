Video Sync GUI — Full Bundle (fix3, wrapper-based)

What this is:
- A clean, Black-friendly package layout `vsg/` that wraps functions from your existing `video_sync_gui.py`.
- No fragile monkeypatching; the wrappers simply re-export names from the monolith.
- Safe to drop into your project alongside `video_sync_gui.py`.

Run:
    python3 app_mod_c.py

Next steps:
- If you want to fully detach from the monolith, we can incrementally move implementations into `vsg/*`.
- Once parity is verified (opts.json + Merge Summary), we can switch the GUI to import `vsg.*` directly.
