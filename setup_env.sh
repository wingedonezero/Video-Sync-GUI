#!/bin/bash

# Video Sync GUI - Environment Setup Script
# Interactive script for managing Python environment and dependencies

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"

# Function to show main menu
show_menu() {
    echo ""
    echo "========================================="
    echo "Video Sync GUI - Environment Setup"
    echo "========================================="
    echo ""
    echo -e "${BLUE}Project Directory:${NC} $PROJECT_DIR"
    echo ""
    echo "Please select an option:"
    echo ""
    echo -e "  ${CYAN}1)${NC} Full Setup - Install Python 3.13 and all dependencies"
    echo -e "  ${CYAN}2)${NC} Update Libraries - Check for and install updates"
    echo -e "  ${CYAN}3)${NC} Install Optional Dependencies (AI audio features)"
    echo -e "  ${CYAN}4)${NC} Verify Dependencies - Check all packages are installed"
    echo -e "  ${CYAN}5)${NC} Exit"
    echo ""
    echo -n "Enter your choice [1-5]: "
}

# Function to check Python version and verify it works
check_python_version() {
    local python_cmd=$1
    if command -v "$python_cmd" &> /dev/null; then
        # Check version
        local version=$("$python_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+')
        if [[ "$version" == 3.13.* ]]; then
            # Verify Python actually works by running a simple command
            if "$python_cmd" -c "import sys; print('OK')" &> /dev/null; then
                echo "$python_cmd"
                return 0
            else
                echo -e "${YELLOW}Warning: $python_cmd version $version found but appears broken, skipping...${NC}" >&2
            fi
        fi
    fi
    return 1
}

# Function to install Python via conda
install_python_conda() {
    echo -e "${YELLOW}Attempting to install Python 3.13 via conda...${NC}"

    # Check if conda is available
    if command -v conda &> /dev/null; then
        echo -e "${BLUE}Found conda, installing Python 3.13...${NC}"
        # Try specific version first, fall back to 3.13.* if not available
        if conda install -y python=3.13.11 -c conda-forge 2>/dev/null || \
           conda install -y "python>=3.13,<3.14" -c conda-forge; then
            return 0
        else
            return 1
        fi
    elif command -v mamba &> /dev/null; then
        echo -e "${BLUE}Found mamba, installing Python 3.13...${NC}"
        # Try specific version first, fall back to 3.13.* if not available
        if mamba install -y python=3.13.11 -c conda-forge 2>/dev/null || \
           mamba install -y "python>=3.13,<3.14" -c conda-forge; then
            return 0
        else
            return 1
        fi
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

# Function to ensure venv exists and is activated
ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${RED}Virtual environment not found!${NC}"
        echo -e "${YELLOW}Please run 'Full Setup' first (option 1)${NC}"
        return 1
    fi

    if [ -z "$VIRTUAL_ENV" ]; then
        echo -e "${BLUE}Activating virtual environment...${NC}"
        source "$VENV_DIR/bin/activate"
    fi
    return 0
}

# Function to check for updates
check_updates() {
    echo ""
    echo "========================================="
    echo "Checking for Updates"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    echo -e "${YELLOW}Checking for package updates...${NC}"
    echo ""

    # Get list of outdated packages
    outdated=$(pip list --outdated --format=json 2>/dev/null)

    if [ "$outdated" == "[]" ] || [ -z "$outdated" ]; then
        echo -e "${GREEN}✓ All packages are up to date!${NC}"

        # Check Python version
        echo ""
        echo -e "${YELLOW}Checking Python version...${NC}"
        current_python=$(python --version 2>&1 | grep -oP '\d+\.\d+\.\d+')
        echo -e "${BLUE}Current Python version: $current_python${NC}"
        echo -e "${YELLOW}Latest Python 3.13 series will be checked during full setup${NC}"
        return 0
    fi

    # Parse and display outdated packages
    echo -e "${YELLOW}The following packages have updates available:${NC}"
    echo ""
    echo "$outdated" | python -c "
import sys, json
data = json.load(sys.stdin)
for pkg in data:
    print(f\"  {pkg['name']:30s} {pkg['version']:15s} -> {pkg['latest_version']}\")
"

    echo ""
    echo -n "Do you want to update these packages? [y/N]: "
    read -r response

    if [[ "$response" =~ ^[Yy]$ ]]; then
        echo ""
        echo -e "${BLUE}Updating packages...${NC}"
        pip install --upgrade $(echo "$outdated" | python -c "
import sys, json
data = json.load(sys.stdin)
print(' '.join([pkg['name'] for pkg in data]))
")
        echo ""
        echo -e "${GREEN}✓ Packages updated successfully!${NC}"
    else
        echo -e "${YELLOW}Update cancelled${NC}"
    fi
}

# Function to install optional dependencies
install_optional() {
    echo ""
    echo "========================================="
    echo "Install Optional Dependencies"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    echo "Optional AI audio features (PyTorch + Demucs):"
    echo "These enable AI-powered vocal/instrument separation"
    echo "for better cross-language audio correlation."
    echo ""
    echo "Select your hardware:"
    echo ""
    echo -e "  ${CYAN}1)${NC} NVIDIA GPU (CUDA)"
    echo -e "  ${CYAN}2)${NC} AMD GPU (ROCm)"
    echo -e "  ${CYAN}3)${NC} CPU only (slower but works everywhere)"
    echo -e "  ${CYAN}4)${NC} Cancel"
    echo ""
    echo -n "Enter your choice [1-4]: "
    read -r hw_choice

    case $hw_choice in
        1)
            echo ""
            echo -e "${BLUE}Installing PyTorch (NVIDIA CUDA) + Demucs...${NC}"
            pip install torch torchvision torchaudio
            pip install demucs
            echo -e "${GREEN}✓ NVIDIA GPU support installed${NC}"
            ;;
        2)
            echo ""
            echo -e "${BLUE}Installing PyTorch (AMD ROCm) + Demucs...${NC}"
            pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.2
            pip install demucs
            echo -e "${GREEN}✓ AMD GPU (ROCm) support installed${NC}"
            ;;
        3)
            echo ""
            echo -e "${BLUE}Installing PyTorch (CPU only) + Demucs...${NC}"
            pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
            pip install demucs
            echo -e "${GREEN}✓ CPU-only support installed${NC}"
            ;;
        4)
            echo -e "${YELLOW}Installation cancelled${NC}"
            return 0
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}"
            return 1
            ;;
    esac
}

