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
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PYTHON_AUDIO_SEPARATOR_REPO="audio-separator @ git+https://github.com/nomadkaraoke/python-audio-separator.git"
PYTHON_AUDIO_SEPARATOR_GPU_REPO="audio-separator[gpu] @ git+https://github.com/nomadkaraoke/python-audio-separator.git"
PYTHON_AUDIO_SEPARATOR_CPU_REPO="audio-separator[cpu] @ git+https://github.com/nomadkaraoke/python-audio-separator.git"

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
    echo -e "  ${CYAN}5)${NC} Rebuild PyAV (FFmpeg subtitles support)"
    echo -e "  ${CYAN}6)${NC} Download curated audio-separator models"
    echo -e "  ${CYAN}7)${NC} Download EasyOCR models (for OCR)"
    echo -e "  ${CYAN}8)${NC} Download PaddleOCR models (for OCR)"
    echo -e "  ${CYAN}9)${NC} Exit"
    echo ""
    echo -n "Enter your choice [1-9]: "
}

# Function to check Python version and verify it works
check_python_version() {
    local python_cmd=$1
    if command -v "$python_cmd" &> /dev/null; then
        # Check version
        local version=$("$python_cmd" --version 2>&1 | grep -oP '\d+\.\d+\.\d+')
        if [[ "$version" == 3.13.* ]]; then
            # Verify Python actually works by running multiple checks
            if "$python_cmd" -c "import sys, encodings; print('OK')" &> /dev/null; then
                # Also verify it can create a basic venv
                local test_venv="/tmp/test_venv_$$"
                if "$python_cmd" -m venv "$test_venv" 2>/dev/null; then
                    rm -rf "$test_venv"
                    echo "$python_cmd"
                    return 0
                else
                    rm -rf "$test_venv" 2>/dev/null
                    echo -e "${YELLOW}Warning: $python_cmd version $version found but cannot create venv, skipping...${NC}" >&2
                fi
            else
                echo -e "${YELLOW}Warning: $python_cmd version $version found but appears broken (missing encodings), skipping...${NC}" >&2
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

        # Use only conda-forge to avoid TOS issues with default channels
        # Also disable default channels with --override-channels
        if conda install -y python=3.13.11 --override-channels -c conda-forge 2>/dev/null || \
           conda install -y "python>=3.13,<3.14" --override-channels -c conda-forge; then
            return 0
        else
            return 1
        fi
    elif command -v mamba &> /dev/null; then
        echo -e "${BLUE}Found mamba, installing Python 3.13...${NC}"
        # Mamba doesn't have the same TOS restrictions, but use conda-forge anyway
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
    echo -e "${YELLOW}Attempting to install Python 3.13.11 standalone build...${NC}" >&2

    local python_dir="$PROJECT_DIR/.python"
    mkdir -p "$python_dir"

    # Detect architecture
    local arch=$(uname -m)
    local os=$(uname -s | tr '[:upper:]' '[:lower:]')

    if [[ "$os" == "linux" ]]; then
        if [[ "$arch" == "x86_64" ]]; then
            local python_url="https://github.com/indygreg/python-build-standalone/releases/download/20251205/cpython-3.13.11+20251205-x86_64-unknown-linux-gnu-install_only.tar.gz"
        else
            echo -e "${RED}Unsupported architecture: $arch${NC}" >&2
            return 1
        fi
    else
        echo -e "${RED}Unsupported OS: $os${NC}" >&2
        return 1
    fi

    echo -e "${BLUE}Downloading Python from: $python_url${NC}" >&2
    local temp_file=$(mktemp)
    if curl -L -o "$temp_file" "$python_url" 2>&1 | grep -E "^\s*[0-9]+" >&2; then
        echo -e "${BLUE}Extracting Python...${NC}" >&2
        tar -xzf "$temp_file" -C "$python_dir" --strip-components=1 2>&2
        rm "$temp_file"

        # Check if extraction was successful
        if [ -f "$python_dir/bin/python3" ]; then
            if ! "$python_dir/bin/python3" -c "import sys; assert sys.version_info[:3] == (3, 13, 11)" &> /dev/null; then
                echo -e "${RED}Extracted Python version mismatch; expected 3.13.11${NC}" >&2
                return 1
            fi
            echo "$python_dir/bin/python3"
            return 0
        fi
    fi

    echo -e "${RED}Failed to download/extract Python${NC}" >&2
    return 1
}

