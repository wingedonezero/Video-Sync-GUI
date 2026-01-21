# vsg_core/subtitles/ocr/romaji_dictionary.py
# -*- coding: utf-8 -*-
"""
Romaji Dictionary Support

Provides Japanese romanization (romaji) word validation for OCR.
Uses JMdict as the source for Japanese vocabulary.

This prevents valid Japanese words written in romaji from being
flagged as unknown words by the OCR spell checker.

Features:
    - Kana to romaji conversion (Hepburn romanization)
    - JMdict parsing for vocabulary extraction
    - Romaji wordlist generation and caching
"""

import gzip
import logging
import os
import re
import tempfile
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Iterator
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

logger = logging.getLogger(__name__)

# JMdict download URL (English-only version is smaller)
JMDICT_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz"
JMDICT_FULL_URL = "http://ftp.edrdg.org/pub/Nihongo/JMdict.gz"

# Alternative mirrors if primary fails
JMDICT_MIRRORS = [
    "http://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
    "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz",
]


class KanaToRomaji:
    """
    Converts Japanese kana (hiragana/katakana) to romaji using Hepburn romanization.

    Supports:
        - All basic hiragana and katakana
        - Small kana (っ, ゃ, ゅ, ょ, etc.)
        - Long vowels (ー)
        - Common digraphs and trigraphs
    """

    # Hiragana to romaji mapping
    HIRAGANA = {
        # Basic vowels
        'あ': 'a', 'い': 'i', 'う': 'u', 'え': 'e', 'お': 'o',
        # K-row
        'か': 'ka', 'き': 'ki', 'く': 'ku', 'け': 'ke', 'こ': 'ko',
        # S-row
        'さ': 'sa', 'し': 'shi', 'す': 'su', 'せ': 'se', 'そ': 'so',
        # T-row
        'た': 'ta', 'ち': 'chi', 'つ': 'tsu', 'て': 'te', 'と': 'to',
        # N-row
        'な': 'na', 'に': 'ni', 'ぬ': 'nu', 'ね': 'ne', 'の': 'no',
        # H-row
        'は': 'ha', 'ひ': 'hi', 'ふ': 'fu', 'へ': 'he', 'ほ': 'ho',
        # M-row
        'ま': 'ma', 'み': 'mi', 'む': 'mu', 'め': 'me', 'も': 'mo',
        # Y-row
        'や': 'ya', 'ゆ': 'yu', 'よ': 'yo',
        # R-row
        'ら': 'ra', 'り': 'ri', 'る': 'ru', 'れ': 're', 'ろ': 'ro',
        # W-row
        'わ': 'wa', 'ゐ': 'wi', 'ゑ': 'we', 'を': 'wo',
        # N
        'ん': 'n',
        # Voiced (dakuten)
        'が': 'ga', 'ぎ': 'gi', 'ぐ': 'gu', 'げ': 'ge', 'ご': 'go',
        'ざ': 'za', 'じ': 'ji', 'ず': 'zu', 'ぜ': 'ze', 'ぞ': 'zo',
        'だ': 'da', 'ぢ': 'ji', 'づ': 'zu', 'で': 'de', 'ど': 'do',
        'ば': 'ba', 'び': 'bi', 'ぶ': 'bu', 'べ': 'be', 'ぼ': 'bo',
        # Half-voiced (handakuten)
        'ぱ': 'pa', 'ぴ': 'pi', 'ぷ': 'pu', 'ぺ': 'pe', 'ぽ': 'po',
        # Small kana
        'ぁ': 'a', 'ぃ': 'i', 'ぅ': 'u', 'ぇ': 'e', 'ぉ': 'o',
        'ゃ': 'ya', 'ゅ': 'yu', 'ょ': 'yo',
        'ゎ': 'wa',
        # Sokuon (small tsu) - handled specially
        'っ': '',
    }

    # Katakana to romaji mapping
    KATAKANA = {
        # Basic vowels
        'ア': 'a', 'イ': 'i', 'ウ': 'u', 'エ': 'e', 'オ': 'o',
        # K-row
        'カ': 'ka', 'キ': 'ki', 'ク': 'ku', 'ケ': 'ke', 'コ': 'ko',
        # S-row
        'サ': 'sa', 'シ': 'shi', 'ス': 'su', 'セ': 'se', 'ソ': 'so',
        # T-row
        'タ': 'ta', 'チ': 'chi', 'ツ': 'tsu', 'テ': 'te', 'ト': 'to',
        # N-row
        'ナ': 'na', 'ニ': 'ni', 'ヌ': 'nu', 'ネ': 'ne', 'ノ': 'no',
        # H-row
        'ハ': 'ha', 'ヒ': 'hi', 'フ': 'fu', 'ヘ': 'he', 'ホ': 'ho',
        # M-row
        'マ': 'ma', 'ミ': 'mi', 'ム': 'mu', 'メ': 'me', 'モ': 'mo',
        # Y-row
        'ヤ': 'ya', 'ユ': 'yu', 'ヨ': 'yo',
        # R-row
        'ラ': 'ra', 'リ': 'ri', 'ル': 'ru', 'レ': 're', 'ロ': 'ro',
        # W-row
        'ワ': 'wa', 'ヰ': 'wi', 'ヱ': 'we', 'ヲ': 'wo',
        # N
        'ン': 'n',
        # Voiced (dakuten)
        'ガ': 'ga', 'ギ': 'gi', 'グ': 'gu', 'ゲ': 'ge', 'ゴ': 'go',
        'ザ': 'za', 'ジ': 'ji', 'ズ': 'zu', 'ゼ': 'ze', 'ゾ': 'zo',
        'ダ': 'da', 'ヂ': 'ji', 'ヅ': 'zu', 'デ': 'de', 'ド': 'do',
        'バ': 'ba', 'ビ': 'bi', 'ブ': 'bu', 'ベ': 'be', 'ボ': 'bo',
        # Half-voiced (handakuten)
        'パ': 'pa', 'ピ': 'pi', 'プ': 'pu', 'ペ': 'pe', 'ポ': 'po',
        # Small kana
        'ァ': 'a', 'ィ': 'i', 'ゥ': 'u', 'ェ': 'e', 'ォ': 'o',
        'ャ': 'ya', 'ュ': 'yu', 'ョ': 'yo',
        'ヮ': 'wa',
        # Sokuon (small tsu) - handled specially
        'ッ': '',
        # Long vowel mark
        'ー': '',
        # Additional katakana for foreign words
        'ヴ': 'vu',
        'ヷ': 'va', 'ヸ': 'vi', 'ヹ': 've', 'ヺ': 'vo',
    }

    # Digraphs (two kana combinations)
    DIGRAPHS = {
        # Hiragana y-compounds
        'きゃ': 'kya', 'きゅ': 'kyu', 'きょ': 'kyo',
        'しゃ': 'sha', 'しゅ': 'shu', 'しょ': 'sho',
        'ちゃ': 'cha', 'ちゅ': 'chu', 'ちょ': 'cho',
        'にゃ': 'nya', 'にゅ': 'nyu', 'にょ': 'nyo',
        'ひゃ': 'hya', 'ひゅ': 'hyu', 'ひょ': 'hyo',
        'みゃ': 'mya', 'みゅ': 'myu', 'みょ': 'myo',
        'りゃ': 'rya', 'りゅ': 'ryu', 'りょ': 'ryo',
        'ぎゃ': 'gya', 'ぎゅ': 'gyu', 'ぎょ': 'gyo',
        'じゃ': 'ja', 'じゅ': 'ju', 'じょ': 'jo',
        'ぢゃ': 'ja', 'ぢゅ': 'ju', 'ぢょ': 'jo',
        'びゃ': 'bya', 'びゅ': 'byu', 'びょ': 'byo',
        'ぴゃ': 'pya', 'ぴゅ': 'pyu', 'ぴょ': 'pyo',
        # Katakana y-compounds
        'キャ': 'kya', 'キュ': 'kyu', 'キョ': 'kyo',
        'シャ': 'sha', 'シュ': 'shu', 'ショ': 'sho',
        'チャ': 'cha', 'チュ': 'chu', 'チョ': 'cho',
        'ニャ': 'nya', 'ニュ': 'nyu', 'ニョ': 'nyo',
        'ヒャ': 'hya', 'ヒュ': 'hyu', 'ヒョ': 'hyo',
        'ミャ': 'mya', 'ミュ': 'myu', 'ミョ': 'myo',
        'リャ': 'rya', 'リュ': 'ryu', 'リョ': 'ryo',
        'ギャ': 'gya', 'ギュ': 'gyu', 'ギョ': 'gyo',
        'ジャ': 'ja', 'ジュ': 'ju', 'ジョ': 'jo',
        'ヂャ': 'ja', 'ヂュ': 'ju', 'ヂョ': 'jo',
        'ビャ': 'bya', 'ビュ': 'byu', 'ビョ': 'byo',
        'ピャ': 'pya', 'ピュ': 'pyu', 'ピョ': 'pyo',
        # Additional katakana combinations for foreign words
        'ファ': 'fa', 'フィ': 'fi', 'フェ': 'fe', 'フォ': 'fo',
        'ティ': 'ti', 'ディ': 'di',
        'トゥ': 'tu', 'ドゥ': 'du',
        'ウィ': 'wi', 'ウェ': 'we', 'ウォ': 'wo',
        'ヴァ': 'va', 'ヴィ': 'vi', 'ヴェ': 've', 'ヴォ': 'vo',
        'シェ': 'she', 'ジェ': 'je', 'チェ': 'che',
        'ツァ': 'tsa', 'ツィ': 'tsi', 'ツェ': 'tse', 'ツォ': 'tso',
    }

    def __init__(self):
        """Initialize converter with combined mappings."""
        # Build combined map with digraphs first (longer matches)
        self.kana_map = {}
        self.kana_map.update(self.DIGRAPHS)
        self.kana_map.update(self.HIRAGANA)
        self.kana_map.update(self.KATAKANA)

        # Sort by length descending for proper matching
        self.sorted_kana = sorted(self.kana_map.keys(), key=len, reverse=True)

    def convert(self, text: str) -> str:
        """
        Convert kana text to romaji.

        Args:
            text: Text containing hiragana/katakana

        Returns:
            Romanized text
        """
        result = []
        i = 0
        prev_char = ''

        while i < len(text):
            matched = False

            # Try matching longest patterns first
            for kana in self.sorted_kana:
                if text[i:].startswith(kana):
                    romaji = self.kana_map[kana]

                    # Handle sokuon (small tsu) - doubles the next consonant
                    if kana in ('っ', 'ッ') and i + len(kana) < len(text):
                        next_char = text[i + len(kana)]
                        # Look ahead for the next kana's romaji
                        for next_kana in self.sorted_kana:
                            if text[i + len(kana):].startswith(next_kana):
                                next_romaji = self.kana_map[next_kana]
                                if next_romaji:
                                    # Double the first consonant
                                    result.append(next_romaji[0])
                                break
                    # Handle long vowel mark (ー) - extends previous vowel
                    elif kana == 'ー' and result:
                        prev_result = result[-1] if result else ''
                        if prev_result and prev_result[-1] in 'aeiou':
                            result.append(prev_result[-1])
                    else:
                        result.append(romaji)

                    i += len(kana)
                    matched = True
                    break

            if not matched:
                # Keep non-kana characters as-is
                result.append(text[i])
                i += 1

        return ''.join(result)

    def is_kana(self, text: str) -> bool:
        """Check if text is entirely kana (hiragana/katakana)."""
        for char in text:
            if char not in self.kana_map:
                # Allow some punctuation
                if char not in '・ーっッ':
                    return False
        return True


