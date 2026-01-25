#!/bin/bash
# Video Sync GUI - Build Script
#
# Usage:
#   ./build.sh          - Build everything (release)
#   ./build.sh debug    - Build debug version
#   ./build.sh run      - Build and run
#   ./build.sh clean    - Clean build artifacts

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

case "${1:-build}" in
    build|release)
        echo "==> Building (release)..."
        cargo build --release
        echo ""
        echo "==> Build complete!"
        echo "    Run: ./target/release/video-sync-gui"
        ;;

    debug)
        echo "==> Building (debug)..."
        cargo build
        echo ""
        echo "==> Build complete!"
        echo "    Run: ./target/debug/video-sync-gui"
        ;;

    run)
        $0 release
        echo ""
        echo "==> Running..."
        exec ./target/release/video-sync-gui
        ;;

    clean)
        echo "==> Cleaning..."
        cargo clean
        echo "==> Clean complete"
        ;;

    *)
        echo "Usage: $0 [build|debug|run|clean]"
        echo ""
        echo "  build/release  - Build release version (default)"
        echo "  debug          - Build debug version"
        echo "  run            - Build and run"
        echo "  clean          - Clean all build artifacts"
        exit 1
        ;;
esac
