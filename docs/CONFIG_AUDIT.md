# Configuration & Settings Audit Report

**Baseline (old, known-good):** `4293a41f3cd1b5221c517c425eae41e17bc4e247`
**Current (post-refactor):** HEAD of main

---

## Section 1 — Regressions vs Old Commit (High-Level)

### 1.1 Architecture Change Summary

The refactor changed the entire config architecture:

| Aspect | Old (4293a41) | Current (HEAD) |
|--------|---------------|-----------------|
| Config storage | `self.settings` = plain `dict` | `self.settings` = `AppSettings` Pydantic model |
| Defaults | Inline dict in `AppConfig.__init__` | `AppSettings` class fields with defaults |
| Settings model | `@dataclass AppSettings` (31 fields, read from config) | Pydantic `BaseModel` (187+ fields, IS the config) |
| Enums | `AnalysisMode`, `SnapMode`, `TrackType` Enums | Replaced with `Literal` type aliases |
| OptionsLogic save | `cfg[key] = value` (dict write) | `setattr(cfg, key, value)` (Pydantic attribute) |
| OptionsLogic load | `cfg.get(key)` (dict read) | `getattr(cfg, key, None)` (attribute read) |
| Validation | Custom `_validate_value()` with enum checks | Pydantic `validate_assignment=True` |
| Type coercion | `_coerce_type()` + `_ensure_types_coerced()` | Pydantic's built-in coercion |

### 1.2 Key Regressions Introduced

1. **Default change: `analysis_lang_source1` / `analysis_lang_others`**
   - Old: `""` (empty string)
   - New: `None`
   - Impact: Code checking `if settings.analysis_lang_source1:` now skips `None` AND `""` the same way, but code checking `== ""` or `is None` may diverge. The old OptionsLogic `_set_widget_val` returns early on `None` (line 79: `if value is None: return`), so **`None` defaults never populate the UI widget** — the QLineEdit stays empty. This is functionally equivalent but fragile: if any runtime code does `if ref_lang is not None:` vs `if ref_lang:`, behavior differs.

2. **Default change: `duration_align_fallback_mode`**
   - Old: `"none"`
   - New: `"duration-offset"`
   - Impact: Changes fallback behavior — old default would warn-and-continue; new default applies duration offset. **This is a behavioral regression.**

3. **Default change: `ocr_char_blacklist`**
   - Old: `""` (empty string)
   - New: `"|"` (pipe character)
   - Impact: OCR now blacklists `|` by default when it previously didn't. May affect OCR results.

4. **Removed validation: Enum value checks**
   - Old: Explicit `_validate_value()` checked `source_separation_device` against `['auto', 'cpu', 'cuda', 'rocm', 'mps']`, `source_separation_mode` against `['none', 'instrumental', 'vocals']`, etc.
   - New: Most string fields in AppSettings are typed as plain `str` with NO Literal constraints. Only `analysis_mode` and `snap_mode` have Literal types. **All other "string switch" settings accept ANY string without validation.**

5. **Silent failure on save**
   - Old OptionsLogic: `cfg[key] = self._get_widget_val(widget)` — always writes.
   - New OptionsLogic (logic.py:33-35): Catches `ValidationError` with `pass` — **silently drops the setting if Pydantic rejects it**. No warning, no log, no user feedback.

6. **`video_verified_frame_audit` missing from old defaults**
   - Old: Not in defaults dict at all (was added in refactor)
   - New: `False` in AppSettings
   - Impact: New feature, not a regression per se, but notable.

7. **`videotimestamps_rounding` added but never in old**
   - Old: Not present
   - New: `"round"` in AppSettings, but NOT in any UI tab widget
   - Impact: Setting exists but cannot be configured via UI.

---

## Section 2 — Dead / Unused Settings

Settings defined in `AppSettings` (`vsg_core/models/settings.py`) that are **never referenced** in any runtime code OR UI widget.

### 2.1 Settings in AppSettings but NOT in any Options dialog tab widget

These settings exist in the model but have NO corresponding UI widget in `vsg_qt/options_dialog/tabs.py`:

