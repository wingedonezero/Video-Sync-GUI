# Next Session: Complete UI Implementation & Backend Testing

## 📋 Session Goal
Complete the Rust GUI implementation with **full working functionality** so you can test that the Python backend (vsg_core) still works correctly through the new Rust interface.

## 🎯 Before You Start

**CRITICAL: Read these files first:**
1. `/home/user/Video-Sync-GUI/RUST_IMPLEMENTATION.md` - Current status, architecture, API reference
2. `/home/user/Video-Sync-GUI/RUST_SETUP.md` - Build setup and dependencies

**Verify the build:**
```bash
cd /home/user/Video-Sync-GUI
cargo check  # Should show 0 errors, ~41 warnings
```

**Current Branch:** `claude/fix-iterator-lifetime-error-brTiQ`
**Build Status:** ✅ Compiles (0 errors, 41 warnings)

## 🚀 Implementation Tasks (Priority Order)

### Task 1: File Dialogs (CRITICAL - 30 min)
**Goal:** All "Browse..." buttons open native file/folder pickers

**Steps:**
1. Add `rfd` crate to `vsg-ui/Cargo.toml`:
   ```toml
   rfd = "0.15"
   ```

2. In `vsg-ui/src/app.rs`, implement browse handlers:
   ```rust
   Message::BrowseFolder => {
       if let Some(path) = rfd::FileDialog::new()
           .pick_folder() {
           self.main_state.folder_path = path.display().to_string();
       }
       Task::none()
   }
   ```

3. Fix these browse handlers:
   - `Message::BrowseFolder` - Main folder input
   - `Message::BrowsePri` - Primary video file
   - `Message::BrowseSec` - Secondary video file
   - `Message::BrowseTer` - Tertiary video file
   - In settings: `BrowseOutputFolder`, `BrowseTempRoot`, etc.

4. Test: Click all browse buttons - dialogs should open

**Files to modify:**
- `vsg-ui/Cargo.toml`
- `vsg-ui/src/app.rs` (update method, around line 240-300)
- `vsg-ui/src/dialogs/settings.rs` (update method)

---

### Task 2: Python Bridge Integration (CRITICAL - 1 hour)
**Goal:** "Analyze Only" button runs Python analysis and shows real results

**Steps:**
1. Review Python bridge code:
   - `vsg-python-bridge/src/lib.rs` - Main interface
   - `vsg-python-bridge/src/ipc.rs` - JSON protocol
   - `vsg-python-bridge/src/subprocess.rs` - Process management

2. In `vsg-ui/src/app.rs`, add async command execution:
   ```rust
   Message::AnalyzeOnly => {
       // Validate inputs
       if self.main_state.pri_input.is_empty() {
           // Show error
           return Task::none();
       }

       // Create analysis command
       let command = Task::future(async move {
           // Call vsg_python_bridge to run analysis
           // Parse JSON response
           // Return Message::AnalysisComplete(results)
       });

       self.status = "Running analysis...".to_string();
       command
   }

   Message::AnalysisComplete(results) => {
       self.main_state.delays = results;
       self.status = "Analysis complete".to_string();
       Task::none()
   }
   ```

3. Define new Message variants:
   ```rust
   pub enum Message {
       // ... existing ...
       AnalysisComplete(Vec<Option<f64>>),
       JobProgress(usize, f32),  // job_id, progress
       JobComplete(usize),
       JobFailed(usize, String),
   }
   ```

4. Wire up subprocess calls using `vsg_python_bridge`:
   - Import: `use vsg_python_bridge::{PythonRuntime, AnalysisParams};`
   - Store runtime in app state
   - Call methods to execute Python code

5. Parse JSON responses and update UI state

**Files to modify:**
- `vsg-ui/src/app.rs` - Add Message variants, update handlers
- `vsg-ui/src/main_state.rs` or app state struct
- May need to update `vsg-python-bridge/src/lib.rs` if interface needs changes

---

### Task 3: Job Queue Functionality (HIGH - 45 min)
**Goal:** Job queue can start/stop batch processing with real Python calls

**Steps:**
1. In `vsg-ui/src/dialogs/job_queue.rs`:
   - Implement `JobQueueMessage::StartBatch` handler
   - Create async task that processes jobs sequentially
   - Update job status as they run
   - Handle errors gracefully

2. Add progress tracking:
   ```rust
   JobQueueMessage::UpdateProgress(job_id, progress) => {
       if let Some(job) = self.jobs.iter_mut().find(|j| j.id == job_id) {
           job.status = JobStatus::Running { progress };
       }
   }
   ```

3. Connect to Python bridge:
   - Each job should call `vsg_python_bridge` to run merge operation
   - Parse progress JSON from Python stdout
   - Update UI in real-time

4. Test: Add jobs to queue, click "Start Batch", see them run

**Files to modify:**
- `vsg-ui/src/dialogs/job_queue.rs`
- `vsg-ui/src/app.rs` (message forwarding to job queue)

---

### Task 4: Settings Persistence (MEDIUM - 30 min)
**Goal:** Settings save to config file and load on startup

**Steps:**
1. Update `vsg-ui/src/config.rs`:
   - Add `save()` and `load()` methods
   - Use `ron` or `toml` crate for serialization

2. Add to `vsg-ui/Cargo.toml`:
   ```toml
   ron = "0.8"  # or serde_json = "1.0"
   ```

3. Save config on changes:
   ```rust
   SettingsMessage::OutputFolderChanged(path) => {
       self.config.output_folder = Some(PathBuf::from(path));
       self.config.save()?;
       self.dirty = true;
       Task::none()
   }
   ```

