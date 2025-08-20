# Architecture

## Layers
- **UI (video_sync_gui.py)**: DearPyGui components, user interactions, and orchestration.
- **Core (`vsg/`):**
  - `analysis` — compute delays via VideoDiff or Audio XCorr
  - `plan` — build merge plan and summaries
  - `mux` — mkvmerge tokenization, option file writing, process execution, chapters
  - `jobs` — job discovery and end-to-end merge flow
  - `settings` — config with defaults and persistence
  - `logbus` — thread-safe logging
  - `tools` — external tool discovery and command running

## Data Flow
UI → analysis → plan → (chapters) → mux options → mkvmerge → output MKV
