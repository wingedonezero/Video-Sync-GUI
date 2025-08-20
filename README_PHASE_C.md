# Video Sync GUI — Modularization Phase C (Audio xcorr + Mux + Jobs)

This phase moves:
- `analysis.audio_xcorr`: get_audio_stream_index, extract_audio_chunk, find_audio_delay, best_from_results, run_audio_correlation_workflow
- `mux.tokens`: _tokens_for_track, build_mkvmerge_tokens
- `mux.run`: write_mkvmerge_json_options, run_mkvmerge_with_json
- `jobs.discover`: discover_jobs
- `jobs.merge_job`: merge_job

Run:
```bash
python3 app_mod_c.py
```
Behavior remains the same; we patched the monolith to use the moved implementations.
