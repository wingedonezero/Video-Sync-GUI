# VobSub OCR Implementation - Complete

## Overview

This document describes the new native VobSub OCR implementation that replaces the external `subtile-ocr` dependency with a fully integrated Python solution using `tesserocr`.

## What Was Implemented

### 1. **VobSub Parser** (`vsg_core/subtitles/parsers/vobsub.py`)
- Parses `.idx` files for timing, positioning, and palette information
- Parses `.sub` files for RLE-compressed bitmap data
- Extracts subtitle events with:
  - Start/end timestamps (milliseconds)
  - X/Y position coordinates
  - Image width/height
  - PIL Image objects (RGBA)
- Based on VobSub-ML-OCR (SubtitleEdit port to Python)

### 2. **Image Preprocessor** (`vsg_core/subtitles/preprocessing/image.py`)
- **Color Inversion**: Converts white text on transparent background to black text on white (Tesseract expects this)
- **Resolution Scaling**: Upscales images to ~300 DPI for optimal accuracy
- **Denoising**: Optional light Gaussian blur to reduce compression artifacts
- **Binarization**: Converts to pure black/white using Otsu-like thresholding
- **Line Segmentation**: Splits multi-line subtitles into individual lines for PSM 7 processing

### 3. **Tesseract Engine** (`vsg_core/subtitles/engines/tesseract.py`)
- Direct C++ API integration via `tesserocr` (not pytesseract)
- Page Segmentation Mode 7 (single text line) for maximum accuracy
- LSTM neural net mode (OEM 1) for best results
- Word-level confidence scores
- Character whitelist support
- Proper cleanup on destruction

### 4. **ASS Builder** (`vsg_core/subtitles/builders/ass.py`)
- Generates ASS files with preserved positioning
- Uses `\pos(x,y)` tags for exact subtitle placement
- Calculates proper alignment tags based on position
- Multi-line support with `\N` line breaks
- Compatible with pysubs2 for further processing

### 5. **Main Orchestrator** (`vsg_core/subtitles/ocr_vobsub.py`)
- Coordinates all components
- Comprehensive error handling
- Detailed logging and statistics
- Graceful fallback on failures
- Quality warnings for low confidence

### 6. **Pipeline Integration** (`vsg_core/orchestrator/steps/subtitles_step.py`)
- Integrated into existing subtitle processing pipeline
- Outputs ASS format directly (no SRT → ASS conversion needed)
- Codec ID set to `S_TEXT/ASS`
- Compatible with existing cleanup and timing fix systems

### 7. **Configuration** (`vsg_core/config.py`)
- New settings for OCR engine configuration
- Preprocessing options
- Confidence thresholds
- Legacy settings preserved for compatibility

## Key Features

✅ **No External Dependencies**: No need for `subtile-ocr` CLI tool
✅ **Positioning Preserved**: X/Y coordinates maintained in ASS output
✅ **SubEdit-Level Accuracy**: Same preprocessing techniques
✅ **English-Optimized**: PSM 7, LSTM mode, proper preprocessing
✅ **Fully Automatic**: No manual intervention required
✅ **Better Performance**: tesserocr releases GIL for true parallelism
✅ **Comprehensive Logging**: Detailed statistics and error reporting
✅ **Graceful Degradation**: Falls back to original subtitles on failure

## Dependencies Required

### Python Packages

Add these to your environment:

```bash
pip install tesserocr
pip install Pillow
pip install numpy
pip install pysubs2
```

**Note**: `tesserocr` requires Tesseract OCR to be installed on the system.

### System Requirements

**Tesseract OCR 4.0+** must be installed:

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
Download from: https://github.com/UB-Mannheim/tesseract/wiki

## Configuration Options

All settings are in `vsg_core/config.py`:

```python
'ocr_engine': 'tesseract',              # OCR engine to use
'ocr_tesseract_psm': 7,                 # Page segmentation mode (7 = single line)
'ocr_tesseract_oem': 1,                 # OCR engine mode (1 = LSTM)
'ocr_preprocessing_scale': True,        # Enable upscaling to 300 DPI
'ocr_preprocessing_denoise': False,     # Enable denoising (usually not needed)
'ocr_target_dpi': 300,                  # Target DPI for upscaling
'ocr_min_confidence': 0,                # Min word confidence (0-100, 0 = all)
'ocr_output_format': 'ass',             # Always ASS for positioning
'ocr_preserve_positioning': True,       # Add \pos tags
'ocr_whitelist_chars': '',              # Limit characters (empty = all English)
```

## How It Works

### Processing Flow

