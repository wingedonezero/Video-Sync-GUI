#!/bin/bash

# Video Sync GUI - Application Launcher
# Runs the application in a terminal window so you can see any errors

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

# Check if virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${RED}Error: Virtual environment not found!${NC}"
    echo ""
    echo "Please run the setup script first:"
    echo -e "  ${BLUE}./setup_env.sh${NC}"
    echo ""
    exit 1
fi

# Function to run in current terminal
run_in_current_terminal() {
    echo "========================================="
    echo "Video Sync GUI"
    echo "========================================="
    echo ""
    echo -e "${BLUE}Starting application...${NC}"
    echo -e "${YELLOW}Press Ctrl+C to exit${NC}"
    echo ""

    cd "$PROJECT_DIR"
    source "$VENV_DIR/bin/activate"
    python main.py

    # Keep terminal open on error
    EXIT_CODE=$?
    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo -e "${RED}Application exited with error code: $EXIT_CODE${NC}"
        echo -e "${YELLOW}Press Enter to close...${NC}"
        read
    fi
}

# If running from a terminal, just run it
if [ -t 0 ]; then
    run_in_current_terminal
else
    # Try to open in a new terminal window
    # Detect available terminal emulator
    if command -v konsole &> /dev/null; then
        # KDE Konsole
        konsole --hold -e bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py || (echo -e '\n${RED}Error occurred. Press Enter to close...${NC}' && read)"
    elif command -v gnome-terminal &> /dev/null; then
        # GNOME Terminal
        gnome-terminal -- bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py || (echo -e '\n${RED}Error occurred. Press Enter to close...${NC}' && read); exec bash"
    elif command -v xfce4-terminal &> /dev/null; then
        # XFCE Terminal
        xfce4-terminal --hold -e "bash -c \"cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py\""
    elif command -v alacritty &> /dev/null; then
        # Alacritty
        alacritty --hold -e bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py"
    elif command -v kitty &> /dev/null; then
        # Kitty
        kitty --hold bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py"
    elif command -v xterm &> /dev/null; then
        # xterm (fallback)
        xterm -hold -e bash -c "cd '$PROJECT_DIR' && source '$VENV_DIR/bin/activate' && python main.py"
    else
        # No terminal found, run in current shell
        echo -e "${YELLOW}No suitable terminal emulator found. Running in current shell...${NC}"
        run_in_current_terminal
    fi
fi
