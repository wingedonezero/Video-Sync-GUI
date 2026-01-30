# vsg_core/orchestrator/steps/context.py
"""
Pipeline execution context.

NOTE: The Context class has been moved to vsg_core/models/context.py
This file re-exports it for backward compatibility.
"""

from __future__ import annotations

# Re-export from centralized location
from vsg_core.models.context import Context

__all__ = ["Context"]