| Setting | AppSettings default | Status |
|---------|-------------------|--------|
| `last_ref_path` | `""` | Used by main window for last-used paths (not user-configurable via Options) — **intentionally hidden** |
| `last_sec_path` | `""` | Same as above |
| `last_ter_path` | `""` | Same as above |
| `fonts_directory` | `""` | Used by `config.get_fonts_dir()` but no UI widget — **missing from UI** |
| `analysis_mode` | `"Audio Correlation"` | Used in pipeline but no UI widget in Options (set elsewhere) — **missing from Options** |
| `videodiff_error_min` | `0.0` | Used in VideoDiff analysis — **missing from UI** |
| `videodiff_error_max` | `100.0` | Used in VideoDiff analysis — **missing from UI** |
| `source_separation_device` | `"auto"` | Used in `source_separation.py:1456` — **missing from UI** |
| `source_separation_timeout` | `900` | Used in `source_separation.py:1457` — **missing from UI** |
| `post_mux_normalize_timestamps` | `False` | Used by mux pipeline — **missing from UI** |
| `post_mux_strip_tags` | `False` | Used by mux pipeline — **missing from UI** |
| `log_tail_lines` | `0` | Used in logging — **missing from UI** |
| `log_progress_step` | `20` | Used in logging — **missing from UI** |
| `auto_apply_strict` | `False` | Referenced in validation.py — **missing from UI** |
| `subtitle_target_fps` | `0.0` | Used in subtitle sync — **missing from UI** |
| `time_based_bypass_subtitle_data` | `True` | Used in subtitles_step.py:180 — **missing from UI** |
| `videotimestamps_rounding` | `"round"` | Used in `subtitles/frame_utils/timing.py:231` — **missing from UI** |
| `correlation_snap_use_scene_changes` | `True` | Used in correlation snap mode — **missing from UI** |
| `corr_anchor_anchor_positions` | `[10, 50, 90]` | Used in corr-guided mode — **missing from UI** |
| `ocr_psm` | `7` | Used in OCR backend — **missing from UI** |
| `ocr_char_whitelist` | `""` | Used in OCR backend — **missing from UI** |
| `ocr_multi_pass` | `True` | Used in OCR backend — **missing from UI** |
| `ocr_target_height` | `80` | Used in OCR preprocessing — **missing from UI** |
| `ocr_border_size` | `5` | Used in OCR preprocessing — **missing from UI** |
| `ocr_binarization_method` | `"otsu"` | Used in OCR preprocessing — **missing from UI** |
| `ocr_denoise` | `False` | Used in OCR preprocessing — **missing from UI** |
| `ocr_video_width` | `1920` | Used in OCR output — **missing from UI** |
| `ocr_video_height` | `1080` | Used in OCR output — **missing from UI** |
| `ocr_run_in_subprocess` | `True` | Used in subtitles_step.py:941 — **missing from UI** |
| `audio_decode_native` | `False` | Used in audio_corr.py — **missing from UI** |
| `stepping_vad_avoid_speech` | `True` | Used in silence snapping — **missing from UI** |
| `stepping_vad_frame_duration_ms` | `30` | Used in VAD — **missing from UI** |
| `stepping_transient_avoid_window_ms` | `50` | Used in transient detection — **missing from UI** |
| `stepping_fusion_weight_silence` | `10` | Used in smart fusion — **missing from UI** |
| `stepping_fusion_weight_no_speech` | `8` | Used in smart fusion — **missing from UI** |
| `stepping_fusion_weight_scene_align` | `5` | Used in smart fusion — **missing from UI** |
| `stepping_fusion_weight_duration` | `2` | Used in smart fusion — **missing from UI** |
| `stepping_fusion_weight_no_transient` | `3` | Used in smart fusion — **missing from UI** |
| `stepping_ffmpeg_silence_noise` | `-40.0` | Used in FFmpeg silencedetect — **missing from UI** |
| `stepping_ffmpeg_silence_duration` | `0.1` | Used in FFmpeg silencedetect — **missing from UI** |
| `stepping_audit_min_score` | `12.0` | Used in stepping audit — **missing from UI** |
| `stepping_audit_overflow_tolerance` | `0.8` | Used in stepping audit — **missing from UI** |
| `stepping_audit_large_correction_s` | `3.0` | Used in stepping audit — **missing from UI** |
| `frame_lock_submillisecond_precision` | `False` | Widget exists but setting may not be consumed — **verify runtime usage** |

### 2.2 Truly Dead Settings (not referenced anywhere in runtime code)

| Setting | Notes |
|---------|-------|
| (none confirmed) | All defined settings appear to have at least one runtime reference. |

**Correction:** `videotimestamps_rounding` IS used in `vsg_core/subtitles/frame_utils/timing.py:231` — it was initially missed because the search scope was too narrow. However, it has **NO UI widget** in the Options dialog, so it's in the "no UI wiring" category (Section 2.1), not dead.

