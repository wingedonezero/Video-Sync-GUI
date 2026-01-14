# Video Sync GUI - Environment Setup

## Problem Solved

After the Arch Linux Python update, many packages became incompatible with the system Python. This setup creates a **completely self-contained environment** with:

- Python 3.13.x (downloaded and installed locally in your project)
- All dependencies installed in `Dependencies/.venv`
- No interference with system Python
- Easy to run without manual activation

## What is `uv`?

`uv` is a blazing-fast Python package manager (written in Rust, like Cargo). It:
- Downloads and manages Python versions for you
- Replaces pip, virtualenv, and other tools
- Installs packages 10-100x faster than pip
- Creates self-contained environments

Think of it as "Cargo for Python" but specifically designed for Python's ecosystem.

## Setup Instructions

### First Time Setup

1. **Run the setup script:**
   ```bash
   ./setup_env.sh
   ```

   This will:
   - Install `uv` if you don't have it
   - Download Python 3.13.x locally (latest available)
   - Create a virtual environment in `Dependencies/.venv`
   - Install all dependencies from `pyproject.toml`

   **Note:** The first run takes a few minutes to download Python and packages. Subsequent runs are much faster.

### Running the Application

2. **Launch the app:**
   ```bash
   ./run.sh
   ```

   This script:
   - Opens a terminal window automatically
   - Runs the application
   - Shows any errors (terminal stays open if something fails)
   - Works with Konsole, GNOME Terminal, XFCE Terminal, Alacritty, Kitty, or xterm

## Manual Usage (Advanced)

If you prefer to run things manually:

```bash
# Activate the environment
source Dependencies/.venv/bin/activate

# Run the application
python main.py

# When done, deactivate
deactivate
```

## Updating Dependencies

If you need to add or update packages:

1. **Edit `pyproject.toml`** and add the package to the `dependencies` list
2. **Re-run setup:**
   ```bash
   ./setup_env.sh
   ```

Or manually:
```bash
source Dependencies/.venv/bin/activate
uv pip install <package-name>
```

## Optional AI Audio Separation (Demucs)

The base installation includes everything needed for the app. However, if you want AI-powered audio separation for cross-language sync, install one of these:

### For NVIDIA GPUs (CUDA):
```bash
source Dependencies/.venv/bin/activate
uv pip install torch demucs
```

### For AMD GPUs (ROCm):
```bash
source Dependencies/.venv/bin/activate
# Install PyTorch with ROCm support first
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
# Then install demucs
uv pip install demucs
```

### For CPU only (slower):
```bash
source Dependencies/.venv/bin/activate
# Install CPU-only PyTorch
uv pip install torch demucs --index-url https://download.pytorch.org/whl/cpu
```

**Note:** Torch + Demucs is a LARGE download (several GB). Only install if you need cross-language audio separation.

## Troubleshooting

### "uv: command not found" after setup
```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

### Want to completely reset?
```bash
rm -rf Dependencies/
./setup_env.sh
```

### Check which Python is being used
```bash
Dependencies/.venv/bin/python --version
```

### Verify packages are installed
```bash
Dependencies/.venv/bin/python -c "import PySide6; print('PySide6 OK')"
```

## Directory Structure

```
Video-Sync-GUI/
├── Dependencies/              # Self-contained environment (gitignored)
│   └── .venv/                # Virtual environment with Python 3.13.x
│       ├── bin/              # Python executable and scripts
│       ├── lib/              # All installed packages
│       └── ...
├── pyproject.toml            # Project configuration and dependencies
├── setup_env.sh              # Setup script (run once)
├── run.sh                    # Launch script (run to start app)
├── main.py                   # Application entry point
└── ...
```

## Benefits of This Approach

✅ **Isolated:** No conflicts with system Python
✅ **Portable:** Everything is in one project directory
✅ **Fast:** `uv` is significantly faster than pip
✅ **Version-locked:** Python 3.13.x won't change unexpectedly
✅ **Clean:** `Dependencies/` is gitignored, won't bloat your repo
✅ **Easy:** Just `./run.sh` to launch the app

## How It Works

1. **`uv`** downloads Python 3.13.x binaries (latest available)
2. Creates a virtual environment at `Dependencies/.venv`
3. Installs all packages using `uv pip` (super fast)
4. `run.sh` activates the environment and runs `main.py`
5. Everything is self-contained—no system Python needed

---

**Questions?** Check the `uv` documentation: https://docs.astral.sh/uv/
