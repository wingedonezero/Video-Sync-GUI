# Phantom Signs Track Feature - Implementation Plan

## Overview

This feature allows users to create "phantom" or generated subtitle tracks that filter specific styles from an existing subtitle track. The primary use case is creating a verified "signs" track from a full subtitle track by excluding certain styles (e.g., removing "Default" dialogue, keeping only "Sign" and other non-dialogue styles).

## User Requirements

1. **Right-click Context Menu**: Right-click on a subtitle track → "Create Signs Track" option
2. **Phantom Track Creation**: Creates a track that:
   - Doesn't physically exist in the source (will be generated)
   - Appears in the track list for ordering and configuration
   - Can be named, ordered, and have defaults set like normal tracks
   - Links to a source track + style filter configuration
3. **Style Selection**: UI to choose which styles to include/exclude
4. **Layout Compatibility**: Must work with copy/paste layouts without breaking existing functionality
5. **Processing**: During job execution, generates the filtered subtitle file and processes it normally

## Current Architecture Understanding

### Track Selection Window
- **Location**: `vsg_qt/manual_selection_dialog/`
- **Key Components**:
  - `FinalList` - Right side track list with drag-drop ordering
  - `TrackWidget` - Individual track representation
  - Context menu in `FinalList._show_context_menu()`

### Track Data Model
- Tracks are dictionaries with fields: `source`, `original_path`, `id`, `type`, `codec_id`, `lang`, `name`, etc.
- Extended with UI state: `is_default`, `is_forced_display`, `custom_name`, `custom_lang`, `style_patch`, etc.

### Layout System
- **Location**: `vsg_core/models/layout_manager.py`
- Layouts saved to `{temp_root}/job_layouts/{job_id}.json`
- Copy/paste uses `structure_signature` and `track_signature` for matching
- **Critical**: Must not break existing matching logic

### Subtitle Processing
- **Location**: `vsg_core/orchestrator/steps/subtitles_step.py`
- **Style Engine**: `vsg_core/subtitles/style_engine.py` (uses pysubs2)
- Pipeline: Extract → OCR → Timing Correction → SRT→ASS → Style Patch → Rescale → Font Size

## Implementation Plan

### Phase 1: Data Model Extensions

#### 1.1 Track Data Structure
Add new fields to track dictionaries to mark them as phantom:

```python
{
    # Existing fields...
    'phantom': True,                          # NEW: Marks this as a phantom track
    'phantom_source_track_id': 2,             # NEW: ID of the source track
    'phantom_source_path': '/path/to/src',    # NEW: Path to source subtitle file
    'phantom_filter_mode': 'exclude',         # NEW: 'include' or 'exclude'
    'phantom_filter_styles': ['Default'],     # NEW: Styles to include/exclude
    'phantom_verification': {                 # NEW: Verification info
        'expected_removed_count': 0,
        'verify_no_content_changes': True
    }
}
```

**Files to modify**:
- Document in comments where track dictionaries are created/used
- No schema enforcement needed (dicts are flexible)

#### 1.2 PlanItem Extensions
Extend `vsg_core/models/jobs.py` → `PlanItem` dataclass:

```python
@dataclass
class PlanItem:
    # Existing fields...

    # NEW: Phantom track fields
    is_phantom: bool = False
    phantom_source_track_id: Optional[int] = None
    phantom_source_path: Optional[str] = None
    phantom_filter_mode: str = 'exclude'  # 'include' or 'exclude'
    phantom_filter_styles: List[str] = field(default_factory=list)
    phantom_verify_no_changes: bool = True
```

**Files to modify**:
- `vsg_core/models/jobs.py` - Add fields to `PlanItem`

### Phase 2: UI - Context Menu

#### 2.1 Add "Create Signs Track" Menu Option
Extend `vsg_qt/manual_selection_dialog/widgets.py` → `FinalList._show_context_menu()`:

```python
def _show_context_menu(self, position):
    # ... existing code ...

    # Only show for subtitle tracks
    if track_type == TrackType.SUBTITLES:
        menu.addSeparator()
        create_phantom_action = menu.addAction("Create Signs Track...")
        # Connect to handler
```

**Implementation**:
- Check if selected track is subtitles and text-based (ASS/SSA/SRT)
- Disable for image-based subtitles (PGS/VobSub) - can't filter by style
- Open style selection dialog

**Files to modify**:
- `vsg_qt/manual_selection_dialog/widgets.py` - Extend context menu

