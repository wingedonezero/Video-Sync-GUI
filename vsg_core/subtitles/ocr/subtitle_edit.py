# vsg_core/subtitles/ocr/subtitle_edit.py
# -*- coding: utf-8 -*-
"""
Subtitle Edit Dictionary Support

Parses and uses Subtitle Edit's dictionary files for OCR correction:
    - OCRFixReplaceList.xml - Pattern-based replacements
    - names.xml - Valid names
    - NoBreakAfterList.xml - Words to keep with following word
    - *_se.xml - Extra valid words for spell check
    - WordSplitList.txt - Dictionary for splitting merged words

These files can be downloaded from:
https://github.com/SubtitleEdit/subtitleedit/tree/main/Dictionaries
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class SEReplacementRule:
    """A replacement rule from Subtitle Edit OCRFixReplaceList."""
    from_text: str
    to_text: str
    rule_type: str  # whole_line, partial_line_always, partial_line, begin_line, end_line,
                    # whole_word, partial_word_always, partial_word, regex

    def __hash__(self):
        return hash((self.from_text, self.to_text, self.rule_type))


@dataclass
class SEDictionaryConfig:
    """Configuration for which SE dictionaries are enabled."""
    ocr_fix_enabled: bool = True
    names_enabled: bool = True
    no_break_enabled: bool = True
    spell_words_enabled: bool = True
    word_split_enabled: bool = True
    interjections_enabled: bool = True


@dataclass
class SEDictionaries:
    """Loaded Subtitle Edit dictionary data."""
    # OCR Fix replacements by type
    whole_lines: List[SEReplacementRule] = field(default_factory=list)
    partial_lines_always: List[SEReplacementRule] = field(default_factory=list)
    partial_lines: List[SEReplacementRule] = field(default_factory=list)
    begin_lines: List[SEReplacementRule] = field(default_factory=list)
    end_lines: List[SEReplacementRule] = field(default_factory=list)
    whole_words: List[SEReplacementRule] = field(default_factory=list)
    partial_words_always: List[SEReplacementRule] = field(default_factory=list)
    partial_words: List[SEReplacementRule] = field(default_factory=list)
    regex_rules: List[SEReplacementRule] = field(default_factory=list)

    # Other dictionaries
    names: Set[str] = field(default_factory=set)
    names_blacklist: Set[str] = field(default_factory=set)
    no_break_after: Set[str] = field(default_factory=set)
    spell_words: Set[str] = field(default_factory=set)
    interjections: Set[str] = field(default_factory=set)
    word_split_list: Set[str] = field(default_factory=set)

    def get_all_valid_words(self) -> Set[str]:
        """Get all words that should be considered valid."""
        words = set()
        words.update(self.names - self.names_blacklist)
        words.update(self.spell_words)
        words.update(self.interjections)
        words.update(self.word_split_list)
        return words

    def get_replacement_count(self) -> int:
        """Get total number of replacement rules."""
        return (len(self.whole_lines) + len(self.partial_lines_always) +
                len(self.partial_lines) + len(self.begin_lines) +
                len(self.end_lines) + len(self.whole_words) +
                len(self.partial_words_always) + len(self.partial_words) +
                len(self.regex_rules))


class SubtitleEditParser:
    """
    Parser for Subtitle Edit dictionary files.

    Supports:
        - eng_OCRFixReplaceList.xml (and other language variants)
        - en_names.xml
        - en_NoBreakAfterList.xml
        - en_US_se.xml (spell check additions)
        - en_interjections_se.xml
        - eng_WordSplitList.txt
    """

    def __init__(self, se_dir: Path):
        """
        Initialize parser with Subtitle Edit dictionaries directory.

        Args:
            se_dir: Path to directory containing SE dictionary files
        """
        self.se_dir = Path(se_dir)
        self._cache: Dict[str, any] = {}

    def get_available_files(self) -> Dict[str, List[Path]]:
        """
        Get available SE dictionary files by category.

        Returns:
            Dict mapping category to list of available files
        """
        files = {
            'ocr_fix': [],
            'names': [],
            'no_break': [],
            'spell_words': [],
            'interjections': [],
            'word_split': [],
        }

        if not self.se_dir.exists():
            return files

        for path in self.se_dir.iterdir():
            name = path.name.lower()

            if name.endswith('_ocrfixreplacelist.xml'):
                files['ocr_fix'].append(path)
            elif name.endswith('_names.xml') or name == 'names.xml':
                files['names'].append(path)
            elif name.endswith('_nobreakafterlist.xml'):
                files['no_break'].append(path)
            elif name.endswith('_se.xml') and 'interjection' not in name:
                files['spell_words'].append(path)
            elif 'interjection' in name and name.endswith('.xml'):
                files['interjections'].append(path)
            elif name.endswith('_wordsplitlist.txt'):
                files['word_split'].append(path)

        return files

    def parse_ocr_fix_list(self, path: Path) -> SEDictionaries:
        """
        Parse an OCRFixReplaceList.xml file.

        Structure:
            <OCRFixReplaceList>
                <WholeLines><Line from="" to="" /></WholeLines>
                <PartialLinesAlways><LinePart from="" to="" /><WordPart from="" to="" /></PartialLinesAlways>
                <PartialLines><LinePart from="" to="" /></PartialLines>
                <BeginLines><Line from="" to="" /></BeginLines>
                <EndLines><Line from="" to="" /></EndLines>
                <WholeWords><Word from="" to="" /></WholeWords>
                <PartialWordsAlways><WordPart from="" to="" /></PartialWordsAlways>
                <PartialWords><WordPart from="" to="" /></PartialWords>
                <RegularExpressions><Regex find="" replaceWith="" /></RegularExpressions>
            </OCRFixReplaceList>
        """
        result = SEDictionaries()

        if not path.exists():
            logger.warning(f"OCR fix list not found: {path}")
            return result

        try:
            tree = ET.parse(path)
            root = tree.getroot()

            # Parse WholeLines
            whole_lines = root.find('WholeLines')
            if whole_lines is not None:
                for elem in whole_lines.findall('Line'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.whole_lines.append(SEReplacementRule(
                            from_text, to_text, 'whole_line'
                        ))

            # Parse PartialLinesAlways
            partial_always = root.find('PartialLinesAlways')
            if partial_always is not None:
                for elem in partial_always.findall('LinePart'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.partial_lines_always.append(SEReplacementRule(
                            from_text, to_text, 'partial_line_always'
                        ))
                for elem in partial_always.findall('WordPart'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.partial_lines_always.append(SEReplacementRule(
                            from_text, to_text, 'partial_line_always'
                        ))

            # Parse PartialLines
            partial_lines = root.find('PartialLines')
            if partial_lines is not None:
                for elem in partial_lines.findall('LinePart'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.partial_lines.append(SEReplacementRule(
                            from_text, to_text, 'partial_line'
                        ))

            # Parse BeginLines
            begin_lines = root.find('BeginLines')
            if begin_lines is not None:
                for elem in begin_lines.findall('Line'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.begin_lines.append(SEReplacementRule(
                            from_text, to_text, 'begin_line'
                        ))

            # Parse EndLines
            end_lines = root.find('EndLines')
            if end_lines is not None:
                for elem in end_lines.findall('Line'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.end_lines.append(SEReplacementRule(
                            from_text, to_text, 'end_line'
                        ))

            # Parse WholeWords
            whole_words = root.find('WholeWords')
            if whole_words is not None:
                for elem in whole_words.findall('Word'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.whole_words.append(SEReplacementRule(
                            from_text, to_text, 'whole_word'
                        ))

            # Parse PartialWordsAlways
            partial_words_always = root.find('PartialWordsAlways')
            if partial_words_always is not None:
                for elem in partial_words_always.findall('WordPart'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.partial_words_always.append(SEReplacementRule(
                            from_text, to_text, 'partial_word_always'
                        ))

            # Parse PartialWords
            partial_words = root.find('PartialWords')
            if partial_words is not None:
                for elem in partial_words.findall('WordPart'):
                    from_text = elem.get('from', '')
                    to_text = elem.get('to', '')
                    if from_text:
                        result.partial_words.append(SEReplacementRule(
                            from_text, to_text, 'partial_word'
                        ))

            # Parse RegularExpressions
            regex_section = root.find('RegularExpressions')
            if regex_section is not None:
                for elem in regex_section.findall('Regex'):
                    find_pattern = elem.get('find', '')
                    replace_with = elem.get('replaceWith', '')
                    if find_pattern:
                        result.regex_rules.append(SEReplacementRule(
                            find_pattern, replace_with, 'regex'
                        ))

            logger.info(f"Loaded OCR fix list: {result.get_replacement_count()} rules from {path.name}")

        except ET.ParseError as e:
            logger.error(f"XML parse error in {path}: {e}")
        except Exception as e:
            logger.error(f"Error loading OCR fix list {path}: {e}")

        return result

    def parse_names_xml(self, path: Path) -> Tuple[Set[str], Set[str]]:
        """
        Parse a names XML file.

        Structure:
            <names>
                <blacklist><name>Name</name></blacklist>
                <name>Name</name>
                ...
            </names>

        Returns:
            (names_set, blacklist_set)
        """
        names = set()
        blacklist = set()

        if not path.exists():
            logger.warning(f"Names file not found: {path}")
            return names, blacklist

        try:
            tree = ET.parse(path)
            root = tree.getroot()

            # Parse blacklist
            blacklist_elem = root.find('blacklist')
            if blacklist_elem is not None:
                for name_elem in blacklist_elem.findall('name'):
                    if name_elem.text:
                        blacklist.add(name_elem.text.strip())

            # Parse names (direct children of root, not in blacklist section)
            for name_elem in root.findall('name'):
                if name_elem.text:
                    names.add(name_elem.text.strip())

            logger.info(f"Loaded {len(names)} names, {len(blacklist)} blacklisted from {path.name}")

        except ET.ParseError as e:
            logger.error(f"XML parse error in {path}: {e}")
        except Exception as e:
            logger.error(f"Error loading names file {path}: {e}")

        return names, blacklist

    def parse_no_break_list(self, path: Path) -> Set[str]:
        """
        Parse a NoBreakAfterList.xml file.

        Structure:
            <NoBreakAfterList><Item>Dr.</Item></NoBreakAfterList>

        Returns:
            Set of words that shouldn't have breaks after them
        """
        items = set()

        if not path.exists():
            logger.warning(f"No break list not found: {path}")
            return items

        try:
            tree = ET.parse(path)
            root = tree.getroot()

            for item_elem in root.findall('Item'):
                if item_elem.text:
                    items.add(item_elem.text.strip())

            logger.info(f"Loaded {len(items)} no-break items from {path.name}")

        except ET.ParseError as e:
            logger.error(f"XML parse error in {path}: {e}")
        except Exception as e:
            logger.error(f"Error loading no break list {path}: {e}")

        return items

    def parse_spell_words_xml(self, path: Path) -> Set[str]:
        """
        Parse a spell check words XML file (*_se.xml).

        Structure:
            <words><word>word</word></words>

        Returns:
            Set of valid words
        """
        words = set()

        if not path.exists():
            logger.warning(f"Spell words file not found: {path}")
            return words

        try:
            tree = ET.parse(path)
            root = tree.getroot()

            for word_elem in root.findall('word'):
                if word_elem.text:
                    words.add(word_elem.text.strip())

            logger.info(f"Loaded {len(words)} spell check words from {path.name}")

        except ET.ParseError as e:
            logger.error(f"XML parse error in {path}: {e}")
        except Exception as e:
            logger.error(f"Error loading spell words file {path}: {e}")

        return words

    def parse_word_split_list(self, path: Path) -> Set[str]:
        """
        Parse a WordSplitList.txt file.

        Format: One word per line, plain text.

        Returns:
            Set of words for word splitting
        """
        words = set()

        if not path.exists():
            logger.warning(f"Word split list not found: {path}")
            return words

        try:
            content = path.read_text(encoding='utf-8')
            for line in content.splitlines():
                word = line.strip()
                if word and not word.startswith('#'):
                    words.add(word)

            logger.info(f"Loaded {len(words)} words for word splitting from {path.name}")

        except Exception as e:
            logger.error(f"Error loading word split list {path}: {e}")

        return words

    def load_all(self, config: Optional[SEDictionaryConfig] = None) -> SEDictionaries:
        """
        Load all available SE dictionary files.

        Args:
            config: Configuration for which dictionaries to enable

        Returns:
            Combined SEDictionaries with all loaded data
        """
        config = config or SEDictionaryConfig()
        result = SEDictionaries()

        available = self.get_available_files()

        # Load OCR fix lists
        if config.ocr_fix_enabled:
            for path in available['ocr_fix']:
                ocr_data = self.parse_ocr_fix_list(path)
                result.whole_lines.extend(ocr_data.whole_lines)
                result.partial_lines_always.extend(ocr_data.partial_lines_always)
                result.partial_lines.extend(ocr_data.partial_lines)
                result.begin_lines.extend(ocr_data.begin_lines)
                result.end_lines.extend(ocr_data.end_lines)
                result.whole_words.extend(ocr_data.whole_words)
                result.partial_words_always.extend(ocr_data.partial_words_always)
                result.partial_words.extend(ocr_data.partial_words)
                result.regex_rules.extend(ocr_data.regex_rules)

        # Load names
        if config.names_enabled:
            for path in available['names']:
                names, blacklist = self.parse_names_xml(path)
                result.names.update(names)
                result.names_blacklist.update(blacklist)

        # Load no break after list
        if config.no_break_enabled:
            for path in available['no_break']:
                no_break = self.parse_no_break_list(path)
                result.no_break_after.update(no_break)

        # Load spell check words
        if config.spell_words_enabled:
            for path in available['spell_words']:
                words = self.parse_spell_words_xml(path)
                result.spell_words.update(words)

        # Load interjections
        if config.interjections_enabled:
            for path in available['interjections']:
                words = self.parse_spell_words_xml(path)  # Same format
                result.interjections.update(words)

        # Load word split list
        if config.word_split_enabled:
            for path in available['word_split']:
                words = self.parse_word_split_list(path)
                result.word_split_list.update(words)

        return result


class WordSplitter:
    """
    Splits merged words using a dictionary of valid words.

    When OCR produces "thisis" or "Idon't", this class can split
    them into "this is" or "I don't".
    """

    def __init__(self, valid_words: Set[str]):
        """
        Initialize with set of valid words.

        Args:
            valid_words: Set of valid words for splitting
        """
        self.valid_words = {w.lower() for w in valid_words}
        self.max_word_len = max(len(w) for w in self.valid_words) if self.valid_words else 20

    def is_valid_word(self, word: str) -> bool:
        """Check if word is in the valid words set."""
        return word.lower() in self.valid_words

    def try_split(self, text: str) -> Optional[str]:
        """
        Try to split a merged word into two valid words.

        Args:
            text: Text that might be merged words

        Returns:
            Split text if successful, None otherwise
        """
        if not text or len(text) < 3:
            return None

        text_lower = text.lower()

        # Try splitting at each position
        for i in range(1, len(text)):
            left = text_lower[:i]
            right = text_lower[i:]

            if self.is_valid_word(left) and self.is_valid_word(right):
                # Preserve original casing for left part
                left_result = text[:i]
                right_result = text[i:]
                return f"{left_result} {right_result}"

        return None

    def split_merged_words(self, text: str, dictionary=None) -> str:
        """
        Split merged words in text.

        Args:
            text: Input text
            dictionary: Optional spell checker to verify words aren't already valid

        Returns:
            Text with merged words split
        """
        words = text.split()
        result_words = []

        for word in words:
            # Skip if word is already valid
            if dictionary and dictionary.check(word):
                result_words.append(word)
                continue

            # Skip if word is in our valid words
            if self.is_valid_word(word):
                result_words.append(word)
                continue

            # Try to split
            split = self.try_split(word)
            if split:
                result_words.append(split)
            else:
                result_words.append(word)

        return ' '.join(result_words)


class SubtitleEditCorrector:
    """
    Applies Subtitle Edit OCR corrections to text.

    Uses the rules loaded from SE dictionary files to fix OCR errors.
    Follows Subtitle Edit's logic: only fix words that are NOT in the dictionary,
    and only accept fixes that produce valid dictionary words.
    """

    def __init__(self, se_dicts: SEDictionaries, spell_checker=None):
        """
        Initialize corrector with loaded dictionaries.

        Args:
            se_dicts: Loaded Subtitle Edit dictionaries
            spell_checker: Spell checker for validating fixes (required for proper operation)
        """
        self.dicts = se_dicts
        self.spell_checker = spell_checker
        self.word_splitter = None

        if se_dicts.word_split_list:
            self.word_splitter = WordSplitter(se_dicts.word_split_list)

        # Compile regex patterns
        self._compiled_regex = []
        for rule in se_dicts.regex_rules:
            try:
                pattern = re.compile(rule.from_text)
                self._compiled_regex.append((pattern, rule.to_text))
            except re.error as e:
                logger.warning(f"Invalid SE regex pattern '{rule.from_text}': {e}")

        # Build lookup dicts for faster word-level processing
        self._whole_word_map = {rule.from_text: rule.to_text for rule in se_dicts.whole_words}

    def _is_word_valid(self, word: str) -> bool:
        """Check if a word is valid (in spell checker or SE dictionaries)."""
        if not word or len(word) <= 1:
            return True  # Skip very short words

        # Strip punctuation for checking
        clean_word = word.strip(".,!?;:\"'()-")
        if not clean_word:
            return True

        # Check spell checker
        if self.spell_checker:
            if self.spell_checker.check(clean_word):
                return True
            if self.spell_checker.check(clean_word.lower()):
                return True
            if self.spell_checker.check(clean_word.capitalize()):
                return True

        # Check SE valid words (names, spell_words, etc.)
        all_valid = self.dicts.get_all_valid_words()
        if clean_word in all_valid or clean_word.lower() in {w.lower() for w in all_valid}:
            return True

        return False

    def _try_fix_word(self, word: str) -> Tuple[str, Optional[str]]:
        """
        Try to fix a single word using SE rules.

        Args:
            word: Word to fix

        Returns:
            (fixed_word, fix_description) or (original_word, None) if no fix applied
        """
        # Strip punctuation but remember it
        prefix = ""
        suffix = ""
        clean_word = word

        # Extract leading punctuation
        while clean_word and not clean_word[0].isalnum():
            prefix += clean_word[0]
            clean_word = clean_word[1:]

        # Extract trailing punctuation
        while clean_word and not clean_word[-1].isalnum():
            suffix = clean_word[-1] + suffix
            clean_word = clean_word[:-1]

        if not clean_word:
            return word, None

        # If word is already valid, don't fix it
        if self._is_word_valid(clean_word):
            return word, None

        # Try whole word replacement
        if clean_word in self._whole_word_map:
            replacement = self._whole_word_map[clean_word]
            if self._is_word_valid(replacement):
                return prefix + replacement + suffix, f"whole_word: {clean_word} -> {replacement}"

        # Try partial word fixes (only PartialWords, not PartialWordsAlways - those are line-level)
        for rule in self.dicts.partial_words:
            if rule.from_text in clean_word:
                new_word = clean_word.replace(rule.from_text, rule.to_text)
                if self._is_word_valid(new_word):
                    return prefix + new_word + suffix, f"partial_word: {rule.from_text} -> {rule.to_text}"

        # Word couldn't be fixed
        return word, None

    def apply_corrections(self, text: str) -> Tuple[str, List[str], List[str]]:
        """
        Apply all SE corrections to text.

        Follows Subtitle Edit's logic:
        1. Line-level fixes (always apply - these are safe patterns)
        2. Word-level fixes (only fix unknown words, only accept valid results)
        3. Word splitting (only for unknown words)

        Args:
            text: Input text

        Returns:
            (corrected_text, list_of_applied_fixes, list_of_unknown_words)
        """
        fixes_applied = []
        unknown_words = []

        # === LINE-LEVEL FIXES (safe patterns, always apply) ===

        # 1. Whole line replacements (exact match of entire line)
        for rule in self.dicts.whole_lines:
            if text.strip() == rule.from_text:
                text = rule.to_text
                fixes_applied.append(f"whole_line: {rule.from_text} -> {rule.to_text}")
                break

        # 2. Begin line replacements
        for rule in self.dicts.begin_lines:
            if text.startswith(rule.from_text):
                text = rule.to_text + text[len(rule.from_text):]
                fixes_applied.append(f"begin_line: {rule.from_text} -> {rule.to_text}")

        # 3. End line replacements
        for rule in self.dicts.end_lines:
            if text.endswith(rule.from_text):
                text = text[:-len(rule.from_text)] + rule.to_text
                fixes_applied.append(f"end_line: {rule.from_text} -> {rule.to_text}")

        # 4. Partial lines always (safe substring fixes like '' -> " or ,., -> ...)
        for rule in self.dicts.partial_lines_always:
            if rule.from_text in text:
                text = text.replace(rule.from_text, rule.to_text)
                fixes_applied.append(f"partial_always: {rule.from_text} -> {rule.to_text}")

        # 5. Partial words always (safe substring fixes applied to whole text)
        for rule in self.dicts.partial_words_always:
            if rule.from_text in text:
                text = text.replace(rule.from_text, rule.to_text)
                fixes_applied.append(f"partial_word_always: {rule.from_text} -> {rule.to_text}")

        # 6. Regex replacements (usually safe patterns)
        for pattern, replacement in self._compiled_regex:
            if pattern.search(text):
                text = pattern.sub(replacement, text)
                fixes_applied.append(f"regex: {pattern.pattern}")

        # === WORD-LEVEL FIXES (require spell check validation) ===

        # Only do word-level processing if we have a spell checker
        if self.spell_checker:
            # Split into words, preserving spacing
            words = re.findall(r'\S+|\s+', text)
            result_words = []

            for word in words:
                # Skip whitespace
                if word.isspace():
                    result_words.append(word)
                    continue

                # Try to fix the word
                fixed_word, fix_desc = self._try_fix_word(word)

                if fix_desc:
                    fixes_applied.append(fix_desc)
                    result_words.append(fixed_word)
                else:
                    result_words.append(word)
                    # Track unknown words (that we couldn't fix)
                    clean = word.strip(".,!?;:\"'()-")
                    if clean and len(clean) > 1 and not self._is_word_valid(clean):
                        if clean not in unknown_words:
                            unknown_words.append(clean)

            text = ''.join(result_words)

            # Word splitting (only for unknown words - already handled in WordSplitter)
            if self.word_splitter:
                new_text = self.word_splitter.split_merged_words(text, self.spell_checker)
                if new_text != text:
                    fixes_applied.append("word_split")
                    text = new_text

        return text, fixes_applied, unknown_words

    def _seems_valid(self, text: str) -> bool:
        """Check if text seems to contain valid words."""
        if not self.spell_checker:
            return True

        words = re.findall(r'\b[a-zA-Z]+\b', text)
        if not words:
            return True

        # Consider valid if at least half the words are recognized
        valid_count = sum(1 for w in words if self.spell_checker.check(w))
        return valid_count >= len(words) / 2

    def is_valid_name(self, word: str) -> bool:
        """Check if word is in the names list (and not blacklisted)."""
        if word in self.dicts.names_blacklist:
            return False
        return word in self.dicts.names

    def is_no_break_word(self, word: str) -> bool:
        """Check if word should not have a line break after it."""
        return word in self.dicts.no_break_after

    def is_valid_word(self, word: str) -> bool:
        """Check if word is in any of the valid word lists."""
        all_valid = self.dicts.get_all_valid_words()
        return word in all_valid or word.lower() in {w.lower() for w in all_valid}


# Configuration storage
SE_CONFIG_FILE = "subtitle_edit_config.json"


def load_se_config(config_dir: Path) -> SEDictionaryConfig:
    """Load Subtitle Edit configuration from file."""
    config_path = config_dir / SE_CONFIG_FILE

    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding='utf-8'))
            return SEDictionaryConfig(
                ocr_fix_enabled=data.get('ocr_fix_enabled', True),
                names_enabled=data.get('names_enabled', True),
                no_break_enabled=data.get('no_break_enabled', True),
                spell_words_enabled=data.get('spell_words_enabled', True),
                word_split_enabled=data.get('word_split_enabled', True),
                interjections_enabled=data.get('interjections_enabled', True),
            )
        except Exception as e:
            logger.error(f"Error loading SE config: {e}")

    return SEDictionaryConfig()


def save_se_config(config_dir: Path, config: SEDictionaryConfig) -> bool:
    """Save Subtitle Edit configuration to file."""
    config_path = config_dir / SE_CONFIG_FILE

    try:
        data = {
            'ocr_fix_enabled': config.ocr_fix_enabled,
            'names_enabled': config.names_enabled,
            'no_break_enabled': config.no_break_enabled,
            'spell_words_enabled': config.spell_words_enabled,
            'word_split_enabled': config.word_split_enabled,
            'interjections_enabled': config.interjections_enabled,
        }
        config_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
        return True
    except Exception as e:
        logger.error(f"Error saving SE config: {e}")
        return False
