import importlib
# Ensure all wrapper modules import without side effects
for mod in [
    "vsg",
    "vsg.settings",
    "vsg.logbus",
    "vsg.tools",
    "vsg.analysis.videodiff",
    "vsg.analysis.audio_xcorr",
    "vsg.plan.build",
    "vsg.mux.tokens",
    "vsg.mux.run",
    "vsg.jobs.discover",
    "vsg.jobs.merge_job",
]:
    importlib.import_module(mod)
print("OK")