### 2.3 Settings in Old Config but NOT in New AppSettings

These were present in the old `AppConfig.defaults` but are **missing** from new `AppSettings`:

| Old Setting | Old Default | Status |
|------------|-------------|--------|
| (none found — all old settings appear to have been migrated) | | |

Note: The old `AppSettings` dataclass (31 fields) was a *subset* used only for pipeline context. The old `AppConfig.defaults` dict (340+ keys) was the actual source of truth. The current AppSettings (187+ fields) absorbs both, but some old defaults may have subtly different values (see Section 1.2).

---

## Section 3 — Missing UI Wiring

### 3.1 Settings in Options Dialog Widget Map but Missing from AppSettings

All widget keys in `tabs.py` match field names in `AppSettings`. **No orphan widgets found.**

### 3.2 Settings in AppSettings but NOT in Options Dialog

(See Section 2.1 for the full list — 40+ settings have no UI widget)

Notable categories that should probably be user-configurable:

1. **`source_separation_device`** — User may need to select CPU/CUDA/ROCm
2. **`source_separation_timeout`** — Long separations may need adjustment
3. **`post_mux_normalize_timestamps`** / **`post_mux_strip_tags`** — User-facing post-processing options
4. **`subtitle_target_fps`** — Needed for frame-based subtitle sync modes
5. **`fonts_directory`** — User may want to set a custom fonts path
6. **All smart fusion weights** — Advanced users tuning stepping correction

### 3.3 Old UI Widgets That Were Present in Old `tabs.py` but Missing in Current

The old `tabs.py` file at commit 4293a41 was 1995 lines (vs current ~2500 lines). The tabs have been reorganized. Key additions and removals need to be compared, but broadly the current tabs contain a superset of the old UI. The main issue is **settings that exist in the model but lack UI exposure**, not the reverse.

---

## Section 4 — Config Flow Bugs (Silent Failures, Multiple AppConfig, etc.)

### 4.1 Multiple AppConfig Instances (HIGH PRIORITY)

**Problem:** Three separate `AppConfig()` calls create independent instances, each with their own settings copy:

| File | Line | Context |
|------|------|---------|
| `vsg_qt/main_window/window.py` | 32 | `self.config = AppConfig()` — Main window (primary instance) |
| `vsg_qt/font_manager_dialog/ui.py` | 61 | `config = AppConfig()` — Font manager creates its own |
| `vsg_qt/subtitle_editor/tabs/styles_tab.py` | 221 | `config = AppConfig()` — Style tab creates its own |

**Why it breaks:** Each `AppConfig()` constructor calls `self.load()` which reads from `settings.json`. If one instance modifies settings in memory (e.g., via Options dialog → `config.settings.xxx = value`), the other instances don't see the change. They have stale copies. When any of them calls `save()`, it writes its stale copy to disk, **overwriting changes made by other instances**.

**Scenario:**
1. User opens Options, changes `fonts_directory`
2. Options dialog calls `save_to_config()` → writes to main config's settings
3. Main config saves to disk
4. User opens Font Manager → `AppConfig()` reads from disk (gets updated value)
5. But if Font Manager was already open before step 2, it has stale value

### 4.2 Silent Failure in OptionsLogic.save_to_config()

**File:** `vsg_qt/options_dialog/logic.py:28-35`

```python
def save_to_config(self, cfg: AppSettings) -> None:
    from pydantic import ValidationError
    for section in self.dlg.sections.values():
        for key, widget in section.items():
            value = self._get_widget_val(widget)
            if hasattr(cfg, key):
                try:
                    setattr(cfg, key, value)
                except ValidationError:
                    pass  # Keep previous value if widget sends invalid data
```

**Problem:** `except ValidationError: pass` silently drops the user's setting. No warning, no log, no user feedback. If a widget returns an unexpected type or value, the user's choice is silently ignored.

**Old behavior:** `cfg[key] = self._get_widget_val(widget)` — always wrote the value. If validation failed later, it was caught at `validate_all()` which warned the user.

### 4.3 Silent Failure in OptionsLogic.load_from_config()

**File:** `vsg_qt/options_dialog/logic.py:19-23`

```python
def load_from_config(self, cfg: AppSettings) -> None:
    for section in self.dlg.sections.values():
        for key, widget in section.items():
            value = getattr(cfg, key, None)
            self._set_widget_val(widget, value)
```

