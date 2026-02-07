# vsg_core/subtitles/ocr/postprocess.py
"""
OCR Post-Processing and Text Correction

Applies corrections from user-managed lists and dictionaries:
    1. Replacement rules from replacements.json (user-configurable patterns)
    2. Subtitle Edit OCR corrections (from SE dictionary XML files)
    3. Confidence-gated rules (user rules that only apply at low confidence)
    4. Dictionary validation (reports unknown words)

All correction patterns are managed through the UI and stored in .config/ocr/.
No hardcoded fix patterns — the user controls what gets corrected.
"""

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .dictionaries import get_dictionaries
from .subtitle_edit import (
    SubtitleEditCorrector,
    SubtitleEditParser,
    load_se_config,
)

logger = logging.getLogger(__name__)

try:
    import enchant

    ENCHANT_AVAILABLE = True
except ImportError:
    ENCHANT_AVAILABLE = False


@dataclass(slots=True)
class PostProcessConfig:
    """Configuration for post-processing."""

    # Master switch - disables all fixes when False
    cleanup_enabled: bool = True

    # Confidence thresholds
    low_confidence_threshold: float = 60.0  # Confidence-gated rules apply below this
    garbage_confidence_threshold: float = 35.0  # Lines below this are likely garbage

    # Fix categories (only apply if cleanup_enabled is True)
    enable_unambiguous_fixes: bool = True  # User replacement rules (always applied)
    enable_confidence_fixes: bool = True  # Confidence-gated user rules
    enable_dictionary_validation: bool = True  # Track unknown words
    enable_garbage_detection: bool = True  # Detect and clean garbage OCR

    # Subtitle Edit integration
    enable_subtitle_edit: bool = True  # Use Subtitle Edit dictionaries

    # Custom wordlist
    custom_wordlist_path: Path | None = None


@dataclass(slots=True)
class ProcessResult:
    """Result of post-processing."""

    text: str
    original_text: str
    unknown_words: list[str] = field(default_factory=list)
    fixes_applied: dict[str, int] = field(default_factory=dict)
    was_modified: bool = False


@dataclass(slots=True)
class UnknownWordInfo:
    """Information about an unknown word."""

    word: str
    context: str  # Surrounding text
    confidence: float
    suggestions: list[str] = field(default_factory=list)


