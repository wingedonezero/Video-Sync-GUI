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

    # Use venv Python directly to ensure correct environment
    # This is more reliable than activating and hoping PATH is correct
    "$VENV_DIR/bin/python" main.py 2>&1
    EXIT_CODE=$?

    # Always show exit status and wait
    echo ""
    if [ $EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}Application exited normally${NC}"
    else
        echo -e "${RED}Application exited with error code: $EXIT_CODE${NC}"
    fi
    echo -e "${YELLOW}Press Enter to close...${NC}"
    read
}

# Wrapper script for terminal emulators - ensures errors are shown
WRAPPER_CMD="cd '$PROJECT_DIR' && echo '=========================================' && echo 'Video Sync GUI' && echo '=========================================' && echo '' && echo 'Starting application...' && echo '' && '$VENV_DIR/bin/python' main.py 2>&1; EXIT_CODE=\$?; echo ''; if [ \$EXIT_CODE -eq 0 ]; then echo -e '${GREEN}Application exited normally${NC}'; else echo -e '${RED}Application exited with error code:' \$EXIT_CODE'${NC}'; fi; echo -e '${YELLOW}Press Enter to close...${NC}'; read"

# If running from a terminal, just run it
if [ -t 0 ]; then
    run_in_current_terminal
else
    # Try to open in a new terminal window
    # Detect available terminal emulator
    if command -v konsole &> /dev/null; then
        # KDE Konsole
        konsole -e bash -c "$WRAPPER_CMD"
    elif command -v gnome-terminal &> /dev/null; then
        # GNOME Terminal
        gnome-terminal -- bash -c "$WRAPPER_CMD"
    elif command -v xfce4-terminal &> /dev/null; then
        # XFCE Terminal
        xfce4-terminal -e "bash -c \"$WRAPPER_CMD\""
    elif command -v alacritty &> /dev/null; then
        # Alacritty
        alacritty -e bash -c "$WRAPPER_CMD"
    elif command -v kitty &> /dev/null; then
        # Kitty
        kitty bash -c "$WRAPPER_CMD"
    elif command -v xterm &> /dev/null; then
        # xterm (fallback)
        xterm -e bash -c "$WRAPPER_CMD"
    else
        # No terminal found, run in current shell
        echo -e "${YELLOW}No suitable terminal emulator found. Running in current shell...${NC}"
        run_in_current_terminal
    fi
fi