**Problem:** `getattr(cfg, key, None)` returns `None` for any missing attribute. Then `_set_widget_val` (line 79) does `if value is None: return` — **silently skips the widget**. This means:
- If a widget key doesn't match any AppSettings field name, the widget shows its hardcoded default instead of the config value
- No warning is emitted for the mismatch

### 4.4 Silent Failure in AppConfig.load() Recovery

**File:** `vsg_core/config.py:238-256`

```python
except ValidationError:
    # Field-by-field recovery
    self.settings = AppSettings.from_config(self.defaults)
    rejected: list[str] = []
    for key, value in loaded_settings.items():
        if key not in self.defaults:
            continue
        try:
            setattr(self.settings, key, value)
        except (ValidationError, ValueError, TypeError):
            rejected.append(key)
```

**Problem:** While this does warn about rejected fields, the **entire settings file triggers full reset** on ANY single validation error. This is much more aggressive than the old behavior which simply coerced types and warned.

### 4.5 AppConfig.set() Returns Bool But Old Code Expected Raise

**File:** `vsg_core/config.py:310-331`

```python
def set(self, key: str, value: Any) -> bool:
    try:
        setattr(self.settings, key, value)
        return True
    except ValidationError:
        warnings.warn(...)
        return False
```

**Old behavior:** `config.set(key, value)` raised `ValueError` on invalid input. New behavior returns `False` silently. Any code that relied on the exception for control flow would now silently proceed with stale values.

### 4.6 get_orphaned_keys() Always Returns Empty Set

**File:** `vsg_core/config.py:384-401`

```python
def get_orphaned_keys(self) -> builtins.set[str]:
    """Note: With AppSettings Pydantic model, this always returns empty set"""
    return set()

def remove_orphaned_keys(self) -> builtins.set[str]:
    """Note: With AppSettings Pydantic model, this is a no-op"""
    return set()
```

**Problem:** The "Remove Invalid Config Entries" button in Storage tab (`ui.py:108-143`) calls `get_orphaned_keys()` which always returns empty. The button is now **completely non-functional** — it always says "No invalid config entries found" even if the JSON has orphaned keys. The old version actually detected and removed them.

### 4.7 Pydantic `extra="ignore"` Silently Drops Unknown Keys

**File:** `vsg_core/models/settings.py:56`

```python
model_config = ConfigDict(
    extra="ignore",  # Unknown JSON keys are silently dropped
)
```

**Combined with 4.6:** If `settings.json` has old/orphaned keys, they are silently ignored on load. The user has no way to know they exist or clean them up.

---

## Section 5 — Dict Schema / Migration Plan

### 5.1 Dict-Based Structures at Risk of KeyError

#### 5.1.1 ManualLayoutItem (context_types.py)

Defined as `TypedDict(total=False)` — all fields are optional. However, runtime code may assume certain keys exist:

**Files accessing layout items with bracket notation:**
- `vsg_core/job_layouts/signature.py:42`: `track.get("type", "unknown")` — safe (uses `.get()`)
- `vsg_core/job_layouts/signature.py:77`: `track.get("id")` — safe
- `vsg_core/job_layouts/signature.py:78`: `track.get("codec_id", "")` — safe
- `vsg_core/job_layouts/manager.py:152`: `source_data.get("attachment_sources", [])` — safe

The job layout code generally uses `.get()` with defaults, which is correct.

#### 5.1.2 source_settings Dict

**File:** `vsg_core/orchestrator/steps/analysis_step.py:101`
```python
per_source = source_settings.get(source_key, {})
return per_source.get("use_source_separation", False)
```
Safe — uses `.get()` with defaults throughout.

#### 5.1.3 chunk_results Dicts (analysis/sync_stability.py)

```python
raw_delays = [r.get("raw_delay", float(r.get("delay", 0))) for r in accepted]
```
Uses nested `.get()` — safe but fragile. If `"delay"` is also missing, `float(None)` would crash. However, `r.get("delay", 0)` provides a fallback.

#### 5.1.4 job_result Dicts (reporting/report_writer.py)

Extensive `.get()` usage throughout — appears safe.

### 5.2 Migration / Normalization Boundary Proposal

**Current state:** Dict validation is scattered. Some dicts use TypedDict for static checking, some are untyped.

**Proposed single normalization boundary:**

Create a `normalize_layout_item(raw: dict) -> ManualLayoutItem` function in `vsg_core/job_layouts/validation.py` that:
1. Ensures all required keys are present (with defaults for missing ones)
2. Coerces types (str → int for track IDs, etc.)
3. Is called once when layouts are loaded from JSON (persistence.py)
4. Returns a guaranteed-complete TypedDict

