# Testing

- **Smoke:** Launch UI, check status Ready, log pumps.
- **Tools:** Verify each tool is found or set path overrides.
- **VideoDiff:** Run analyze on known pair (sanity ms).
- **Audio XCorr:** Compare delay close to VideoDiff (± a few ms).
- **Chapters:** Enable rename + snap; verify output MKV chapters.
- **Parity:** Compare `opts.json` and summary vs old build.
