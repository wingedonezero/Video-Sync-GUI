# Video-Sync-GUI Codebase Cleanup Plan

## Executive Summary

This plan outlines the cleanup of the Video-Sync-GUI codebase to:
1. Remove deprecated modes (frame-matched, frame-perfect, frame-snapped, videotimestamps, dual-videotimestamps, raw-delay)
2. Keep modes: **time-based**, **duration-align**, **correlation-frame-snap**
3. Add "use raw values" checkbox to time-based mode (using pysubs instead of mkvmerge)
4. Implement conditional visibility for mode-specific settings
5. Consolidate duplicate hash settings across modes

---

## Section 1: Current Mode Inventory

### All Current Modes
```
time-based, frame-perfect, frame-snapped, videotimestamps,
dual-videotimestamps, frame-matched, raw-delay, duration-align,
correlation-frame-snap
```

### Modes to KEEP (3)
| Mode | Purpose |
|------|---------|
| **time-based** | Default, simple delay via mkvmerge --sync (+ optional raw checkbox) |
| **duration-align** | Frame alignment via total duration difference + validation |
| **correlation-frame-snap** | Audio correlation + scene-based frame boundary refinement |

### Modes to REMOVE (6)
| Mode | Reason |
|------|--------|
| frame-matched | Slow, replaced by correlation-frame-snap |
| frame-perfect | Overly complex middle/aegisub timing |
| frame-snapped | Redundant - correlation-frame-snap is better |
| videotimestamps | Single video mode, deprecated |
| dual-videotimestamps | Complex, rarely needed |
| raw-delay | Integrated into time-based as checkbox |

---

## Section 2: New "Use Raw Values" Feature for Time-Based Mode

### Current Behavior (time-based)
- Delay applied via mkvmerge `--sync` option
- Subtitle file unchanged, delay stored in container

### New Behavior (time-based + "Use raw values" checkbox)
When checked:
- Use pysubs2 to embed delay directly into subtitle timestamps
- Apply rounding based on `raw_delay_rounding` setting (default: floor)
- Set mkvmerge `--sync 0:0` (no additional delay)
- Essentially "raw-delay" mode integrated into time-based

### New Config Key
```python
'time_based_use_raw_values': False,  # Use pysubs instead of mkvmerge for delay
```

---

## Section 3: Settings to Remove

### Config Keys to Remove (in `vsg_core/config.py`)

**Frame-perfect/frame-snapped settings:**
```python
'frame_sync_mode': 'middle',           # REMOVE
'frame_shift_rounding': 'round',       # REMOVE
'frame_sync_fix_zero_duration': False, # REMOVE
'videotimestamps_rounding': 'round',   # REMOVE
```

**Frame-matched settings (all):**
```python
'frame_match_search_window_sec': 1,           # REMOVE
'frame_match_search_window_frames': 5,        # REMOVE
'frame_match_use_timestamp_prefilter': True,  # REMOVE
'frame_match_hash_size': 8,                   # REMOVE
'frame_match_threshold': 5,                   # REMOVE
'frame_match_method': 'dhash',                # REMOVE
'frame_match_skip_unmatched': False,          # REMOVE
'frame_match_max_search_frames': 300,         # REMOVE
'frame_match_workers': 0,                     # REMOVE
```

---

## Section 4: Duplicate Settings Consolidation (Hash Settings)

### Current Duplication
| Setting | duration-align | correlation-frame-snap |
|---------|---------------|----------------------|
| Algorithm | `duration_align_hash_algorithm` | `correlation_snap_hash_algorithm` |
| Size | `duration_align_hash_size` | `correlation_snap_hash_size` |
| Threshold | `duration_align_hash_threshold` | `correlation_snap_hash_threshold` |

### Consolidation: Create Unified Hash Settings
```python
# Both modes will use these (with backward compatibility fallback)
'frame_verify_hash_algorithm': 'dhash',  # 'dhash', 'phash', 'average_hash'
'frame_verify_hash_size': 8,             # 4, 8, or 16
'frame_verify_hash_threshold': 5,        # 0-64
```

### Backend reads with backward compatibility:
```python
hash_algorithm = config.get('frame_verify_hash_algorithm',
                 config.get('duration_align_hash_algorithm', 'dhash'))
```

