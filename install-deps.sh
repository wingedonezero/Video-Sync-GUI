#!/bin/bash
# Install system dependencies for building Video Sync GUI with libcosmic

set -e

echo "Installing system dependencies for Video Sync GUI..."
echo

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
else
    echo "Cannot detect operating system"
    exit 1
fi

case "$OS" in
    ubuntu|debian|pop)
        echo "Detected Ubuntu/Debian/Pop!_OS"
        sudo apt install -y \
            cargo \
            cmake \
            just \
            libexpat1-dev \
            libfontconfig-dev \
            libfreetype-dev \
            libxkbcommon-dev \
            pkgconf \
            wayland-protocols \
            libwayland-dev
        ;;

    arch|manjaro)
        echo "Detected Arch Linux/Manjaro"
        sudo pacman -S --needed \
            rustup \
            cmake \
            pkgconf \
            libxkbcommon \
            wayland \
            fontconfig \
            freetype2
        ;;

    fedora)
        echo "Detected Fedora"
        sudo dnf install -y \
            cargo \
            cmake \
            pkgconf-pkg-config \
            libxkbcommon-devel \
            wayland-devel \
            fontconfig-devel \
            freetype-devel
        ;;

    *)
        echo "Unsupported OS: $OS"
        echo "Please manually install the dependencies listed in RUST_SETUP.md"
        exit 1
        ;;
esac

echo
echo "Dependencies installed successfully!"
echo "You can now build the project with: cargo build"