#### 2.2 Style Selection Dialog
Create new dialog: `vsg_qt/phantom_track_dialog/`

**Components**:
- **StyleSelectionDialog** UI with:
  - Preview of available styles from source subtitle
  - Checkboxes for each style (with event counts)
  - "Include" vs "Exclude" mode toggle
  - Preview: "X events will be included, Y will be excluded"
  - Track naming field (default: "{original_name} (Signs)")
  - Verification option: "Verify no content changes except removal"
  - OK/Cancel buttons

**Logic**:
1. Load source subtitle using `StyleEngine`
2. Extract all style names with event counts
3. Let user select styles and mode
4. Return configuration for phantom track creation

**Files to create**:
- `vsg_qt/phantom_track_dialog/__init__.py`
- `vsg_qt/phantom_track_dialog/ui.py`
- `vsg_qt/phantom_track_dialog/logic.py`

### Phase 3: UI - Phantom Track Widget

#### 3.1 Visual Distinction
Modify `vsg_qt/track_widget/` to visually distinguish phantom tracks:

**Visual indicators**:
- Special icon/badge showing it's a generated track
- Lighter background color or dashed border
- Subtitle showing: "Generated from Track X (excluding: Default)"

**Disabled controls**:
- OCR options (not applicable - source is already text)
- Possibly rescale/size controls if they should match the source

**Additional controls**:
- Button to edit style filter ("Edit Filter...")
- Shows source track relationship

**Files to modify**:
- `vsg_qt/track_widget/ui.py` - Add visual indicators
- `vsg_qt/track_widget/logic.py` - Handle phantom track config

#### 3.2 Track Settings Integration
Extend `vsg_qt/track_settings_dialog/` to support phantom tracks:

**Additional tab or section**:
- "Style Filter" tab showing:
  - Source track info
  - Current filter mode and styles
  - Button to edit filter (opens style selection dialog)
  - Verification settings

**Files to modify**:
- `vsg_qt/track_settings_dialog/ui.py`
- `vsg_qt/track_settings_dialog/logic.py`

### Phase 4: Layout System Compatibility

#### 4.1 Layout Saving
Ensure phantom tracks are saved in layouts with all their configuration.

**Implementation**:
- Phantom fields are already in the track dictionary
- Will be saved automatically by `JobLayoutManager`
- No changes needed to saving logic

**Files to verify**:
- `vsg_core/models/layout_manager.py` - Verify dict serialization preserves phantom fields

#### 4.2 Layout Matching for Copy/Paste
**Challenge**: When pasting a layout with phantom tracks to a new job, need to:
1. Match the phantom track's source track to the new job's tracks
2. Recreate the phantom track relationship

**Solution**: Extend matching algorithm in `JobLayoutManager`:

```python
def _match_tracks_for_paste(saved_layout, new_tracks):
    """Match saved layout tracks (including phantoms) to new job's tracks"""

    # First pass: Match physical tracks normally
    physical_matches = _match_physical_tracks(saved_layout, new_tracks)

    # Second pass: Match phantom tracks
    for saved_track in saved_layout:
        if saved_track.get('phantom'):
            # Find the matched source track
            source_id = saved_track['phantom_source_track_id']
            if source_id in physical_matches:
                # Re-create phantom track referencing new source
                new_phantom = saved_track.copy()
                new_phantom['phantom_source_track_id'] = physical_matches[source_id].id
                new_phantom['phantom_source_path'] = physical_matches[source_id].path
                # Add to layout
```

**Files to modify**:
- `vsg_qt/job_queue_dialog/logic.py` - Extend `paste_layout()` logic
- May need helper in layout_manager for phantom track matching

### Phase 5: Processing Pipeline Integration

#### 5.1 Create Style Filter Module
Create new module: `vsg_core/subtitles/style_filter.py`

```python
class StyleFilterEngine:
    """Filters subtitle events by style name"""

    def __init__(self, subtitle_path: str):
        self.engine = StyleEngine(subtitle_path)

    def get_available_styles(self) -> Dict[str, int]:
        """Returns {style_name: event_count}"""

    def filter_by_styles(self, styles: List[str], mode: str = 'exclude') -> Dict[str, Any]:
        """
        Filters events by style.

        Args:
            styles: List of style names
            mode: 'include' (keep only these) or 'exclude' (remove these)

        Returns:
            {
                'original_count': int,
                'filtered_count': int,
                'removed_count': int,
                'styles_found': List[str],
                'styles_missing': List[str]
            }
        """

    def verify_content_unchanged(self, original_events, filtered_events) -> bool:
        """Verifies that only style filtering was done, no text changes"""
        # Compare event text content to ensure no modifications
```

