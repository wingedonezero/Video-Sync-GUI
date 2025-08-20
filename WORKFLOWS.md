# Workflows

## Analyze only
1. Read settings, resolve tools.
2. Depending on `analysis_mode`, run VideoDiff or Audio XCorr.
3. Emit delay value and logs.

## Analyze & Merge
1. Compute delay (as above).
2. Build plan + summary.
3. Extract/rename/snap chapters from REF (if enabled).
4. Write mkvmerge JSON opts and run mkvmerge.
5. Output MKV in `output_folder`.
