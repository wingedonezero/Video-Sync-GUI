# PGS OCR System

OCR system for PGS (Presentation Graphic Stream) subtitles from Blu-ray discs.

## Overview

This module provides complete OCR functionality for PGS/SUP subtitle files, converting bitmap-based subtitles to text-based ASS format with position preservation.

Based on SubtitleEdit's proven implementation, ported to Python.

## Features

- **Complete PGS Parser**: Binary SUP file parsing with segment handling
- **RLE Decompression**: Decodes PGS run-length encoded bitmaps
- **YCbCr Color Conversion**: Supports BT.601 and BT.709 standards
- **Image Preprocessing**: Optimized for OCR accuracy
  - Transparent border cropping
  - Margin addition
  - Yellow to white conversion
  - Binarization (black & white)
  - Contrast enhancement
- **Tesseract Integration**: hOCR output parsing
- **Position Preservation**: Maintains subtitle positioning in ASS format
- **Multi-object Support**: Handles complex compositions

## Requirements

- Python 3.8+
- Pillow (PIL)
- Tesseract OCR (system installation)

Install dependencies:
```bash
pip install Pillow
```

Install Tesseract:
- **Ubuntu/Debian**: `sudo apt-get install tesseract-ocr`
- **macOS**: `brew install tesseract`
- **Windows**: Download from https://github.com/UB-Mannheim/tesseract/wiki

## Usage

### Basic Usage

```python
from vsg_core.subtitles.pgs import extract_pgs_subtitles

# Extract and OCR PGS subtitles
output_file = extract_pgs_subtitles(
    sup_file="subtitles.sup",
    lang="eng"
)
```

### Advanced Usage

```python
from vsg_core.subtitles.pgs import extract_pgs_subtitles, PreprocessSettings

# Custom preprocessing settings
settings = PreprocessSettings(
    crop_transparent=True,
    crop_max=20,
    add_margin=10,
    yellow_to_white=True,
    binarize=True,
    binarize_threshold=200,
    enhance_contrast=1.5
)

# Extract with custom settings
output_file = extract_pgs_subtitles(
    sup_file="subtitles.sup",
    output_file="output.ass",
    lang="eng",
    video_width=1920,
    video_height=1080,
    preprocess_settings=settings,
    tesseract_path="/usr/bin/tesseract"
)
```

### Integration with Existing OCR System

The PGS OCR is automatically integrated into the existing `run_ocr()` function:

```python
from vsg_core.subtitles.ocr import run_ocr

# Automatically detects format (.sup vs .idx) and runs appropriate OCR
result = run_ocr(
    subtitle_path="subtitles.sup",
    lang="eng",
    runner=runner,
    tool_paths={},
    config={}
)
```

## Configuration Options

Configuration parameters for `run_pgs_ocr()` in config dict:

```python
config = {
    # Video dimensions for positioning
    'pgs_video_width': 1920,
    'pgs_video_height': 1080,

    # Tesseract path (optional, auto-detected)
    'tesseract_path': '/usr/bin/tesseract',

    # Preprocessing options
    'pgs_crop_transparent': True,
    'pgs_crop_max': 20,
    'pgs_add_margin': 10,
    'pgs_invert_colors': False,
    'pgs_yellow_to_white': True,
    'pgs_binarize': True,
    'pgs_binarize_threshold': 200,
    'pgs_scale_percent': 100,
    'pgs_enhance_contrast': 1.5,
}
```

## Output Format

Generates ASS subtitle files with:
- Preserved positioning (`\pos(x,y)` tags)
- Calculated alignment (`\an1-9`)
- Proper timing from PGS timestamps
- Support for top, bottom, and side-positioned subtitles

Example ASS output:
```
[Script Info]
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, ...
Style: Default,Arial,20,&H00FFFFFF,...

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,{\an2\pos(960,1020)}Hello World
```

## Architecture

```
pgs/
├── models.py          # Data structures (SupSegment, PcsData, etc.)
├── parser.py          # Binary SUP file parser
├── palette.py         # YCbCr → RGB conversion
├── image.py           # RLE decompression, image compositing
├── preprocessor.py    # Image preprocessing for OCR
├── ocr_tesseract.py   # Tesseract integration
└── __init__.py        # Main workflow (extract_pgs_subtitles)
```

## PGS File Format

PGS subtitles consist of segments:
- **0x14 (PDS)**: Palette Definition - YCbCrA color data
- **0x15 (ODS)**: Object Definition - RLE-compressed bitmap
- **0x16 (PCS)**: Picture Composition - timing, positioning
- **0x17 (WDS)**: Window Display - display area
- **0x80 (END)**: End of display set

## Troubleshooting

### Tesseract Not Found
```
ERROR: Tesseract not found. Please install Tesseract OCR.
```
**Solution**: Install Tesseract (see Requirements section)

### Poor OCR Accuracy
Try adjusting preprocessing settings:
- Increase `binarize_threshold` (200-220) for lighter text
- Decrease `binarize_threshold` (180-200) for darker text
- Enable `invert_colors` if white text on dark background
- Increase `enhance_contrast` (1.5-2.0) for low-contrast text

### Position Not Preserved
Check video dimensions match actual video:
```python
extract_pgs_subtitles(
    sup_file="subs.sup",
    video_width=1920,  # Must match video
    video_height=1080
)
```

## Testing

Test with a sample PGS file:
```bash
python -c "
from vsg_core.subtitles.pgs import extract_pgs_subtitles
result = extract_pgs_subtitles('test.sup', lang='eng')
print(f'Created: {result}')
"
```

## Credits

Implementation based on:
- **SubtitleEdit** by Nikolaj Olsson - PGS parsing and OCR logic
- **Tesseract OCR** - Text recognition engine

## License

Part of Video-Sync-GUI project.
