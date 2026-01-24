# Video-Sync-GUI Rewrite Plan

## AI Rules (Must Follow)

1. **Discuss Before Changes** - No implementations without approval
2. **Libs Discussed As Needed** - Research replacements/alternatives together
3. **Research, Don't Assume** - Especially for Rust, consult official docs
4. **Latest Lib Versions** - Use latest stable, discuss if issues arise
5. **Rewrite for Quality** - Same features, better architecture, no single points of failure

---

## Planned Architecture

### Core Principles
- **Separation of Concerns**: UI, Core Logic, and Data layers completely separate
- **Unidirectional Data Flow**: Data flows one direction to prevent state confusion
- **Immutable Data Passing**: Pass copies/new objects between components
- **Explicit Error Handling**: No silent failures, all errors surface appropriately
- **Single Responsibility**: Each module does one thing well

### Technology Stack (To Discuss)
- **UI**: PySide6 (or discuss alternatives)
- **Core**: Python + potential Rust modules for performance-critical paths
- **Data Models**: Pydantic or dataclasses with validation
- **IPC**: TBD if Rust modules used

### Key Patterns
- **Pipeline**: Clear step-based processing with validation gates
- **Repository Pattern**: Centralized data access
- **Event-Driven UI**: Signals/slots with clear boundaries
- **Context Objects**: Typed, immutable context passed through pipeline

---

## Reference Code Tracking

### Legend
- `[ ]` Not Started
- `[P]` Partial
- `[X]` Implemented

---

### Entry Point
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `main.py` | App entry, Qt init, env setup | Simplify, clean startup |

---

### Data Models (`vsg_core/models/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `enums.py` | TrackType, AnalysisMode, SnapMode | Keep clean enums |
| [ ] | `media.py` | Track, StreamProps, Attachment | Validate on creation |
| [ ] | `settings.py` | AppSettings config model | Add validation |
| [ ] | `jobs.py` | JobSpec, Delays, MergePlan, JobResult | Immutable where possible |
| [ ] | `converters.py` | Type conversions | Centralize all conversions |
| [ ] | `results.py` | Result types | Standardize result handling |

---

### Configuration (`vsg_core/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `config.py` | Settings persistence (JSON) | Single source of truth |

---

### Analysis (`vsg_core/analysis/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `audio_corr.py` | Audio cross-correlation delay detection | Core sync logic |
| [ ] | `drift_detection.py` | DBSCAN clustering for stepping/drift | Consider Rust for perf |
| [ ] | `sync_stability.py` | Delay consistency analysis | Quality metrics |
| [ ] | `videodiff.py` | Frame-based video sync | GPU acceleration TBD |
| [ ] | `source_separation.py` | Vocal isolation for cleaner correlation | Heavy DSP work |

---

### Audio Correction (`vsg_core/correction/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `linear.py` | Constant drift correction (resample) | ffmpeg based |
| [ ] | `pal.py` | PAL speed correction (50/60Hz) | ffmpeg based |
| [ ] | `stepping.py` | Stepping pattern correction | EDL-based timing |

---

### Subtitle Processing (`vsg_core/subtitles/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `data.py` | SubtitleData container | Single load, process, write |
| [ ] | `convert.py` | Format conversion | ASS/SRT handling |
| [ ] | `edit_plan.py` | Edit operations | Clear operation order |
| [ ] | `frame_utils.py` | Frame timing utilities | Precision critical |
| [ ] | `frame_verification.py` | Verify frame timing | Validation |
| [ ] | `checkpoint_selection.py` | Anchor point selection | Sync algorithm |

#### Subtitle Parsers/Writers
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `parsers/` | ASS/SRT parsing | Robust error handling |
| [ ] | `writers/` | ASS/SRT writing | Preserve formatting |
| [ ] | `operations/` | Style patches, rescaling | Composable ops |
| [ ] | `style.py` | Style definitions | |
| [ ] | `style_engine.py` | Style manipulation | |

#### OCR Subsystem (`vsg_core/subtitles/ocr/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `engine.py` | Tesseract wrapper | Confidence tracking |
| [ ] | `preprocessing.py` | Image enhancement | OpenCV based |
| [ ] | `postprocess.py` | Text cleanup | |
| [ ] | `pipeline.py` | OCR orchestration | Subprocess isolation |
| [ ] | `backends.py` | OCR backend abstraction | |
| [ ] | `dictionaries.py` | Custom word lists | |
| [ ] | `debug.py` | OCR debug output | |
| [ ] | `output.py` | OCR result formatting | |
| [ ] | `parsers/` | VobSub etc parsing | |
| [ ] | `preview_subprocess.py` | Preview in subprocess | Thread safety |

---

### Extraction (`vsg_core/extraction/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `tracks.py` | Track extraction (ffmpeg/mkvextract) | Probe codec info |
| [ ] | `attachments.py` | Attachment extraction | Fonts, etc |

---

### Muxing (`vsg_core/mux/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `options_builder.py` | Build mkvmerge command tokens | Token-based |

---

### Pipeline/Orchestration
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `pipeline.py` (legacy) | Old linear orchestrator | Reference only |
| [ ] | `orchestrator/pipeline.py` | New step-based orchestrator | Preferred pattern |
| [ ] | `orchestrator/validation.py` | Step validation | Gate between steps |
| [ ] | `orchestrator/steps/context.py` | Shared context object | Immutable passing |