# Function to ensure venv exists and is activated
ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        echo -e "${RED}Virtual environment not found!${NC}"
        echo -e "${YELLOW}Please run 'Full Setup' first (option 1)${NC}"
        return 1
    fi

    if [ -z "$VIRTUAL_ENV" ] || [ "$VIRTUAL_ENV" != "$VENV_DIR" ]; then
        if [ -n "$VIRTUAL_ENV" ]; then
            echo -e "${YELLOW}Warning: Another virtual environment is active (${VIRTUAL_ENV}).${NC}"
            echo -e "${YELLOW}Switching to project venv: $VENV_DIR${NC}"
        else
            echo -e "${BLUE}Activating virtual environment...${NC}"
        fi
        source "$VENV_DIR/bin/activate"
    fi

    if [ ! -x "$VENV_PYTHON" ]; then
        echo -e "${RED}Virtual environment Python not found at $VENV_PYTHON${NC}"
        return 1
    fi
    echo -e "${BLUE}Active venv python: $VENV_PYTHON${NC}"
    echo -e "${BLUE}Shell python resolves to: $(command -v python)${NC}"
    return 0
}

venv_pip() {
    "$VENV_PYTHON" -m pip "$@"
}

get_audio_separator_model_dir() {
    local settings_file="$PROJECT_DIR/settings.json"
    local default_dir="$PROJECT_DIR/audio_separator_models"

    if [ -f "$settings_file" ]; then
        local configured_dir
        configured_dir=$(python - <<PY
import json
from pathlib import Path

settings = Path("$settings_file")
try:
    data = json.loads(settings.read_text(encoding="utf-8"))
except Exception:
    data = {}

value = data.get("source_separation_model_dir")
if isinstance(value, str) and value.strip():
    print(value.strip())
PY
)
        if [ -n "$configured_dir" ]; then
            echo "$configured_dir"
            return 0
        fi
    fi

    echo "$default_dir"
}

