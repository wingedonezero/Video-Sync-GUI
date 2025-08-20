    # External tool runners (robust) — consolidated bundle
    from __future__ import annotations
    import os, shutil, subprocess, logging, re, time
    from typing import Dict, List, Optional
    from vsg.logbus import _log

    ABS: Dict[str, str] = {}

    REQUIRED = ["ffmpeg", "ffprobe", "mkvmerge", "mkvextract"]
    OPTIONAL = ["videodiff"]  # needed only in VideoDiff mode

    def _resolve_tool(name: str) -> Optional[str]:
        # 1) PATH
        p = shutil.which(name)
        if p:
            return p
        # 2) current working dir
        cwd_path = os.path.join(os.getcwd(), name)
        if os.path.isfile(cwd_path) and os.access(cwd_path, os.X_OK):
            return os.path.abspath(cwd_path)
        # 3) settings override
        try:
            from vsg.settings import CONFIG
            override_key = f"{name}_path"
            if isinstance(CONFIG, dict):
                ov = CONFIG.get(override_key)
                if ov and os.path.isfile(ov) and os.access(ov, os.X_OK):
                    return os.path.abspath(ov)
        except Exception:
            pass
        return None

    def find_required_tools() -> bool:
        """
        Populate ABS[...] with absolute paths. Returns True if all REQUIRED are found.
        """
        ok = True
        for nm in REQUIRED + OPTIONAL:
            path = _resolve_tool(nm)
            if path:
                ABS[nm] = path
            else:
                if nm in REQUIRED:
                    ok = False
        missing_req = [n for n in REQUIRED if n not in ABS]
        if missing_req:
            _log(f"Missing tools: {', '.join(missing_req)}")
        else:
            _log("All required tools found.")
        # Optional notice
        if "videodiff" not in ABS:
            _log("Optional tool not found: videodiff (only needed in VideoDiff mode)")
        return ok

    def run_command(args: List[str], log_cmd: Optional[str] = None) -> int:
        """
        Run a command, compact logging similar to the monolith.
        - args: full argv (use ABS[...] for known tools)
        - log_cmd: if provided, displayed instead of args
        """
        display = log_cmd or " ".join(args)
        _log(f"$ {display}")
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        except FileNotFoundError:
            _log("Command not found.")
            return 127
        last_progress = 0.0
        prog_re = re.compile(r"(?:frame|size|time|speed|Progress)")
        if proc.stdout:
            for line in proc.stdout:
                line = line.rstrip("
")
                # Throttle very noisy progress lines
                if prog_re.search(line):
                    now = time.time()
                    if now - last_progress < 0.25:
                        continue
                    last_progress = now
                _log(line)
        rc = proc.wait()
        _log(f"[exit {rc}]")
        return rc
