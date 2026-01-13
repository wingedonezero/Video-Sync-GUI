# Video Sync GUI - Rust Implementation Status

> **Branch:** `claude/fix-iterator-lifetime-error-brTiQ`
> **Build Status:** ✅ Compiles successfully (41 warnings, 0 errors)
> **Last Updated:** 2025-01-13

## Overview

This document tracks the Rust/libcosmic GUI implementation for Video Sync, which replaces the Python PySide6 interface. The GUI is built using the COSMIC desktop toolkit (libcosmic), providing native integration with System76's COSMIC desktop environment.

## Current Status: Stage 1 - Foundation (90% Complete)

### ✅ Completed

1. **Project Structure**
   - Workspace with two crates: `vsg-ui` (GUI), `vsg-python-bridge` (Python integration)
   - libcosmic integration with proper features enabled
   - i18n/localization framework setup (Fluent)

2. **Core Application (vsg-ui)**
   - ✅ Main application trait implementation
   - ✅ Multi-page architecture (Main, Settings, Job Queue)
   - ✅ File input widgets with browse buttons
   - ✅ Progress indicators and status displays
   - ✅ Settings dialog with 9 tabbed sections
   - ✅ Job queue management interface
   - ✅ Log viewer widget

3. **libcosmic API Migration** ✅
   - Fixed i18n-embed iterator lifetime error (E0310) - see below
   - Converted all `widget::button()` → `widget::button::standard()`
   - Converted macros to builder pattern: `column![]` → `widget::column().push()`
   - Fixed container styling: `.style()` → `.class()`
   - Resolved all borrow checker issues with proper lifetimes
   - Added missing `'static` bounds where needed

4. **Python Bridge (vsg-python-bridge)**
   - ✅ Subprocess management for Python runtime
   - ✅ JSON IPC protocol design
   - ✅ Bootstrap/download of standalone Python
   - ✅ Message passing infrastructure
   - ⏳ Not yet connected to UI (pending Stage 2)

### 🔧 Critical Fix: i18n-embed Iterator Lifetime Error

**Problem:** The `i18n-embed` 0.16.0 crate had an E0310 error with Rust 1.92+ due to incorrect lifetime bounds in the `filenames_iter()` trait method.

**Solution:** Created a patched version in `vendor/i18n-embed/`:
- Changed trait definition: `+ '_` → `+ 'static`
- Modified implementations to collect into `Vec<String>` before boxing
- Updated `Cargo.toml` with `[patch.crates-io]` directive

**Files Changed:**
- `vendor/i18n-embed/src/assets.rs` - Fixed 4 implementations
- `Cargo.toml` - Added patch path
- `vsg-ui/i18n.toml` - Created missing config file

### 🚧 Remaining Stage 1 Tasks

1. **File Dialogs** - Implement native file pickers for "Browse..." buttons
   - Use `rfd` crate or libcosmic's native dialogs
   - Wire to existing browse button handlers

2. **Python Bridge Connection** - Wire UI to Python subprocess
   - Connect "Analyze Only" button → Python subprocess call
   - Connect job queue "Start Batch" → Python pipeline execution
   - Parse JSON responses and update UI state

3. **Settings Persistence** - Complete settings tabs
   - Currently 4/9 tabs have basic UI
   - Need to implement save/load from config file
   - Add validation for numeric inputs

4. **Job Execution** - Wire job queue to vsg_core pipeline
   - Implement job state machine (Pending → Running → Complete/Failed)
   - Add progress tracking via JSON IPC
   - Handle job cancellation

5. **Real-time Progress** - Implement IPC progress updates
   - Parse progress JSON from Python stdout
   - Update progress bars and status text
   - Handle log message streaming

## Build Instructions

### Quick Build Check
```bash
# From repository root
cargo check              # Check compilation without building
cargo build             # Build debug version
cargo build --release   # Build optimized release version
```

### Run the Application
```bash
cargo run --bin video-sync-gui
```

### Fix Warnings
```bash
# Auto-fix unused variable warnings and other trivial issues
cargo fix --bin "video-sync-gui" -p vsg-ui
```

### Common Issues

**Error: Missing xkbcommon library**
```bash
sudo apt-get install libxkbcommon-dev libxkbcommon-x11-dev
```

**Error: i18n-embed lifetime issues**
This should be fixed by the vendor patch. If you still see issues:
```bash
cargo clean
cargo build
```

## Architecture

### Application Flow