Similarly for `normalize_source_settings(raw: dict) -> SourceSettings`.

This creates a single "trust boundary" — code after normalization can safely use bracket access.

---

## Section 6 — Validation Plan (Literal Switches, Defaults, Coercion Rules)

### 6.1 String Fields That Need Literal Type Constraints

These settings are "string switches" — they accept only specific values, but are currently typed as plain `str` in AppSettings with no validation:

| Setting | Current Type | Valid Values (from old `_validate_value`) | Runtime File |
|---------|-------------|-------------------------------------------|-------------|
| `source_separation_mode` | `str` | `"none"`, `"instrumental"`, `"vocals"` | `analysis/source_separation.py` |
| `source_separation_device` | `str` | `"auto"`, `"cpu"`, `"cuda"`, `"rocm"`, `"mps"` | `analysis/source_separation.py` |
| `source_separation_model` | `str` | `"default"` or model filename | `analysis/source_separation.py` |
| `filtering_method` | `str` | `"None"`, `"Low-Pass Filter"`, `"Dialogue Band-Pass Filter"` | `analysis/audio_corr.py` |
| `correlation_method` | `str` | `"Standard Correlation (SCC)"`, `"Phase Correlation (GCC-PHAT)"`, `"Onset Detection"`, `"GCC-SCOT"`, `"DTW (Dynamic Time Warping)"`, `"Spectrogram Correlation"`, `"VideoDiff"` | `analysis/audio_corr.py` |
| `correlation_method_source_separated` | `str` | Same minus VideoDiff | `analysis/audio_corr.py` |
| `delay_selection_mode` | `str` | `"Mode (Most Common)"`, `"Mode (Clustered)"`, `"Mode (Early Cluster)"`, `"First Stable"`, `"Average"` | `orchestrator/steps/analysis_step.py` |
| `delay_selection_mode_source_separated` | `str` | Same as above | `orchestrator/steps/analysis_step.py` |
| `sync_mode` | `str` | `"positive_only"`, `"allow_negative"` | `orchestrator/steps/analysis_step.py` |
| `subtitle_sync_mode` | `str` | `"time-based"`, `"timebase-frame-locked-timestamps"`, `"duration-align"`, `"correlation-frame-snap"`, `"subtitle-anchored-frame-snap"`, `"correlation-guided-frame-anchor"`, `"video-verified"` | `orchestrator/steps/subtitles_step.py` |
| `subtitle_rounding` | `str` | `"floor"`, `"round"`, `"ceil"` | `orchestrator/steps/subtitles_step.py` |
| `videotimestamps_snap_mode` | `str` | `"start"`, `"exact"` | subtitle sync code |
| `frame_hash_algorithm` | `str` | `"dhash"`, `"phash"`, `"average_hash"`, `"whash"` | frame matching code |
| `frame_comparison_method` | `str` | `"hash"`, `"ssim"`, `"mse"` | frame matching code |
| `stepping_silence_detection_method` | `str` | `"smart_fusion"`, `"ffmpeg_silencedetect"`, `"rms_basic"` | stepping code |
| `stepping_boundary_mode` | `str` | `"start"`, `"majority"`, `"midpoint"` | `subtitles_step.py` |
| `stepping_correction_mode` | `str` | `"full"`, `"filtered"`, `"strict"`, `"disabled"` | `drift_detection.py` |
| `stepping_quality_mode` | `str` | `"strict"`, `"normal"`, `"lenient"`, `"custom"` | `drift_detection.py` |
| `stepping_filtered_fallback` | `str` | `"nearest"`, `"interpolate"`, `"uniform"`, `"skip"`, `"reject"` | stepping code |
| `stepping_fill_mode` | `str` | `"silence"`, `"auto"`, `"content"` | stepping code |
| `stepping_video_snap_mode` | `str` | `"scenes"`, `"keyframes"`, `"any_frame"` | stepping code |
| `segment_resample_engine` | `str` | `"aresample"`, `"atempo"`, `"rubberband"` | resampling code |
| `segment_rb_transients` | `str` | `"crisp"`, `"mixed"`, `"smooth"` | rubberband code |
| `interlaced_force_mode` | `str` | `"auto"`, `"interlaced"`, `"telecine"`, `"progressive"` | interlaced code |
| `interlaced_deinterlace_method` | `str` | `"bwdif"`, `"yadif"`, `"yadifmod"`, `"bob"`, `"w3fdif"` | interlaced code |
| `interlaced_comparison_method` | `str` | `"hash"`, `"ssim"`, `"mse"` | interlaced code |
| `interlaced_hash_algorithm` | `str` | `"ahash"`, `"phash"`, `"dhash"`, `"whash"` | interlaced code |
| `ocr_engine` | `str` | `"tesseract"`, `"easyocr"`, `"paddleocr"` | OCR code |
| `ocr_output_format` | `str` | `"ass"`, `"srt"` | OCR code |
| `ocr_binarization_method` | `str` | `"otsu"` (and possibly others) | OCR preprocessing |
| `corr_anchor_fallback_mode` | `str` | `"use-correlation"`, `"use-median"`, `"abort"` | corr-guided code |
| `sub_anchor_fallback_mode` | `str` | `"abort"`, `"use-median"` | sub-anchored code |
| `correlation_snap_fallback_mode` | `str` | `"snap-to-frame"`, `"use-raw"`, `"abort"` | corr-snap code |
| `duration_align_fallback_mode` | `str` | `"none"`, `"abort"`, `"duration-offset"` | duration-align code |
| `sync_stability_outlier_mode` | `str` | `"any"`, `"threshold"` | sync_stability.py |

