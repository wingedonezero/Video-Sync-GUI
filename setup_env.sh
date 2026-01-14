#!/bin/bash

# Video Sync GUI - Environment Setup Script
# This script sets up a self-contained Python environment with all dependencies using pixi

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

echo -e "${BLUE}Project Directory:${NC} $PROJECT_DIR"
echo ""

# Step 1: Check for pixi installation
echo -e "${YELLOW}[1/3] Checking for pixi...${NC}"
if ! command -v pixi &> /dev/null; then
    echo -e "${YELLOW}pixi not found. Installing pixi...${NC}"
    curl -fsSL https://pixi.sh/install.sh | bash

    # Add pixi to PATH for this session
    export PATH="$HOME/.pixi/bin:$PATH"

    if ! command -v pixi &> /dev/null; then
        echo -e "${RED}Failed to install pixi. Please install manually:${NC}"
        echo "  curl -fsSL https://pixi.sh/install.sh | bash"
        exit 1
    fi
fi
echo -e "${GREEN}✓ pixi is installed${NC}"
echo ""

# Step 2: Install Python 3.13 and dependencies using pixi
echo -e "${YELLOW}[2/3] Setting up Python 3.13 environment and installing dependencies...${NC}"
echo "This may take a few minutes on first run..."
cd "$PROJECT_DIR"

# Install all dependencies with pixi
pixi install

echo -e "${GREEN}✓ Environment and dependencies installed${NC}"
echo ""

# Step 3: Verify installation
echo -e "${YELLOW}[3/3] Verifying installation...${NC}"
pixi run python --version
echo -e "${GREEN}✓ Setup complete!${NC}"
echo ""

echo "========================================="
echo -e "${GREEN}Environment setup successful!${NC}"
echo "========================================="
echo ""
echo "To run the application, use:"
echo -e "  ${BLUE}./run.sh${NC}"
echo ""
echo "Or manually run with pixi:"
echo -e "  ${BLUE}pixi run start${NC}"
echo ""
echo "Or activate the environment and run:"
echo -e "  ${BLUE}pixi shell${NC}"
echo -e "  ${BLUE}python main.py${NC}"
echo ""
