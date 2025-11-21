# PGS OCR Testing Guide

## Prerequisites

1. **Install Tesseract OCR**:
   ```bash
   # Ubuntu/Debian
   sudo apt-get install tesseract-ocr tesseract-ocr-eng

   # macOS
   brew install tesseract

   # Verify installation
   tesseract --version
   ```

2. **Install Python dependencies** (should already be installed):
   ```bash
   pip install Pillow
   ```

## Testing Steps

### Option 1: Test with Real Job (Recommended)

1. **Open Video-Sync-GUI**
   ```bash
   python main.py
   ```

2. **Configure PGS OCR Settings**:
   - Go to **Options** (gear icon or menu)
   - Navigate to **"Storage & Tools"** tab
   - Scroll down to **"PGS OCR (Blu-ray SUP)"** section
   - Settings you can adjust:
     - **Tesseract Path**: Leave blank for auto-detection (or specify path)
     - **Video Dimensions**: Set to match your video (default 1920x1080)
     - **Crop transparent borders**: Enabled (recommended)
     - **Convert yellow text to white**: Enabled (recommended)
     - **Binarize image**: Enabled (recommended)
     - **Binarize Threshold**: 200 (adjust if OCR quality is poor)
     - **Contrast Enhancement**: 1.5 (increase if low-contrast subs)
     - **Add Margin**: 10px (adds white space around text)
   - Click **Save**

3. **Add a Job with PGS Subtitles**:
   - Add your video file(s) that contain PGS subtitles (.sup format)
   - OR: Add extracted .sup files directly
   - Make sure "Enable OCR" is checked in job settings
   - Set OCR language to "eng" (or appropriate language code)

4. **Run the Job**:
   - Start the job and monitor the log output
   - Look for messages like:
     ```
     [PGS OCR] Parsing movie_subtitles.sup...
     [PGS OCR] Found 523 subtitles
     [PGS OCR] Processing subtitle 1/523...
     [PGS OCR]   -> 'Hello, world!' at (960, 1020)
     [PGS OCR] Successfully created movie_subtitles.ass with 523 subtitles
     ```

5. **Check Output**:
   - Output will be an .ass file (Advanced SubStation Alpha)
   - Check that positioning is preserved (top/bottom/side subtitles)
   - Verify OCR accuracy

### Option 2: Standalone Test Script

If you want to test just the OCR without a full job:

```bash
python test_pgs_ocr.py /path/to/your/subtitle.sup
```

This will:
- Parse the .sup file
- Extract all subtitle images
- Run OCR on each
- Generate an .ass file
- Show progress and results

### Option 3: Python API Test

```python
from vsg_core.subtitles.pgs import extract_pgs_subtitles

# Basic test
result = extract_pgs_subtitles(
    sup_file="/path/to/subtitles.sup",
    lang="eng"
)
print(f"Generated: {result}")
```

## Troubleshooting

### Issue: "Tesseract not found"
**Solution**:
- Install Tesseract (see Prerequisites)
- Or specify path in Settings > Storage & Tools > Tesseract Path

### Issue: Poor OCR Accuracy
**Solutions**:
1. **Increase Binarize Threshold** (200 → 220) for lighter text
2. **Decrease Binarize Threshold** (200 → 180) for darker text
3. **Increase Contrast Enhancement** (1.5 → 2.0) for low-contrast subs
4. **Enable "Convert yellow to white"** if not already enabled

### Issue: Subtitles in Wrong Position
**Solutions**:
1. Check **Video Dimensions** match your actual video resolution
2. Verify source .sup file has correct positioning data

### Issue: "No text extracted"
**Possible causes**:
- Image too small/blurry
- Subtitle is actually blank/empty
- Preprocessing too aggressive (try reducing contrast/threshold)

## Expected Performance

- **Parsing speed**: ~1000 subtitles/second
- **OCR speed**: ~1-3 subtitles/second (depends on CPU and subtitle size)
- **Accuracy**: 95%+ for clean, clear subtitles

## Log Messages to Look For

**Success indicators**:
```
[PGS OCR] Using Tesseract: /usr/bin/tesseract
[PGS OCR] Found 500 subtitles
[PGS OCR] Successfully created output.ass with 500 subtitles
```

**Warning indicators**:
```
[PGS OCR] Warning: No text extracted from subtitle 42
[PGS OCR] Skipping subtitle 10: incomplete data
```

**Error indicators**:
```
[PGS OCR] ERROR: Tesseract not found
[PGS OCR] ERROR: Failed to parse SUP file
[PGS OCR] ERROR: No subtitles found in file
```

## What to Report

If you encounter issues, please report:

1. **Log output** (especially [PGS OCR] lines)
2. **Tesseract version**: `tesseract --version`
3. **Python version**: `python --version`
4. **Sample .sup file** (if possible)
5. **Settings used** (screenshot of PGS OCR settings)
6. **Expected vs actual behavior**

## Files to Check

After running a job with PGS OCR:

1. **Generated .ass file**: Should contain positioned subtitles
2. **Log file**: Check for errors or warnings
3. **settings.json**: Verify PGS settings were saved

Example .ass output:
```ass
[Script Info]
PlayResX: 1920
PlayResY: 1080

[Events]
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\an2\pos(960,1020)}Hello World
```

The `\an2` is the alignment (bottom-center) and `\pos(960,1020)` is the position.

## Success Criteria

✅ **System is working if**:
- Tesseract detected and runs without errors
- .sup file parsed successfully
- Images extracted and preprocessed
- OCR produces readable text (>90% accuracy)
- .ass file generated with positioning tags
- Subtitles display at correct positions

---

**Good luck with testing!** 🎬
