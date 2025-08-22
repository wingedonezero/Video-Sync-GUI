This bundle migrates your repo to a PySide6/Qt front-end and removes DearPyGui UI.
What changed:
- Removed: app_direct.py, video_sync_gui.py, vsg/ui/*
- Replaced: vsg/logbus.py (now UI-agnostic), vsg/settings.py (robust JSON I/O)
- Added: app_qt.py, vsg_qt/main_window.py, vsg_qt/settings_io.py, vsg_qt/widgets/options_dialog.py

Run:
  pip install PySide6
  python3 app_qt.py

The backend modules under vsg/* remain as in your repo (minus DPG calls in merge_job/logbus).
