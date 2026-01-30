# vsg_core/orchestrator/steps/mux_step.py
from __future__ import annotations

from pathlib import Path

from vsg_core.io.runner import CommandRunner
from vsg_core.models import Context, Delays, MergePlan
from vsg_core.mux.options_builder import MkvmergeOptionsBuilder


class MuxStep:
    """
    Builds mkvmerge tokens and stores them on the context.
    """

    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        plan = MergePlan(
            items=ctx.extracted_items or [],
            delays=ctx.delays or Delays(),
            chapters_xml=Path(ctx.chapters_xml) if ctx.chapters_xml else None,
            attachments=[Path(a) for a in (ctx.attachments or [])],
        )

        builder = MkvmergeOptionsBuilder()
        # FIX: The builder no longer needs the output path.
        # The --output flag will be added later by the JobPipeline.
        tokens = builder.build(plan, ctx.settings, audit=ctx.audit)

        # The pipeline will now determine the final output file
        ctx.out_file = None
        ctx.tokens = tokens
        return ctx
