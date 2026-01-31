# vsg_core/subtitles/ocr/unified_subprocess.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import run_ocr_unified

JSON_PREFIX = "__VSG_UNIFIED_OCR_JSON__ "


class _SubprocessRunner:
    def _log_message(self, message: str) -> None:
        print(message, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run unified OCR in a subprocess.")
    parser.add_argument("--subtitle-path", required=True, help="Path to subtitle (.idx/.sub/.sup)")
    parser.add_argument("--lang", required=True, help="OCR language code (e.g., eng)")
    parser.add_argument("--config-json", required=True, help="Path to OCR settings JSON file")
    parser.add_argument("--output-json", required=True, help="Path to output SubtitleData JSON file")
    parser.add_argument("--work-dir", required=True, help="Working directory for OCR temp files")
    parser.add_argument("--logs-dir", required=True, help="Directory for OCR logs/reports")
    parser.add_argument("--track-id", required=True, type=int, help="Track ID for OCR output")
    args = parser.parse_args()

    config_path = Path(args.config_json)
    output_path = Path(args.output_json)
    work_dir = Path(args.work_dir)
    logs_dir = Path(args.logs_dir)

    try:
        with open(config_path, encoding='utf-8') as f:
            config = json.load(f)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to load config JSON: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    runner = _SubprocessRunner()

    try:
        subtitle_data = run_ocr_unified(
            args.subtitle_path,
            args.lang,
            runner,
            {},
            config,
            work_dir=work_dir,
            logs_dir=logs_dir,
            track_id=args.track_id,
        )
    except Exception as exc:
        payload = {"success": False, "error": str(exc)}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    if subtitle_data is None or not subtitle_data.events:
        payload = {"success": False, "error": "OCR returned no subtitle data"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        subtitle_data.save_json(output_path)
    except Exception as exc:
        payload = {"success": False, "error": f"Failed to save SubtitleData JSON: {exc}"}
        print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
        return 1

    payload = {"success": True, "json_path": str(output_path)}
    print(f"{JSON_PREFIX}{json.dumps(payload)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
