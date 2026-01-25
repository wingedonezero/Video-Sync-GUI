#!/bin/bash
# Video Sync GUI - Build Script
#
# Usage:
#   ./build.sh          - Build everything
#   ./build.sh run      - Build and run
#   ./build.sh clean    - Clean build artifacts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BUILD_DIR="qt_ui/build"

case "${1:-build}" in
    build|all)
        echo "==> Building Rust crates..."
        cargo build --release

        echo "==> Building Qt UI..."
        mkdir -p "$BUILD_DIR"
        cd "$BUILD_DIR"
        cmake ..
        make -j$(nproc)
        cd "$SCRIPT_DIR"

        echo "==> Build complete!"
        echo "    Run with: $BUILD_DIR/video-sync-gui"
        ;;

    run)
        $0 build
        echo "==> Running..."
        exec "$BUILD_DIR/video-sync-gui"
        ;;

    clean)
        echo "==> Cleaning..."
        cargo clean
        rm -rf "$BUILD_DIR"
        echo "==> Clean complete"
        ;;

    rust)
        echo "==> Building Rust crates..."
        cargo build --release
        ;;

    qt)
        echo "==> Building Qt UI..."
        mkdir -p "$BUILD_DIR"
        cd "$BUILD_DIR"
        cmake ..
        make -j$(nproc)
        ;;

    *)
        echo "Usage: $0 [build|run|clean|rust|qt]"
        exit 1
        ;;
esac
