# libcosmic API Fixes Applied

This document summarizes the libcosmic API compatibility fixes that were applied to update the codebase to work with the latest libcosmic version.

## Summary of Changes

### 1. Button API Updates

**Old API (deprecated):**
```rust
button::standard("Text")
button::suggested("Text")
button::icon(icon)
```

**New API:**
```rust
widget::button(text("Text"))
widget::button(text("Text")).style(cosmic::theme::Button::Suggested)
widget::button(icon)
```

#### Files Modified:
- `vsg-ui/src/app.rs`
- `vsg-ui/src/dialogs/settings.rs`
- `vsg-ui/src/dialogs/job_queue.rs`
- `vsg-ui/src/widgets/file_input.rs`

### 2. Container Styling

**Old API:**
```rust
container(content).class(cosmic::theme::Container::Card)
```

**New API:**
```rust
container(content).style(cosmic::theme::Container::Card)
```

### 3. Progress Bar API

**Old API:**
```rust
widget::progress_bar(0.0..=100.0, value).height(Length::Fixed(8.0))
```

**New API:**
```rust
widget::progress_bar(0.0..=100.0, value)
// Height is automatically sized
```

### 4. Text Editor Simplification

The `widget::text_editor` API has changed significantly. For simple log viewing, we replaced it with a scrollable text widget:

**Old:**
```rust
let log_content = widget::text_editor::Content::with_text(&self.log_output);
let log_editor = widget::text_editor(&log_content).height(Length::Fill);
```

**New:**
```rust
let log_viewer = widget::scrollable(
    text(&self.log_output).size(12)
).height(Length::Fill);
```

### 5. Import Cleanup

Removed deprecated imports:
- `cosmic::app::context_drawer` (unused)
- `cosmic::ApplicationExt` (auto-derived)
- `cosmic::Apply` (not needed for current usage)
- Direct `button` imports (use `widget::button` instead)

## Build Instructions

### 1. Install System Dependencies

Run the provided installation script:

```bash
./install-deps.sh
```

Or manually install dependencies based on your distro (see RUST_SETUP.md).

### 2. Build the Project

```bash
# Check for errors
cargo check

# Build debug version
cargo build

# Build release version
cargo build --release

# Run the application
cargo run --release --bin video-sync-gui
```

## Next Steps (Stage 1 Completion)

The following tasks remain to complete Stage 1:

### ✅ Completed
- [x] Fix libcosmic API compilation errors
- [x] Update button API to modern style
- [x] Fix container and widget styling

### 🔄 In Progress
- [ ] Implement native file dialogs for "Browse..." buttons
- [ ] Connect UI buttons to actual vsg_core Python functions via subprocess
- [ ] Complete all settings dialog tabs
- [ ] Implement job execution with progress updates

### 📋 Planned
- [ ] Add file picker integration using `rfd` or cosmic file dialogs
- [ ] Implement Python subprocess bridge for:
  - Analysis jobs
  - Merge operations
  - Progress reporting via JSON IPC
- [ ] Complete settings tabs:
  - Stepping (frame stepping configuration)
  - Frame Matching (videodiff integration)
  - Subtitle Sync (OCR cleanup settings)
  - Merge (mkvmerge options)
  - Logging (log level, output settings)

## API Reference Links

Based on the latest libcosmic documentation:

- [cosmic::app API](https://pop-os.github.io/libcosmic/cosmic/app/index.html)
- [cosmic::widget](https://pop-os.github.io/libcosmic/cosmic/widget/index.html)
- [Application Trait Guide](https://pop-os.github.io/libcosmic-book/application-trait.html)
- [libcosmic GitHub](https://github.com/pop-os/libcosmic)
- [libcosmic Examples](https://github.com/pop-os/libcosmic/tree/master/examples)

## Known Issues

1. **System Dependencies Required**: The build requires Wayland development libraries. This is a compile-time requirement for libcosmic applications.

2. **Button Conditional Rendering**: The new button API doesn't have `.on_press_maybe()`. We use conditional expressions to create different buttons for enabled/disabled states.

3. **Text Editor**: For now, we're using a simple scrollable text view for logs. The full `text_editor` widget can be re-implemented later if rich editing features are needed.

## Testing

After installing dependencies and building successfully, test the following:

1. **Application Launch**: `cargo run --bin video-sync-gui`
2. **Window Displays**: Main window with all UI elements
3. **Button Interactions**: Settings, Job Queue, Browse buttons
4. **Navigation**: Switching between pages (if implemented)
5. **Progress Indicators**: Bootstrap progress bar displays correctly

## Migration Notes for Future API Changes

When libcosmic APIs change in the future:

1. **Check Examples**: Always refer to the official examples in the libcosmic repo
2. **Use Latest Docs**: The online docs at pop-os.github.io/libcosmic are auto-generated
3. **Builder Pattern**: libcosmic heavily uses builder patterns - chain methods for configuration
4. **Styling**: Use `.style()` for cosmic theme integration, not `.class()`
5. **Icons**: Use `widget::icon::from_name()` for named icons from the icon theme
