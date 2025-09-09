# vsg_core/orchestrator/steps/mux_step.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path

from vsg_core.io.runner import CommandRunner
from vsg_core.orchestrator.steps.context import Context
from vsg_core.models.jobs import MergePlan, Delays
from vsg_core.mux.options_builder import MkvmergeOptionsBuilder

class MuxStep:
    """
    Builds mkvmerge tokens and stores them on the context.
    """
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        source1_file = ctx.sources.get("Source 1")
        if not source1_file:
            raise ValueError("Context is missing Source 1 for determining output filename.")

        out_path = Path(ctx.output_dir) / Path(source1_file).name

        plan = MergePlan(
            items=ctx.extracted_items or [],
            delays=ctx.delays or Delays(),
            chapters_xml=Path(ctx.chapters_xml) if ctx.chapters_xml else None,
            attachments=[Path(a) for a in (ctx.attachments or [])]
        )

        builder = MkvmergeOptionsBuilder()
        tokens = builder.build(plan, ctx.settings, out_path)

        ctx.out_file = str(out_path)
        ctx.tokens = tokens
        return ctx
