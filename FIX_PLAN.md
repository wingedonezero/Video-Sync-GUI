# VSG Rewrite Bug Fix Plan

This document describes the issues identified by comparing the original Python logs with the Rust rewrite logs, and provides a detailed plan to fix each issue.

## Summary of Issues

| Issue | Severity | Status |
|-------|----------|--------|
| 1. Sync Mode Not Matching Python | HIGH | Config default differs |
| 2. Delay Double-Add Bug | CRITICAL | Investigation needed |
| 3. Attachments From Wrong Source | HIGH | Code hardcodes Source 1 |
| 4. Chapter Snapping Not Wired | MEDIUM | Function exists but not called |
| 5. Missing Detailed Logging | LOW | Parity with Python |

---

## Issue 1: Sync Mode Default

### Problem
Python log shows: `TIMING SYNC MODE: ALLOW_NEGATIVE`
Rust log shows: `Sync Mode: Positive Only`

### Root Cause
The Rust code defaults to `SyncMode::PositiveOnly` in `crates/vsg_core/src/models/enums.rs:102`:
```rust
#[default]
#[serde(rename = "positive_only")]
PositiveOnly,
```

The Python original defaulted to `ALLOW_NEGATIVE`.

### Impact
- With `PositiveOnly`, a global shift is applied to make all delays non-negative
- This changes the sync behavior significantly
- Users migrating from Python will get different results

### Fix Location
`crates/vsg_core/src/models/enums.rs` - Consider changing default to match Python

### Fix Options

**Option A: Change Default**
```rust
// In enums.rs
#[serde(rename = "allow_negative")]
#[default]  // Move this attribute
AllowNegative,
```

**Option B: Document Difference** (less disruptive)
- Keep `PositiveOnly` as default
- Add migration note in docs
- Users must set `sync_mode = "allow_negative"` in their config

### Recommendation
Option B - since `PositiveOnly` is arguably safer for most users. Document clearly.

---

## Issue 2: Delay Double-Add Bug (CRITICAL)

### Problem
Python log shows Source 3 with correct delay: `-46ms` (raw), expected mkvmerge sync: `+955ms` after shift
Rust log shows mkvmerge command with: `--sync 0:+1956`

**Math:**
- Raw correlation delay: `-46ms`
- Global shift: `+1001ms`
- Expected adjusted: `-46 + 1001 = +955ms`
- Actual in mkvmerge: `+1956ms`
- Difference: `+1956 - 955 = +1001ms` = **global shift added twice**

### Root Cause Investigation

The delay flows through:
1. `AnalyzeStep` calculates raw delays and applies global shift to `delays.raw_source_delays_ms`
2. `JobState.analysis.delays` stores the adjusted delays
3. `MuxStep.build_merge_plan()` reads from `state.delays()`
4. Sets `plan_item.container_delay_ms_raw`
5. `MkvmergeOptionsBuilder` outputs `--sync` from `item.container_delay_ms_raw`

### Suspected Locations

**Location A: `crates/vsg_core/src/orchestrator/steps/analyze.rs:429-436`**
```rust
// This applies shift to ALL sources including Source 1
for (source, raw_delay) in delays.raw_source_delays_ms.iter_mut() {
    let original = *raw_delay;
    *raw_delay += raw_shift;
}
```
This is correct - it applies shift once.

**Location B: `crates/vsg_core/src/orchestrator/steps/mux.rs:181-187`**
```rust
// Apply delay from raw_source_delays_ms (already includes global shift)
if let Some(&delay_ms_raw) = delays.raw_source_delays_ms.get(source_key) {
    plan_item.container_delay_ms_raw = delay_ms_raw;
}
```
This just reads the value - should be correct.

### Fix Strategy

Add debug logging to trace the delay values at each step:

```rust
// In mux.rs build_merge_plan, around line 185:
if let Some(&delay_ms_raw) = delays.raw_source_delays_ms.get(source_key) {
    ctx.logger.info(&format!(
        "DEBUG: {} track {} delay from raw_source_delays_ms: {:+.3}ms",
        source_key, track_id, delay_ms_raw
    ));
    plan_item.container_delay_ms_raw = delay_ms_raw;
}
```

Then run a test job and check:
1. What value is in `delays.raw_source_delays_ms["Source 3"]` at the start of MuxStep
2. What value gets assigned to `container_delay_ms_raw`
3. What value gets output in the `--sync` token

### Alternative Theory

The double-add might happen if:
- The pipeline is somehow running twice
- Or the UI is pre-populating delays that already include a shift

Check `run_job_pipeline` in `helpers.rs` to ensure the JobSpec doesn't carry delay info.

---

## Issue 3: Attachments From Wrong Source

### Problem
Python log: `Extracting 14 fonts from: Source 3`
Rust log: `Processing attachments from Source 1... No attachments found`

### Root Cause
`crates/vsg_core/src/orchestrator/steps/attachments.rs:51-56`:
```rust
.and_then(|_layout| {
    // Look for attachment_sources in the layout metadata
    // For now, default to Source 1 if not specified  <-- HARDCODED!
    Some(vec!["Source 1".to_string()])
})
.unwrap_or_else(|| vec!["Source 1".to_string()]);
```

The code ignores the layout parameter `_layout` and always returns Source 1.

### Fix Location
`crates/vsg_core/src/orchestrator/steps/attachments.rs`

### Fix Implementation

