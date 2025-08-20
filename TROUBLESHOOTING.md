# Troubleshooting

- Missing tools: set explicit paths in Settings or put binaries on PATH.
- No chapters: ensure REF has embedded chapters; otherwise provide external XML.
- Snap skipped: ffprobe keyframe list empty → check video stream / codec.
- Double runs: ensure RUN_LOCK/JOB_RUNNING guard in button callbacks.
