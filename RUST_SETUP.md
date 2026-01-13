# Rust UI Setup Guide

This document describes how to set up the Rust-based UI for Video Sync GUI.

## System Dependencies

### Arch Linux / Manjaro

```bash
sudo pacman -S rustup cmake pkgconf libxkbcommon wayland fontconfig freetype2
```

### Pop!_OS / Ubuntu / Debian

```bash
sudo apt install cargo cmake just libexpat1-dev libfontconfig-dev libfreetype-dev libxkbcommon-dev pkgconf wayland-protocols libwayland-dev
```

### Fedora

```bash
sudo dnf install cargo cmake pkgconf-pkg-config libxkbcommon-devel wayland-devel fontconfig-devel freetype-devel
```

## Building

From the repository root:

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

## Project Structure

```
Video-Sync-GUI/
├── Cargo.toml              # Workspace root
├── vsg-ui/                 # libcosmic GUI application
│   ├── src/
│   │   ├── main.rs         # Entry point
│   │   ├── app.rs          # Main application (cosmic::Application)
│   │   ├── config.rs       # Configuration management
│   │   ├── i18n.rs         # Internationalization
│   │   ├── pages/          # Page views (like Qt widgets)
│   │   ├── dialogs/        # Modal dialogs
│   │   └── widgets/        # Reusable components
│   └── i18n/               # Translation files
├── vsg-python-bridge/      # PyO3 bridge to Python code
│   └── src/
│       ├── lib.rs          # Library entry
│       ├── bootstrap.rs    # Python runtime bootstrapper
│       └── runtime.rs      # Python interface wrapper
├── vsg_core/               # Existing Python code (unchanged)
└── vsg_qt/                 # Legacy Qt UI (to be deprecated)
```

## How It Works

### Python Runtime Isolation

The application bundles its own Python interpreter using [python-build-standalone](https://github.com/astral-sh/python-build-standalone). On first launch:

1. Downloads a standalone Python 3.13.x interpreter (~25MB compressed)
2. Creates an isolated virtual environment
3. Installs dependencies from `requirements.txt`

This means:
- **No system Python dependency** - Works regardless of your system's Python version
- **No pip conflicts** - Dependencies are isolated from your system packages
- **Reproducible** - Same Python version every time

The runtime is stored in `~/.local/share/video-sync-gui/runtime/`.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Rust Application                      │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  libcosmic  │  │ PyO3 Bridge  │  │  Bootstrap    │  │
│  │     UI      │  │              │  │  (Downloads   │  │
│  │  (iced)     │  │  Calls into  │  │   Python)     │  │
│  │             │  │  vsg_core    │  │               │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  │
└────────────────────────┬────────────────────────────────┘
                         │ PyO3
                         ▼
┌─────────────────────────────────────────────────────────┐
│              Isolated Python Environment                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │                    vsg_core                       │  │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────────┐  │  │
│  │  │  analysis  │ │ correction │ │  subtitles   │  │  │
│  │  │ audio_corr │ │  stepping  │ │ frame_sync   │  │  │
│  │  │            │ │            │ │              │  │  │
│  │  └────────────┘ └────────────┘ └──────────────┘  │  │
│  │  ┌────────────┐ ┌────────────┐ ┌──────────────┐  │  │
│  │  │   mux      │ │ extraction │ │ orchestrator │  │  │
│  │  │ mkvmerge   │ │   tracks   │ │   pipeline   │  │  │
│  │  └────────────┘ └────────────┘ └──────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## Gradual Migration Path

The current architecture allows gradual migration from Python to Rust:

1. **Phase 1 (Current)**: Rust UI, Python backend via PyO3
2. **Phase 2**: Port performance-critical modules to Rust (audio_corr, stepping, frame_matching)
3. **Phase 3**: Move remaining logic to Rust
4. **Phase 4**: Remove Python dependency entirely

Each phase maintains full functionality while improving performance.
