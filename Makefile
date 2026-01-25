# Video Sync GUI - Build System
#
# Usage:
#   make          - Build everything (release)
#   make debug    - Build debug version
#   make run      - Build and run
#   make clean    - Clean all build artifacts

.PHONY: all release debug run clean help

# Default: build release
all: release

# Release build
release:
	cargo build --release
	@echo ""
	@echo "Build complete: ./target/release/video-sync-gui"

# Debug build
debug:
	cargo build
	@echo ""
	@echo "Build complete: ./target/debug/video-sync-gui"

# Build and run
run: release
	./target/release/video-sync-gui

# Clean all artifacts
clean:
	cargo clean

# Help
help:
	@echo "Video Sync GUI Build System"
	@echo ""
	@echo "Usage:"
	@echo "  make          - Build release version"
	@echo "  make debug    - Build debug version"
	@echo "  make run      - Build and run"
	@echo "  make clean    - Clean all artifacts"
	@echo ""
	@echo "The Qt UI is automatically built via cargo."
	@echo "Requires: Qt6, cmake, and Rust toolchain."
