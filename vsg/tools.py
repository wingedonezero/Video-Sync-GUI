    # External tool runners (modularized, robust, black-formatted)
    from __future__ import annotations

    import logging
    import os
    import re
    import shutil
    import subprocess
    import time
    from pathlib import Path
    from typing import Dict, Optional

    from vsg.logbus import _log

    # Absolute paths to resolved tools after find_required_tools()
    ABS: Dict[str, str] = {}

    REQUIRED = ["ffmpeg", "ffprobe", "mkvmerge", "mkvextract"]
    OPTIONAL = ["videodiff"]  # optional when running Audio Correlation mode

    def _resolve_in_cwd(name: str) -> Optional[str]:
        exe = Path(os.getcwd()) / name
        if exe.exists() and os.access(exe, os.X_OK):
            return str(exe.resolve())
        # Try with common Windows extension names just in case
        for ext in (".exe", ".bat", ".cmd"):
            exe2 = Path(os.getcwd()) / f"{name}{ext}"
            if exe2.exists() and os.access(exe2, os.X_OK):
                return str(exe2.resolve())
        return None

    def _resolve_with_overrides(name: str) -> Optional[str]:
        # Allow config-driven override like videodiff_path, ffmpeg_path, etc.
        try:
            from vsg.settings import CONFIG  # lazy import to avoid circulars
        except Exception:
            CONFIG = {}

        override_key = f"{name}_path"
        override = CONFIG.get(override_key) if isinstance(CONFIG, dict) else None
        if override:
            p = Path(override)
            if p.exists() and os.access(p, os.X_OK):
                return str(p.resolve())
        return None

    def _resolve_tool(name: str) -> Optional[str]:
        # 1) PATH
        path = shutil.which(name)
        if path:
            return str(Path(path).resolve())
        # 2) Current working directory (drop a local binary like ./videodiff)
        path = _resolve_in_cwd(name)
        if path:
            return path
        # 3) Settings override
        path = _resolve_with_overrides(name)
        if path:
            return path
        return None

    def find_required_tools() -> bool:
        """
        Resolve tool absolute paths and populate ABS.
        Returns True if all REQUIRED are found, else False.
        """
        missing = []
        for name in REQUIRED:
            path = _resolve_tool(name)
            if not path:
                missing.append(name)
                continue
            ABS[name] = path

        # Optional tools
        for name in OPTIONAL:
            path = _resolve_tool(name)
            if path:
                ABS[name] = path

        if missing:
            _log(f"Missing tools: {', '.join(missing)}")
            return False

        # Nice summary
        for k, v in ABS.items():
            _log(f"Tool resolved: {k} -> {v}")
        return True

    def run_command(cmd: list[str], log_prefix: str = "$ ", progress_pattern: str = r"Progress:\s*(\d+)%") -> int:
        """
        Run a subprocess with compact logging.
        - Logs the command once, prefixed with `$ `.
        - Throttles repeated progress lines (e.g., 'Progress: 12%').
        - Streams stderr and stdout to the GUI log.
        Returns the process return code.
        """
        try:
            printable = " ".join(cmd)
            _log(f"{log_prefix}{printable}")
        except Exception:
            pass

        prog_re = re.compile(progress_pattern)
        last_prog = None
        rc = 0

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
            ) as proc:
                assert proc.stdout is not None
                for line in proc.stdout:
                    line = line.rstrip("
")
                    m = prog_re.search(line)
                    if m:
                        prog = m.group(1)
                        if prog != last_prog:
                            _log(f"Progress: {prog}%")
                            last_prog = prog
                        continue
                    if line:
                        _log(line)
                proc.wait()
                rc = int(proc.returncode or 0)
        except FileNotFoundError as e:
            _log(f"Command not found: {e}")
            return 127
        except Exception as e:
            _log(f"Command failed to start: {e}")
            return 1

        if rc != 0:
            _log(f"Process exited with code {rc}")
        return rc
