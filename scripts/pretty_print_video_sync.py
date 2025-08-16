#!/usr/bin/env python3
"""
pretty_print_video_sync.py
---------------------------------
Non-invasive formatter for Video-Sync-GUI.

- Reads:   ./video_sync_gui.py
- Writes:  ./video_sync_gui_formatted.py
- Method:  Parses to Python AST, then un-parses back to source.
           This normalizes whitespace/indentation and expands long single-line
           constructs into a tidy, multi-line form. Comments may be lost if the
           source is fully minified; semantics are preserved by the AST.

Usage:
    python3 scripts/pretty_print_video_sync.py
"""
from __future__ import annotations

import ast
import io
from pathlib import Path
import sys

SRC = Path(__file__).resolve().parents[1] / "video_sync_gui.py"
DST = Path(__file__).resolve().parents[1] / "video_sync_gui_formatted.py"


def read_text_keep_header(p: Path) -> tuple[str, list[str]]:
    """Return (body_text, header_lines) preserving shebang/encoding if present."""
    raw = p.read_text(encoding="utf-8", errors="surrogatepass")
    lines = raw.splitlines(keepends=True)
    header: list[str] = []
    body_start = 0
    for i, ln in enumerate(lines[:2]):
        if ln.startswith("#!") or ("coding" in ln and ("utf" in ln.lower() or "coding:" in ln)):
            header.append(ln)
            body_start = i + 1
    body = "".join(lines[body_start:])
    return body, header


def write_with_header(p: Path, header: list[str], body: str) -> None:
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        for h in header:
            f.write(h if h.endswith("\n") else h + "\n")
        f.write(body if body.endswith("\n") else body + "\n")


def format_ast(src_text: str) -> str:
    """Parse and unparse using stdlib AST; on failure, return original source."""
    try:
        tree = ast.parse(src_text)
        formatted = ast.unparse(tree)  # Python 3.9+
        formatted = formatted.replace("\r\n", "\n").rstrip() + "\n"
        return formatted
    except Exception as e:
        sys.stderr.write(f"[pretty] AST formatting failed: {e}\n")
        return src_text


def main() -> int:
    if not SRC.exists():
        sys.stderr.write(f"[pretty] Not found: {SRC}\n")
        return 2
    body, header = read_text_keep_header(SRC)
    formatted = format_ast(body)
    write_with_header(DST, header, formatted)
    print(f"[pretty] Wrote formatted source to: {DST}")
    print("[pretty] Review the output; if it looks good, replace the original:")
    print("         mv video_sync_gui_formatted.py video_sync_gui.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