#### Pipeline Steps
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `steps/analysis_step.py` | Calculate sync delays | |
| [ ] | `steps/extract_step.py` | Extract tracks | |
| [ ] | `steps/audio_correction_step.py` | Apply corrections | |
| [ ] | `steps/subtitles_step.py` | Process subtitles | |
| [ ] | `steps/chapters_step.py` | Handle chapters | |
| [ ] | `steps/attachments_step.py` | Handle attachments | |
| [ ] | `steps/mux_step.py` | Build merge command | |

#### Pipeline Components (legacy)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `pipeline_components/tool_validator.py` | Validate tools exist | |
| [ ] | `pipeline_components/log_manager.py` | Logging setup | |
| [ ] | `pipeline_components/sync_planner.py` | Plan sync strategy | |
| [ ] | `pipeline_components/sync_executor.py` | Execute sync | |
| [ ] | `pipeline_components/output_writer.py` | Write output | |
| [ ] | `pipeline_components/result_auditor.py` | Audit results | |

---

### Job Management
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `job_discovery.py` | Find/match source files | |

#### Job Layouts (`vsg_core/job_layouts/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `manager.py` | Layout API | |
| [ ] | `signature.py` | File signatures | |
| [ ] | `persistence.py` | Save/load JSON | |
| [ ] | `validation.py` | Layout validation | |

---

### Post-Processing (`vsg_core/postprocess/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `final_auditor.py` | Coordinate all auditors | |
| [ ] | `finalizer.py` | Output finalization | |
| [ ] | `chapter_backup.py` | Chapter backup | |

#### Auditors (`vsg_core/postprocess/auditors/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `base.py` | Base auditor class | |
| [ ] | `track_flags.py` | Default/forced flags | |
| [ ] | `audio_sync.py` | Verify sync applied | |
| [ ] | `audio_quality.py` | Audio integrity | |
| [ ] | `audio_channels.py` | Channel layout | |
| [ ] | `audio_object_based.py` | Atmos/DTS:X | |
| [ ] | `drift_correction.py` | Drift fix validation | |
| [ ] | `stepping_correction.py` | Stepping validation | |
| [ ] | `global_shift.py` | Global shift check | |
| [ ] | `video_metadata.py` | Video properties | |
| [ ] | `subtitle_formats.py` | Subtitle integrity | |
| [ ] | `chapters.py` | Chapter validation | |
| [ ] | `attachments.py` | Attachment validation | |
| [ ] | `track_order.py` | Track ordering | |
| [ ] | `track_names.py` | Track naming | |
| [ ] | `language_tags.py` | Language tags | |
| [ ] | `codec_integrity.py` | Codec checks | |
| [ ] | `dolby_vision.py` | DV layer handling | |

---

### Chapters (`vsg_core/chapters/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `process.py` | Chapter processing | |
| [ ] | `keyframes.py` | Keyframe handling | |

---

### Audit Trail (`vsg_core/audit/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `trail.py` | Debug audit trail | Pipeline debugging |

---

### Reporting (`vsg_core/reporting/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `report_writer.py` | Markdown reports | |

---

### I/O (`vsg_core/io/`)
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `runner.py` | Command execution | Subprocess handling |

---

### Utilities
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `font_manager.py` | Font replacement | |
| [ ] | `favorite_colors.py` | Color presets | |

---

### UI Layer (`vsg_qt/`)

#### Main Window
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `main_window/window.py` | UI shell | |
| [ ] | `main_window/controller.py` | Main logic | Clean MVC |

#### Worker/Threading
| Status | File | Purpose | Notes |
|--------|------|---------|-------|
| [ ] | `worker/runner.py` | Background job runner | Thread pool |
| [ ] | `worker/signals.py` | Qt signals | Thread-safe |

#### Dialogs
| Status | Dialog | Purpose | Notes |
|--------|--------|---------|-------|
| [ ] | `job_queue_dialog/` | Batch queue management | |
| [ ] | `track_settings_dialog/` | Track configuration | |
| [ ] | `manual_selection_dialog/` | Manual track mapping | |
| [ ] | `options_dialog/` | Global settings | |
| [ ] | `style_editor_dialog/` | Subtitle style editor | Video preview |
| [ ] | `track_widget/` | Track display widget | |
| [ ] | `report_dialogs/` | Results display | |
| [ ] | `add_job_dialog/` | Add new jobs | |
| [ ] | `font_manager_dialog/` | Font editor | |
| [ ] | `ocr_dictionary_dialog/` | OCR word lists | |
| [ ] | `source_settings_dialog/` | Source correlation | |
| [ ] | `sync_exclusion_dialog/` | Style exclusions | |
| [ ] | `resample_dialog/` | Resampling options | |
| [ ] | `generated_track_dialog/` | Filtered tracks | |
| [ ] | `favorites_dialog/` | Favorites | |
| [ ] | `batch_completion_dialog/` | Batch results | |

---

## Implementation Order (Suggested)

1. **Foundation**: Models, Enums, Config
2. **Core Pipeline**: Orchestrator, Context, Steps
3. **Analysis**: Audio correlation, drift detection
4. **Processing**: Corrections, Subtitles
5. **Extraction/Muxing**: Track handling, mkvmerge
6. **Validation**: Auditors, Post-processing
7. **UI**: Main window, Dialogs, Workers
8. **Polish**: Reporting, Layouts, Edge cases

---

## Session Notes

_Add notes here as we progress_

- **2025-01-24**: Initial plan created from Reference Only original analysis