### 6.2 Recommended Approach

Per Rules.txt preference for `Literal[...]` types:

```python
# In vsg_core/models/types.py, add:
SourceSeparationModeStr = Literal["none", "instrumental", "vocals"]
FilteringMethodStr = Literal["None", "Low-Pass Filter", "Dialogue Band-Pass Filter"]
# ... etc for all string switches above
```

Then in `AppSettings`:
```python
source_separation_mode: SourceSeparationModeStr = "none"
```

Pydantic will automatically validate on load and assignment.

### 6.3 Default Changes to Restore

| Setting | Current Default | Old Default | Action |
|---------|----------------|-------------|--------|
| `analysis_lang_source1` | `None` | `""` | **Change to `""`** to match old behavior |
| `analysis_lang_others` | `None` | `""` | **Change to `""`** to match old behavior |
| `duration_align_fallback_mode` | `"duration-offset"` | `"none"` | **Change to `"none"`** to restore old default |
| `ocr_char_blacklist` | `"\|"` | `""` | **Discuss** — this may be an intentional improvement |
| `segment_resample_engine` valid values | includes `"atempo"` | only `"aresample"`, `"rubberband"` | **Discuss** — `atempo` is new |

---

## Section 7 — Step-by-Step Fix Plan (Ordered Commits)

### Commit 1: Add Literal types for all string switches
**Files:** `vsg_core/models/types.py`, `vsg_core/models/settings.py`
**What:** Define Literal type aliases for all 30+ string switch settings (Section 6.1). Update AppSettings fields to use them.
**Why:** Prevents invalid string values from entering the system. Pydantic validates automatically.
**Risk:** Low — additive change, existing valid values will pass validation. Any broken saved config values will be caught by field-by-field recovery.
**Size:** Medium

### Commit 2: Restore changed defaults
**Files:** `vsg_core/models/settings.py`
**What:**
- `analysis_lang_source1`: `None` → `""`
- `analysis_lang_others`: `None` → `""`
- `duration_align_fallback_mode`: `"duration-offset"` → `"none"`
**Why:** Restores old behavior per Section 1.2.
**Risk:** Low — restores known-good behavior.
**Size:** Small

### Commit 3: Fix OptionsLogic silent failures
**Files:** `vsg_qt/options_dialog/logic.py`
**What:**
- In `save_to_config()`: Replace `except ValidationError: pass` with a warning log + user notification
- In `load_from_config()`: Add warning when `getattr(cfg, key, None)` returns `None` for a key that should exist
**Why:** Users need to know when their settings are rejected.
**Risk:** Low — adds logging, no behavior change for valid settings.
**Size:** Small

### Commit 4: Fix get_orphaned_keys() to actually work
**Files:** `vsg_core/config.py`
**What:** Read settings.json directly and compare keys against AppSettings.get_field_names(). Return keys in JSON but not in model.
**Why:** The "Remove Invalid Config Entries" button is completely broken (Section 4.6).
**Risk:** Low — read-only comparison against JSON file.
**Size:** Small

