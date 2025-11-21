#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for PGS OCR system.
Tests the complete PGS subtitle extraction and OCR workflow.
"""
import sys
import argparse
from pathlib import Path


def test_pgs_ocr(sup_file: str, output_file: str = None, lang: str = 'eng'):
    """
    Test PGS OCR on a sample file.

    Args:
        sup_file: Path to .sup file
        output_file: Output .ass file (optional)
        lang: Language code for OCR (default 'eng')
    """
    print("=" * 60)
    print("PGS OCR Test")
    print("=" * 60)

    # Check if file exists
    sup_path = Path(sup_file)
    if not sup_path.exists():
        print(f"ERROR: File not found: {sup_file}")
        return False

    print(f"\nInput file: {sup_path}")
    print(f"Language: {lang}")

    # Import PGS OCR module
    try:
        from vsg_core.subtitles.pgs import extract_pgs_subtitles, PreprocessSettings
        print("✓ PGS OCR module imported successfully")
    except ImportError as e:
        print(f"ERROR: Failed to import PGS OCR module: {e}")
        return False

    # Check Tesseract
    from vsg_core.subtitles.pgs.ocr_tesseract import find_tesseract
    tesseract_path = find_tesseract()
    if tesseract_path:
        print(f"✓ Tesseract found: {tesseract_path}")
    else:
        print("ERROR: Tesseract not found. Please install Tesseract OCR.")
        print("  Ubuntu/Debian: sudo apt-get install tesseract-ocr")
        print("  macOS: brew install tesseract")
        print("  Windows: https://github.com/UB-Mannheim/tesseract/wiki")
        return False

    # Run extraction
    print("\n" + "-" * 60)
    print("Starting PGS extraction and OCR...")
    print("-" * 60 + "\n")

    try:
        result = extract_pgs_subtitles(
            sup_file=str(sup_path),
            output_file=output_file,
            lang=lang,
            video_width=1920,
            video_height=1080,
            from_matroska=False,
            tesseract_path=tesseract_path,
            preprocess_settings=None,  # Use defaults
            log_callback=print
        )

        if result:
            print("\n" + "=" * 60)
            print("✓ SUCCESS!")
            print("=" * 60)
            print(f"\nOutput file: {result}")

            # Show file size
            output_path = Path(result)
            if output_path.exists():
                size = output_path.stat().st_size
                print(f"File size: {size:,} bytes")

                # Show first few lines
                print("\nFirst 10 lines of output:")
                print("-" * 60)
                with open(output_path, 'r', encoding='utf-8') as f:
                    for i, line in enumerate(f):
                        if i >= 10:
                            break
                        print(line.rstrip())
                print("-" * 60)

            return True
        else:
            print("\n" + "=" * 60)
            print("✗ FAILED")
            print("=" * 60)
            print("OCR extraction failed. Check logs above for errors.")
            return False

    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Test PGS OCR system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_pgs_ocr.py movie_subtitles.sup
  python test_pgs_ocr.py subs.sup -o output.ass
  python test_pgs_ocr.py subs.sup -l eng

Note: Requires Tesseract OCR to be installed on the system.
        """
    )

    parser.add_argument(
        'sup_file',
        help='Path to PGS .sup subtitle file'
    )

    parser.add_argument(
        '-o', '--output',
        help='Output .ass file path (default: same as input with .ass extension)',
        default=None
    )

    parser.add_argument(
        '-l', '--lang',
        help='Tesseract language code (default: eng)',
        default='eng'
    )

    args = parser.parse_args()

    # Run test
    success = test_pgs_ocr(args.sup_file, args.output, args.lang)

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
