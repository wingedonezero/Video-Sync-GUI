# VobSub OCR Setup Guide

## Quick Start

### 1. Install Tesseract OCR

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr tesseract-ocr-eng libtesseract-dev libleptonica-dev
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
1. Download installer from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run installer
3. Add Tesseract to PATH

### 2. Install Python Dependencies

```bash
pip install tesserocr Pillow numpy pysubs2
```

**Note**: On some systems, tesserocr may need to be built from source. If `pip install tesserocr` fails:

**Ubuntu/Debian:**
```bash
sudo apt-get install python3-dev
pip install tesserocr --no-binary tesserocr
```

**macOS:**
```bash
brew install pkg-config
pip install tesserocr --no-binary tesserocr
```

### 3. Verify Installation

```bash
# Check Tesseract version (should be 4.0+)
tesseract --version

# Check English language data is installed
tesseract --list-langs
# Should show 'eng' in the list

# Test tesserocr in Python
python3 -c "import tesserocr; print('tesserocr OK')"
```

### 4. Test with Sample VobSub

1. Load a VobSub subtitle track (.idx/.sub) in Video-Sync-GUI
2. Enable "Perform OCR" in track settings
3. Run the pipeline
4. Check output logs for OCR statistics

## Expected Output

```
[OCR] Using native VobSub OCR implementation
[OCR] Processing VobSub file: movie.idx
[OCR] Language: eng
[OCR] Parsing VobSub files...
[OCR] Found 342 subtitle events
[OCR] Initializing OCR engine...
[OCR] Performing OCR on subtitle images...
[OCR] === OCR Statistics ===
[OCR] Total events: 342
[OCR] Successful: 340
[OCR] Low confidence: 12
[OCR] Failed: 2
[OCR] Output: movie.ass
[OCR] Successfully created movie.ass
```

## Troubleshooting

### tesserocr won't install

Try building from source:
```bash
pip install tesserocr --no-binary tesserocr
```

Or use conda:
```bash
conda install -c conda-forge tesserocr
```

### ImportError: libtesseract.so.4

Tesseract library not found. Install system package:
```bash
sudo apt-get install libtesseract-dev
```

### No text recognized

1. Check Tesseract is working:
   ```bash
   tesseract --list-langs
   ```

2. Check English data is installed:
   ```bash
   ls /usr/share/tesseract-ocr/*/eng.traineddata
   ```

3. If missing, install language data:
   ```bash
   sudo apt-get install tesseract-ocr-eng
   ```

## Performance Tips

- **Enable upscaling**: Set `ocr_preprocessing_scale: True` (default)
- **Disable denoising**: Set `ocr_preprocessing_denoise: False` unless needed
- **Use PSM 7**: Keep `ocr_tesseract_psm: 7` for best subtitle accuracy
- **Use LSTM mode**: Keep `ocr_tesseract_oem: 1` for best accuracy

## Configuration

Edit settings in GUI or `settings.json`:

```json
{
  "ocr_engine": "tesseract",
  "ocr_tesseract_psm": 7,
  "ocr_tesseract_oem": 1,
  "ocr_preprocessing_scale": true,
  "ocr_preprocessing_denoise": false,
  "ocr_target_dpi": 300,
  "ocr_min_confidence": 0,
  "ocr_preserve_positioning": true
}
```

## What Changed from Old System

- ❌ **Removed**: `subtile_ocr_path` (no longer needed)
- ❌ **Removed**: `subtile_ocr_char_blacklist` (use `ocr_whitelist_chars` instead)
- ✅ **Added**: Native Python VobSub parser
- ✅ **Added**: Direct Tesseract integration
- ✅ **Added**: ASS output with positioning
- ✅ **Added**: Confidence scores and statistics

## Support

For issues:
1. Check logs for detailed error messages
2. Verify Tesseract installation: `tesseract --version`
3. Verify tesserocr import: `python -c "import tesserocr"`
4. Check VobSub files are valid (can be opened in SubtitleEdit)