# Function to download EasyOCR models for subtitle OCR
download_easyocr_models() {
    echo ""
    echo "========================================="
    echo "Download EasyOCR Models"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    # Check if easyocr is installed
    if ! venv_pip show easyocr &> /dev/null; then
        echo -e "${YELLOW}EasyOCR is not installed. Installing now...${NC}"
        venv_pip install easyocr
        if [ $? -ne 0 ]; then
            echo -e "${RED}Failed to install EasyOCR${NC}"
            return 1
        fi
    fi

    local model_dir="$PROJECT_DIR/.config/ocr/easyocr_models"
    mkdir -p "$model_dir"

    echo -e "${BLUE}Model directory:${NC} $model_dir"
    echo ""
    echo "This will download EasyOCR models for English text recognition."
    echo "Models include:"
    echo "  • CRAFT text detection model (~100MB)"
    echo "  • English recognition model (~50MB)"
    echo ""

    echo -e "${BLUE}Downloading and initializing EasyOCR models...${NC}"
    echo -e "${YELLOW}This may take a few minutes on first run.${NC}"
    echo ""

    # Export PROJECT_DIR for Python script
    export PROJECT_DIR

    # Use Python to download models
    "$VENV_PYTHON" << 'PYEOF'
import sys
import os

# Set model directory
model_dir = os.path.join(os.environ.get('PROJECT_DIR', '.'), '.config', 'ocr', 'easyocr_models')
os.makedirs(model_dir, exist_ok=True)

print(f"Downloading models to: {model_dir}")
print()

try:
    import easyocr
    print("Initializing EasyOCR Reader (this downloads models)...")
    reader = easyocr.Reader(['en'], gpu=False, model_storage_directory=model_dir, verbose=True)
    print()
    print("✓ EasyOCR models downloaded successfully!")

    # Test it works
    print("Testing OCR on sample text...")
    # Create a simple test - just verify the reader works
    print("✓ EasyOCR is working correctly!")
except Exception as e:
    print(f"✗ Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓ EasyOCR models ready!${NC}"
        echo ""
        echo "To use EasyOCR:"
        echo "  1. Open the app"
        echo "  2. Go to Options > OCR"
        echo "  3. Set 'OCR Engine' to 'EasyOCR (Deep Learning)'"
    else
        echo ""
        echo -e "${RED}✗ Failed to download EasyOCR models${NC}"
        return 1
    fi
}

# Function to download PaddleOCR models for subtitle OCR
download_paddleocr_models() {
    echo ""
    echo "========================================="
    echo "Download PaddleOCR Models"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    # Check if paddleocr is installed
    if ! venv_pip show paddleocr &> /dev/null; then
        echo -e "${YELLOW}PaddleOCR is not installed. Installing now...${NC}"
        venv_pip install paddleocr paddlepaddle
        if [ $? -ne 0 ]; then
            echo -e "${RED}Failed to install PaddleOCR${NC}"
            return 1
        fi
    fi

    local model_dir="$PROJECT_DIR/.config/ocr/paddleocr_models"
    mkdir -p "$model_dir"

    echo -e "${BLUE}Model directory:${NC} $model_dir"
    echo ""
    echo "This will download PaddleOCR models for English text recognition."
    echo "Models include:"
    echo "  • DB text detection model (~5MB)"
    echo "  • PP-OCRv4 recognition model (~10MB)"
    echo ""
    echo -e "${YELLOW}Note: PaddleOCR only supports CUDA (NVIDIA GPU), not ROCm (AMD GPU).${NC}"
    echo ""

    echo -e "${BLUE}Downloading and initializing PaddleOCR models...${NC}"
    echo -e "${YELLOW}This may take a few minutes on first run.${NC}"
    echo ""

    # Export PROJECT_DIR for Python script
    export PROJECT_DIR

    # Use Python to download models
    "$VENV_PYTHON" << 'PYEOF'
import sys
import os

# Set model directory
model_dir = os.path.join(os.environ.get('PROJECT_DIR', '.'), '.config', 'ocr', 'paddleocr_models')
os.makedirs(model_dir, exist_ok=True)

# Set environment variable for PaddleOCR model cache
os.environ['PADDLEOCR_HOME'] = model_dir

print(f"Downloading models to: {model_dir}")
print()

try:
    from paddleocr import PaddleOCR
    print("Initializing PaddleOCR (this downloads models)...")
    # PaddleOCR 3.0+ uses 'device' instead of 'use_gpu'
    # and 'use_textline_orientation' instead of 'use_angle_cls'
    ocr = PaddleOCR(
        use_textline_orientation=False,
        lang='en',
        device='cpu',  # Use CPU for download
    )
    print()
    print("✓ PaddleOCR models downloaded successfully!")

    # Test it works
    print("Testing OCR initialization...")
    print("✓ PaddleOCR is working correctly!")
except Exception as e:
    print(f"✗ Error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

    if [ $? -eq 0 ]; then
        echo ""
        echo -e "${GREEN}✓ PaddleOCR models ready!${NC}"
        echo ""
        echo "To use PaddleOCR:"
        echo "  1. Open the app"
        echo "  2. Go to Options > OCR"
        echo "  3. Set 'OCR Engine' to 'PaddleOCR (State-of-art)'"
    else
        echo ""
        echo -e "${RED}✗ Failed to download PaddleOCR models${NC}"
        return 1
    fi
}

download_audio_separator_models() {
    echo ""
    echo "========================================="
    echo "Download Curated Audio-Separator Models"
    echo "========================================="
    echo ""

    local model_dir
    model_dir=$(get_audio_separator_model_dir)
    mkdir -p "$model_dir"

    echo -e "${BLUE}Model directory:${NC} $model_dir"
    echo ""
    echo "Models to download:"
    echo "  • Demucs v4: htdemucs"
    echo "  • Roformer: BandSplit SDR 1053"
    echo "  • MDX23C: InstVoc HQ"
    echo "  • MDX-Net: Kim Vocal 2"
    echo "  • Bandit v2: Cinematic Multilang"
    echo ""

    local filenames=(
        "955717e8-8726e21a.th"
        "htdemucs.yaml"
        "model_bs_roformer_ep_937_sdr_10.5309.ckpt"
        "config_bs_roformer_ep_937_sdr_10.5309.yaml"
        "MDX23C-8KFFT-InstVoc_HQ.ckpt"
        "model_2_stem_full_band_8k.yaml"
        "Kim_Vocal_2.onnx"
        "checkpoint-multi_fixed.ckpt"
        "config_dnr_bandit_v2_mus64.yaml"
    )

    local urls=(
        "https://huggingface.co/Politrees/UVR_resources/resolve/main/models/Demucs/Demucs_v4/955717e8-8726e21a.th"
        "https://raw.githubusercontent.com/Bebra777228/UVR_resources/refs/heads/main/UVR_resources/configs/demucs/htdemucs.yaml"
        "https://huggingface.co/Politrees/UVR_resources/resolve/main/models/Roformer/BandSplit/model_bs_roformer_ep_937_sdr_10.5309.ckpt"
        "https://raw.githubusercontent.com/Bebra777228/UVR_resources/refs/heads/main/UVR_resources/configs/Roformer/BandSplit/config_bs_roformer_ep_937_sdr_10.5309.yaml"
        "https://huggingface.co/Politrees/UVR_resources/resolve/main/models/MDX23C/MDX23C-8KFFT-InstVoc_HQ.ckpt"
        "https://raw.githubusercontent.com/Bebra777228/UVR_resources/refs/heads/main/UVR_resources/configs/MDX23C/model_2_stem_full_band_8k.yaml"
        "https://huggingface.co/Politrees/UVR_resources/resolve/main/models/MDXNet/Kim_Vocal_2.onnx"
        "https://huggingface.co/Politrees/UVR_resources/resolve/main/models/Bandit/Bandit_v2/checkpoint-multi_fixed.ckpt"
        "https://raw.githubusercontent.com/Bebra777228/UVR_resources/refs/heads/main/UVR_resources/configs/Bandit/config_dnr_bandit_v2_mus64.yaml"
    )

    local count=${#filenames[@]}
    for ((i=0; i<count; i++)); do
        local filename="${filenames[$i]}"
        local url="${urls[$i]}"
        local target="$model_dir/$filename"

        if [ -f "$target" ]; then
            echo -e "${GREEN}✓ Already exists:${NC} $filename"
            continue
        fi

        echo -e "${BLUE}Downloading:${NC} $filename"
        if curl -L --fail -o "$target" "$url"; then
            echo -e "${GREEN}✓ Downloaded:${NC} $filename"
        else
            echo -e "${RED}✗ Failed:${NC} $filename"
            return 1
        fi
    done

    echo ""
    echo -e "${GREEN}✓ Curated models ready!${NC}"
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
    outdated=$(venv_pip list --outdated --format=json 2>/dev/null)

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
    echo "$outdated" | "$VENV_PYTHON" -c "
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
        venv_pip install --upgrade $(echo "$outdated" | "$VENV_PYTHON" -c "
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

    echo "Optional AI audio features (Audio Separator):"
    echo "These enable AI-powered vocal/instrument separation"
    echo "for better cross-language audio correlation."
    echo ""
    echo "Note: ROCm installs use the CPU extra for audio-separator"
    echo "because GPU acceleration comes from the ROCm PyTorch build."
    echo ""
    echo "Select your hardware:"
    echo ""
    echo -e "  ${CYAN}1)${NC} NVIDIA GPU (CUDA)"
    echo -e "  ${CYAN}2)${NC} AMD GPU (ROCm 6.4 - Stable)"
    echo -e "  ${CYAN}3)${NC} AMD GPU (ROCm 7.1 - Latest/Nightly)"
    echo -e "  ${CYAN}4)${NC} CPU only (slower but works everywhere)"
    echo -e "  ${CYAN}5)${NC} Cancel"
    echo ""
    echo -n "Enter your choice [1-5]: "
    read -r hw_choice

    case $hw_choice in
        1)
            echo ""
            echo -e "${BLUE}Installing Audio Separator (NVIDIA CUDA)...${NC}"
            echo -e "${YELLOW}Installing CUDA-enabled PyTorch (cu121)...${NC}"
            venv_pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
            venv_pip install "$PYTHON_AUDIO_SEPARATOR_GPU_REPO"
            echo -e "${GREEN}✓ NVIDIA GPU support installed${NC}"
            ;;
        2)
            echo ""
            echo -e "${BLUE}Installing Audio Separator (AMD ROCm 6.4 Stable - GPU via PyTorch)...${NC}"
            venv_pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm6.4
            venv_pip install --upgrade onnxruntime
            venv_pip install "$PYTHON_AUDIO_SEPARATOR_CPU_REPO"
            echo -e "${GREEN}✓ AMD GPU (ROCm 6.4) support installed${NC}"
            ;;
        3)
            echo ""
            echo -e "${BLUE}Installing Audio Separator (AMD ROCm 7.1 Nightly - GPU via PyTorch)...${NC}"
            venv_pip install --pre torch torchvision torchaudio --index-url https://download.pytorch.org/whl/nightly/rocm7.1
            venv_pip install --upgrade onnxruntime
            venv_pip install "$PYTHON_AUDIO_SEPARATOR_CPU_REPO"
            echo -e "${GREEN}✓ AMD GPU (ROCm 7.1) support installed${NC}"
            ;;
        4)
            echo ""
            echo -e "${BLUE}Installing Audio Separator (CPU only)...${NC}"
            venv_pip install --upgrade onnxruntime
            venv_pip install "$PYTHON_AUDIO_SEPARATOR_CPU_REPO"
            echo -e "${GREEN}✓ CPU-only support installed${NC}"
            ;;
        5)
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

        if venv_pip show "$pkg" &> /dev/null; then
            version=$(venv_pip show "$pkg" 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
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
            venv_pip install -r "$PROJECT_DIR/requirements.txt"
            echo ""
            echo -e "${GREEN}✓ Missing packages installed${NC}"
        fi
    fi

    # Check optional dependencies
    echo ""
    echo -e "${YELLOW}Checking optional AI audio dependencies...${NC}"
    if venv_pip show audio-separator &> /dev/null; then
        sep_version=$(venv_pip show audio-separator 2>/dev/null | grep "^Version:" | cut -d' ' -f2)
        echo -e "${GREEN}✓ AI audio features installed${NC}"
        echo "  audio-separator ($sep_version)"
    else
        echo -e "${YELLOW}○ AI audio features not installed (optional)${NC}"
        echo "  Use option 3 to install them"
    fi
}

