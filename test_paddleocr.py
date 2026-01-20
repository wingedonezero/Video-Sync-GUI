#!/usr/bin/env python3
"""Quick test script to check PaddleOCR output format."""

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sys

def create_test_image():
    """Create a simple test image with text."""
    # Create a white image with black text
    img = Image.new('RGB', (400, 100), color='white')
    draw = ImageDraw.Draw(img)

    # Try to use a default font
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36)
    except:
        font = ImageFont.load_default()

    draw.text((20, 30), "Hello World!", fill='black', font=font)
    return np.array(img)

def main():
    print("Testing PaddleOCR...")
    print("=" * 50)

    try:
        from paddleocr import PaddleOCR
        print(f"PaddleOCR imported successfully")
    except ImportError as e:
        print(f"ERROR: Cannot import PaddleOCR: {e}")
        sys.exit(1)

    # Create OCR instance
    print("\nInitializing PaddleOCR...")
    try:
        ocr = PaddleOCR(
            use_textline_orientation=False,
            lang='en',
            device='cpu'
        )
        print("PaddleOCR initialized")
    except Exception as e:
        print(f"ERROR initializing PaddleOCR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Create test image
    print("\nCreating test image...")
    test_img = create_test_image()
    print(f"Image shape: {test_img.shape}, dtype: {test_img.dtype}")

    # Run OCR
    print("\nRunning predict()...")
    try:
        predictions = ocr.predict(test_img)
        print(f"predict() returned: {type(predictions)}")
    except Exception as e:
        print(f"ERROR during predict(): {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Analyze results
    print("\nAnalyzing results...")
    pred = None
    try:
        for i, p in enumerate(predictions):
            print(f"\n  Result {i}:")
            print(f"    Type: {type(p)}")
            print(f"    Attributes: {[a for a in dir(p) if not a.startswith('_')]}")

            # Try various ways to access data
            if hasattr(p, 'json'):
                json_val = p.json
                print(f"    .json type: {type(json_val)}")
                if isinstance(json_val, dict):
                    print(f"    .json keys: {list(json_val.keys())}")
                    for k, v in json_val.items():
                        if isinstance(v, (list, tuple)):
                            print(f"      {k}: {type(v).__name__}[{len(v)}] = {str(v)[:200]}")
                        else:
                            print(f"      {k}: {v}")
                else:
                    print(f"    .json value: {json_val}")

            if hasattr(p, '__dict__'):
                print(f"    __dict__ keys: {list(p.__dict__.keys())}")

            if hasattr(p, 'rec_texts'):
                print(f"    .rec_texts: {p.rec_texts}")
            if hasattr(p, 'rec_scores'):
                print(f"    .rec_scores: {p.rec_scores}")

            pred = p
            break  # Only check first result
    except Exception as e:
        print(f"ERROR iterating results: {e}")
        import traceback
        traceback.print_exc()

    if pred is None:
        print("\nNo predictions returned!")

    print("\n" + "=" * 50)
    print("Test complete")

if __name__ == "__main__":
    main()
