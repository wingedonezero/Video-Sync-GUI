
from __future__ import annotations
import sys
from PySide6 import QtWidgets
from vsg.settings_io import load_settings
from vsg.log_compat import ensure_logbus_compat

def _patch_logging():
    try:
        ensure_logbus_compat()
    except Exception as e:
        print('logbus compat warning:', e)

_patch_logging()
from vsg_qt.main_window import MainWindow
# --- Global fallbacks so legacy modules calling bare set_status/progress won't crash ---
def _install_global_status_functions():
    try:
        import builtins  # type: ignore
        try:
            from vsg.logbus import set_status as _ss, set_progress as _sp  # type: ignore
        except Exception:
            # Last resort: import from compat-initialized module
            from vsg import logbus as _lb  # type: ignore
            _ss = getattr(_lb, 'set_status', lambda *_a, **_k: None)
            _sp = getattr(_lb, 'set_progress', lambda *_a, **_k: None)
        builtins.set_status = _ss  # type: ignore
        builtins.set_progress = _sp  # type: ignore
    except Exception as e:
        print('global status fallback warning:', e)

_install_global_status_functions()


def main() -> None:
    # Load settings (merges defaults, never wipes unknown keys, ensures folders)
    load_settings()
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow(app)
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
