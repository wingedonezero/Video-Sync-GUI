# vsg_core/io/runner.py
"""
Wrapper for running external command-line processes.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vsg_core.models import AppSettings

# Import GPU environment support
try:
    from vsg_core.system.gpu_env import get_subprocess_environment

    GPU_ENV_AVAILABLE = True
except ImportError:
    GPU_ENV_AVAILABLE = False

    def get_subprocess_environment():
        import os

        return os.environ.copy()


class CommandRunner:
    """Executes external commands and streams output."""

    def __init__(self, settings: AppSettings, log_callback: Callable[[str], None]):
        self.settings = settings
        self.log = log_callback
        self.abs_paths = {}

    def _log_message(self, message: str):
        """Formats and sends a message to the log callback."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        self.log(line)

    def run(
        self,
        cmd: list[str],
        tool_paths: dict,
        is_binary: bool = False,
        input_data: bytes | None = None,
    ) -> str | bytes | None:
        """
        Executes a command and handles logging based on configuration.
        Can optionally pass binary `input_data` to the process's stdin.
        Returns captured stdout as a string, or bytes if is_binary=True.
        Returns None on failure.
        """
        if not cmd:
            return None

        tool_name = cmd[0]
        full_cmd = [tool_paths.get(tool_name, tool_name), *list(map(str, cmd[1:]))]

        try:
            pretty_cmd = " ".join(shlex.quote(str(c)) for c in full_cmd)
        except Exception:
            pretty_cmd = " ".join(map(str, full_cmd))

        self._log_message(f"$ {pretty_cmd}")

        compact = self.settings.log_compact
        tail_ok = self.settings.log_tail_lines
        err_tail = self.settings.log_error_tail
        prog_step = max(1, self.settings.log_progress_step)

        try:
            # Get environment with GPU support
            env = get_subprocess_environment()

            popen_kwargs = {
                "stdout": subprocess.PIPE,
                # For binary output, capture stderr separately to avoid corrupting binary data
                # For text output, merge stderr with stdout for unified logging
                "stderr": subprocess.PIPE if is_binary else subprocess.STDOUT,
                "env": env,  # Pass environment with GPU variables
            }
            # (THE FIX IS HERE) Add stdin handling
            if input_data is not None:
                popen_kwargs["stdin"] = subprocess.PIPE

            if not is_binary:
                popen_kwargs["text"] = True
                popen_kwargs["encoding"] = "utf-8"
                popen_kwargs["errors"] = "replace"

            proc = subprocess.Popen(full_cmd, **popen_kwargs)

            # (THE FIX IS HERE) Pass input_data to communicate
            stdout_data, stderr_data = proc.communicate(input=input_data)
            rc = proc.returncode or 0

            # For binary mode, log any stderr separately (don't mix with binary data)
            if is_binary and stderr_data:
                try:
                    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                    if stderr_text:
                        self._log_message(f"[ffmpeg stderr] {stderr_text}")
                except Exception:
                    pass

            # Handle text stream for logging if not binary mode
            out_buf_list = []
            if not is_binary and stdout_data:
                out_buf_list = stdout_data.splitlines(keepends=True)

            if compact and not is_binary:
                from collections import deque

                tail_buffer = deque(maxlen=max(tail_ok, err_tail, 1))
                last_prog = -1
                for line in out_buf_list:
                    if line.startswith("Progress: "):
                        try:
                            pct = int(line.strip().split()[-1].rstrip("%"))
                            if (
                                last_prog < 0
                                or pct >= last_prog + prog_step
                                or pct == 100
                            ):
                                self._log_message(f"Progress: {pct}%")
                                last_prog = pct
                        except (ValueError, IndexError):
                            pass
                    else:
                        tail_buffer.append(line)
            elif not is_binary:
                for line in out_buf_list:
                    self._log_message(line.rstrip("\n"))

            if rc != 0:
                self._log_message(f"[!] Command failed with exit code {rc}")
                if compact and not is_binary and err_tail > 0 and tail_buffer:
                    error_lines = list(tail_buffer)[-err_tail:]
                    if error_lines:
                        self._log_message(
                            "[stderr/tail]\n" + "".join(error_lines).rstrip()
                        )
                return None

            if compact and not is_binary and tail_ok > 0 and tail_buffer:
                success_lines = list(tail_buffer)[-tail_ok:]
                if success_lines:
                    self._log_message(
                        "[stdout/tail]\n" + "".join(success_lines).rstrip()
                    )

            return stdout_data if is_binary else "".join(out_buf_list)
        except Exception as e:
            self._log_message(f"[!] Failed to execute command: {e}")
            return None