4. Load config in `Application::new()`:
   ```rust
   let config = AppConfig::load().unwrap_or_default();
   ```

5. Test: Change settings, restart app, settings should persist

**Files to modify:**
- `vsg-ui/src/config.rs`
- `vsg-ui/Cargo.toml`
- `vsg-ui/src/app.rs` (load on startup)

---

### Task 5: Real-time Progress & Logs (MEDIUM - 30 min)
**Goal:** Progress bars and log viewer show real data from Python

**Steps:**
1. Set up IPC listener for Python stdout:
   ```rust
   // In vsg_python_bridge or app.rs
   fn parse_progress_json(line: &str) -> Option<ProgressUpdate> {
       serde_json::from_str(line).ok()
   }
   ```

2. Update progress bars with real percentages
3. Stream log messages to log viewer widget
4. Handle different log levels (info, warning, error)

5. Test: Run analysis, see real-time progress updates

**Files to modify:**
- `vsg-ui/src/app.rs`
- `vsg-python-bridge/src/ipc.rs`
- `vsg-ui/src/widgets/log_viewer.rs`

---

### Task 6: Error Handling (MEDIUM - 20 min)
**Goal:** Show user-friendly error dialogs

**Steps:**
1. Add error dialog state to app:
   ```rust
   pub struct App {
       // ...
       error_message: Option<String>,
   }
   ```

2. Show error dialog when set:
   ```rust
   if let Some(error) = &self.error_message {
       // Show modal error dialog
       widget::dialog(error)
           .on_close(Message::ClearError)
   }
   ```

3. Add error handlers:
   - Python runtime not found
   - Invalid file paths
   - Analysis/merge failures
   - Job queue errors

4. Test: Try to analyze with no files selected, should show error

**Files to modify:**
- `vsg-ui/src/app.rs`

---

## ✅ Testing Checklist

After implementing all tasks, verify:

### Basic Functionality
- [ ] App launches without crashes
- [ ] All browse buttons open file/folder dialogs
- [ ] Selected paths appear in text inputs
- [ ] Settings tabs all display correctly

### Analysis Workflow
- [ ] Click "Analyze Only" with valid files → Python runs
- [ ] Progress bar updates during analysis
- [ ] Results display when complete (delays shown)
- [ ] Logs appear in log viewer
- [ ] Errors show in dialog if files invalid

### Job Queue Workflow
- [ ] Add job to queue → appears in list
- [ ] Click "Start Batch" → jobs run sequentially
- [ ] Job status updates (Pending → Running → Complete)
- [ ] Progress bars update for each job
- [ ] Can remove jobs from queue
- [ ] Errors handled gracefully

### Settings
- [ ] Change settings → values update
- [ ] Restart app → settings persist
- [ ] Browse buttons work in settings tabs

### Backend Verification
- [ ] Python subprocess starts correctly
- [ ] vsg_core analysis produces correct output
- [ ] Merge operations work end-to-end
- [ ] Output files created in expected locations

---

## 🔍 Verification Commands

```bash
# Build and run
cargo build --release
./target/release/video-sync-gui

# Check for issues
cargo check
cargo clippy  # Lint warnings

# Run with debug logging
RUST_LOG=debug cargo run

# Test Python bridge directly
cd vsg-python-bridge
cargo test
```

---

## 📝 Expected Completion State

By end of session, you should have:

1. ✅ **Working GUI** - All buttons functional, dialogs open
2. ✅ **Python Integration** - Can run analysis through UI
3. ✅ **Job Queue** - Can batch process multiple jobs
4. ✅ **Settings** - Persist across restarts
5. ✅ **Error Handling** - Graceful failures with user feedback
6. ✅ **Backend Test** - Confirmed vsg_core still works

**Final Test:** Select 2-3 video files, click "Analyze Only", see real sync delays calculated by Python backend.

---

## 🆘 If You Get Stuck

**Common Issues:**

1. **"Task::perform not found"** → Use `Task::future()` instead
2. **Lifetime errors** → Add `'static` bounds or clone strings
3. **Python not found** → Check `vsg_python_bridge::bootstrap::ensure_python()`
4. **No progress updates** → Verify JSON parsing in IPC layer

**Debug Steps:**
```bash
# Test Python bridge independently
cd vsg-python-bridge
cargo test --all

# Check Python runtime
ls -la ~/.local/share/video-sync-gui/python/

# Enable verbose logging
RUST_LOG=vsg_ui=debug,vsg_python_bridge=debug cargo run
```

---

## 📚 Key Files Reference

**Core Application:**
- `vsg-ui/src/app.rs` - Main app logic, message handling
- `vsg-ui/src/config.rs` - Configuration types
- `vsg-ui/src/dialogs/job_queue.rs` - Job queue implementation
- `vsg-ui/src/dialogs/settings.rs` - Settings dialog

**Python Integration:**
- `vsg-python-bridge/src/lib.rs` - Public API
- `vsg-python-bridge/src/subprocess.rs` - Process management
- `vsg-python-bridge/src/ipc.rs` - JSON protocol
- `vsg-python-bridge/src/bootstrap.rs` - Python setup

**Resources:**
- `RUST_IMPLEMENTATION.md` - Full implementation guide
- `RUST_SETUP.md` - Build dependencies

---

## 🎉 Success Criteria

Session is complete when you can:
1. Open the app
2. Browse and select video files
3. Click "Analyze Only"
4. See Python backend calculate sync delays
5. Results display in GUI
6. Log messages appear
7. Settings save/load correctly

**You should be able to fully replace the Python PySide6 GUI with the Rust version and have all core functionality working.**