class JMdictParser:
    """
    Parses JMdict XML files to extract readings (kana) and convert to romaji.

    JMdict structure:
        <entry>
            <k_ele><keb>漢字</keb></k_ele>
            <r_ele><reb>かんじ</reb></r_ele>
            <sense>...</sense>
        </entry>
    """

    def __init__(self, converter: Optional[KanaToRomaji] = None):
        """
        Initialize parser.

        Args:
            converter: KanaToRomaji converter instance
        """
        self.converter = converter or KanaToRomaji()

    def parse_file(self, file_path: Path, progress_callback=None) -> Set[str]:
        """
        Parse a JMdict XML file and extract romaji readings.

        Args:
            file_path: Path to JMdict XML (can be .gz compressed)
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Set of romaji words
        """
        romaji_words = set()

        # Open file (handle gzip)
        if str(file_path).endswith('.gz'):
            open_func = lambda p: gzip.open(p, 'rt', encoding='utf-8')
        else:
            open_func = lambda p: open(p, 'r', encoding='utf-8')

        try:
            # Use iterparse for memory efficiency
            with open_func(file_path) as f:
                entry_count = 0

                for event, elem in ET.iterparse(f, events=('end',)):
                    if elem.tag == 'entry':
                        entry_count += 1

                        # Extract all readings from this entry
                        for r_ele in elem.findall('.//r_ele'):
                            reb = r_ele.find('reb')
                            if reb is not None and reb.text:
                                kana = reb.text.strip()
                                romaji = self.converter.convert(kana)
                                # Filter: must be alphabetic and at least 3 chars
                                # (filters out "a", "aa", "i", "e", "o", etc.)
                                if romaji and romaji.isalpha() and len(romaji) >= 3:
                                    romaji_words.add(romaji.lower())

                        # Clear element to free memory
                        elem.clear()

                        # Progress callback
                        if progress_callback and entry_count % 10000 == 0:
                            progress_callback(entry_count, 0)  # Total unknown

        except ET.ParseError as e:
            logger.error(f"XML parse error in {file_path}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error parsing JMdict file {file_path}: {e}")
            raise

        logger.info(f"Extracted {len(romaji_words)} romaji words from {entry_count} entries")
        return romaji_words

    def parse_stream(self, stream, progress_callback=None) -> Set[str]:
        """
        Parse JMdict from a file-like stream.

        Args:
            stream: File-like object with XML content
            progress_callback: Optional callback(current, total) for progress

        Returns:
            Set of romaji words
        """
        romaji_words = set()
        entry_count = 0

        try:
            for event, elem in ET.iterparse(stream, events=('end',)):
                if elem.tag == 'entry':
                    entry_count += 1

                    for r_ele in elem.findall('.//r_ele'):
                        reb = r_ele.find('reb')
                        if reb is not None and reb.text:
                            kana = reb.text.strip()
                            romaji = self.converter.convert(kana)
                            if romaji and romaji.isalpha():
                                romaji_words.add(romaji.lower())

                    elem.clear()

                    if progress_callback and entry_count % 10000 == 0:
                        progress_callback(entry_count, 0)

        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            raise

        logger.info(f"Extracted {len(romaji_words)} romaji words from {entry_count} entries")
        return romaji_words


