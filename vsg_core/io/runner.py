# vsg_core/io/runner.py

# -*- coding: utf-8 -*-

"""
Wrapper for running external command-line processes.
"""

import subprocess
import shlex
from typing import List, Callable, Optional, Union
from datetime import datetime

class CommandRunner:
    """Executes external commands and streams output."""

    def __init__(self, config: dict, log_callback: Callable[[str], None]):
        self.config = config
        self.log = log_callback
        self.abs_paths = {}

    def _log_message(self, message: str):
        """Formats and sends a message to the log callback."""
        ts = datetime.now().strftime('%H:%M:%S')
        line = f'[{ts}] {message}'
        self.log(line)

    def run(self, cmd: List[str], tool_paths: dict, is_binary: bool = False) -> Optional[Union[str, bytes]]:
        """
        Executes a command and handles logging based on configuration.
        Returns captured stdout as a string, or bytes if is_binary=True.
        Returns None on failure.
        """
        if not cmd:
            return None

        tool_name = cmd[0]
        full_cmd = [tool_paths.get(tool_name, tool_name)] + list(map(str, cmd[1:]))

        try:
            pretty_cmd = ' '.join(shlex.quote(str(c)) for c in full_cmd)
        except Exception:
            pretty_cmd = ' '.join(map(str, full_cmd))

        self._log_message(f'$ {pretty_cmd}')

        compact = self.config.get('log_compact', True)
        tail_ok = int(self.config.get('log_tail_lines', 0))
        err_tail = int(self.config.get('log_error_tail', 20))
        prog_step = max(1, int(self.config.get('log_progress_step', 100)))

        try:
            # Setup for either text or binary mode
            popen_kwargs = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            }
            if not is_binary:
                popen_kwargs["text"] = True
                popen_kwargs["encoding"] = 'utf-8'
                popen_kwargs["errors"] = 'replace'

            proc = subprocess.Popen(full_cmd, **popen_kwargs)

            # Handle text stream for logging if not binary mode
            stream = proc.stdout if not is_binary else None
            out_buf_list = []
            tail_buffer = []
            last_prog = -1

            if compact:
                from collections import deque
                tail_buffer = deque(maxlen=max(tail_ok, err_tail, 1))

            if stream:
                for line in iter(stream.readline, ''):
                    out_buf_list.append(line)
                    if compact:
                        if line.startswith('Progress: '):
                            try:
                                pct = int(line.strip().split()[-1].rstrip('%'))
                                if last_prog < 0 or pct >= last_prog + prog_step or pct == 100:
                                    self._log_message(f'Progress: {pct}%')
                                    last_prog = pct
                            except (ValueError, IndexError):
                                pass
                        else:
                            tail_buffer.append(line)
                    else:
                        self._log_message(line.rstrip('\n'))

            # Wait and get final output
            stdout_data, _ = proc.communicate()
            rc = proc.returncode or 0

            # Use final captured data if binary mode
            final_output = stdout_data if is_binary else "".join(out_buf_list)

            if rc != 0:
                self._log_message(f'[!] Command failed with exit code {rc}')
                if compact and err_tail > 0 and tail_buffer:
                    from itertools import islice
                    error_lines = list(tail_buffer)[-err_tail:]
                    if error_lines:
                        self._log_message('[stderr/tail]\n' + ''.join(error_lines).rstrip())
                return None

            if compact and tail_ok > 0 and tail_buffer:
                success_lines = list(tail_buffer)[-tail_ok:]
                if success_lines:
                    self._log_message('[stdout/tail]\n' + ''.join(success_lines).rstrip())

            return final_output
        except Exception as e:
            self._log_message(f'[!] Failed to execute command: {e}')
            return None
