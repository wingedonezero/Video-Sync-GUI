# Video Sync GUI - Environment Setup

## Problem Solved

After the Arch Linux Python update, many packages became incompatible with the system Python. This setup creates a **completely self-contained environment** with:

- Python 3.13.x (downloaded and installed locally in your project)
- All dependencies installed in `python/.venv`
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
   ./python/setup_env.sh
   ```

   This will:
   - Install `uv` if you don't have it
   - Download Python 3.13.x locally (latest available)
   - Create a virtual environment in `python/.venv`
   - Install all dependencies from `pyproject.toml`

   **Note:** The first run takes a few minutes to download Python and packages. Subsequent runs are much faster.

### Running the Application

2. **Launch the app:**
   ```bash
   ./python/run.sh
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
source python/.venv/bin/activate

# Run the application
cd python
python main.py

# When done, deactivate
deactivate
```

## Updating Dependencies

If you need to add or update packages:

1. **Edit `pyproject.toml`** and add the package to the `dependencies` list
2. **Re-run setup:**
   ```bash
   ./python/setup_env.sh
   ```

Or manually:
```bash
source python/.venv/bin/activate
uv pip install <package-name>
```

## Optional AI Audio Separation (Audio Separator)

The base installation includes everything needed for the app. However, if you want AI-powered audio separation for cross-language sync, install one of these:

### For NVIDIA GPUs (CUDA):
```bash
source python/.venv/bin/activate
uv pip install "audio-separator[gpu]"
```

### For AMD GPUs (ROCm):
```bash
source python/.venv/bin/activate
# Install PyTorch with ROCm support first
pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
# Then install audio-separator (CPU extra works with ROCm torch)
uv pip install "audio-separator[cpu]"
```

### For CPU only (slower):
```bash
source python/.venv/bin/activate
# Install audio-separator CPU build
uv pip install "audio-separator[cpu]"
```

**Note:** Audio-separator downloads model files automatically on first use. Only install if you need cross-language audio separation.

## Troubleshooting

### "uv: command not found" after setup
```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

### Want to completely reset?
```bash
rm -rf python/.venv
./python/setup_env.sh
```

### Check which Python is being used
```bash
python/.venv/bin/python --version
```

### Verify packages are installed
```bash
python/.venv/bin/python -c "import PySide6; print('PySide6 OK')"
```

## Directory Structure

```
Video-Sync-GUI/
├── python/
│   ├── .venv/                # Virtual environment with Python 3.13.x
│   │   ├── bin/              # Python executable and scripts
│   │   ├── lib/              # All installed packages
│   │   └── ...
│   ├── setup_env.sh          # Setup script (run once)
│   ├── run.sh                # Launch script (run to start app)
│   ├── main.py               # Application entry point
└── ...
```

## Benefits of This Approach

✅ **Isolated:** No conflicts with system Python
✅ **Portable:** Everything is in one project directory
✅ **Fast:** `uv` is significantly faster than pip
✅ **Version-locked:** Python 3.13.x won't change unexpectedly
✅ **Clean:** `python/.venv` is gitignored, won't bloat your repo
✅ **Easy:** Just `./python/run.sh` to launch the app

## How It Works

1. **`uv`** downloads Python 3.13.x binaries (latest available)
2. Creates a virtual environment at `python/.venv`
3. Installs all packages using `uv pip` (super fast)
4. `python/run.sh` activates the environment and runs `main.py`
5. Everything is self-contained—no system Python needed

---

**Questions?** Check the `uv` documentation: https://docs.astral.sh/uv/
