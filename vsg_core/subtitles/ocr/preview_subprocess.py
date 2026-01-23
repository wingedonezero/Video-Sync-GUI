# vsg_core/subtitles/ocr/preview_subprocess.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import run_preview_ocr


JSON_PREFIX = "__VSG_PREVIEW_JSON__ "


def main() -> int:
    parser = argparse.ArgumentParser(description="Run preview OCR in a subprocess.")
    parser.add_argument("--subtitle-path", required=True, help="Path to subtitle (.idx/.sub/.sup)")
    parser.add_argument("--lang", required=True, help="OCR language code (e.g., eng)")
    parser.add_argument("--output-dir", required=True, help="Output directory for preview OCR files")
    args = parser.parse_args()

    subtitle_path = args.subtitle_path
    lang = args.lang
    output_dir = Path(args.output_dir)

    def log_callback(message: str) -> None:
        print(message, flush=True)

    try:
        result = run_preview_ocr(
            subtitle_path=subtitle_path,
            lang=lang,
            output_dir=output_dir,
            log_callback=log_callback,
        )
    except Exception as exc:
        payload = {"success": False, "error": str(exc)}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    if result is None:
        payload = {"success": False, "error": "Preview OCR returned no result"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    json_path, ass_path = result
    payload = {
        "success": True,
        "json_path": str(json_path),
        "ass_path": str(ass_path),
    }
    print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
