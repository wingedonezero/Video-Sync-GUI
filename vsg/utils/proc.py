from typing import List, Tuple
import subprocess

def run_command(argv: List[str]) -> Tuple[int,str,str]:
    p = subprocess.run(argv, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr
