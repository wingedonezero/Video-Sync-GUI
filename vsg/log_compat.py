
from __future__ import annotations

def ensure_logbus_compat():
    """
    Ensure vsg.logbus exposes:
      - _log(str, ...)
      - LOG_Q (queue)
      - STATUS_Q (queue)
      - PROGRESS_Q (queue)
      - set_status(str)
      - set_progress(float)
    Without requiring the user to replace their existing logbus.py.
    """
    import types, queue
    try:
        import vsg.logbus as lb
    except Exception:
        # create a minimal module if somehow missing
        lb = types.SimpleNamespace()
        import sys
        sys.modules['vsg.logbus'] = lb

    # _log
    if not hasattr(lb, '_log'):
        def _log(*args):
            try:
                text = " ".join(str(a) for a in args)
            except Exception:
                text = " ".join(repr(a) for a in args)
            print(text)
        lb._log = _log

    # Queues
    if not hasattr(lb, 'LOG_Q'):
        lb.LOG_Q = queue.Queue()
    if not hasattr(lb, 'STATUS_Q'):
        lb.STATUS_Q = queue.Queue()
    if not hasattr(lb, 'PROGRESS_Q'):
        lb.PROGRESS_Q = queue.Queue()

    # set_status / set_progress
    if not hasattr(lb, 'set_status'):
        def set_status(text: str):
            try:
                lb.STATUS_Q.put_nowait(str(text))
            except Exception:
                pass
        lb.set_status = set_status

    if not hasattr(lb, 'set_progress'):
        def set_progress(frac: float):
            try:
                lb.PROGRESS_Q.put_nowait(float(frac))
            except Exception:
                pass
        lb.set_progress = set_progress