# Function to verify dependencies
verify_dependencies() {
    echo ""
    echo "========================================="
    echo "Verify Dependencies"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    echo -e "${YELLOW}Checking required dependencies...${NC}"
    echo ""

    # Read requirements.txt and check each package
    missing=()
    installed=()

    while IFS= read -r line; do
        # Skip comments and empty lines
        [[ "$line" =~ ^#.*$ ]] && continue
        [[ -z "$line" ]] && continue

        # Extract package name (before any version specifier)
        pkg=$(echo "$line" | sed 's/[>=<\[].*$//' | xargs)

        if pip show "$pkg" &> /dev/null; then
            version=$(pip show "$pkg" 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
            installed+=("$pkg ($version)")
        else
            missing+=("$pkg")
        fi
    done < "$PROJECT_DIR/requirements.txt"

    # Display results
    echo -e "${GREEN}✓ Installed packages: ${#installed[@]}${NC}"
    for pkg in "${installed[@]}"; do
        echo "  $pkg"
    done

    echo ""

    if [ ${#missing[@]} -eq 0 ]; then
        echo -e "${GREEN}✓ All required dependencies are installed!${NC}"
    else
        echo -e "${RED}✗ Missing packages: ${#missing[@]}${NC}"
        for pkg in "${missing[@]}"; do
            echo "  $pkg"
        done
        echo ""
        echo -n "Do you want to install missing packages? [y/N]: "
        read -r response

        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo ""
            echo -e "${BLUE}Installing missing packages...${NC}"
            pip install -r "$PROJECT_DIR/requirements.txt"
            echo ""
            echo -e "${GREEN}✓ Missing packages installed${NC}"
        fi
    fi

    # Check optional dependencies
    echo ""
    echo -e "${YELLOW}Checking optional AI audio dependencies...${NC}"
    if pip show torch &> /dev/null && pip show demucs &> /dev/null; then
        torch_version=$(pip show torch 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
        demucs_version=$(pip show demucs 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
        echo -e "${GREEN}✓ AI audio features installed${NC}"
        echo "  torch ($torch_version)"
        echo "  demucs ($demucs_version)"
    else
        echo -e "${YELLOW}○ AI audio features not installed (optional)${NC}"
        echo "  Use option 3 to install them"
    fi
}

# Function for full setup
full_setup() {
    echo ""
    echo "========================================="
    echo "Full Setup"
    echo "========================================="
    echo ""

# Step 1: Find or install Python 3.13
echo -e "${YELLOW}[1/3] Checking for Python 3.13...${NC}"

PYTHON_CMD=""

# Initialize conda if it exists but isn't in PATH
if [ -z "$(command -v conda)" ] && [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -z "$(command -v conda)" ] && [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    source "$HOME/anaconda3/etc/profile.d/conda.sh"
elif [ -z "$(command -v conda)" ] && [ -f "/opt/conda/etc/profile.d/conda.sh" ]; then
    source "/opt/conda/etc/profile.d/conda.sh"
fi

# First, try to install via conda if available (preferred method)
if command -v conda &> /dev/null || command -v mamba &> /dev/null; then
    echo -e "${BLUE}Conda/Mamba detected, installing Python 3.13...${NC}"
    if install_python_conda; then
        for py in python3.13 python3 python; do
            if PYTHON_CMD=$(check_python_version "$py"); then
                echo -e "${GREEN}✓ Installed Python 3.13 via conda: $PYTHON_CMD${NC}"
                break
            fi
        done
    fi
else
    echo -e "${YELLOW}Conda/Mamba not detected in PATH${NC}"
fi

# If conda install failed or not available, try to find existing Python 3.13
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}Checking for existing Python 3.13...${NC}"
    for py in python3.13 python3 python; do
        if PYTHON_CMD=$(check_python_version "$py"); then
            echo -e "${GREEN}✓ Found Python 3.13: $PYTHON_CMD${NC}"
            break
        fi
    done
fi

# If still not found, try standalone as last resort
if [ -z "$PYTHON_CMD" ]; then
    echo -e "${YELLOW}Python 3.13 not found. Downloading standalone build...${NC}"
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

# Try creating venv with pip first
if "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null; then
    echo -e "${GREEN}✓ Virtual environment created with pip${NC}"
else
    # If that fails (missing ensurepip), create without pip and install manually
    echo -e "${YELLOW}ensurepip not available, creating venv without pip...${NC}"
    "$PYTHON_CMD" -m venv --without-pip "$VENV_DIR"

    # Activate and install pip manually
    source "$VENV_DIR/bin/activate"

    echo -e "${BLUE}Installing pip manually...${NC}"
    curl -sS https://bootstrap.pypa.io/get-pip.py | python

    if ! command -v pip &> /dev/null; then
        echo -e "${RED}Failed to install pip${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ pip installed successfully${NC}"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Upgrade pip
echo -e "${BLUE}Upgrading pip...${NC}"
pip install --upgrade pip

echo -e "${GREEN}✓ Virtual environment ready${NC}"
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
}

# Main script execution
main() {
    # If script is run with arguments, execute directly
    case "$1" in
        --full-setup)
            full_setup
            exit 0
            ;;
        --update)
            check_updates
            exit 0
            ;;
        --optional)
            install_optional
            exit 0
            ;;
        --verify)
            verify_dependencies
            exit 0
            ;;
    esac

    # Interactive menu mode
    while true; do
        show_menu
        read -r choice

        case $choice in
            1)
                full_setup
                ;;
            2)
                check_updates
                ;;
            3)
                install_optional
                ;;
            4)
                verify_dependencies
                ;;
            5)
                echo ""
                echo -e "${GREEN}Goodbye!${NC}"
                echo ""
                exit 0
                ;;
            *)
                echo ""
                echo -e "${RED}Invalid choice. Please enter 1-5.${NC}"
                ;;
        esac

        echo ""
        echo -n "Press Enter to return to menu..."
        read -r
    done
}

# Run main function
main "$@"
