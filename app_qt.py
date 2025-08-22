
from __future__ import annotations
import sys
from PySide6 import QtWidgets
from vsg.settings_io import load_settings
from vsg_qt.main_window import MainWindow

def main():
    load_settings()  # populate CONFIG and ensure folders
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(app)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