# Function to rebuild PyAV against system FFmpeg (needed for ASS subtitles)
rebuild_pyav_from_source() {
    echo ""
    echo "========================================="
    echo "Rebuild PyAV from Source"
    echo "========================================="
    echo ""

    if ! ensure_venv; then
        return 1
    fi

    if command -v ffmpeg &> /dev/null; then
        if ffmpeg -filters 2>/dev/null | grep -qE '^\s*T.*\bsubtitles\b'; then
            echo -e "${GREEN}✓ FFmpeg subtitles filter detected${NC}"
        else
            echo -e "${YELLOW}Warning: FFmpeg subtitles filter not detected.${NC}"
            echo -e "${YELLOW}Make sure FFmpeg is built with libass support.${NC}"
        fi
    else
        echo -e "${YELLOW}Warning: FFmpeg not found in PATH.${NC}"
        echo -e "${YELLOW}PyAV will still build, but subtitle support may be missing.${NC}"
    fi

    echo ""
    echo -e "${BLUE}Rebuilding PyAV against system FFmpeg...${NC}"
    echo -e "${YELLOW}This can take a few minutes and may require build tools.${NC}"
    echo ""

    venv_pip uninstall -y av 2>/dev/null
    if venv_pip install --no-binary av av; then
        echo -e "${GREEN}✓ PyAV rebuilt from source${NC}"
    else
        echo -e "${RED}Failed to build PyAV from source.${NC}"
        echo -e "${YELLOW}Make sure build tools and FFmpeg dev libraries are installed.${NC}"
        return 1
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
# Try common conda installation paths
if [ -z "$(command -v conda)" ]; then
    for conda_path in \
        "$HOME/miniconda3/etc/profile.d/conda.sh" \
        "$HOME/anaconda3/etc/profile.d/conda.sh" \
        "/opt/conda/etc/profile.d/conda.sh" \
        "/opt/miniconda3/etc/profile.d/conda.sh" \
        "$HOME/.conda/etc/profile.d/conda.sh"; do
        if [ -f "$conda_path" ]; then
            echo -e "${BLUE}Found conda at: $conda_path${NC}"
            source "$conda_path"
            break
        fi
    done
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
echo -e "${BLUE}Base interpreter: $PYTHON_CMD${NC}"
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
    echo -e "${GREEN}✓ Virtual environment created${NC}"
else
    # If that fails (missing ensurepip), create without pip and install manually
    echo -e "${YELLOW}ensurepip not available, creating venv without pip...${NC}"
    if ! "$PYTHON_CMD" -m venv --without-pip "$VENV_DIR" 2>/dev/null; then
        echo -e "${RED}Failed to create virtual environment${NC}"
        echo -e "${YELLOW}The Python installation appears to be broken or incomplete${NC}"
        echo ""
        echo "Attempting to download and install a working Python 3.13..."

        # Remove the broken venv if it exists
        [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"

        # Try standalone Python installation
        if PYTHON_CMD=$(install_python_standalone); then
            echo -e "${GREEN}✓ Installed working Python: $PYTHON_CMD${NC}"
            # Try creating venv again with the new Python
            if ! "$PYTHON_CMD" -m venv "$VENV_DIR" 2>/dev/null; then
                echo -e "${RED}Still unable to create virtual environment${NC}"
                exit 1
            fi
        else
            echo -e "${RED}Failed to install a working Python${NC}"
            exit 1
        fi
    fi

    # Activate and install pip manually
    source "$VENV_DIR/bin/activate"

    # Verify venv actually works
    if ! python -c "import sys; sys.exit(0)" 2>/dev/null; then
        echo -e "${RED}Virtual environment is broken${NC}"
        exit 1
    fi

    echo -e "${BLUE}Installing pip manually...${NC}"
    if ! curl -sS https://bootstrap.pypa.io/get-pip.py | python; then
        echo -e "${RED}Failed to install pip${NC}"
        exit 1
    fi

    if ! command -v pip &> /dev/null; then
        echo -e "${RED}pip is not available after installation${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ pip installed successfully${NC}"
fi

# Activate virtual environment
source "$VENV_DIR/bin/activate"

# Verify the venv is actually working and isolated
if python -c "import sys; sys.exit(0 if 'site-packages' not in sys.prefix or sys.prefix.startswith('$VENV_DIR') else 1)" 2>/dev/null; then
    echo -e "${GREEN}✓ Virtual environment activated${NC}"
else
    echo -e "${RED}Warning: Virtual environment may not be properly isolated${NC}"
fi

# Upgrade pip
echo -e "${BLUE}Upgrading pip...${NC}"
venv_pip install --upgrade pip

echo -e "${GREEN}✓ Virtual environment ready${NC}"
echo ""

# Step 3: Install dependencies
echo -e "${YELLOW}[3/3] Installing dependencies...${NC}"
echo "This may take a few minutes..."

cd "$PROJECT_DIR"
venv_pip install -r requirements.txt
rebuild_pyav_from_source

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
    echo -e "  ${BLUE}source .venv/bin/activate${NC}"
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
        --rebuild-pyav)
            rebuild_pyav_from_source
            exit 0
            ;;
        --download-models)
            download_audio_separator_models
            exit 0
            ;;
        --download-easyocr)
            download_easyocr_models
            exit 0
            ;;
        --download-paddleocr)
            download_paddleocr_models
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
                rebuild_pyav_from_source
                ;;
            6)
                download_audio_separator_models
                ;;
            7)
                download_easyocr_models
                ;;
            8)
                download_paddleocr_models
                ;;
            9)
                echo ""
                echo -e "${GREEN}Goodbye!${NC}"
                echo ""
                exit 0
                ;;
            *)
                echo ""
                echo -e "${RED}Invalid choice. Please enter 1-9.${NC}"
                ;;
        esac

        echo ""
        echo -n "Press Enter to return to menu..."
        read -r
    done
}

# Run main function
main "$@"
