# app_qt.py
from __future__ import annotations
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from vsg_qt.main_window import MainWindow

def main() -> int:
    proj_root = Path(__file__).resolve().parent
    app = QApplication(sys.argv)
    win = MainWindow(project_root=proj_root)
    win.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
