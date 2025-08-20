# Video Sync GUI — Final Modular Release (v1.0.0)

**Status:** Stable · Fully modular (no monolith dependencies for logic) · Black-formatted

## What it does
- **Analysis:** VideoDiff and Audio cross-correlation (XCorr) to compute signed A/V delay.
- **Planning:** Generates a merge plan (track map, delays, filters).
- **Chapters:** Extracts REF chapters, optionally renames them, and can snap to I-frames.
- **Muxing:** Writes mkvmerge JSON opts and runs mkvmerge to produce the final MKV.
- **Logging:** Thread-safe GUI log with optional autoscroll.
- **Settings:** Default-backed configuration to avoid KeyErrors.

## Run
```bash
python3 app_direct.py
```

## Requirements
- Tools on PATH or set in Settings: `ffmpeg`, `ffprobe`, `mkvmerge`, `mkvextract`.
- Optional: `videodiff` binary for VideoDiff analysis (else use Audio XCorr).