```rust
// Replace lines 47-56 with:
let attachment_sources: Vec<String> = ctx
    .job_spec
    .manual_layout
    .as_ref()
    .and_then(|layout| {
        // Look for attachment_sources in the first item or a metadata field
        // Check if any items specify attachment extraction
        let sources: Vec<String> = layout
            .iter()
            .filter_map(|item| {
                // Check if this item requests attachments
                item.get("extract_attachments")
                    .and_then(|v| v.as_bool())
                    .and_then(|extract| {
                        if extract {
                            item.get("source")
                                .and_then(|s| s.as_str())
                                .map(|s| s.to_string())
                        } else {
                            None
                        }
                    })
            })
            .collect();

        if sources.is_empty() {
            // Fallback: check for attachment_sources field in layout metadata
            // Or default to all sources that have attachments
            None
        } else {
            Some(sources)
        }
    })
    .unwrap_or_else(|| {
        // Default: try all sources
        ctx.job_spec.sources.keys().cloned().collect()
    });
```

**Alternative Simpler Fix:**
```rust
// Extract from ALL sources by default
let attachment_sources: Vec<String> = ctx.job_spec.sources.keys().cloned().collect();
```

---

## Issue 4: Chapter Snapping Not Wired

### Problem
The chapters module has `snap_chapters()` function but `ChaptersStep` never calls it.

### Root Cause
`crates/vsg_core/src/orchestrator/steps/chapters.rs` does:
1. ✅ Extract chapters
2. ✅ Parse chapters
3. ✅ Shift chapters by global shift
4. ❌ **Does NOT snap to keyframes**
5. ✅ Write chapters

### Fix Location
`crates/vsg_core/src/orchestrator/steps/chapters.rs`

### Fix Implementation

Add after the shift (around line 114):

```rust
// Apply chapter snapping if enabled
if ctx.settings.chapters.snap_chapters {
    ctx.logger.info("Snapping chapters to keyframes...");

    // Get video source for keyframe extraction
    let video_source = ctx.primary_source().ok_or_else(|| {
        StepError::invalid_input("No video source for keyframe extraction")
    })?;

    // Extract keyframes
    match crate::chapters::extract_keyframes(video_source) {
        Ok(keyframes) => {
            let snap_mode = ctx.settings.chapters.snap_mode;
            crate::chapters::snap_chapters(&mut chapter_data, &keyframes, snap_mode);

            // Log snap stats
            let stats = crate::chapters::calculate_snap_stats(&chapter_data, &keyframes);
            ctx.logger.info(&format!(
                "Snapped {} chapters (avg shift: {:.1}ms)",
                stats.snapped_count, stats.avg_shift_ms
            ));
        }
        Err(e) => {
            ctx.logger.warn(&format!("Failed to extract keyframes: {} (skipping snap)", e));
        }
    }
}
```

### Also Needed: Chapter Settings

Check that `ChapterSettings` has the required fields in `crates/vsg_core/src/config/settings.rs`:

```rust
pub struct ChapterSettings {
    pub snap_chapters: bool,
    pub snap_mode: SnapMode,
    // ... other fields
}
```

---

## Issue 5: Missing Detailed Logging

### Problem
Python logs show much more detail:
- Command prefixes with `$`
- Decode debug info
- Drift diagnosis
- Track-level details

### Locations to Add Logging

**A. Command prefix with `$`**
`crates/vsg_core/src/logging/job_logger.rs` - add `command()` method that prefixes with `$ `:
```rust
pub fn command(&self, cmd: &str) {
    self.log(&format!("$ {}", cmd));
}
```

**B. Audio decode debug**
`crates/vsg_core/src/analysis/ffmpeg.rs` - add logging for:
- FFmpeg command being run
- Audio duration/sample count
- Resampling info

**C. Drift diagnosis**
`crates/vsg_core/src/analysis/analyzer.rs` - add more detail when drift detected:
```rust
if drift_detected {
    self.log(&format!(
        "[Drift Diagnosis] {}: std_dev={:.1}ms, min={:.1}ms, max={:.1}ms",
        source_name, std_dev,
        delays.iter().cloned().fold(f64::INFINITY, f64::min),
        delays.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
    ));
}
```

---

## Implementation Priority

1. **CRITICAL**: Issue 2 (Delay Double-Add) - This breaks sync completely
2. **HIGH**: Issue 3 (Attachments) - Fonts won't be included
3. **HIGH**: Issue 1 (Sync Mode) - Document the default difference
4. **MEDIUM**: Issue 4 (Chapter Snapping) - Feature incomplete
5. **LOW**: Issue 5 (Logging) - Nice to have for debugging

---

## Testing Plan

After fixes, run the same job that produced the gist logs and verify:

1. [ ] Sync mode is read from config correctly
2. [ ] Delays in mkvmerge command match expected values
3. [ ] Attachments extracted from correct sources
4. [ ] Chapters are snapped (if enabled)
5. [ ] Log output has similar detail level to Python

### Test Commands

```bash
# Build and run test job
cargo build --release

# Run with debug logging
RUST_LOG=debug cargo run --release -- job test.toml

# Compare delays in output
mkvinfo output.mkv | grep -A5 "Track"
```

---

## Files Modified

| File | Changes |
|------|---------|
| `crates/vsg_core/src/orchestrator/steps/attachments.rs` | Fix source selection |
| `crates/vsg_core/src/orchestrator/steps/chapters.rs` | Wire up snapping |
| `crates/vsg_core/src/orchestrator/steps/mux.rs` | Add debug logging |
| `crates/vsg_core/src/orchestrator/steps/analyze.rs` | Verify delay math |
| `crates/vsg_core/src/config/settings.rs` | Add chapter snap settings |
| `crates/vsg_core/src/logging/job_logger.rs` | Add command() method |
| `crates/vsg_core/src/analysis/analyzer.rs` | Enhanced drift logging |

---

## Questions to Resolve

1. Should `SyncMode` default be changed to match Python's `ALLOW_NEGATIVE`?
2. Should attachments extract from ALL sources by default or require explicit config?
3. What should happen if keyframe extraction fails during chapter snap?
