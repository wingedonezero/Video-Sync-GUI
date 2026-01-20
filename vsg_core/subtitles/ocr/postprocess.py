# vsg_core/subtitles/ocr/postprocess.py
# -*- coding: utf-8 -*-
"""
OCR Post-Processing and Text Correction

Improves OCR output through:
    1. Confidence-driven pattern fixes (aggressive fixes for low confidence)
    2. Unambiguous fixes (always applied - clear OCR errors)
    3. Dictionary validation (tracks unknown words, doesn't block fixes)
    4. Custom wordlist support (anime names, romaji, etc.)

Key difference from the old cleanup.py:
    - OLD: Dictionary blocks fixes even when OCR is wrong
    - NEW: Confidence drives fix aggressiveness, dictionary just reports unknowns

The approach is:
    - LOW confidence = apply aggressive fixes (OCR is uncertain)
    - HIGH confidence = trust OCR, minimal fixes
    - Dictionary = report unknown words, don't block corrections
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    import enchant
    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False


@dataclass
class PostProcessConfig:
    """Configuration for post-processing."""
    # Confidence thresholds
    low_confidence_threshold: float = 60.0  # Apply aggressive fixes below this
    very_low_confidence_threshold: float = 40.0  # Apply extra aggressive fixes
    garbage_confidence_threshold: float = 35.0  # Lines below this are likely garbage

    # Fix categories
    enable_unambiguous_fixes: bool = True  # Always-apply fixes
    enable_confidence_fixes: bool = True  # Confidence-gated fixes
    enable_dictionary_validation: bool = True  # Track unknown words
    enable_garbage_detection: bool = True  # Detect and clean garbage OCR

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
    UNAMBIGUOUS_FIXES = {
        # I/l confusion in contractions
        "l'm": "I'm",
        "l've": "I've",
        "l'll": "I'll",
        "l'd": "I'd",
        "lt's": "It's",
        "lt'II": "It'll",
        "lt'Il": "It'll",
        "l'II": "I'll",
        "l'Il": "I'll",
        "lf": "If",
        "ln": "In",
        "ls": "Is",
        "lsn't": "Isn't",
        "lt": "It",
        "lts": "Its",
        "lf": "If",
        # Double-I confusion
        "II": "ll",  # Will handle in context
        "IIl": "Ill",
        "IIi": "Ili",
        # Common full words
        "l": "I",  # Standalone l → I (handled specially)
        # Pipe confusion (| read as I or l)
        "|": "I",
        "||": "ll",
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
        self._init_dictionary()
        self._load_custom_wordlist()
        self._init_patterns()

    def _init_dictionary(self):
        """Initialize spell-check dictionary."""
        self.dictionary = None
        if ENCHANT_AVAILABLE and self.config.enable_dictionary_validation:
            try:
                self.dictionary = enchant.Dict("en_US")
                # Add common subtitle words
                for word in self.COMMON_WORDS:
                    self.dictionary.add_to_session(word)
            except enchant.errors.DictNotFoundError:
                pass

    def _load_custom_wordlist(self):
        """Load custom wordlist from file."""
        self.custom_words: Set[str] = set()

        if self.config.custom_wordlist_path:
            path = Path(self.config.custom_wordlist_path)
            if path.is_file():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        for line in f:
                            word = line.strip()
                            if word and not word.startswith('#'):
                                self.custom_words.add(word)
                                # Also add to enchant dictionary
                                if self.dictionary:
                                    self.dictionary.add_to_session(word)
                except Exception:
                    pass

    def _init_patterns(self):
        """Compile regex patterns for efficient matching."""
        # Standalone 'l' that should be 'I'
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

        # Step 0: Detect and clean garbage OCR output
        if self.config.enable_garbage_detection:
            current_text = self._clean_garbage_from_text(current_text, result)
            if not current_text.strip():
                # Entire text was garbage
                result.text = ""
                result.was_modified = True
                return result

        # Step 1: Always apply unambiguous fixes
        if self.config.enable_unambiguous_fixes:
            current_text = self._apply_unambiguous_fixes(current_text, result)

        # Step 2: Apply confidence-gated fixes
        if self.config.enable_confidence_fixes:
            current_text = self._apply_confidence_fixes(
                current_text, confidence, result
            )

        # Step 3: Normalization
        current_text = self._apply_normalization(current_text, result)

        # Step 4: Dictionary validation (report, don't fix)
        if self.config.enable_dictionary_validation:
            result.unknown_words = self._find_unknown_words(current_text)

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

        These patterns are never valid English and always represent OCR errors.
        """
        # Apply direct replacements
        for wrong, right in self.UNAMBIGUOUS_FIXES.items():
            if wrong == 'l':
                continue  # Handle standalone l separately
            if wrong in text:
                count = text.count(wrong)
                text = text.replace(wrong, right)
                result.fixes_applied[f'{wrong}→{right}'] += count

        # Handle standalone 'l' → 'I' (word boundaries)
        matches = list(self.standalone_l_pattern.finditer(text))
        if matches:
            text = self.standalone_l_pattern.sub('I', text)
            result.fixes_applied['l→I (standalone)'] += len(matches)

        # Handle 'l' at sentence start
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

    def _apply_confidence_fixes(
        self,
        text: str,
        confidence: float,
        result: ProcessResult
    ) -> str:
        """
        Apply fixes based on OCR confidence level.

        Low confidence → aggressive fixes
        High confidence → trust OCR output
        """
        # Skip confidence fixes if confidence is high
        if confidence >= self.config.low_confidence_threshold:
            return text

        is_very_low = confidence < self.config.very_low_confidence_threshold

        # Apply rn → m fixes (common OCR confusion)
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

            # Skip if in custom wordlist
            if word in self.custom_words or word.lower() in self.custom_words:
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

        # Check custom wordlist first
        if word in self.custom_words or word.lower() in self.custom_words:
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

        # Custom words always valid
        if word in self.custom_words or word.lower() in self.custom_words:
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
        low_confidence_threshold=settings_dict.get('ocr_low_confidence_threshold', 60.0),
        normalize_ellipsis=settings_dict.get('ocr_cleanup_normalize_ellipsis', False),
        custom_wordlist_path=Path(custom_path) if custom_path else None,
    )

    return OCRPostProcessor(config)
