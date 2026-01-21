#!/usr/bin/env python3
"""Test PaddleOCR on a single image to see the result format."""
import sys

image_path = sys.argv[1] if len(sys.argv) > 1 else "/home/chaoz/Desktop/Makemkv/Starship Operators/[DVDISO] Starship Operators (2005) [R1US]/1_track4_[eng]/0_00_22_556__0_00_24_183_02.png"

print(f"Testing PaddleOCR on: {image_path}")
print("=" * 60)

from paddleocr import PaddleOCR
import numpy as np
from PIL import Image

# Load image
img = Image.open(image_path)
img_array = np.array(img.convert('RGB'))
print(f"Image shape: {img_array.shape}")

# Initialize PaddleOCR
print("\nInitializing PaddleOCR...")
ocr = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    lang='en',
    device='cpu'
)

# Run OCR
print("\nRunning ocr.ocr()...")
result = ocr.ocr(img_array)

print(f"\nResult type: {type(result)}")
print(f"Result: {result}")

# If it's a generator, convert to list
if hasattr(result, '__next__'):
    result = list(result)
    print(f"\nConverted generator to list: {result}")

if result:
    print(f"\nNumber of results: {len(result)}")
    for i, r in enumerate(result):
        print(f"\n--- Result {i} ---")
        print(f"Type: {type(r)}")
        if hasattr(r, 'json'):
            print(f".json: {r.json}")
        elif isinstance(r, dict):
            print(f"Keys: {r.keys()}")
            print(f"Content: {r}")
        elif isinstance(r, list):
            print(f"List length: {len(r)}")
            if r:
                print(f"First item type: {type(r[0])}")
                print(f"First item: {r[0]}")
        else:
            print(f"Value: {r}")
