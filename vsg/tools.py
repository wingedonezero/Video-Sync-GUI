# External tool runners (moved)
from __future__ import annotations
import subprocess, logging, re, time
from .logbus import _log

def find_required_tools():
    for tool in ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract']:
        path = shutil.which(tool)
        if not path:
            raise RuntimeError(f"Required tool '{tool}' not found in PATH.")
        ABS[tool] = path


def run_command(cmd: List[str], logger) -> Optional[str]:
    silent_capture = False  # default; set to True for noisy ffprobe JSON
    """
    Settings-driven compact logger:
      - If CONFIG['log_compact'] is True (default), prints one $ line and throttled "Progress: N%".
      - On failure prints a short stderr tail (CONFIG['log_error_tail']).
      - On success (compact mode) optionally prints last N stdout lines (CONFIG['log_tail_lines']).
      - If compact is False, streams all output like the original.
    """
    if not cmd:
        return None
    tool = cmd[0]
    cmd = [ABS.get(tool, tool)] + list(map(str, cmd[1:]))
    compact = bool(CONFIG.get('log_compact', True))
    tail_ok = int(CONFIG.get('log_tail_lines', 0))
    err_tail = int(CONFIG.get('log_error_tail', 20))
    prog_step = max(1, int(CONFIG.get('log_progress_step', 100)))
    try:
        import shlex
        pretty = ' '.join((shlex.quote(str(c)) for c in cmd))
    except Exception:
        pretty = ' '.join(map(str, cmd))
    _log(logger, '$ ' + pretty)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
        out_buf = ''
        last_prog = -1
        if compact:
            from collections import deque
            tail = deque(maxlen=max(tail_ok, err_tail, 1))
        for line in iter(proc.stdout.readline, ''):
            if silent_capture:
                out_buf += line
                continue
            out_buf += line
            if compact:
                if line.startswith('Progress: '):
                    try:
                        pct = int(line.strip().split()[-1].rstrip('%'))
                    except Exception:
                        pct = None
                    if pct is not None and (last_prog < 0 or pct >= last_prog + prog_step or pct == 100):
                        _log(logger, f'Progress: {pct}%')
                        last_prog = pct
                else:
                    tail.append(line)
            else:
                _log(logger, line.rstrip('\n'))
        proc.wait()
        rc = proc.returncode or 0
        if rc and rc > 1:
            _log(logger, f'[!] Command failed with exit code {rc}')
            if compact and err_tail > 0:
                from itertools import islice
                t = list(tail)[-err_tail:] if 'tail' in locals() else []
                if t:
                    _log(logger, '[stderr/tail]\n' + ''.join(t).rstrip())
            return None
        if compact and tail_ok > 0 and ('tail' in locals()):
            t = list(tail)[-tail_ok:]
            if t:
                _log(logger, '[stdout/tail]\n' + ''.join(t).rstrip())
        return out_buf
    except Exception as e:
        _log(logger, f'[!] Failed to execute: {e}')
        return None


