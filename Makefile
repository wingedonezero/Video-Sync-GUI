# Video Sync GUI - Unified Build
#
# Usage:
#   make          - Build everything (Rust + Qt)
#   make rust     - Build Rust crates only
#   make qt       - Build Qt UI only
#   make clean    - Clean all build artifacts
#   make run      - Build and run the application

.PHONY: all rust qt clean run configure

BUILD_DIR := qt_ui/build
CARGO := cargo
CMAKE := cmake
MAKE_CMD := $(MAKE)

# Default: build everything
all: rust qt

# Build Rust crates (vsg_core, vsg_bridge)
rust:
	$(CARGO) build --release

# Configure Qt build (only needs to run once or after CMakeLists changes)
configure:
	@mkdir -p $(BUILD_DIR)
	cd $(BUILD_DIR) && $(CMAKE) ..

# Build Qt UI (automatically configures if needed)
qt: rust
	@mkdir -p $(BUILD_DIR)
	@if [ ! -f $(BUILD_DIR)/Makefile ]; then \
		cd $(BUILD_DIR) && $(CMAKE) ..; \
	fi
	$(MAKE_CMD) -C $(BUILD_DIR)

# Clean all build artifacts
clean:
	$(CARGO) clean
	rm -rf $(BUILD_DIR)

# Build and run
run: all
	./$(BUILD_DIR)/video-sync-gui

# Development build (debug mode)
dev:
	$(CARGO) build
	@mkdir -p $(BUILD_DIR)
	@if [ ! -f $(BUILD_DIR)/Makefile ]; then \
		cd $(BUILD_DIR) && $(CMAKE) -DCMAKE_BUILD_TYPE=Debug ..; \
	fi
	$(MAKE_CMD) -C $(BUILD_DIR)

# Help
help:
	@echo "Video Sync GUI Build System"
	@echo ""
	@echo "Targets:"
	@echo "  make          - Build everything (Rust + Qt)"
	@echo "  make rust     - Build Rust crates only"
	@echo "  make qt       - Build Qt UI only"
	@echo "  make clean    - Clean all build artifacts"
	@echo "  make run      - Build and run the application"
	@echo "  make dev      - Debug build"
	@echo "  make configure - Re-run CMake configuration"