class RomajiDictionary:
    """
    Manages romaji wordlist for OCR validation.

    Handles:
        - Loading cached romaji dictionary
        - Downloading and parsing JMdict if needed
        - Word validation
    """

    DICT_FILENAME = "romaji_dictionary.txt"
    JMDICT_CACHE = "JMdict_e.gz"

    def __init__(self, config_dir: Path):
        """
        Initialize romaji dictionary.

        Args:
            config_dir: Directory for dictionary files
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.dict_path = self.config_dir / self.DICT_FILENAME
        self.jmdict_path = self.config_dir / self.JMDICT_CACHE

        self._words: Optional[Set[str]] = None
        self._words_mtime: float = 0  # Track file modification time
        self._converter = KanaToRomaji()

    def load(self) -> Set[str]:
        """
        Load romaji dictionary from file.

        Automatically reloads if the file was modified since last load.

        Returns:
            Set of romaji words
        """
        # Check if file exists
        if not self.dict_path.exists():
            if self._words is None or len(self._words) > 0:
                logger.warning(f"Romaji dictionary not found at: {self.dict_path}")
            self._words = set()
            self._words_mtime = 0
            return self._words

        # Check if we need to reload (file modified since last load)
        try:
            current_mtime = self.dict_path.stat().st_mtime
        except OSError:
            current_mtime = 0

        if self._words is not None and current_mtime == self._words_mtime:
            # File hasn't changed, use cached data
            return self._words

        # Load the file (first time or file changed)
        try:
            words = set()
            with open(self.dict_path, 'r', encoding='utf-8') as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith('#'):
                        words.add(word.lower())

            self._words = words
            self._words_mtime = current_mtime
            logger.info(f"Loaded {len(words)} romaji words from {self.dict_path}")
            return words

        except Exception as e:
            logger.error(f"Error loading romaji dictionary: {e}")
            self._words = set()
            self._words_mtime = 0
            return self._words

    def save(self, words: Set[str]) -> bool:
        """
        Save romaji dictionary to file.

        Args:
            words: Set of romaji words

        Returns:
            True if successful
        """
        try:
            # Atomic write
            fd, temp_path = tempfile.mkstemp(suffix=".txt", dir=self.config_dir)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    f.write("# Romaji Dictionary - Japanese words in romanized form\n")
                    f.write(f"# Generated from JMdict - {len(words)} words\n")
                    f.write("# https://www.edrdg.org/jmdict/j_jmdict.html\n\n")

                    for word in sorted(words):
                        f.write(word + '\n')

                shutil.move(temp_path, self.dict_path)
                self._words = words
                logger.info(f"Saved {len(words)} romaji words to {self.dict_path}")
                return True

            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.error(f"Error saving romaji dictionary: {e}")
            return False

    def is_valid_word(self, word: str) -> bool:
        """
        Check if a word is a valid romaji word.

        Args:
            word: Word to check

        Returns:
            True if word is in romaji dictionary
        """
        words = self.load()
        word_lower = word.lower()
        is_valid = word_lower in words

        # Debug logging for troubleshooting
        if not is_valid and len(words) > 0:
            logger.debug(f"Romaji check: '{word_lower}' not in dictionary ({len(words)} words loaded from {self.dict_path})")

        return is_valid

    def download_jmdict(self, progress_callback=None) -> bool:
        """
        Download JMdict file.

        Args:
            progress_callback: Optional callback(downloaded, total) for progress

        Returns:
            True if successful
        """
        for url in JMDICT_MIRRORS:
            try:
                logger.info(f"Downloading JMdict from {url}...")

                request = Request(url, headers={'User-Agent': 'Video-Sync-GUI/1.0'})

                with urlopen(request, timeout=60) as response:
                    total_size = response.headers.get('Content-Length')
                    total_size = int(total_size) if total_size else 0

                    # Download to temp file
                    fd, temp_path = tempfile.mkstemp(suffix=".gz", dir=self.config_dir)
                    try:
                        downloaded = 0
                        chunk_size = 8192

                        with os.fdopen(fd, 'wb') as f:
                            while True:
                                chunk = response.read(chunk_size)
                                if not chunk:
                                    break
                                f.write(chunk)
                                downloaded += len(chunk)

                                if progress_callback:
                                    progress_callback(downloaded, total_size)

                        # Move to final location
                        shutil.move(temp_path, self.jmdict_path)
                        logger.info(f"Downloaded JMdict: {downloaded} bytes")
                        return True

                    except Exception:
                        if os.path.exists(temp_path):
                            os.unlink(temp_path)
                        raise

            except (URLError, HTTPError) as e:
                logger.warning(f"Failed to download from {url}: {e}")
                continue
            except Exception as e:
                logger.warning(f"Error downloading from {url}: {e}")
                continue

        logger.error("Failed to download JMdict from all mirrors")
        return False

    def build_dictionary(self, progress_callback=None) -> Tuple[bool, str]:
        """
        Build romaji dictionary from JMdict.

        Downloads JMdict if not cached, parses it, and saves the romaji wordlist.

        Args:
            progress_callback: Optional callback(status, current, total)

        Returns:
            (success, message) tuple
        """
        try:
            # Download if needed
            if not self.jmdict_path.exists():
                if progress_callback:
                    progress_callback("Downloading JMdict...", 0, 0)

                def download_progress(downloaded, total):
                    if progress_callback:
                        progress_callback("Downloading JMdict...", downloaded, total)

                if not self.download_jmdict(download_progress):
                    return False, "Failed to download JMdict"

            # Parse JMdict
            if progress_callback:
                progress_callback("Parsing JMdict...", 0, 0)

            parser = JMdictParser(self._converter)

            def parse_progress(current, total):
                if progress_callback:
                    progress_callback(f"Parsing... {current} entries", current, total)

            romaji_words = parser.parse_file(self.jmdict_path, parse_progress)

            # Add common suffixes and particles
            romaji_words.update(self._get_common_particles())

            # Save
            if progress_callback:
                progress_callback("Saving dictionary...", 0, 0)

            if self.save(romaji_words):
                return True, f"Built romaji dictionary with {len(romaji_words)} words"
            else:
                return False, "Failed to save dictionary"

        except Exception as e:
            logger.error(f"Error building romaji dictionary: {e}")
            return False, f"Error: {str(e)}"

    def _get_common_particles(self) -> Set[str]:
        """Get common Japanese particles and suffixes in romaji."""
        return {
            # Particles
            'wa', 'wo', 'ga', 'no', 'ni', 'de', 'to', 'mo', 'ka', 'ne', 'yo', 'na',
            'he', 'kara', 'made', 'yori', 'dake', 'shika', 'bakari', 'nado',
            # Common suffixes
            'san', 'sama', 'kun', 'chan', 'sensei', 'senpai', 'kouhai',
            'shi', 'tachi', 'ra', 'domo',
            # Common words often in anime
            'hai', 'iie', 'nani', 'dou', 'naze', 'dare', 'doko', 'itsu',
            'kore', 'sore', 'are', 'dore',
            'kono', 'sono', 'ano', 'dono',
            'kou', 'sou', 'aa', 'dou',
            'sugoi', 'kawaii', 'kakkoii', 'kirei', 'utsukushii',
            'baka', 'aho', 'uso', 'hontou', 'maji',
            'gomen', 'sumimasen', 'arigatou', 'doumo',
            'ohayou', 'konnichiwa', 'konbanwa', 'sayonara', 'oyasumi',
            'ittekimasu', 'itterasshai', 'tadaima', 'okaeri',
            'itadakimasu', 'gochisousama',
            'suki', 'daisuki', 'kirai', 'daikirai',
            'onegai', 'kudasai', 'choudai',
            'chotto', 'matte', 'yamete', 'dame',
            'yatta', 'yosh', 'ganbare', 'ganbatte',
            'nee', 'ano', 'eto', 'maa', 'hora',
            # Common anime/otaku terms
            'anime', 'manga', 'otaku', 'waifu', 'husbando',
            'senpai', 'kouhai', 'sensei', 'shonen', 'shoujo',
            'mecha', 'isekai', 'ecchi', 'hentai', 'yaoi', 'yuri',
            'chibi', 'moe', 'tsundere', 'yandere', 'kuudere', 'dandere',
            'nakama', 'tomodachi', 'koibito', 'kareshi', 'kanojo',
        }

    def get_stats(self) -> Dict[str, any]:
        """Get dictionary statistics."""
        words = self.load()
        return {
            'word_count': len(words),
            'dict_exists': self.dict_path.exists(),
            'jmdict_cached': self.jmdict_path.exists(),
            'dict_path': str(self.dict_path),
        }


# Global instance
_romaji_dict: Optional[RomajiDictionary] = None


def get_romaji_dictionary(config_dir: Optional[Path] = None) -> RomajiDictionary:
    """
    Get or create the global romaji dictionary instance.

    Args:
        config_dir: Optional config directory path

    Returns:
        RomajiDictionary instance
    """
    global _romaji_dict

    if _romaji_dict is None or config_dir is not None:
        if config_dir is None:
            # Default to project .config/ocr/
            project_root = Path(__file__).parent.parent.parent.parent
            config_dir = project_root / ".config" / "ocr"
        _romaji_dict = RomajiDictionary(config_dir)

    return _romaji_dict


def is_romaji_word(word: str, config_dir: Optional[Path] = None) -> bool:
    """
    Check if a word is a valid romaji word.

    Convenience function for quick lookups.

    Args:
        word: Word to check
        config_dir: Optional config directory

    Returns:
        True if word is in romaji dictionary
    """
    return get_romaji_dictionary(config_dir).is_valid_word(word)
