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
VENV_DIR="$PROJECT_DIR/.venv"

echo -e "${BLUE}Project Directory:${NC} $PROJECT_DIR"
echo -e "${BLUE}Virtual environment:${NC} $VENV_DIR"
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

# Step 2: Install Python 3.13 and dependencies using uv sync
echo -e "${YELLOW}[2/4] Setting up Python 3.13 environment and installing dependencies...${NC}"
echo "This may take a few minutes on first run..."
cd "$PROJECT_DIR"

# Use uv sync to install from pyproject.toml with lock file
# This ensures correct versions for Python 3.13
uv sync --python 3.13

echo -e "${GREEN}✓ Virtual environment created and dependencies installed${NC}"
echo ""

# Step 3: Verify installation
echo -e "${YELLOW}[3/4] Verifying installation...${NC}"
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
echo -e "  ${BLUE}source .venv/bin/activate${NC}"
echo -e "  ${BLUE}python main.py${NC}"
echo ""