### Commit 5: Centralize AppConfig — remove duplicate instantiations ✅ DONE
**Files:** `vsg_core/config.py`, `vsg_qt/font_manager_dialog/ui.py`, `vsg_qt/subtitle_editor/tabs/styles_tab.py`
**What:** Added standalone `get_config_dir_path()` and `get_fonts_dir_path()` helpers to `config.py`. `StylesTab` now uses `get_config_dir_path()` instead of `AppConfig()`. `FontManagerDialog` accepts `fonts_dir` as parameter, falls back to `get_fonts_dir_path()`.
**Risk:** Low — standalone helpers compute the same paths without loading settings.
**Size:** Small

### Commit 6: Add explicit warnings for unvalidated settings on load
**Files:** `vsg_core/config.py`
**What:** In `load()`, after field-by-field recovery, log which fields were reset and their old vs new values. Use `warnings.warn()` (already partially done but can be improved).
**Risk:** Low — logging only.
**Size:** Small

### Commit 7: Wire missing settings to UI (batch 1 — high-priority)
**Files:** `vsg_qt/options_dialog/tabs.py`
**What:** Add UI widgets for the most impactful missing settings:
- `source_separation_device` (Analysis tab)
- `source_separation_timeout` (Analysis tab)
- `fonts_directory` (Storage tab)
- `post_mux_normalize_timestamps` (new Merge Behavior tab)
- `post_mux_strip_tags` (new Merge Behavior tab)
- `subtitle_target_fps` (Subtitle Sync tab)
**Why:** These are user-facing settings that can't be configured without editing JSON.
**Risk:** Low — additive UI, no behavior change.
**Size:** Medium

### Commit 8: Wire missing settings to UI (batch 2 — advanced)
**Files:** `vsg_qt/options_dialog/tabs.py`
**What:** Add widgets for remaining advanced settings from Section 2.1 that are actively used in runtime code.
**Risk:** Low — additive UI.
**Size:** Large

### Commit 9: Document intentionally-hidden settings
**Files:** `vsg_core/models/settings.py`
**What:** Add comments to intentionally-hidden settings like `last_ref_path`, `last_sec_path`, `last_ter_path` (managed by main window, not user-editable via Options). Also add `videotimestamps_rounding` to the Subtitle Sync tab UI (it is used in `timing.py` but has no widget).
**Risk:** Low — documentation + minor UI addition.
**Size:** Small

### Commit 10: Add dict normalization boundary for layout items
**Files:** `vsg_core/job_layouts/validation.py`
**What:** Add `normalize_layout_item()` that fills in defaults for missing keys. Call it in `LayoutPersistence` when loading from JSON.
**Why:** Prevents potential KeyError on layout dicts with missing keys (Section 5.2).
**Risk:** Low — additive, provides defaults for missing keys.
**Size:** Small

---

## Appendix A: Complete Widget-to-Setting Map (Current)

Tabs and their widget keys (from `vsg_qt/options_dialog/tabs.py`):

### StorageTab
`output_folder`, `temp_root`, `logs_folder`, `videodiff_path`, `ocr_custom_wordlist_path`

### OCRTab
`ocr_enabled`, `ocr_engine`, `ocr_language`, `ocr_char_blacklist`, `ocr_preprocess_auto`, `ocr_force_binarization`, `ocr_upscale_threshold`, `ocr_cleanup_enabled`, `ocr_cleanup_normalize_ellipsis`, `ocr_low_confidence_threshold`, `timing_fix_enabled`, `timing_fix_overlaps`, `timing_overlap_min_gap_ms`, `timing_fix_short_durations`, `timing_min_duration_ms`, `timing_fix_long_durations`, `timing_max_cps`, `ocr_output_format`, `ocr_font_size_ratio`, `ocr_preserve_positions`, `ocr_bottom_threshold`, `ocr_generate_report`, `ocr_save_debug_images`, `ocr_debug_output`

### AnalysisTab
`source_separation_mode`, `source_separation_model`, `source_separation_model_dir`, `filtering_method`, `audio_bandlimit_hz`, `correlation_method`, `correlation_method_source_separated`, `scan_chunk_count`, `scan_chunk_duration`, `min_match_pct`, `min_accepted_chunks`, `delay_selection_mode`, `delay_selection_mode_source_separated`, `first_stable_min_chunks`, `first_stable_skip_unstable`, `early_cluster_window`, `early_cluster_threshold`, `multi_correlation_enabled`, `multi_corr_scc`, `multi_corr_gcc_phat`, `multi_corr_onset`, `multi_corr_gcc_scot`, `multi_corr_gcc_whiten`, `multi_corr_dtw`, `multi_corr_spectrogram`, `scan_start_percentage`, `scan_end_percentage`, `filter_bandpass_lowcut_hz`, `filter_bandpass_highcut_hz`, `filter_bandpass_order`, `filter_lowpass_taps`, `analysis_lang_source1`, `analysis_lang_others`, `sync_mode`, `use_soxr`, `audio_peak_fit`, `log_audio_drift`