```
┌─────────────────┐
│   vsg-ui        │  Rust GUI (libcosmic)
│   - Main Window │
│   - Settings    │───┐
│   - Job Queue   │   │ JSON IPC
└─────────────────┘   │
                      │
┌─────────────────┐   │
│ vsg-python-     │◄──┘
│ bridge          │  Subprocess management
│   - Bootstrap   │
│   - IPC Handler │───┐
└─────────────────┘   │
                      │ Function calls
┌─────────────────┐   │
│   vsg_core      │◄──┘
│   (Python)      │  Core analysis engine
│   - Analysis    │
│   - Merging     │
└─────────────────┘
```

### Directory Structure

```
Video-Sync-GUI/
├── vsg-ui/               # Main GUI application
│   ├── src/
│   │   ├── app.rs        # Application trait impl
│   │   ├── config.rs     # Configuration types
│   │   ├── pages/        # Page implementations
│   │   ├── dialogs/      # Settings, job queue dialogs
│   │   └── widgets/      # Custom widgets
│   └── i18n/             # Localization files (Fluent)
├── vsg-python-bridge/    # Python integration
│   └── src/
│       ├── bootstrap.rs  # Python runtime setup
│       ├── ipc.rs        # JSON IPC protocol
│       └── subprocess.rs # Process management
├── vendor/
│   └── i18n-embed/       # Patched dependency
└── Cargo.toml            # Workspace config + patches
```

## libcosmic API Reference

### Common Patterns

**Buttons:**
```rust
// Standard button
widget::button::standard("Click Me")
    .on_press(Message::ButtonClicked)

// Suggested (primary) button
widget::button::standard("Save")
    .on_press(Message::Save)
    .class(cosmic::theme::Button::Suggested)

// Destructive button
widget::button::destructive("Delete")
    .on_press(Message::Delete)
```

**Layout:**
```rust
// Column (vertical)
widget::column()
    .push(widget1)
    .push(widget2)
    .spacing(8)

// Row (horizontal)
widget::row()
    .push(widget1)
    .push(widget2)
    .spacing(8)
    .align_y(Alignment::Center)

// Extend with iterator
widget::column()
    .extend(items.iter().map(|item| text(item)))
```

**Text Input:**
```rust
widget::text_input("placeholder", &value)
    .on_input(Message::ValueChanged)
    .width(Length::Fill)
```

**Container Styling:**
```rust
container(content)
    .padding(12)
    .class(cosmic::theme::Container::Card)  // Not .style()!
```

### Resources
- [libcosmic Documentation](https://pop-os.github.io/libcosmic/cosmic/)
- [COSMIC Toolkit Book](https://pop-os.github.io/libcosmic-book/)
- [Application Trait Guide](https://pop-os.github.io/libcosmic-book/application-trait.html)

## Next Steps (Stage 2)

1. **File Dialog Integration**
   - Add `rfd` or cosmic file picker dependency
   - Implement async file selection handlers
   - Update UI state with selected paths

2. **Python IPC Connection**
   - Create Message variants for Python commands
   - Implement Task-based async subprocess calls
   - Parse JSON responses into Rust types

3. **Job Execution Pipeline**
   - Design job lifecycle state machine
   - Implement progress tracking with real data
   - Add error handling and retry logic

4. **Settings Completion**
   - Finish remaining 5 settings tabs
   - Add form validation
   - Implement config persistence (RON or TOML)

5. **Testing & Polish**
   - Add unit tests for core logic
   - Integration tests for Python bridge
   - UI polish (icons, spacing, alignment)

## Known Issues & TODOs

- [ ] Async bootstrap task disabled (using `Task::none()` placeholder)
- [ ] Settings tabs not fully functional (display only)
- [ ] File dialogs not implemented (buttons exist but don't open dialogs)
- [ ] Python bridge not connected to UI messages
- [ ] No error handling for Python subprocess failures
- [ ] Log viewer doesn't display real logs yet
- [ ] Progress bars show static values
- [x] i18n-embed lifetime error (FIXED with vendor patch)
- [x] libcosmic API compatibility (FIXED)

## Commit History (Recent)

```
1cea6ce - Fix button syntax and remaining column!/row! conversions
2365a2e - Fix libcosmic API compatibility - widget buttons and layout containers
e4e99eb - Fix i18n-embed iterator lifetime error (E0310) with Rust 1.92+
3cb5de0 - Merge pull request #290 (previous work)
```

## Contributors

- Claude (AI Assistant) - Implementation, debugging, API migration
- Original Python codebase by project maintainers

---

**For the next development session, focus on connecting the Python bridge to enable actual analysis functionality.**
