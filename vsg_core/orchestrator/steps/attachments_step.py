# vsg_core/orchestrator/steps/attachments_step.py
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from vsg_core.extraction.attachments import extract_attachments

if TYPE_CHECKING:
    from vsg_core.io.runner import CommandRunner
    from vsg_core.orchestrator.steps.context import Context


class AttachmentsStep:
    """
    Extracts attachments from all sources specified by the user in the UI.
    Also handles copying replacement fonts from Font Manager.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        if not ctx.and_merge or not ctx.attachment_sources:
            ctx.attachments = []
            # Still need to check for replacement fonts even without other attachments
            self._add_replacement_fonts(ctx, runner)
            return ctx

        all_attachments: list[str] = []
        for source_key in ctx.attachment_sources:
            source_file = ctx.sources.get(source_key)
            if source_file:
                runner._log_message(f"Extracting attachments from {source_key}...")
                attachments_from_source = extract_attachments(
                    str(source_file), ctx.temp_dir, runner, ctx.tool_paths, source_key
                )
                if attachments_from_source:
                    all_attachments.extend(attachments_from_source)

        ctx.attachments = all_attachments

        # Add replacement fonts
        self._add_replacement_fonts(ctx, runner)

        return ctx

    def _add_replacement_fonts(self, ctx: Context, runner: CommandRunner):
        """
        Copy replacement fonts from Font Manager to temp directory and add to attachments.
        """
        if not ctx.extracted_items:
            return

        # Collect all font replacements from tracks
        replacement_files: set[str] = set()
        for item in ctx.extracted_items:
            if item.font_replacements:
                for repl_data in item.font_replacements.values():
                    font_file = repl_data.get("font_file_path")
                    if font_file:
                        replacement_files.add(font_file)

        if not replacement_files:
            return

        runner._log_message(
            f"[Font] Copying {len(replacement_files)} replacement font(s)..."
        )

        # Create fonts subdirectory in temp
        fonts_temp_dir = ctx.temp_dir / "replacement_fonts"
        fonts_temp_dir.mkdir(parents=True, exist_ok=True)

        copied_fonts = []
        for font_file in replacement_files:
            src_path = Path(font_file)
            if src_path.exists():
                dst_path = fonts_temp_dir / src_path.name
                try:
                    shutil.copy2(src_path, dst_path)
                    copied_fonts.append(str(dst_path))
                    runner._log_message(f"[Font] Copied: {src_path.name}")
                except Exception as e:
                    runner._log_message(
                        f"[Font] WARNING: Failed to copy {src_path.name}: {e}"
                    )
            else:
                runner._log_message(f"[Font] WARNING: Font file not found: {font_file}")

        # Add copied fonts to attachments
        if copied_fonts:
            if ctx.attachments is None:
                ctx.attachments = []
            ctx.attachments.extend(copied_fonts)
            runner._log_message(
                f"[Font] Added {len(copied_fonts)} replacement font(s) to attachments."
            )
