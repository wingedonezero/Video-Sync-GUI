
from __future__ import annotations
import sys
from PySide6 import QtWidgets
from vsg.settings_io import load_settings
from vsg_qt.main_window import MainWindow

def main() -> None:
    # Load settings (merges defaults, never wipes unknown keys, ensures folders)
    load_settings()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(app)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
