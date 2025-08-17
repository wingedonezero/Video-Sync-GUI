from __future__ import annotations

import argparse
from pathlib import Path
from .api import analyze_and_plan, merge_with_plan
from .settings import AppSettings

def main() -> None:
    p = argparse.ArgumentParser(description="Video-Sync CLI (experimental)")
    p.add_argument("--ref", type=Path, required=True)
    p.add_argument("--sec", type=Path)
    p.add_argument("--ter", type=Path)
    p.add_argument("--mode", choices=["audio","video"], default="audio")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    settings = AppSettings()
    plan = analyze_and_plan(args.ref, args.sec, args.ter, mode=args.mode, settings=settings)
    merge_with_plan(args.out, args.ref, args.sec, args.ter, plan, settings=settings)

if __name__ == "__main__":
    main()
