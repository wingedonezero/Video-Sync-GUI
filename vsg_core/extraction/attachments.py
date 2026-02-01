# vsg_core/extraction/attachments.py
from pathlib import Path

from ..io.runner import CommandRunner
from .tracks import get_stream_info


def extract_attachments(
    mkv: str, temp_dir: Path, runner: CommandRunner, tool_paths: dict, role: str
) -> list[str]:
    info = get_stream_info(mkv, runner, tool_paths)
    if not info:
        return []

    files, specs = [], []
    font_count = 0
    total_attachments = len((info or {}).get("attachments", []))

    for attachment in (info or {}).get("attachments", []):
        mime_type = attachment.get("content_type", "").lower()
        file_name = attachment.get("file_name", "").lower()

        # Comprehensive font detection covering all common cases
        is_font = (
            # Standard font MIME types
            mime_type.startswith(("font/", "application/font", "application/x-font"))
            or
            # TrueType fonts (multiple variations)
            mime_type
            in ["application/x-truetype-font", "application/truetype", "font/ttf"]
            or
            # OpenType fonts (multiple variations)
            mime_type
            in ["application/vnd.ms-opentype", "application/opentype", "font/otf"]
            or
            # WOFF fonts
            mime_type in ["application/font-woff", "font/woff", "font/woff2"]
            or
            # PostScript fonts
            mime_type in ["application/postscript", "application/x-font-type1"]
            or
            # Generic binary (some MKVs use this for fonts)
            (
                mime_type in ["application/octet-stream", "binary/octet-stream"]
                and file_name.endswith((".ttf", ".otf", ".ttc", ".woff", ".woff2"))
            )
            or
            # Any MIME with 'font' or 'truetype' or 'opentype' in it
            any(x in mime_type for x in ["font", "truetype", "opentype"])
            or
            # File extension fallback (most reliable)
            file_name.endswith(
                (
                    ".ttf",
                    ".otf",
                    ".ttc",
                    ".woff",
                    ".woff2",
                    ".eot",
                    ".fon",
                    ".fnt",
                    ".pfb",
                    ".pfa",
                )
            )
        )

        if is_font:
            font_count += 1
            out_path = (
                temp_dir / f"{role}_att_{attachment['id']}_{attachment['file_name']}"
            )
            specs.append(f"{attachment['id']}:{out_path}")
            files.append(str(out_path))

    if specs:
        runner._log_message(
            f"[Attachments] Found {total_attachments} attachments, extracting {font_count} font file(s)..."
        )
        runner.run(["mkvextract", str(mkv), "attachments", *specs], tool_paths)
    else:
        runner._log_message(
            f"[Attachments] Found {total_attachments} attachments, but none were identified as fonts."
        )

    return files