class OCRPostProcessor:
    """
    Post-processes OCR text using user-managed correction lists.

    Corrections come from:
    - User replacement rules (replacements.json, managed via UI)
    - Subtitle Edit OCR fix lists (XML files)
    - Confidence-gated rules (user rules applied only at low confidence)
    - Dictionary validation (Enchant + user dictionaries for unknown word reporting)
    """

    def __init__(self, config: PostProcessConfig | None = None):
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
        logger.debug(
            f"Romaji dictionary: {romaji_stats.get('word_count', 0)} words "
            f"from {romaji_stats.get('dict_path', 'N/A')}"
        )

        # ValidationManager will be initialized after spell checker is ready
        self.validation_manager = None

    def _init_spell_checker(self):
        """Initialize spell-check dictionary and ValidationManager."""
        self.dictionary = None
        if ENCHANT_AVAILABLE and self.config.enable_dictionary_validation:
            try:
                self.dictionary = enchant.Dict("en_US")
                # Add user dictionary words and names
                for word in self.all_custom_words:
                    self.dictionary.add_to_session(word)
            except enchant.errors.DictNotFoundError:
                logger.warning(
                    "[OCR] Enchant dictionary not found, spell checking disabled"
                )

        # Initialize ValidationManager with spell checker
        self.validation_manager = self.ocr_dicts.init_validation_manager(
            self.dictionary
        )

    def _init_patterns(self):
        """Compile regex patterns from user-defined replacement rules."""
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
                pattern = re.compile(r"\b" + re.escape(rule.pattern) + r"\b")
                self.word_boundary_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_start":
                pattern = re.compile(r"\b" + re.escape(rule.pattern))
                self.word_start_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_end":
                pattern = re.compile(re.escape(rule.pattern) + r"\b")
                self.word_end_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "word_middle":
                # Match pattern when not at word boundary
                pattern = re.compile(
                    r"(?<=[a-zA-Z])" + re.escape(rule.pattern) + r"(?=[a-zA-Z])"
                )
                self.word_middle_patterns[rule.pattern] = (pattern, rule.replacement)
            elif rule.rule_type == "regex":
                try:
                    pattern = re.compile(rule.pattern)
                    self.regex_patterns[rule.pattern] = (pattern, rule.replacement)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern '{rule.pattern}': {e}")

        # Garbage detection patterns
        self.garbage_pattern = re.compile(
            r'^[A-Z0-9\s\(\)\[\]\-\.,;:!?\'"~]+$'  # All caps/numbers/punctuation
        )
        # Pattern for sequences of short "words" (1-2 chars each)
        self.short_word_sequence = re.compile(
            r"(?:\b[A-Z]{1,2}\b\s*){3,}"  # 3+ consecutive 1-2 char uppercase "words"
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

            # Add SE valid words to spell checker first (before creating corrector)
            if self.dictionary:
                for word in self.se_dicts.get_all_valid_words():
                    self.dictionary.add_to_session(word)

            # Create corrector with ValidationManager for unified validation
            self.se_corrector = SubtitleEditCorrector(
                self.se_dicts,
                self.dictionary,
                validation_manager=self.validation_manager,
            )

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
        self, text: str, confidence: float = 100.0, timestamp: str = ""
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

        # Step 1: Detect and clean garbage OCR output
        if self.config.enable_garbage_detection:
            current_text = self._clean_garbage_from_text(current_text, result)
            if not current_text.strip():
                # Entire text was garbage
                result.text = ""
                result.was_modified = True
                return result

        # Step 2: Apply user replacement rules
        if self.config.enable_unambiguous_fixes:
            current_text = self._apply_replacement_rules(current_text, result)

        # Step 3: Apply Subtitle Edit corrections
        if self.config.enable_subtitle_edit and self.se_corrector:
            current_text = self._apply_subtitle_edit_fixes(current_text, result)

        # Step 4: Apply confidence-gated user rules
        if self.config.enable_confidence_fixes:
            current_text = self._apply_confidence_rules(
                current_text, confidence, result
            )

        # Step 5: Dictionary validation (report, don't fix)
        if self.config.enable_dictionary_validation:
            dict_unknown = self._find_unknown_words(current_text)
            # Merge with SE unknown words (dedupe)
            all_unknown = set(result.unknown_words)
            all_unknown.update(dict_unknown)
            result.unknown_words = list(all_unknown)

        result.text = current_text
        result.was_modified = current_text != text

        # Log summary if we made changes or found issues
        if result.was_modified or result.unknown_words:
            self._log_process_summary(result, timestamp)

        return result

    def _log_process_summary(self, result: ProcessResult, timestamp: str = ""):
        """Log a summary of processing results."""
        parts = []

        # Fixes applied
        if result.fixes_applied:
            total_fixes = sum(result.fixes_applied.values())
            parts.append(f"{total_fixes} fixes")

        # Unknown words
        if result.unknown_words:
            unknown_preview = result.unknown_words[:3]
            if len(result.unknown_words) > 3:
                unknown_preview.append(f"+{len(result.unknown_words) - 3}")
            parts.append(
                f"{len(result.unknown_words)} unknown: {', '.join(unknown_preview)}"
            )

        # ValidationManager stats (if tracked)
        if (
            self.validation_manager
            and self.validation_manager._stats.total_validated > 0
        ):
            stats = self.validation_manager._stats
            source_parts = [f"{count} {src}" for src, count in stats.by_source.items()]
            if source_parts:
                parts.append(f"validated: {', '.join(source_parts)}")

        if parts:
            ts_prefix = f"[{timestamp}] " if timestamp else ""
            logger.info(f"[OCR] {ts_prefix}{'; '.join(parts)}")

    def _apply_replacement_rules(self, text: str, result: ProcessResult) -> str:
        """
        Apply user-defined replacement rules from replacements.json.

        Rules are managed via the dictionary editor UI.
        """
        # Apply literal replacements (exact string match)
        for rule in self.literal_rules:
            if rule.pattern in text:
                count = text.count(rule.pattern)
                text = text.replace(rule.pattern, rule.replacement)
                result.fixes_applied[f"{rule.pattern}→{rule.replacement}"] += count

        # Apply word-boundary replacements
        for pattern_str, (pattern, replacement) in self.word_boundary_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f"{pattern_str}→{replacement}"] += len(matches)

        # Apply word-start replacements
        for pattern_str, (pattern, replacement) in self.word_start_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f"{pattern_str}→{replacement} (word start)"] += (
                    len(matches)
                )

        # Apply word-end replacements
        for pattern_str, (pattern, replacement) in self.word_end_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f"{pattern_str}→{replacement} (word end)"] += len(
                    matches
                )

        # Apply regex replacements
        for pattern_str, (pattern, replacement) in self.regex_patterns.items():
            matches = list(pattern.finditer(text))
            if matches:
                text = pattern.sub(replacement, text)
                result.fixes_applied[f"regex:{pattern_str}"] += len(matches)

        return text

    def _apply_subtitle_edit_fixes(self, text: str, result: ProcessResult) -> str:
        """
        Apply Subtitle Edit OCR corrections.

        These are applied after user's custom rules, so user rules take precedence.
        """
        if not self.se_corrector:
            return text

        try:
            corrected_text, fixes, _ = self.se_corrector.apply_corrections(text)

            # Track fixes applied
            for fix in fixes:
                result.fixes_applied[f"SE:{fix}"] += 1

            return corrected_text

        except Exception as e:
            logger.warning(f"Error applying Subtitle Edit fixes: {e}")
            return text

    def _apply_confidence_rules(
        self, text: str, confidence: float, result: ProcessResult
    ) -> str:
        """
        Apply confidence-gated user rules.

        Only applies replacement rules marked as confidence_gated when OCR
        confidence is below the threshold. High confidence = trust OCR output.
        """
        # Skip if confidence is high enough
        if confidence >= self.config.low_confidence_threshold:
            return text

        # Apply confidence-gated rules from user's database
        for rule in self.confidence_gated_rules:
            if rule.rule_type == "word_middle":
                pattern = re.compile(
                    r"(?<=[a-zA-Z])" + re.escape(rule.pattern) + r"(?=[a-zA-Z])"
                )
                new_text = pattern.sub(rule.replacement, text)
            elif rule.rule_type == "word":
                pattern = re.compile(r"\b" + re.escape(rule.pattern) + r"\b")
                new_text = pattern.sub(rule.replacement, text)
            elif rule.rule_type == "literal":
                new_text = text.replace(rule.pattern, rule.replacement)
            else:
                continue

            if new_text != text:
                result.fixes_applied[
                    f"{rule.pattern}→{rule.replacement} (low conf)"
                ] += 1
                text = new_text

        return text

    def _find_unknown_words(self, text: str, track_stats: bool = True) -> list[str]:
        """
        Find words not in dictionary.

        These are reported but not "fixed" - they may be:
        - Names (character names, place names)
        - Foreign words (romaji, etc.)
        - OCR errors that weren't caught by patterns
        - Technical terms

        Uses ValidationManager for unified checking across all word lists.
        """
        if not self.dictionary and not self.validation_manager:
            return []

        unknown = []
        # Extract words (alphanumeric, apostrophes allowed)
        word_pattern = re.compile(r"[A-Za-z][A-Za-z']*[A-Za-z]|[A-Za-z]")

        for match in word_pattern.finditer(text):
            word = match.group()

            # Skip common contractions that might not be in dict
            if "'" in word:
                continue

            # Skip short words (likely valid)
            if len(word) <= 2:
                continue

            # Use ValidationManager for unified checking
            if self.validation_manager:
                vresult = self.validation_manager.is_known_word(
                    word, track_stats=track_stats
                )
                if vresult.is_known:
                    continue
            else:
                # Fallback to legacy checking
                if self.ocr_dicts.is_known_word(word, check_romaji=True):
                    continue
                if self.se_corrector and self.se_corrector.is_valid_word(word):
                    continue

            # Check dictionary as final fallback
            if not self._is_valid_word(word):
                unknown.append(word)
                if track_stats and self.validation_manager:
                    self.validation_manager._stats.add_unknown(word)

        return list(set(unknown))  # Remove duplicates

    def _is_valid_word(self, word: str) -> bool:
        """Check if word is valid according to dictionary."""
        if not self.dictionary and not self.validation_manager:
            return True

        # Use ValidationManager if available
        if self.validation_manager:
            vresult = self.validation_manager.is_known_word(word)
            if vresult.is_known:
                return True
        else:
            # Fallback to legacy checking
            if self.ocr_dicts.is_known_word(word, check_romaji=True):
                return True
            if self.se_corrector and self.se_corrector.is_valid_word(word):
                return True

        # Check dictionary
        if self.dictionary:
            if self.dictionary.check(word):
                return True
            if self.dictionary.check(word.lower()):
                return True
            if self.dictionary.check(word.capitalize()):
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
                space_ratio = text.count(" ") / len(text)
                if space_ratio > 0.3:  # More than 30% spaces
                    return True

        return False

    def _clean_garbage_from_text(
        self,
        text: str,
        result: ProcessResult,
        line_confidences: list[float] | None = None,
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
        lines = text.split("\\N")

        if len(lines) == 1:
            # Single line - check if entire thing is garbage
            if self._is_garbage_line(
                text, line_confidences[0] if line_confidences else 100.0
            ):
                result.fixes_applied["garbage line removed"] += 1
                return ""
            return text

        # Multi-line - check each line
        clean_lines = []
        for i, line in enumerate(lines):
            conf = (
                line_confidences[i]
                if line_confidences and i < len(line_confidences)
                else 100.0
            )

            if self._is_garbage_line(line, conf):
                result.fixes_applied["garbage line removed"] += 1
                continue

            # Also remove short garbage-like fragments
            line = self._remove_garbage_fragments(line, result)
            if line.strip():
                clean_lines.append(line)

        return "\\N".join(clean_lines)

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
            rest = text[len(garbage) :].strip()
            # Check if the rest looks like valid text
            if rest and not self._is_garbage_line(rest):
                result.fixes_applied["garbage prefix removed"] += 1
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
    custom_path = settings_dict.get("ocr_custom_wordlist_path", "")

    config = PostProcessConfig(
        cleanup_enabled=settings_dict.get("ocr_cleanup_enabled", True),
        low_confidence_threshold=settings_dict.get(
            "ocr_low_confidence_threshold", 60.0
        ),
        custom_wordlist_path=Path(custom_path) if custom_path else None,
    )

    return OCRPostProcessor(config)
