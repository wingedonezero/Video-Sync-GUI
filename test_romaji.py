#!/usr/bin/env python3
"""
Diagnostic script to test romaji dictionary integration.
Run this from the project root to verify the dictionary is working.

Usage:
    python test_romaji.py
"""

import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("=" * 60)
    print("ROMAJI DICTIONARY DIAGNOSTIC")
    print("=" * 60)

    # 1. Check dictionaries module
    print("\n1. Loading OCRDictionaries...")
    try:
        from vsg_core.subtitles.ocr.dictionaries import get_dictionaries
        dicts = get_dictionaries()
        print(f"   Config dir: {dicts.config_dir}")
        print(f"   Config exists: {dicts.config_dir.exists()}")
    except Exception as e:
        print(f"   ERROR: {e}")
        return

    # 2. Check romaji dictionary directly
    print("\n2. Checking RomajiDictionary...")
    try:
        romaji_dict = dicts._get_romaji_dictionary()
        print(f"   Dict path: {romaji_dict.dict_path}")
        print(f"   File exists: {romaji_dict.dict_path.exists()}")

        if romaji_dict.dict_path.exists():
            # Get file size
            size = romaji_dict.dict_path.stat().st_size
            print(f"   File size: {size:,} bytes")

            # Count lines in file directly
            with open(romaji_dict.dict_path, 'r', encoding='utf-8') as f:
                line_count = sum(1 for line in f if line.strip() and not line.startswith('#'))
            print(f"   Lines in file: {line_count:,}")
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Load the dictionary
    print("\n3. Loading dictionary via load()...")
    try:
        # Force reload by clearing cache
        romaji_dict._words = None
        romaji_dict._words_mtime = 0
        words = romaji_dict.load()
        print(f"   Words loaded: {len(words):,}")

        if len(words) > 0:
            # Show some sample words
            sample = sorted(list(words))[:10]
            print(f"   Sample words: {sample}")
        else:
            print("   WARNING: Dictionary is empty!")
    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()
        return

    # 4. Test specific Japanese words
    print("\n4. Testing specific romaji words...")
    test_words = ['sora', 'hirogaru', 'musuu', 'hoshikuzu', 'arigatou', 'sugoi', 'kawaii']
    for word in test_words:
        in_dict = word.lower() in words
        via_method = romaji_dict.is_valid_word(word)
        status = "OK" if in_dict else "MISSING"
        print(f"   '{word}': {status} (in_dict={in_dict}, is_valid_word={via_method})")

    # 5. Test via is_known_word
    print("\n5. Testing via OCRDictionaries.is_known_word()...")
    for word in test_words[:3]:  # Just test a few
        result = dicts.is_known_word(word, check_romaji=True)
        result_no_romaji = dicts.is_known_word(word, check_romaji=False)
        print(f"   is_known_word('{word}', check_romaji=True): {result}")
        print(f"   is_known_word('{word}', check_romaji=False): {result_no_romaji}")

    # 6. Check postprocessor integration
    print("\n6. Testing OCRPostProcessor integration...")
    try:
        from vsg_core.subtitles.ocr.postprocess import OCRPostProcessor
        processor = OCRPostProcessor()

        # Check that it has the dictionaries
        print(f"   Postprocessor config_dir: {processor.ocr_dicts.config_dir}")

        # Test _find_unknown_words with Japanese text
        test_text = "hirogaru sora ni musuu no hoshikuzu"
        unknown = processor._find_unknown_words(test_text)
        print(f"   Test text: '{test_text}'")
        print(f"   Unknown words: {unknown}")

        if any(w in unknown for w in ['sora', 'hirogaru', 'musuu', 'hoshikuzu']):
            print("   PROBLEM: Japanese words still showing as unknown!")
        else:
            print("   SUCCESS: Japanese words recognized!")

    except Exception as e:
        print(f"   ERROR: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    main()
