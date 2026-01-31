# vsg_core/pipeline_components/tool_validator.py
"""
Tool validation component.

Validates that required external tools are available in the system PATH.
"""

import shutil


class ToolValidator:
    """Validates and locates required external tools."""

    REQUIRED_TOOLS = ['ffmpeg', 'ffprobe', 'mkvmerge', 'mkvextract', 'mkvpropedit']
    OPTIONAL_TOOLS = ['videodiff']

    @staticmethod
    def validate_tools() -> dict[str, str]:
        """
        Validates that all required tools are available in PATH.

        Returns:
            Dict mapping tool names to their paths

        Raises:
            FileNotFoundError: If any required tool is not found
        """
        tool_paths = {}

        # Validate required tools
        for tool in ToolValidator.REQUIRED_TOOLS:
            tool_paths[tool] = shutil.which(tool)
            if not tool_paths[tool]:
                raise FileNotFoundError(f"Required tool '{tool}' not found in PATH.")

        # Optional tools (don't fail if missing)
        for tool in ToolValidator.OPTIONAL_TOOLS:
            tool_paths[tool] = shutil.which(tool)

        return tool_paths
