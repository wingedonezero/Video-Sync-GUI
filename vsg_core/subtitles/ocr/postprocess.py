# vsg_core/subtitles/ocr/postprocess.py
# -*- coding: utf-8 -*-
"""
OCR Post-Processing and Text Correction

Improves OCR output through:
    1. Confidence-driven pattern fixes (aggressive fixes for low confidence)
    2. Unambiguous fixes (always applied - clear OCR errors)
    3. Dictionary validation (tracks unknown words, doesn't block fixes)
    4. Custom wordlist support (anime names, romaji, etc.)

Rules are loaded from editable database files in .config/ocr/:
    - replacements.json: Pattern-based corrections
    - user_dictionary.txt: Custom valid words
    - names.txt: Proper names

Key difference from the old cleanup.py:
    - OLD: Dictionary blocks fixes even when OCR is wrong
    - NEW: Confidence drives fix aggressiveness, dictionary just reports unknowns

The approach is:
    - LOW confidence = apply aggressive fixes (OCR is uncertain)
    - HIGH confidence = trust OCR, minimal fixes
    - Dictionary = report unknown words, don't block corrections
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .dictionaries import OCRDictionaries, ReplacementRule, get_dictionaries
from .subtitle_edit import (
    SubtitleEditParser, SubtitleEditCorrector, SEDictionaries, SEDictionaryConfig,
    load_se_config, save_se_config
)

logger = logging.getLogger(__name__)

try:
    import enchant
    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False


@dataclass
class PostProcessConfig:
    """Configuration for post-processing."""
    # Master switch - disables all fixes when False
    cleanup_enabled: bool = True  # Master enable/disable for OCR cleanup

    # Confidence thresholds
    low_confidence_threshold: float = 60.0  # Apply aggressive fixes below this
    very_low_confidence_threshold: float = 40.0  # Apply extra aggressive fixes
    garbage_confidence_threshold: float = 35.0  # Lines below this are likely garbage

    # Fix categories (only apply if cleanup_enabled is True)
    enable_unambiguous_fixes: bool = True  # Always-apply fixes
    enable_confidence_fixes: bool = True  # Confidence-gated fixes
    enable_dictionary_validation: bool = True  # Track unknown words
    enable_garbage_detection: bool = True  # Detect and clean garbage OCR

    # Subtitle Edit integration
    enable_subtitle_edit: bool = True  # Use Subtitle Edit dictionaries

    # Normalization
    normalize_ellipsis: bool = False  # Convert … to ...
    normalize_quotes: bool = True  # Standardize quote characters
    fix_spacing: bool = True  # Fix common spacing issues

    # Custom wordlist
    custom_wordlist_path: Optional[Path] = None


@dataclass
class ProcessResult:
    """Result of post-processing."""
    text: str
    original_text: str
    unknown_words: List[str] = field(default_factory=list)
    fixes_applied: Dict[str, int] = field(default_factory=dict)
    was_modified: bool = False


@dataclass
class UnknownWordInfo:
    """Information about an unknown word."""
    word: str
    context: str  # Surrounding text
    confidence: float
    suggestions: List[str] = field(default_factory=list)


class OCRPostProcessor:
    """
    Post-processes OCR text to fix common errors.

    Uses a confidence-driven approach:
    - Unambiguous fixes always applied (clear OCR errors like l'm → I'm)
    - Confidence-gated fixes only applied when OCR confidence is low
    - Dictionary validation reports unknowns but doesn't block fixes
    """

    # Unambiguous fixes - these are NEVER valid English text
    # and always represent OCR errors
    # NOTE: These should be whole-word replacements or use word boundaries
    # Don't add patterns that could match inside valid words!
    UNAMBIGUOUS_FIXES = {
        # I/l confusion in contractions - these are safe (apostrophe context)
        "l'm": "I'm",
        "l've": "I've",
        "l'll": "I'll",
        "l'd": "I'd",
        "lt's": "It's",
        "lt'II": "It'll",
        "lt'Il": "It'll",
        "l'II": "I'll",
        "l'Il": "I'll",
        "lsn't": "Isn't",
        # Double-I confusion
        "IIl": "Ill",
        "IIi": "Ili",
        # Pipe confusion (| read as I or l)
        "|": "I",
        "||": "ll",
    }

    # Word-boundary fixes - only apply when the pattern is a complete word
    # These use regex with \b word boundaries
    WORD_BOUNDARY_FIXES = {
        "lf": "If",
        "ln": "In",
        "ls": "Is",
        "lt": "It",
        "lts": "Its",
        "l": "I",  # Standalone l → I
        "ll": "ll",  # Keep as-is (valid word ending)
        "II": "II",  # Context-dependent, handled separately
    }

    # Confidence-gated fixes - only apply when confidence is low
    CONFIDENCE_FIXES = {
        # rn → m confusion
        'rn': 'm',
        # O/0 confusion
        '0': 'O',  # Context-dependent
        # 1/l confusion (beyond contractions)
        '1': 'l',  # Context-dependent
    }

    # Common subtitle words to add to dictionary
    COMMON_WORDS = {
        'okay', 'OK', 'yeah', 'gonna', 'wanna', 'gotta',
        "ain't", "y'all", "ma'am", 'hmm', 'uh', 'um',
        'whoa', 'wow', 'hey', 'huh', 'eh', 'ah', 'oh',
        'bye', 'hi', 'nope', 'yep', 'nah', 'duh',
    }

    def __init__(self, config: Optional[PostProcessConfig] = None):
        self.config = config or PostProcessConfig()
        self._init_dictionaries()
        self._init_spell_checker()
        self._init_patterns()
        self._init_subtitle_edit()

    def _init_dictionaries(self):
        """Initialize OCR dictionaries from database."""
        self.ocr_dicts = get_dictionaries()
        self.replacement_rules = self.ocr_dicts.load_replacements()
        self.custom_words = self.ocr_dicts.load_user_dictionary()
        self.custom_names = self.ocr_dicts.load_names()

        # Combine user dictionary and names for validation
        self.all_custom_words = self.custom_words | self.custom_names

        # Pre-load romaji dictionary and log stats
        romaji_stats = self.ocr_dicts.get_romaji_stats()

        logger.debug(f"OCR dictionaries loaded from: {self.ocr_dicts.config_dir}")
        logger.debug(f"Loaded {len(self.replacement_rules)} replacement rules")
        logger.debug(f"Loaded {len(self.custom_words)} user dictionary words")
        logger.debug(f"Loaded {len(self.custom_names)} names")
        logger.debug(f"Romaji dictionary: {romaji_stats.get('word_count', 0)} words from {romaji_stats.get('dict_path', 'N/A')}")

    def _init_spell_checker(self):
        """Initialize spell-check dictionary."""
        self.dictionary = None
        if ENCHANT_AVAILABLE and self.config.enable_dictionary_validation:
            try:
                self.dictionary = enchant.Dict("en_US")
                # Add common subtitle words
                for word in self.COMMON_WORDS:
                    self.dictionary.add_to_session(word)
                # Add user dictionary words and names
                for word in self.all_custom_words:
                    self.dictionary.add_to_session(word)
            except enchant.errors.DictNotFoundError:
                pass

    def _init_patterns(self):
        """Compile regex patterns from database rules."""
        # Categorize rules by type
        self.literal_rules = []  # Direct string replacements
        self.word_boundary_patterns = {}  # Word boundary regex
        self.word_start_patterns = {}
        self.word_end_patterns = {}
        self.word_middle_patterns = {}
        self.regex_patterns = {}
        self.confidence_gated_rules = []  # Applied only when confidence is low

        for rule in self.replacement_rules:
            if not rule.enabled:
                continue

            if rule.confidence_gated:
                self.confidence_gated_rules.append(rule)
                continue

            if rule.rule_type == "literal":
                self.literal_rules.append(rule)
            elif rule.rule_type == "word":
                pattern = re.compile(r'\b' + re.escape(rule.pattern) + r'\b')
                self.word_boundary_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_start":
                pattern = re.compile(r'\b' + re.escape(rule.pattern))
                self.word_start_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_end":
                pattern = re.compile(re.escape(rule.pattern) + r'\b')
                self.word_end_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_middle":
                # Match pattern when not at word boundary
                pattern = re.compile(r'(?<=[a-zA-Z])' + re.escape(rule.pattern) + r'(?=[a-zA-Z])')
                self.word_middle_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "regex":
                try:
                    pattern = re.compile(rule.pattern)
                    self.regex_patterns[rule.pattern] = (pattern, rule.replacement)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{rule.pattern}': {e}")

        # Standalone 'l' that should be 'I' (backup, covered by WORD_BOUNDARY_FIXES)
        self.standalone_l_pattern = re.compile(r'\bl\b')

        # 'l' at start of sentence (likely 'I')
        self.sentence_start_l_pattern = re.compile(r'(^|[.!?]\s+)l\s')

        # rn patterns (context-aware)
        self.rn_patterns = [
            (re.compile(r'\brn([aeiou])'), r'm\1'),  # rn before vowel
            (re.compile(r'([aeiou])rn\b'), r'\1m'),  # rn after vowel at word end
            (re.compile(r'\b([a-z]+)rn([a-z]+)\b'), self._fix_rn_in_word),  # rn in middle
        ]

        # Trailing l/ll that might be ! or !!
        self.trailing_exclaim_pattern = re.compile(r'\b(\w+?)l{1,2}$')

        # Space before punctuation
        self.space_before_punct = re.compile(r'\s+([!?.,;:])')

        # Multiple spaces
        self.multiple_spaces = re.compile(r' {2,}')

        # Trailing OCR artifacts (underscore, tilde, etc. at end of text)
        self.trailing_artifacts = re.compile(r'[_~`]+\s*$')

        # Leading/trailing underscores on words
        self.word_underscores = re.compile(r'\b_+(\w+)_*\b|\b(\w+)_+\b')

        # II that should be ll (in words)
        self.double_i_pattern = re.compile(r'\b(\w*)II(\w*)\b')

        # Garbage patterns - random capital letters with spaces
        # Matches things like "U B D N TR S A" or "L ol T T T"
        self.garbage_pattern = re.compile(
            r'^[A-Z0-9\s\(\)\[\]\-\.,;:!?\'"~]+$'  # All caps/numbers/punctuation
        )
        # Pattern for sequences of short "words" (1-2 chars each)
        self.short_word_sequence = re.compile(
            r'(?:\b[A-Z]{1,2}\b\s*){3,}'  # 3+ consecutive 1-2 char uppercase "words"
        )

    def _init_subtitle_edit(self):
        """Initialize Subtitle Edit dictionary integration."""
        self.se_corrector = None
        self.se_dicts = None

        if not self.config.enable_subtitle_edit:
            return

        try:
            # Get SE dictionaries directory
            se_dir = self.ocr_dicts.config_dir / "subtitleedit"

            if not se_dir.exists():
                # Create the directory for users to add SE files
                se_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created Subtitle Edit dictionaries directory: {se_dir}")
                return

            # Load SE configuration
            se_config = load_se_config(self.ocr_dicts.config_dir)

            # Parse all available SE files
            parser = SubtitleEditParser(se_dir)
            available_files = parser.get_available_files()

            # Check if any files are available
            has_files = any(files for files in available_files.values())
            if not has_files:
                logger.debug("No Subtitle Edit dictionary files found")
                return

            # Load dictionaries
            self.se_dicts = parser.load_all(se_config)

            # Create corrector
            self.se_corrector = SubtitleEditCorrector(self.se_dicts, self.dictionary)

            # Add SE valid words to spell checker
            if self.dictionary:
                for word in self.se_dicts.get_all_valid_words():
                    self.dictionary.add_to_session(word)

            logger.info(
                f"Loaded Subtitle Edit dictionaries: "
                f"{self.se_dicts.get_replacement_count()} rules, "
                f"{len(self.se_dicts.names)} names, "
                f"{len(self.se_dicts.word_split_list)} split words"
            )

        except Exception as e:
            logger.error(f"Error initializing Subtitle Edit integration: {e}")
            self.se_corrector = None
            self.se_dicts = None

    def process(
        self,
        text: str,
        confidence: float = 100.0,
        timestamp: str = ""
    ) -> ProcessResult:
        """
        Process OCR text and apply corrections.

        Args:
            text: Raw OCR output text
            confidence: OCR confidence (0-100)
            timestamp: Subtitle timestamp for context

        Returns:
            ProcessResult with corrected text and metadata
        """
        result = ProcessResult(
            text=text,
            original_text=text,
            fixes_applied=defaultdict(int),
        )

        if not text.strip():
            return result

        current_text = text

        # If cleanup is disabled, skip all fixes but still do dictionary validation
        if not self.config.cleanup_enabled:
            # Only do dictionary validation for reporting
            if self.config.enable_dictionary_validation:
                result.unknown_words = self._find_unknown_words(current_text)
            result.text = current_text
            return result

        # Step 0: Detect and clean garbage OCR output
        if self.config.enable_garbage_detection:
            current_text = self._clean_garbage_from_text(current_text, result)
            if not current_text.strip():
                # Entire text was garbage
                result.text = ""
                result.was_modified = True
                return result

        # Step 1: Always apply unambiguous fixes (user's rules first)
        if self.config.enable_unambiguous_fixes:
            current_text = self._apply_unambiguous_fixes(current_text, result)

        # Step 2: Apply Subtitle Edit corrections (after user rules)
        if self.config.enable_subtitle_edit and self.se_corrector:
            current_text = self._apply_subtitle_edit_fixes(current_text, result)

        # Step 3: Apply confidence-gated fixes
        if self.config.enable_confidence_fixes:
            current_text = self._apply_confidence_fixes(
                current_text, confidence, result
            )

        # Step 4: Normalization
        current_text = self._apply_normalization(current_text, result)

        # Step 5: Dictionary validation (report, don't fix)
        if self.config.enable_dictionary_validation:
            dict_unknown = self._find_unknown_words(current_text)
            # Merge with SE unknown words (dedupe)
            all_unknown = set(result.unknown_words)
            all_unknown.update(dict_unknown)
            result.unknown_words = list(all_unknown)

        result.text = current_text
        result.was_modified = current_text != text

        return result

    def _apply_unambiguous_fixes(
        self,
        text: str,
        result: ProcessResult
    ) -> str:
        """
        Apply fixes that are always correct.

        These patterns are loaded from the replacements database.
        """
        # Apply literal replacements (exact string match)
        for rule in self.literal_rules:
            if rule.pattern in text:
                count = text.count(rule.pattern)
                text = text.replace(rule.pattern, rule.replacement)
                result.fixes_applied[f'{rule.pattern}→{rule.replacement}'] += count

        # Apply word-boundary replacements
        for pattern_str, (pattern, replacement) in self.word_boundary_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f'{pattern_str}→{replacement}'] += len(matches)

        # Apply word-start replacements
        for pattern_str, (pattern, replacement) in self.word_start_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f'{pattern_str}→{replacement} (word start)'] += len(matches)

        # Apply word-end replacements
        for pattern_str, (pattern, replacement) in self.word_end_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f'{pattern_str}→{replacement} (word end)'] += len(matches)

        # Apply regex replacements
        for pattern_str, (pattern, replacement) in self.regex_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f'regex:{pattern_str}'] += len(matches)

        # Handle 'l' at sentence start (additional context check)
        def fix_sentence_start(m):
            return m.group(1) + 'I '
        new_text = self.sentence_start_l_pattern.sub(fix_sentence_start, text)
        if new_text != text:
            result.fixes_applied['l→I (sentence start)'] += 1
            text = new_text

        # Handle II → ll in words (like "wiII" → "will")
        def fix_double_i(m):
            prefix, suffix = m.group(1), m.group(2)
            # Only fix if it makes a plausible word
            potential_word = prefix + 'll' + suffix
            if self._is_likely_word(potential_word):
                return potential_word
            return m.group(0)

        new_text = self.double_i_pattern.sub(fix_double_i, text)
        if new_text != text:
            result.fixes_applied['II→ll'] += 1
            text = new_text

        return text

    def _apply_subtitle_edit_fixes(
        self,
        text: str,
        result: ProcessResult
    ) -> str:
        """
        Apply Subtitle Edit OCR corrections.

        These are applied after user's custom rules, so user rules take precedence.
        """
        if not self.se_corrector:
            return text

        try:
            corrected_text, fixes, se_unknown_words = self.se_corrector.apply_corrections(text)

            # Track fixes applied
            for fix in fixes:
                result.fixes_applied[f'SE:{fix}'] += 1

            # Log unknown words that couldn't be fixed
            if se_unknown_words:
                logger.debug(f"SE unknown words: {', '.join(se_unknown_words)}")
                # Add to result's unknown words (will be merged later)
                result.unknown_words.extend(se_unknown_words)

            return corrected_text

        except Exception as e:
            logger.warning(f"Error applying Subtitle Edit fixes: {e}")
            return text

    def _apply_confidence_fixes(
        self,
        text: str,
        confidence: float,
        result: ProcessResult
    ) -> str:
        """
        Apply fixes based on OCR confidence level.

        Low confidence → aggressive fixes (confidence-gated rules from database)
        High confidence → trust OCR output
        """
        # Skip confidence fixes if confidence is high
        if confidence >= self.config.low_confidence_threshold:
            return text

        is_very_low = confidence < self.config.very_low_confidence_threshold

        # Apply confidence-gated rules from database
        for rule in self.confidence_gated_rules:
            if rule.rule_type == "word_middle":
                # Match pattern when not at word boundary
                pattern = re.compile(r'(?<=[a-zA-Z])' + re.escape(rule.pattern) + r'(?=[a-zA-Z])')
                new_text = pattern.sub(rule.replacement, text)
            elif rule.rule_type == "word":
                pattern = re.compile(r'\b' + re.escape(rule.pattern) + r'\b')
                new_text = pattern.sub(rule.replacement, text)
            elif rule.rule_type == "literal":
                new_text = text.replace(rule.pattern, rule.replacement)
            else:
                continue

            if new_text != text:
                result.fixes_applied[f'{rule.pattern}→{rule.replacement} (low conf)'] += 1
                text = new_text

        # Also apply the built-in rn patterns for backward compatibility
        for pattern, replacement in self.rn_patterns:
            if callable(replacement):
                new_text = pattern.sub(replacement, text)
            else:
                new_text = pattern.sub(replacement, text)
            if new_text != text:
                result.fixes_applied['rn→m'] += 1
                text = new_text

        # Very low confidence: apply more aggressive fixes
        if is_very_low:
            # Fix trailing l/ll that might be exclamation
            text = self._fix_trailing_exclamation(text, result)

        return text

    def _fix_rn_in_word(self, match) -> str:
        """
        Fix 'rn' in the middle of a word if it makes sense.

        Only fixes if replacing 'rn' with 'm' produces a valid word.
        """
        full_match = match.group(0)
        prefix, suffix = match.group(1), match.group(2)

        # Check if replacing rn with m makes a valid word
        potential_word = prefix + 'm' + suffix

        if self._is_likely_word(potential_word):
            return potential_word
        return full_match

    def _fix_trailing_exclamation(
        self,
        text: str,
        result: ProcessResult
    ) -> str:
        """
        Fix words ending in 'l' or 'll' that should be '!' or '!!'.

        Common OCR error: "Yes!" becomes "Yesl"
        """
        words = text.split()
        modified = False

        for i, word in enumerate(words):
            # Check for trailing l or ll
            match = self.trailing_exclaim_pattern.match(word)
            if not match:
                continue

            base = match.group(1)
            trailing = word[len(base):]

            # Check if base without trailing l is a valid word
            # and the result looks like an exclamation
            if base and self._is_likely_word(base):
                # Check context - is this likely an exclamation?
                if self._is_likely_exclamation(base, words, i):
                    if trailing == 'll':
                        words[i] = base + '!!'
                        result.fixes_applied['ll→!!'] += 1
                        modified = True
                    elif trailing == 'l':
                        words[i] = base + '!'
                        result.fixes_applied['l→!'] += 1
                        modified = True

        if modified:
            text = ' '.join(words)

        return text

    def _is_likely_exclamation(
        self,
        word: str,
        words: List[str],
        position: int
    ) -> bool:
        """
        Determine if a word is likely meant to be an exclamation.

        Considers: word type, position in sentence, common patterns.
        """
        word_lower = word.lower()

        # Common exclamation words
        exclamation_words = {
            'yes', 'no', 'stop', 'wait', 'help', 'go', 'run',
            'hey', 'what', 'wow', 'oh', 'ah', 'look', 'watch',
            'hurry', 'quick', 'move', 'come', 'get', 'damn',
            'god', 'hell', 'please', 'sorry', 'thanks',
        }

        if word_lower in exclamation_words:
            return True

        # End of line/sentence is more likely to be exclamation
        if position == len(words) - 1:
            return True

        return False

    def _apply_normalization(
        self,
        text: str,
        result: ProcessResult
    ) -> str:
        """Apply text normalization fixes."""
        # Remove trailing OCR artifacts (underscores, tildes at end of text)
        new_text = self.trailing_artifacts.sub('', text)
        if new_text != text:
            result.fixes_applied['trailing artifact removed'] += 1
            text = new_text

        # Remove underscores attached to words (OCR noise)
        def fix_word_underscores(m):
            # Return the word without underscores
            return m.group(1) or m.group(2) or ''
        new_text = self.word_underscores.sub(fix_word_underscores, text)
        if new_text != text:
            result.fixes_applied['underscore removed'] += 1
            text = new_text

        # Normalize ellipsis
        if self.config.normalize_ellipsis:
            if '…' in text:
                text = text.replace('…', '...')
                result.fixes_applied['ellipsis normalized'] += 1

        # Fix spacing before punctuation
        if self.config.fix_spacing:
            new_text = self.space_before_punct.sub(r'\1', text)
            if new_text != text:
                result.fixes_applied['spacing fixed'] += 1
                text = new_text

            # Fix multiple spaces
            new_text = self.multiple_spaces.sub(' ', text)
            if new_text != text:
                result.fixes_applied['multiple spaces'] += 1
                text = new_text

        # Normalize quotes
        if self.config.normalize_quotes:
            quote_fixes = [
                ('"', '"'),  # Left double quote
                ('"', '"'),  # Right double quote
                (''', "'"),  # Left single quote
                (''', "'"),  # Right single quote
            ]
            for old, new in quote_fixes:
                if old in text:
                    text = text.replace(old, new)
                    result.fixes_applied['quotes normalized'] += 1

        return text

    def _find_unknown_words(self, text: str) -> List[str]:
        """
        Find words not in dictionary.

        These are reported but not "fixed" - they may be:
        - Names (character names, place names)
        - Foreign words (romaji, etc.)
        - OCR errors that weren't caught by patterns
        - Technical terms
        """
        if not self.dictionary:
            return []

        unknown = []
        # Extract words (alphanumeric, apostrophes allowed)
        word_pattern = re.compile(r"[A-Za-z][A-Za-z']*[A-Za-z]|[A-Za-z]")

        for match in word_pattern.finditer(text):
            word = match.group()

            # Skip if in user dictionary, names, or romaji dictionary
            if self.ocr_dicts.is_known_word(word, check_romaji=True):
                continue

            # Skip if in Subtitle Edit dictionaries
            if self.se_corrector and self.se_corrector.is_valid_word(word):
                continue

            # Skip common contractions that might not be in dict
            if "'" in word:
                continue

            # Skip short words (likely valid)
            if len(word) <= 2:
                continue

            # Check dictionary
            if not self._is_valid_word(word):
                unknown.append(word)

        return list(set(unknown))  # Remove duplicates

    def _is_valid_word(self, word: str) -> bool:
        """Check if word is valid according to dictionary."""
        if not self.dictionary:
            return True

        # Check user dictionary, names, and romaji dictionary first
        if self.ocr_dicts.is_known_word(word, check_romaji=True):
            return True

        # Check Subtitle Edit dictionaries
        if self.se_corrector and self.se_corrector.is_valid_word(word):
            return True

        # Check dictionary
        if self.dictionary.check(word):
            return True
        if self.dictionary.check(word.lower()):
            return True
        if self.dictionary.check(word.capitalize()):
            return True

        return False

    def _is_likely_word(self, word: str) -> bool:
        """
        Check if something is likely a valid English word.

        Less strict than dictionary check - used for fix validation.
        """
        if not word:
            return False

        # Check user dictionary, names, and romaji first
        if self.ocr_dicts.is_known_word(word, check_romaji=True):
            return True

        # Dictionary check
        if self.dictionary and self._is_valid_word(word):
            return True

        # Common short words often not in dictionary
        common_short = {'a', 'an', 'as', 'at', 'be', 'by', 'do', 'go', 'he',
                       'if', 'in', 'is', 'it', 'me', 'my', 'no', 'of', 'ok',
                       'on', 'or', 'so', 'to', 'up', 'us', 'we'}
        if word.lower() in common_short:
            return True

        return False

    def _is_garbage_line(self, text: str, confidence: float = 100.0) -> bool:
        """
        Detect if a line is likely OCR garbage.

        Garbage patterns include:
        - Random capital letters with spaces: "U B D N TR S A"
        - Very low confidence with mostly non-words
        - High ratio of uppercase single characters

        Args:
            text: Text to check
            confidence: OCR confidence for this text

        Returns:
            True if text appears to be garbage
        """
        if not text or len(text.strip()) < 3:
            return False

        text = text.strip()

        # Very low confidence is a strong signal
        if confidence < self.config.garbage_confidence_threshold:
            # Check if it looks like garbage
            words = text.split()
            if len(words) >= 3:
                # Count short "words" (1-2 chars)
                short_words = sum(1 for w in words if len(w) <= 2)
                if short_words / len(words) > 0.6:
                    return True

        # Check for sequences of short uppercase "words"
        if self.short_word_sequence.search(text):
            # Verify it's not a valid acronym or initialism
            # by checking if there are normal words around it
            words = text.split()
            uppercase_short = sum(1 for w in words if len(w) <= 2 and w.isupper())
            if uppercase_short >= 3 and uppercase_short / len(words) > 0.5:
                return True

        # Check character composition
        letters = [c for c in text if c.isalpha()]
        if letters:
            uppercase_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            # If mostly uppercase and has many spaces, likely garbage
            if uppercase_ratio > 0.8:
                space_ratio = text.count(' ') / len(text)
                if space_ratio > 0.3:  # More than 30% spaces
                    return True

        return False

    def _clean_garbage_from_text(
        self,
        text: str,
        result: ProcessResult,
        line_confidences: Optional[List[float]] = None
    ) -> str:
        """
        Remove garbage segments from multi-line text.

        For subtitles with format "garbage\\Ngood text", removes the garbage
        while keeping the good text.

        Args:
            text: Full subtitle text (may contain \\N line breaks)
            result: ProcessResult to track fixes
            line_confidences: Optional confidence per line

        Returns:
            Cleaned text with garbage removed
        """
        if not self.config.enable_garbage_detection:
            return text

        # Split on subtitle line breaks
        lines = text.split('\\N')

        if len(lines) == 1:
            # Single line - check if entire thing is garbage
            if self._is_garbage_line(text, line_confidences[0] if line_confidences else 100.0):
                result.fixes_applied['garbage line removed'] += 1
                return ""
            return text

        # Multi-line - check each line
        clean_lines = []
        for i, line in enumerate(lines):
            conf = line_confidences[i] if line_confidences and i < len(line_confidences) else 100.0

            if self._is_garbage_line(line, conf):
                result.fixes_applied['garbage line removed'] += 1
                continue

            # Also remove short garbage-like fragments
            line = self._remove_garbage_fragments(line, result)
            if line.strip():
                clean_lines.append(line)

        return '\\N'.join(clean_lines)

    def _remove_garbage_fragments(self, text: str, result: ProcessResult) -> str:
        """
        Remove garbage fragments from within a line.

        Handles cases like "U B D N TR S A All units, report" where
        garbage precedes valid text.
        """
        # Look for garbage at the start of the line
        # Pattern: sequence of short uppercase "words" followed by valid text
        match = self.short_word_sequence.match(text)
        if match:
            garbage = match.group(0)
            rest = text[len(garbage):].strip()
            # Check if the rest looks like valid text
            if rest and not self._is_garbage_line(rest):
                result.fixes_applied['garbage prefix removed'] += 1
                return rest

        return text


def create_postprocessor(settings_dict: dict) -> OCRPostProcessor:
    """
    Create post-processor from settings dictionary.

    Args:
        settings_dict: Application settings

    Returns:
        Configured OCRPostProcessor
    """
    custom_path = settings_dict.get('ocr_custom_wordlist_path', '')

    config = PostProcessConfig(
        cleanup_enabled=settings_dict.get('ocr_cleanup_enabled', True),
        low_confidence_threshold=settings_dict.get('ocr_low_confidence_threshold', 60.0),
        normalize_ellipsis=settings_dict.get('ocr_cleanup_normalize_ellipsis', False),
        custom_wordlist_path=Path(custom_path) if custom_path else None,
    )

    return OCRPostProcessor(config)
