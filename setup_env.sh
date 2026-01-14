#!/bin/bash

# Video Sync GUI - Environment Setup Script
# This script sets up a self-contained Python environment with all dependencies

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
DEPS_DIR="$PROJECT_DIR/Dependencies"
VENV_DIR="$DEPS_DIR/.venv"

echo -e "${BLUE}Project Directory:${NC} $PROJECT_DIR"
echo -e "${BLUE}Dependencies will be installed to:${NC} $DEPS_DIR"
echo ""

# Step 1: Check for uv installation
echo -e "${YELLOW}[1/5] Checking for uv...${NC}"
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}uv not found. Installing uv...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh

    # Add uv to PATH for this session
    export PATH="$HOME/.cargo/bin:$PATH"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}Failed to install uv. Please install manually:${NC}"
        echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
fi
echo -e "${GREEN}✓ uv is installed${NC}"
echo ""

# Step 2: Create Dependencies directory
echo -e "${YELLOW}[2/5] Creating Dependencies directory...${NC}"
mkdir -p "$DEPS_DIR"
echo -e "${GREEN}✓ Dependencies directory created${NC}"
echo ""

# Step 3: Install Python 3.13.11 and create virtual environment
echo -e "${YELLOW}[3/5] Setting up Python 3.13.11 environment...${NC}"
echo "This may take a few minutes on first run..."
cd "$PROJECT_DIR"

# Create venv with specific Python version
uv venv "$VENV_DIR" --python 3.13.11

echo -e "${GREEN}✓ Virtual environment created${NC}"
echo ""

# Step 4: Install dependencies
echo -e "${YELLOW}[4/5] Installing dependencies...${NC}"
echo "This will install all packages from pyproject.toml..."

# Use uv pip to install the project and its dependencies
uv pip install -e . --python "$VENV_DIR/bin/python"

echo -e "${GREEN}✓ All dependencies installed${NC}"
echo ""

# Step 5: Verify installation
echo -e "${YELLOW}[5/5] Verifying installation...${NC}"
"$VENV_DIR/bin/python" --version
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""

echo "========================================="
echo -e "${GREEN}Environment setup successful!${NC}"
echo "========================================="
echo ""
echo "To run the application, use:"
echo -e "  ${BLUE}./run.sh${NC}"
echo ""
echo "Or manually activate the environment:"
echo -e "  ${BLUE}source Dependencies/.venv/bin/activate${NC}"
echo -e "  ${BLUE}python main.py${NC}"
echo ""
