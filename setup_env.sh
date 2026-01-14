#!/bin/bash

# Video Sync GUI - Environment Setup Script
# This script sets up a Python virtual environment with all dependencies

set -e  # Exit on error

echo "========================================="
echo "Video Sync GUI - Environment Setup"
echo "========================================="
echo ""

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

echo -e "${BLUE}Project Directory:${NC} $PROJECT_DIR"
echo ""

# Function to check Python version
check_python_version() {
    local python_cmd=$1
    if command -v "$python_cmd" &> /dev/null; then
        local version=$("$python_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+')
        if [[ "$version" == 3.13.* ]]; then
            echo "$python_cmd"
            return 0
        fi
    fi
    return 1
}

# Function to install Python via conda
install_python_conda() {
    echo -e "${YELLOW}Attempting to install Python 3.13.11 via conda...${NC}"

    # Check if conda is available
    if command -v conda &> /dev/null; then
        echo -e "${BLUE}Found conda, installing Python 3.13.11...${NC}"
        conda install -y python=3.13.11 -c conda-forge
        return 0
    elif command -v mamba &> /dev/null; then
        echo -e "${BLUE}Found mamba, installing Python 3.13.11...${NC}"
        mamba install -y python=3.13.11 -c conda-forge
        return 0
    else
        echo -e "${YELLOW}conda/mamba not found${NC}"
        return 1
    fi
}

# Function to download and install standalone Python
install_python_standalone() {
    echo -e "${YELLOW}Attempting to install Python 3.13.11 standalone build...${NC}"

    local python_dir="$PROJECT_DIR/.python"
    mkdir -p "$python_dir"

    # Detect architecture
    local arch=$(uname -m)
    local os=$(uname -s | tr '[:upper:]' '[:lower:]')

    if [[ "$os" == "linux" ]]; then
        if [[ "$arch" == "x86_64" ]]; then
            local python_url="https://github.com/indygreg/python-build-standalone/releases/download/20241016/cpython-3.13.0+20241016-x86_64-unknown-linux-gnu-install_only.tar.gz"
        else
            echo -e "${RED}Unsupported architecture: $arch${NC}"
            return 1
        fi
    else
        echo -e "${RED}Unsupported OS: $os${NC}"
        return 1
    fi

    echo -e "${BLUE}Downloading Python from: $python_url${NC}"
    local temp_file=$(mktemp)
    if curl -L -o "$temp_file" "$python_url"; then
        echo -e "${BLUE}Extracting Python...${NC}"
        tar -xzf "$temp_file" -C "$python_dir" --strip-components=1
        rm "$temp_file"

        # Check if extraction was successful
        if [ -f "$python_dir/bin/python3" ]; then
            echo "$python_dir/bin/python3"
            return 0
        fi
    fi

    echo -e "${RED}Failed to download/extract Python${NC}"
    return 1
}

# Step 1: Find or install Python 3.13
echo -e "${YELLOW}[1/3] Checking for Python 3.13...${NC}"

PYTHON_CMD=""

# Try to find existing Python 3.13
for py in python3.13 python3 python; do
    if PYTHON_CMD=$(check_python_version "$py"); then
        echo -e "${GREEN}✓ Found Python 3.13: $PYTHON_CMD${NC}"
        break
    fi
done

# If not found, try to install
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}Python 3.13 not found. Installing...${NC}"

    # Try conda first
    if install_python_conda; then
        for py in python3.13 python3 python; do
            if PYTHON_CMD=$(check_python_version "$py"); then
                echo -e "${GREEN}✓ Installed Python 3.13 via conda: $PYTHON_CMD${NC}"
                break
            fi
        done
    fi

    # If conda failed, try standalone
    if [ -z "$PYTHON_CMD" ]; then
        if PYTHON_CMD=$(install_python_standalone); then
            echo -e "${GREEN}✓ Installed Python 3.13 standalone: $PYTHON_CMD${NC}"
        else
            echo -e "${RED}Failed to install Python 3.13${NC}"
            echo ""
            echo "Please install Python 3.13 manually:"
            echo "  - Via conda: conda install python=3.13"
            echo "  - Or download from: https://www.python.org/downloads/"
            exit 1
        fi
    fi
fi

# Verify Python version
PYTHON_VERSION=$("$PYTHON_CMD" --version)
echo -e "${BLUE}Using: $PYTHON_VERSION${NC}"
echo ""

# Step 2: Create virtual environment
echo -e "${YELLOW}[2/3] Setting up virtual environment...${NC}"

if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Removing existing virtual environment...${NC}"
    rm -rf "$VENV_DIR"
fi

echo -e "${BLUE}Creating virtual environment at: $VENV_DIR${NC}"
"$PYTHON_CMD" -m venv "$VENV_DIR"

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo -e "${BLUE}Upgrading pip...${NC}"
pip install --upgrade pip

echo -e "${GREEN}✓ Virtual environment created${NC}"
echo ""

# Step 3: Install dependencies
echo -e "${YELLOW}[3/3] Installing dependencies...${NC}"
echo "This may take a few minutes..."

cd "$PROJECT_DIR"
pip install -r requirements.txt

echo -e "${GREEN}✓ Dependencies installed${NC}"
echo ""

# Verify installation
echo -e "${YELLOW}Verifying installation...${NC}"
python --version
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""

echo "========================================="
echo -e "${GREEN}Environment setup successful!${NC}"
echo "========================================="
echo ""
echo "To run the application, use:"
echo -e "  ${BLUE}./run.sh${NC}"
echo ""
echo "Or manually activate the environment and run:"
echo -e "  ${BLUE}source venv/bin/activate${NC}"
echo -e "  ${BLUE}python main.py${NC}"
echo ""
