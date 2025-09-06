# UI Architecture

This document describes the **UI layer** (`vsg_qt/`) of the Video Sync GUI project.  
It follows the same philosophy as the core: **split into small, focused modules** so each file has a single responsibility, is easy to test, and keeps imports stable through re-export shims.

---

## 📂 Package Layout

```
vsg_qt/
├── __init__.py
│
├── main_window/
│   ├── __init__.py      # re-export MainWindow
│   ├── window.py        # Qt QMainWindow (view)
│   ├── controller.py    # event handling, job orchestration
│   └── helpers.py       # pure functions (signatures, layouts)
│
├── manual_selection_dialog/
│   ├── __init__.py      # re-export ManualSelectionDialog
│   ├── ui.py            # QDialog & widget layout
│   ├── logic.py         # guardrails, layout prepopulation
│   └── widgets.py       # SourceList & FinalList components
│
├── options_dialog/
│   ├── __init__.py      # re-export OptionsDialog
│   ├── ui.py            # QDialog with tab container
│   ├── tabs.py          # Storage, Analysis, Chapters, Merge, Logging tabs
│   └── logic.py         # load/save config to widgets
│
├── track_settings_dialog/
│   ├── __init__.py      # re-export TrackSettingsDialog
│   ├── ui.py            # QDialog, widgets
│   └── logic.py         # helper to init/read values
│
├── track_widget/
│   ├── __init__.py      # re-export TrackWidget
│   ├── ui.py            # TrackWidget row
│   ├── logic.py         # attaches menu + refresh
│   └── helpers.py       # string builders for label/summary
│
└── worker/
    ├── __init__.py      # re-export WorkerSignals, JobWorker
    ├── runner.py        # QRunnable job worker
    └── signals.py       # QObject signal class
```

---

## 🖥️ Main Window

- **`window.py`**
  - Creates the `QMainWindow`, layouts, buttons, log panel, progress bar.
  - Delegates all logic to `MainController`.

- **`controller.py`**
  - Orchestrates config <-> UI.
  - Discovers jobs (via core), opens dialogs (Options, Manual).
  - Spawns background `JobWorker`.
  - Handles worker signals, updates status/log/progress.
  - Manages log archiving.

- **`helpers.py`**
  - Signature generation for auto-apply.
  - Layout materialization from previous sessions.
  - Template conversion for persistence.

---

## 🛠️ Worker

- **`signals.py`**
  - Defines `WorkerSignals` (`log`, `progress`, `status`, `finished_job`, `finished_all`).

- **`runner.py`**
  - Implements `JobWorker (QRunnable)`:
    - Runs `JobPipeline` from core.
    - Emits signals as progress/log updates.
    - Produces results back to controller.

---

## 📑 Options Dialog

- **`ui.py`**
  - The main `OptionsDialog` class.
  - Contains a `QTabWidget` with multiple scrollable tabs.

- **`tabs.py`**
  - Each tab as a small QWidget subclass:
    - **StorageTab**: output dirs, temp, videodiff path.
    - **AnalysisTab**: mode, audio thresholds, video error bounds, language hints.
    - **ChaptersTab**: renaming, snapping.
    - **MergeBehaviorTab**: mux flags (dialog norm, track stats).
    - **LoggingTab**: verbosity, autoscroll, progress/error tail, mkvmerge option display.

- **`logic.py`**
  - Reads values from config into widgets.
  - Writes widget state back to config dict.
  - Handles composite widgets (file/dir pickers, line edits, checkboxes, combos).

---

## 📝 Manual Selection Dialog

- **`ui.py`**
  - `ManualSelectionDialog (QDialog)`.
  - Left: 3 source lists (REF, SEC, TER).
  - Right: Final list (drag-drop, context menus).
  - Pre-populates from previous layout if available.

- **`logic.py`**
  - Guardrails (SEC/TER video blocked).
  - Maps old layouts to current file’s tracks.
  - Builds final layout from widget states.
  - Normalization: enforce one default per type, one forced subtitle.

- **`widgets.py`**
  - `SourceList`: list of tracks per source.
  - `FinalList`: accepts drops, hosts TrackWidgets, supports context menu (move, toggle, delete).

---

## ⚙️ Track Settings Dialog

- **`ui.py`**
  - Popup dialog to adjust per-track settings:
    - Default, Forced, Convert to ASS, Rescale, Size multiplier, Keep Name.

- **`logic.py`**
  - Initializes visibility and enablement (e.g., only show Convert to ASS for SRT subs).
  - Applies values to widgets.
  - Reads back values into a dict.

---

## 🎛️ Track Widget

- **`ui.py`**
  - Row widget used in Manual FinalList.
  - Displays label, inline summary, and “Settings…” popup menu.
  - Stores hidden controls (checkboxes/spinbox) as single source of truth.

- **`logic.py`**
  - Installs the menu (wraps hidden controls).
  - Refreshes label + summary when state changes.
  - Provides `get_config()` to return dict of flags.

- **`helpers.py`**
  - String formatters:
    - `compose_label_text`: top-row label with badges.
    - `build_summary_text`: grey summary text line.

---

## 🔄 Imports & Compatibility

- Each package has an `__init__.py` that re-exports the main class.  
- Old imports remain valid:
  ```python
  from vsg_qt.main_window import MainWindow
  from vsg_qt.options_dialog import OptionsDialog
  from vsg_qt.manual_selection_dialog import ManualSelectionDialog
  from vsg_qt.track_settings_dialog import TrackSettingsDialog
  from vsg_qt.track_widget import TrackWidget
  from vsg_qt.worker import JobWorker
  ```

---

## 📌 Design Philosophy

- **Split by responsibility**: UI (`ui.py`), logic (`logic.py`), helpers (`helpers.py`).
- **Re-export at package root**: keeps old import paths stable.
- **Minimize coupling**: controllers talk to dialogs/workers via public methods, not internals.
- **Consistency with core**: everything is modular, small, and easy to test independently.
