# Next Development Session Prompt

Use this prompt to continue development in a new chat session:

---

## Context

I'm working on the **Video Sync GUI** Rust implementation, a libcosmic-based replacement for the Python PySide6 interface.

**Current Branch:** `claude/fix-iterator-lifetime-error-brTiQ`

**Build Status:** ✅ Compiles successfully
- Run `cargo check` to verify
- 41 warnings (mostly unused variables)
- 0 compilation errors

## What's Been Completed

✅ **Core GUI Framework** - Main window, settings dialog, job queue interface
✅ **libcosmic API Migration** - All API compatibility issues resolved
✅ **i18n-embed Fix** - Fixed iterator lifetime error with vendor patch
✅ **Basic UI Components** - File inputs, buttons, progress bars, log viewer

Read `RUST_IMPLEMENTATION.md` for complete details.

## Your Next Tasks (Stage 2: Functionality)

Please implement the following in priority order:

### 1. File Dialog Integration (High Priority)
- Add file picker functionality to all "Browse..." buttons
- Use `rfd` crate or libcosmic native dialogs
- Connect to existing `Message::Browse*` handlers in `vsg-ui/src/app.rs`
- Update UI state when files/folders are selected

### 2. Python Bridge Connection (High Priority)
- Wire "Analyze Only" button to call Python subprocess
- Connect job queue "Start Batch" to vsg_core pipeline
- Implement async Message handlers for Python commands
- Parse JSON responses from Python and update UI

### 3. Settings Persistence (Medium Priority)
- Complete remaining 5 settings tabs (currently 4/9 done)
- Implement save/load from config file (use RON or TOML)
- Add input validation for numeric fields
- Wire settings changes to update AppConfig

### 4. Real Progress Updates (Medium Priority)
- Parse progress JSON from Python stdout
- Update progress bars with real data
- Stream log messages to log viewer widget
- Handle job state transitions (Pending → Running → Complete/Failed)

### 5. Error Handling (Medium Priority)
- Add error dialogs for Python subprocess failures
- Handle missing Python runtime gracefully
- Validate file paths before starting jobs
- Show user-friendly error messages

## Quick Reference

**Test the build:**
```bash
cargo check                    # Quick compile check
cargo build                   # Full build
cargo run --bin video-sync-gui # Run the app
```

**Fix warnings:**
```bash
cargo fix --bin "video-sync-gui" -p vsg-ui
```

**Key files to modify:**
- `vsg-ui/src/app.rs` - Main application logic
- `vsg-ui/src/dialogs/job_queue.rs` - Job queue implementation
- `vsg-python-bridge/src/ipc.rs` - Python communication
- `vsg-ui/src/config.rs` - Settings configuration

**libcosmic resources:**
- Docs: https://pop-os.github.io/libcosmic/cosmic/
- Book: https://pop-os.github.io/libcosmic-book/

## Important Notes

- All libcosmic API issues are resolved - just focus on functionality now
- The Python bridge infrastructure exists but isn't connected to UI
- Use `Task::future()` or similar for async operations (not `Task::perform`)
- Settings tabs are display-only - need to wire up actual functionality

## Expected Outcome

By the end of this session, users should be able to:
1. Click "Browse..." and select files/folders
2. Click "Analyze Only" and see Python analysis run
3. View real progress updates during job execution
4. Save and load settings from a config file

Let me know if you need clarification on anything!

---

**Start by reading `RUST_IMPLEMENTATION.md` to understand the current state, then begin with Task #1 (File Dialog Integration).**