---

## Section 5: Conditional Visibility Matrix

| Setting | time-based | +raw | duration-align | corr-frame-snap |
|---------|-----------|------|----------------|-----------------|
| Use raw values checkbox | YES | YES | - | - |
| Raw delay rounding | - | YES | - | - |
| VapourSynth indexing | - | - | YES | - |
| Validation checkbox | - | - | YES | - |
| Validation points | - | - | YES | - |
| Strictness | - | - | YES | - |
| Hybrid verification | - | - | YES | - |
| Verify search window | - | - | YES* | - |
| Verify tolerance | - | - | YES* | - |
| Fallback mode | - | - | YES | YES |
| Fallback target | - | - | YES* | - |
| Skip validation generated | - | - | YES | - |
| Window radius | - | - | - | YES |
| Search range | - | - | - | YES |
| Use scene changes | - | - | - | YES |
| **Hash Settings** | - | - | YES | YES |

*Only when hybrid mode enabled

---

## Section 6: Files to Modify

### Primary Files
| File | Changes |
|------|---------|
| `vsg_core/config.py` | Remove deprecated settings, add unified settings |
| `vsg_qt/options_dialog/tabs.py` | Remove modes, remove widgets, add unified hash group, visibility logic |
| `vsg_core/orchestrator/steps/subtitles_step.py` | Remove mode handling, add time-based+raw |
| `vsg_core/subtitles/frame_sync.py` | Update hash setting references |

### Files to Potentially Delete
| File | Reason |
|------|--------|
| `vsg_core/subtitles/frame_matching.py` | Only used by frame-matched mode (but check for VideoReader usage first) |

---

## Section 7: Implementation Order

### Phase 1: Backend Preparation (Safe)
1. Add new config keys (backward compatible)
2. Update hash setting reads with fallbacks
3. Add time-based+raw handling in subtitles_step.py

### Phase 2: UI Cleanup
4. Update mode dropdown (remove 6 modes)
5. Remove deprecated widget definitions
6. Add unified hash settings group
7. Add "Use raw values" checkbox
8. Implement `_update_fps_visibility` with conditional logic

### Phase 3: Dead Code Removal
9. Remove deprecated config keys
10. Remove handling for removed modes
11. Clean up dead imports

### Phase 4: Testing
12. Test all 3 remaining modes
13. Test time-based with raw checkbox
14. Verify UI visibility toggles correctly

---

## Section 8: UI Layout (Proposed)

```
Subtitle Sync Mode: [time-based ▼]

═══════════════════════════════════════════════════════
Time-Based Options (only shown when time-based selected)
───────────────────────────────────────────────────────
☐ Use raw correlation values (pysubs)
   └── Rounding: [floor ▼]  (only shown when checked)

═══════════════════════════════════════════════════════
Duration-Align Options (only shown when duration-align)
───────────────────────────────────────────────────────
☐ Use VapourSynth for indexing
☐ Enable validation
   └── Validation points: [5 ▼]
   └── Strictness: [balanced ▼]
☐ Hybrid frame verification
   └── Search window: [± 3 frames]
   └── Tolerance: [1.5x threshold]
Fallback mode: [report-only ▼]
☐ Skip validation for generated tracks

═══════════════════════════════════════════════════════
Correlation+FrameSnap Options (only shown for that mode)
───────────────────────────────────────────────────────
☐ Use scene changes for anchors
Window radius: [3 ▼] frames
Search range: [± 5 ▼] frames
Fallback mode: [abort ▼]

═══════════════════════════════════════════════════════
Frame Verification (duration-align OR corr-frame-snap)
───────────────────────────────────────────────────────
Hash algorithm: [dhash ▼]
Hash size: [8 ▼]
Hash threshold: [5 ▼]
```

---

## Approval Checklist

Before implementation, confirm:
- [ ] Remove frame-matched, frame-perfect, frame-snapped, videotimestamps, dual-videotimestamps, raw-delay
- [ ] Keep time-based, duration-align, correlation-frame-snap
- [ ] Add "Use raw values" checkbox to time-based (pysubs, floor rounding default)
- [ ] Unify hash settings into single group
- [ ] Implement conditional visibility
- [ ] Keep backward compatibility during transition

**Ready to proceed?**