### SteppingTab
`segmented_enabled`, `detection_dbscan_epsilon_ms`, `detection_dbscan_min_samples`, `segment_triage_std_dev_ms`, `drift_detection_r2_threshold`, `drift_detection_r2_threshold_lossless`, `drift_detection_slope_threshold_lossy`, `drift_detection_slope_threshold_lossless`, `stepping_correction_mode`, `stepping_quality_mode`, `stepping_filtered_fallback`, `stepping_min_chunks_per_cluster`, `stepping_min_cluster_percentage`, `stepping_min_cluster_duration_s`, `stepping_min_match_quality_pct`, `stepping_min_total_clusters`, `stepping_first_stable_min_chunks`, `stepping_first_stable_skip_unstable`, `stepping_scan_start_percentage`, `stepping_scan_end_percentage`, `segment_coarse_chunk_s`, `segment_coarse_step_s`, `segment_search_locality_s`, `segment_min_confidence_ratio`, `segment_fine_chunk_s`, `segment_fine_iterations`, `segmented_qa_threshold`, `segment_qa_chunk_count`, `segment_qa_min_accepted_chunks`, `segment_resample_engine`, `segment_rb_pitch_correct`, `segment_rb_transients`, `segment_rb_smoother`, `segment_rb_pitchq`, `stepping_fill_mode`, `stepping_content_correlation_threshold`, `stepping_content_search_window_s`, `segment_drift_r2_threshold`, `segment_drift_slope_threshold`, `segment_drift_outlier_sensitivity`, `segment_drift_scan_buffer_pct`, `stepping_corrected_track_label`, `stepping_preserved_track_label`, `stepping_adjust_subtitles`, `stepping_adjust_subtitles_no_audio`, `stepping_boundary_mode`, `stepping_diagnostics_verbose`, `stepping_silence_detection_method`, `stepping_vad_enabled`, `stepping_vad_aggressiveness`, `stepping_transient_detection_enabled`, `stepping_transient_threshold`, `stepping_snap_to_silence`, `stepping_silence_search_window_s`, `stepping_silence_threshold_db`, `stepping_silence_min_duration_ms`, `stepping_snap_to_video_frames`, `stepping_video_snap_mode`, `stepping_video_snap_max_offset_s`, `stepping_video_scene_threshold`

### SubtitleSyncTab
`subtitle_sync_mode`, `frame_hash_algorithm`, `frame_hash_size`, `frame_hash_threshold`, `frame_window_radius`, `frame_search_range_ms`, `frame_agreement_tolerance_ms`, `frame_use_vapoursynth`, `frame_comparison_method`, `subtitle_rounding`, `time_based_use_raw_values`, `duration_align_validate`, `duration_align_validate_points`, `duration_align_strictness`, `duration_align_verify_with_frames`, `duration_align_skip_validation_generated_tracks`, `duration_align_fallback_mode`, `frame_lock_submillisecond_precision`, `videotimestamps_snap_mode`, `correlation_snap_fallback_mode`, `sub_anchor_fallback_mode`, `corr_anchor_fallback_mode`, `corr_anchor_refine_per_line`, `corr_anchor_refine_workers`, `video_verified_zero_check_frames`, `video_verified_min_quality_advantage`, `video_verified_num_checkpoints`, `video_verified_search_range_frames`, `video_verified_sequence_length`, `video_verified_use_pts_precision`, `video_verified_frame_audit`, `interlaced_handling_enabled`, `interlaced_force_mode`, `interlaced_hash_algorithm`, `interlaced_hash_size`, `interlaced_hash_threshold`, `interlaced_sequence_length`, `interlaced_num_checkpoints`, `interlaced_search_range_frames`, `interlaced_deinterlace_method`, `interlaced_comparison_method`, `interlaced_use_ivtc`, `interlaced_fallback_to_audio`

### ChaptersTab / MergeBehaviorTab / LoggingTab
(Remaining settings for chapters, muxing, and logging — verified present and wired)

## Appendix B: All AppSettings Fields (Current)

Total: ~187 fields. See `vsg_core/models/settings.py` for the complete list.