**Files to create**:
- `vsg_core/subtitles/style_filter.py`

#### 5.2 Integrate into Extraction Step
Modify `vsg_core/orchestrator/steps/extract_step.py`:

**Logic**:
1. After extracting physical tracks, process phantom tracks
2. For each phantom track in layout:
   - Find the extracted source track file
   - Create a filtered copy using `StyleFilterEngine`
   - Save to temp directory with unique name
   - Create a `PlanItem` for the phantom track with the filtered file path

```python
class ExtractStep:
    def run(self, ctx: Context, runner: CommandRunner) -> Context:
        # ... existing extraction ...

        # NEW: Process phantom tracks
        phantom_items = self._create_phantom_tracks(ctx, runner)
        ctx.extracted_items.extend(phantom_items)

        return ctx

    def _create_phantom_tracks(self, ctx: Context, runner: CommandRunner) -> List[PlanItem]:
        """Create phantom track files and PlanItems"""
        phantom_items = []

        for track_cfg in ctx.plan.manual_layout:
            if not track_cfg.get('phantom'):
                continue

            # Find source track's extracted file
            source_item = self._find_source_item(
                ctx.extracted_items,
                track_cfg['phantom_source_track_id']
            )

            if not source_item:
                runner._log_message(f"[Phantom] Warning: Source track not found")
                continue

            # Filter the subtitle file
            filtered_path = self._create_filtered_subtitle(
                source_item.extracted_path,
                track_cfg,
                runner
            )

            # Create PlanItem for phantom track
            phantom_item = self._create_phantom_plan_item(
                track_cfg,
                filtered_path,
                source_item
            )
            phantom_items.append(phantom_item)

        return phantom_items
```

**Files to modify**:
- `vsg_core/orchestrator/steps/extract_step.py` - Add phantom track generation

#### 5.3 Subtitles Step Handling
Modify `vsg_core/orchestrator/steps/subtitles_step.py`:

**Logic**:
- Phantom tracks flow through normal processing
- Already have filtered content, so they just get:
  - Timing corrections (stepping, frame-perfect, etc.)
  - Font size multiplication (if configured)
  - Rescaling (if configured)
- Skip OCR (already text-based)

**No special handling needed** - they're just regular subtitle PlanItems at this point.

**Files to verify**:
- `vsg_core/orchestrator/steps/subtitles_step.py` - Ensure phantom tracks process correctly

#### 5.4 Verification and Logging
Add verification logging to subtitles step:

```python
if item.is_phantom and item.phantom_verify_no_changes:
    # Log verification results
    runner._log_message(
        f"[Phantom Track] Filtered {item.custom_name or 'track'}: "
        f"Removed {removed_count} events, kept {kept_count} events"
    )
```

**Files to modify**:
- Processing steps - Add logging for phantom track operations

### Phase 6: Testing and Edge Cases

#### 6.1 Edge Cases to Handle

1. **Source track deleted**: What if user deletes the source track after creating phantom?
   - **Solution**: Show warning, allow user to delete phantom or recreate from different source

2. **Source track modified**: User changes source track's styles
   - **Solution**: Phantom track uses the modified source automatically (re-reads on execution)

3. **Invalid style names**: Selected styles don't exist in current source file
   - **Solution**: Log warning, filter proceeds with available styles

4. **All events filtered out**: Filter removes all events
   - **Solution**: Log warning, create empty subtitle track (valid but empty)

5. **Multiple phantom tracks from same source**: User creates multiple filtered versions
   - **Solution**: Fully supported, each has independent filter config

6. **Phantom track in layouts with different source structure**:
   - **Solution**: Matching algorithm handles this in Phase 4.2

#### 6.2 UI Workflow Testing

Test complete workflows:
1. Create phantom track → configure → save layout → execute job
2. Create phantom track → copy layout → paste to different job → execute
3. Create phantom track → modify source track styles → execute
4. Create phantom track → delete source → verify error handling
5. Create multiple phantom tracks from same source with different filters

### Phase 7: Documentation

#### 7.1 User Documentation
Document the feature:
- How to create phantom signs tracks
- Style selection dialog usage
- Verification options
- Layout compatibility
- Common use cases