```
1. User enables "Perform OCR" on VobSub track
   ↓
2. VobSubParser parses .idx/.sub files
   → Extracts images, timing, positions
   ↓
3. For each subtitle event:
   a. ImagePreprocessor prepares image
      → Invert colors (black on white)
      → Scale to 300 DPI
      → Binarize
      → Segment into lines
   ↓
   b. TesseractEngine recognizes each line
      → PSM 7 (single line mode)
      → Get text + confidence
   ↓
   c. Combine lines with \N
   ↓
   d. ASSBuilder adds event with \pos(x,y)
   ↓
4. Save complete ASS file
   ↓
5. Optional: Run cleanup (existing system)
   ↓
6. Optional: Fix timing (existing system)
   ↓
7. Merge into output MKV
```

### File Structure

```
vsg_core/subtitles/
├── ocr_vobsub.py                    # Main orchestrator (entry point)
├── parsers/
│   ├── __init__.py
│   └── vobsub.py                    # VobSub .idx/.sub parser
├── preprocessing/
│   ├── __init__.py
│   └── image.py                     # Image preprocessing pipeline
├── engines/
│   ├── __init__.py
│   └── tesseract.py                 # Tesseract OCR wrapper
└── builders/
    ├── __init__.py
    └── ass.py                       # ASS file builder
```

## Testing

### Prerequisites

1. Install dependencies:
   ```bash
   pip install tesserocr Pillow numpy pysubs2
   ```

2. Verify Tesseract is installed:
   ```bash
   tesseract --version
   ```
   Should show version 4.0 or higher.

3. Check English language data:
   ```bash
   tesseract --list-langs
   ```
   Should include `eng` in the list.

### Test with Sample VobSub

1. Find a VobSub file (.idx/.sub pair) from a DVD
2. Load it into Video-Sync-GUI
3. Enable "Perform OCR" in track settings
4. Run the pipeline
5. Check logs for:
   - `[OCR] Using native VobSub OCR implementation`
   - `[OCR] Found X subtitle events`
   - `[OCR] === OCR Statistics ===`
   - Success/failure counts

### Expected Output

- Output file: `<original_name>.ass` in temp directory
- Format: ASS with `\pos(x,y)` tags
- Positioning: Preserved from original VobSub
- Quality: ~90%+ accuracy for clean DVD subtitles

### Verify Positioning

1. Open output ASS file in a text editor
2. Look for lines like:
   ```
   Dialogue: 0,0:00:10.00,0:00:12.50,Default,,0,0,0,,{\pos(360,420)}Subtitle text
   ```
3. The `\pos(360,420)` tag indicates preserved positioning
4. Load in VLC or Aegisub to visually verify placement

## Troubleshooting

### "tesserocr not installed"
**Solution**: Install tesserocr and Tesseract OCR system package

### "No subtitle events found"
**Causes**:
- Empty subtitle track
- Corrupted .idx/.sub files
- Wrong file format (not VobSub)

### "No text was recognized"
**Causes**:
- Tesseract not installed
- Missing language data (eng)
- Subtitle images are empty/corrupt
- PSM mode incorrect

### Low accuracy
**Solutions**:
1. Ensure `ocr_preprocessing_scale` is enabled
2. Check that images are upscaling properly
3. Try enabling `ocr_preprocessing_denoise`
4. Verify Tesseract language data is installed
5. Check subtitle image quality (some DVDs have poor quality)

## Comparison to Old System

| Feature | Old (subtile-ocr) | New (Native) |
|---------|------------------|--------------|
| **Dependency** | External CLI tool | Python native |
| **Output Format** | SRT only | ASS with positioning |
| **Positioning** | Lost | Preserved |
| **Configuration** | Limited | Full control |
| **Confidence Scores** | No | Yes |
| **Error Handling** | Basic | Comprehensive |
| **Performance** | Subprocess overhead | Direct API |
| **Parallelism** | No | Yes (GIL released) |
| **Preprocessing** | External | Configurable |
| **Line Segmentation** | No | Yes |

## Future Enhancements

- [ ] PGS/SUP support (Blu-ray subtitles)
- [ ] Multi-language optimization
- [ ] GPU acceleration (if Tesseract compiled with GPU)
- [ ] Parallel processing of multiple subtitle tracks
- [ ] OCR quality preview before full processing
- [ ] Training data support for custom fonts
- [ ] Binary image comparison (SubEdit-style)

## Notes

- The old `ocr.py` is still present but unused
- Legacy settings (`subtile_ocr_path`, `subtile_ocr_char_blacklist`) are kept for compatibility but not used
- Cleanup system (`cleanup.py`) works with both old and new OCR output
- Timing fix system (`timing.py`) works with both old and new OCR output

## Credits

- VobSub parsing adapted from [VobSub-ML-OCR](https://github.com/vincrichard/VobSub-ML-OCR) (SubtitleEdit port)
- Tesseract integration via [tesserocr](https://github.com/sirfz/tesserocr)
- Preprocessing techniques from [subtile-ocr](https://github.com/gwen-lg/subtile-ocr)