#### 7.2 Code Documentation
Add docstrings and comments:
- Phantom track data structure fields
- Style filter API
- Processing pipeline changes
- Layout matching logic

## Implementation Order

1. **Phase 1** - Data model (foundation)
2. **Phase 5.1** - Style filter module (core logic)
3. **Phase 2** - UI context menu and dialog (user interaction)
4. **Phase 3** - Track widget visualization (UI feedback)
5. **Phase 5.2, 5.3** - Processing pipeline integration (execution)
6. **Phase 4** - Layout system compatibility (copy/paste)
7. **Phase 5.4** - Verification and logging (polish)
8. **Phase 6** - Testing and edge cases (validation)
9. **Phase 7** - Documentation (completion)

## Key Design Decisions

### Decision 1: When to Generate Filtered File?
**Chosen**: During extract step (early in pipeline)
- **Rationale**: Phantom tracks become regular tracks early, flow through normal processing
- **Alternative**: Generate during subtitles step (too late, complicates logic)

### Decision 2: How to Store Phantom Relationship?
**Chosen**: Store source track ID + path in phantom track config
- **Rationale**: Simple, works with existing dict-based track system
- **Alternative**: Separate phantom track registry (over-engineered)

### Decision 3: Layout Matching Strategy?
**Chosen**: Two-pass matching (physical first, then phantoms)
- **Rationale**: Preserves existing matching logic, extends cleanly
- **Alternative**: Unified matching (too complex, risk of breaking existing)

### Decision 4: Visual Distinction?
**Chosen**: Badge + subtitle text showing relationship
- **Rationale**: Clear but non-intrusive
- **Alternative**: Completely different widget style (too different from normal tracks)

### Decision 5: Style Selection UI?
**Chosen**: Separate dialog on creation + editable in track settings
- **Rationale**: Clear workflow, allows refinement later
- **Alternative**: Inline in track widget (too cramped)

## Success Criteria

1. ✅ User can right-click subtitle track and create phantom signs track
2. ✅ Style selection dialog shows available styles with event counts
3. ✅ Phantom track appears in track list with visual distinction
4. ✅ Phantom track can be ordered, named, and configured like normal tracks
5. ✅ Copy/paste layouts preserves phantom tracks correctly
6. ✅ Job execution creates filtered subtitle file and processes it
7. ✅ Verification logging shows what was filtered
8. ✅ Edge cases handled gracefully (deleted source, missing styles, etc.)

## Files to Create

1. `vsg_core/subtitles/style_filter.py` - Style filtering engine
2. `vsg_qt/phantom_track_dialog/__init__.py` - Dialog package
3. `vsg_qt/phantom_track_dialog/ui.py` - Dialog UI
4. `vsg_qt/phantom_track_dialog/logic.py` - Dialog logic

## Files to Modify

1. `vsg_core/models/jobs.py` - Add PlanItem fields
2. `vsg_qt/manual_selection_dialog/widgets.py` - Context menu
3. `vsg_qt/track_widget/ui.py` - Visual indicators
4. `vsg_qt/track_widget/logic.py` - Phantom track handling
5. `vsg_qt/track_settings_dialog/ui.py` - Settings dialog extension
6. `vsg_qt/track_settings_dialog/logic.py` - Settings logic
7. `vsg_core/orchestrator/steps/extract_step.py` - Phantom generation
8. `vsg_qt/job_queue_dialog/logic.py` - Layout paste matching

## Estimated Complexity

- **Data Model**: Low (simple dict fields)
- **Style Filter**: Medium (pysubs2 manipulation)
- **UI Dialog**: Medium (new dialog, style listing)
- **Track Widget**: Low (badge/visual changes)
- **Processing Pipeline**: Medium (integration points)
- **Layout Matching**: High (complex logic, must not break existing)
- **Testing**: High (many edge cases and workflows)

**Overall**: Medium-High complexity feature

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking copy/paste layouts | Extensive testing, two-pass matching preserves existing logic |
| Performance with many styles | Lazy loading, cache style info, limit events shown |
| User confusion about phantom tracks | Clear visual indicators, help text, documentation |
| Source track changes breaking phantom | Graceful degradation, warnings in logs |
| Complex edge cases | Comprehensive edge case testing plan |

## Next Steps

1. Review plan with user for approval
2. Begin Phase 1 implementation
3. Create working branch for development
4. Implement and test each phase sequentially
5. Integration testing across all phases
6. Documentation and final review
