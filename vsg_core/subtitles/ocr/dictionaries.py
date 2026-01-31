# vsg_core/subtitles/ocr/dictionaries.py
"""
OCR Dictionary Management

Manages databases for OCR text correction:
    1. replacements.json - Pattern-based character/word replacements
    2. user_dictionary.txt - User's custom valid words
    3. names.txt - Proper names (characters, places, etc.)
    4. romaji_dictionary.txt - Japanese romanization words

Now integrates with ValidationManager for unified word validation
across all OCR components.

Features:
    - Atomic writes (write to temp, then rename)
    - Automatic backups before changes
    - Duplicate prevention
    - Import/export functions
    - ValidationManager integration for unified validation
"""

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy import to avoid circular dependency
_romaji_dict = None


class RuleType(Enum):
    """Types of replacement rules."""

    LITERAL = "literal"  # Exact match anywhere in text
    WORD = "word"  # Match whole word only (word boundaries)
    WORD_START = "word_start"  # Match at start of word
    WORD_END = "word_end"  # Match at end of word
    WORD_MIDDLE = "word_middle"  # Match inside word only
    REGEX = "regex"  # Full regex pattern


@dataclass
class ReplacementRule:
    """A single replacement rule."""

    pattern: str
    replacement: str
    rule_type: str = "literal"  # RuleType value as string
    confidence_gated: bool = False  # Only apply when confidence is low
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "pattern": self.pattern,
            "replacement": self.replacement,
            "type": self.rule_type,
            "confidence_gated": self.confidence_gated,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReplacementRule":
        """Create from dictionary."""
        return cls(
            pattern=data.get("pattern", ""),
            replacement=data.get("replacement", ""),
            rule_type=data.get("type", "literal"),
            confidence_gated=data.get("confidence_gated", False),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
        )


# Default replacement rules - empty by default, SE OCR fix list provides comprehensive coverage
# Users can add custom rules as needed via the UI
DEFAULT_REPLACEMENT_RULES = []


class OCRDictionaries:
    """
    Manages OCR correction dictionaries.

    Provides atomic file operations, backups, and duplicate prevention.
    """

    @staticmethod
    def _find_config_dir() -> Path:
        """
        Find the OCR config directory.

        Searches in order:
        1. Current working directory .config/ocr/
        2. __file__ based project root .config/ocr/
        3. Creates in cwd if none found
        """
        candidates = []

        # 1. Current working directory (most reliable for running apps)
        cwd_config = Path.cwd() / ".config" / "ocr"
        candidates.append(cwd_config)

        # 2. __file__ based (4 levels up from this file)
        try:
            file_based = Path(__file__).parent.parent.parent.parent / ".config" / "ocr"
            candidates.append(file_based)
        except Exception:
            pass

        # 3. Check if any candidate has existing dictionary files
        for candidate in candidates:
            if candidate.exists():
                # Check if it has any of our files
                if (
                    (candidate / "replacements.json").exists()
                    or (candidate / "user_dictionary.txt").exists()
                    or (candidate / "romaji_dictionary.txt").exists()
                ):
                    logger.info(f"[OCR] Found existing config at: {candidate}")
                    return candidate

        # 4. If no existing config found, use cwd-based path
        logger.info(f"[OCR] Creating new config dir at: {cwd_config}")
        return cwd_config

    def __init__(self, config_dir: Path | None = None):
        """
        Initialize dictionary manager.

        Args:
            config_dir: Directory for database files. Defaults to .config/ocr/
        """
        if config_dir is None:
            config_dir = self._find_config_dir()

        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[OCR] Using config dir: {self.config_dir}")

        # File paths
        self.replacements_path = self.config_dir / "replacements.json"
        self.user_dict_path = self.config_dir / "user_dictionary.txt"
        self.names_path = self.config_dir / "names.txt"

        # Cached data
        self._replacements: list[ReplacementRule] = []
        self._user_words: set[str] = set()
        self._names: set[str] = set()
        self._romaji_dict = None  # Lazy-loaded romaji dictionary

        # ValidationManager integration (lazy loaded)
        self._validation_manager = None

        # Load or create defaults
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Ensure default files exist."""
        # Create replacements.json with defaults if not exists
        if not self.replacements_path.exists():
            self._save_replacements_internal(DEFAULT_REPLACEMENT_RULES)
            logger.info(
                f"Created default replacements.json with {len(DEFAULT_REPLACEMENT_RULES)} rules"
            )

        # Create empty dictionary files if not exist
        if not self.user_dict_path.exists():
            self.user_dict_path.write_text(
                "# User Dictionary - one word per line\n# Words here won't be flagged as unknown\n",
                encoding="utf-8",
            )

        if not self.names_path.exists():
            self.names_path.write_text(
                "# Names Dictionary - one name per line\n# Character names, places, etc.\n",
                encoding="utf-8",
            )

    # =========================================================================
    # Replacements
    # =========================================================================

    def load_replacements(self) -> list[ReplacementRule]:
        """Load replacement rules from JSON file."""
        if self._replacements:
            return self._replacements

        try:
            if self.replacements_path.exists():
                data = json.loads(self.replacements_path.read_text(encoding="utf-8"))
                rules = data.get("rules", [])
                self._replacements = [ReplacementRule.from_dict(r) for r in rules]
                logger.debug(f"Loaded {len(self._replacements)} replacement rules")
            else:
                self._replacements = list(DEFAULT_REPLACEMENT_RULES)
        except Exception as e:
            logger.error(f"Error loading replacements: {e}")
            self._replacements = list(DEFAULT_REPLACEMENT_RULES)

        return self._replacements

    def save_replacements(self, rules: list[ReplacementRule]) -> bool:
        """
        Save replacement rules to JSON file.

        Creates backup before saving, uses atomic write.
        """
        # Create backup
        self._backup_file(self.replacements_path)

        # Save with atomic write
        success = self._save_replacements_internal(rules)
        if success:
            self._replacements = rules

        return success

    def _save_replacements_internal(self, rules: list[ReplacementRule]) -> bool:
        """Internal save without backup (for initial creation)."""
        try:
            data = {"version": 1, "rules": [r.to_dict() for r in rules]}

            # Atomic write: write to temp, then rename
            fd, temp_path = tempfile.mkstemp(suffix=".json", dir=self.config_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                shutil.move(temp_path, self.replacements_path)
                logger.debug(f"Saved {len(rules)} replacement rules")
                return True
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.error(f"Error saving replacements: {e}")
            return False

    def add_replacement(self, rule: ReplacementRule) -> tuple[bool, str]:
        """
        Add a replacement rule.

        Returns:
            (success, message) tuple
        """
        rules = self.load_replacements()

        # Check for duplicate pattern
        for existing in rules:
            if (
                existing.pattern == rule.pattern
                and existing.rule_type == rule.rule_type
            ):
                return False, f"Rule for pattern '{rule.pattern}' already exists"

        rules.append(rule)
        if self.save_replacements(rules):
            return True, "Rule added successfully"
        return False, "Failed to save rules"

    def remove_replacement(
        self, pattern: str, rule_type: str = None
    ) -> tuple[bool, str]:
        """Remove a replacement rule by pattern."""
        rules = self.load_replacements()
        original_count = len(rules)

        if rule_type:
            rules = [
                r
                for r in rules
                if not (r.pattern == pattern and r.rule_type == rule_type)
            ]
        else:
            rules = [r for r in rules if r.pattern != pattern]

        if len(rules) == original_count:
            return False, f"Pattern '{pattern}' not found"

        if self.save_replacements(rules):
            return True, "Rule removed successfully"
        return False, "Failed to save rules"

    def update_replacement(
        self, old_pattern: str, new_rule: ReplacementRule
    ) -> tuple[bool, str]:
        """Update an existing replacement rule."""
        rules = self.load_replacements()

        for i, rule in enumerate(rules):
            if rule.pattern == old_pattern:
                rules[i] = new_rule
                if self.save_replacements(rules):
                    return True, "Rule updated successfully"
                return False, "Failed to save rules"

        return False, f"Pattern '{old_pattern}' not found"

    # =========================================================================
    # User Dictionary
    # =========================================================================

    def load_user_dictionary(self) -> set[str]:
        """Load user dictionary words."""
        if self._user_words:
            return self._user_words

        self._user_words = self._load_wordlist(self.user_dict_path)
        return self._user_words

    def save_user_dictionary(self, words: set[str]) -> bool:
        """Save user dictionary."""
        self._backup_file(self.user_dict_path)
        success = self._save_wordlist(self.user_dict_path, words, "User Dictionary")
        if success:
            self._user_words = words
        return success

    def add_user_word(self, word: str) -> tuple[bool, str]:
        """Add a word to user dictionary."""
        word = word.strip()
        if not word:
            return False, "Word cannot be empty"

        words = self.load_user_dictionary()
        if word.lower() in {w.lower() for w in words}:
            return False, f"Word '{word}' already exists"

        words.add(word)
        if self.save_user_dictionary(words):
            return True, f"Added '{word}'"
        return False, "Failed to save dictionary"

    def remove_user_word(self, word: str) -> tuple[bool, str]:
        """Remove a word from user dictionary."""
        words = self.load_user_dictionary()
        word_lower = word.lower()

        # Find and remove (case-insensitive)
        to_remove = None
        for w in words:
            if w.lower() == word_lower:
                to_remove = w
                break

        if to_remove is None:
            return False, f"Word '{word}' not found"

        words.discard(to_remove)
        if self.save_user_dictionary(words):
            return True, f"Removed '{to_remove}'"
        return False, "Failed to save dictionary"

    # =========================================================================
    # Names Dictionary
    # =========================================================================

    def load_names(self) -> set[str]:
        """Load names dictionary."""
        if self._names:
            return self._names

        self._names = self._load_wordlist(self.names_path)
        return self._names

    def save_names(self, names: set[str]) -> bool:
        """Save names dictionary."""
        self._backup_file(self.names_path)
        success = self._save_wordlist(self.names_path, names, "Names Dictionary")
        if success:
            self._names = names
        return success

    def add_name(self, name: str) -> tuple[bool, str]:
        """Add a name to names dictionary."""
        name = name.strip()
        if not name:
            return False, "Name cannot be empty"

        names = self.load_names()
        if name.lower() in {n.lower() for n in names}:
            return False, f"Name '{name}' already exists"

        names.add(name)
        if self.save_names(names):
            return True, f"Added '{name}'"
        return False, "Failed to save names"

    def remove_name(self, name: str) -> tuple[bool, str]:
        """Remove a name from names dictionary."""
        names = self.load_names()
        name_lower = name.lower()

        to_remove = None
        for n in names:
            if n.lower() == name_lower:
                to_remove = n
                break

        if to_remove is None:
            return False, f"Name '{name}' not found"

        names.discard(to_remove)
        if self.save_names(names):
            return True, f"Removed '{to_remove}'"
        return False, "Failed to save names"

    # =========================================================================
    # Import/Export
    # =========================================================================

    def import_replacements(self, file_path: Path) -> tuple[int, int, list[str]]:
        """
        Import replacement rules from a text file.

        Format: pattern|replacement|type|confidence_gated
        Example: l'm|I'm|literal|false

        Returns:
            (added_count, skipped_count, errors)
        """
        added = 0
        skipped = 0
        errors = []

        try:
            lines = Path(file_path).read_text(encoding="utf-8").splitlines()

            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split("|")
                if len(parts) < 2:
                    errors.append(
                        f"Line {line_num}: Invalid format (need at least pattern|replacement)"
                    )
                    continue

                pattern = parts[0]
                replacement = parts[1]
                rule_type = parts[2] if len(parts) > 2 else "literal"
                confidence_gated = (
                    parts[3].lower() == "true" if len(parts) > 3 else False
                )

                # Validate rule type
                valid_types = [t.value for t in RuleType]
                if rule_type not in valid_types:
                    errors.append(
                        f"Line {line_num}: Invalid type '{rule_type}' (use: {', '.join(valid_types)})"
                    )
                    continue

                rule = ReplacementRule(
                    pattern=pattern,
                    replacement=replacement,
                    rule_type=rule_type,
                    confidence_gated=confidence_gated,
                )

                success, msg = self.add_replacement(rule)
                if success:
                    added += 1
                else:
                    skipped += 1

        except Exception as e:
            errors.append(f"Error reading file: {e}")

        return added, skipped, errors

    def export_replacements(self, file_path: Path) -> bool:
        """Export replacement rules to text file."""
        try:
            rules = self.load_replacements()
            lines = [
                "# OCR Replacement Rules",
                "# Format: pattern|replacement|type|confidence_gated",
                "",
            ]

            for rule in rules:
                if rule.enabled:
                    lines.append(
                        f"{rule.pattern}|{rule.replacement}|{rule.rule_type}|{str(rule.confidence_gated).lower()}"
                    )

            Path(file_path).write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Error exporting replacements: {e}")
            return False

    def import_wordlist(self, file_path: Path, target: str = "user") -> tuple[int, int]:
        """
        Import words from a text file (one word per line).

        Args:
            file_path: Path to text file
            target: "user" or "names"

        Returns:
            (added_count, skipped_count)
        """
        added = 0
        skipped = 0

        try:
            lines = Path(file_path).read_text(encoding="utf-8").splitlines()

            for line in lines:
                word = line.strip()
                if not word or word.startswith("#"):
                    continue

                if target == "names":
                    success, _ = self.add_name(word)
                else:
                    success, _ = self.add_user_word(word)

                if success:
                    added += 1
                else:
                    skipped += 1

        except Exception as e:
            logger.error(f"Error importing wordlist: {e}")

        return added, skipped

    def export_wordlist(self, file_path: Path, target: str = "user") -> bool:
        """Export wordlist to text file."""
        try:
            if target == "names":
                words = self.load_names()
                header = "# Names Dictionary"
            else:
                words = self.load_user_dictionary()
                header = "# User Dictionary"

            lines = [header, ""]
            lines.extend(sorted(words, key=str.lower))

            Path(file_path).write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Error exporting wordlist: {e}")
            return False

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _load_wordlist(self, path: Path) -> set[str]:
        """Load a wordlist from file."""
        words = set()
        try:
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    word = line.strip()
                    if word and not word.startswith("#"):
                        words.add(word)
        except Exception as e:
            logger.error(f"Error loading wordlist {path}: {e}")
        return words

    def _save_wordlist(self, path: Path, words: set[str], header: str) -> bool:
        """Save a wordlist to file with atomic write."""
        try:
            lines = [f"# {header} - one word per line", ""]
            lines.extend(sorted(words, key=str.lower))

            # Atomic write
            fd, temp_path = tempfile.mkstemp(suffix=".txt", dir=self.config_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                shutil.move(temp_path, path)
                return True
            except Exception:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.error(f"Error saving wordlist {path}: {e}")
            return False

    def _backup_file(self, path: Path):
        """Create a backup of a file before modifying."""
        if path.exists():
            backup_path = path.with_suffix(path.suffix + ".bak")
            try:
                shutil.copy2(path, backup_path)
            except Exception as e:
                logger.warning(f"Could not create backup of {path}: {e}")

    def reload(self):
        """Force reload all dictionaries from disk."""
        self._replacements = []
        self._user_words = set()
        self._names = set()
        # Reset romaji dictionary so it reloads on next access
        if self._romaji_dict is not None:
            self._romaji_dict._words = None
        self._romaji_dict = None
        self.load_replacements()
        self.load_user_dictionary()
        self.load_names()
        logger.info(f"Reloaded all dictionaries from {self.config_dir}")

    def is_known_word(
        self, word: str, check_romaji: bool = True, track_stats: bool = False
    ) -> bool:
        """
        Check if a word is known (in any dictionary).

        Uses ValidationManager if initialized, otherwise falls back to
        direct checking of user dictionary, names, and romaji.

        Args:
            word: Word to check
            check_romaji: Whether to also check romaji dictionary
            track_stats: Whether to track validation statistics

        Returns:
            True if word is known
        """
        # Use ValidationManager if available
        if self._validation_manager is not None:
            result = self._validation_manager.is_known_word(
                word, track_stats=track_stats
            )
            return result.is_known

        # Fallback to direct checking (backward compatibility)
        word_lower = word.lower()
        user_words = self.load_user_dictionary()
        names = self.load_names()

        # Check user dictionary and names
        if word_lower in {w.lower() for w in user_words}:
            return True
        if word_lower in {n.lower() for n in names}:
            return True

        # Check romaji dictionary (last, after other dictionaries)
        if check_romaji:
            romaji_dict = self._get_romaji_dictionary()
            romaji_words = romaji_dict.load()
            if word_lower in romaji_words:
                logger.debug(f"Word '{word}' found in romaji dictionary")
                return True

        return False

    def is_protected_word(self, word: str) -> bool:
        """
        Check if a word is protected from auto-fixing.

        Uses ValidationManager if initialized.

        Args:
            word: Word to check

        Returns:
            True if word should not be auto-fixed
        """
        if self._validation_manager is not None:
            return self._validation_manager.is_protected_word(word)

        # Fallback: any known word is protected
        return self.is_known_word(word, check_romaji=True)

    def is_valid_fix_result(self, word: str) -> bool:
        """
        Check if a word is a valid result for an OCR fix.

        Uses ValidationManager if initialized.

        Args:
            word: Word to check

        Returns:
            True if word is acceptable as a fix result
        """
        if self._validation_manager is not None:
            return self._validation_manager.is_valid_fix_result(word)

        # Fallback: any known word except romaji-only words
        word_lower = word.lower()

        # Check user dictionary and names first (these are valid fix results)
        user_words = self.load_user_dictionary()
        names = self.load_names()
        if word_lower in {w.lower() for w in user_words}:
            return True
        if word_lower in {n.lower() for n in names}:
            return True

        # Romaji words are NOT valid fix results (OCR wouldn't produce Japanese)
        # So we don't check romaji here
        return False

    # =========================================================================
    # ValidationManager Integration
    # =========================================================================

    def get_validation_manager(self):
        """Get the ValidationManager instance, initializing if needed."""
        if self._validation_manager is None:
            from .word_lists import initialize_validation_manager

            self._validation_manager = initialize_validation_manager(self.config_dir)
        return self._validation_manager

    def set_validation_manager(self, manager):
        """Set the ValidationManager instance (for external initialization)."""
        self._validation_manager = manager

    def init_validation_manager(self, spell_checker=None):
        """
        Initialize the ValidationManager with all word lists.

        Args:
            spell_checker: Optional Enchant spell checker instance

        Returns:
            Initialized ValidationManager
        """
        from .word_lists import initialize_validation_manager

        self._validation_manager = initialize_validation_manager(
            self.config_dir, spell_checker=spell_checker
        )
        return self._validation_manager

    # =========================================================================
    # Romaji Dictionary
    # =========================================================================

    def _get_romaji_dictionary(self):
        """Get romaji dictionary instance (lazy loading)."""
        if self._romaji_dict is None:
            from .romaji_dictionary import RomajiDictionary

            self._romaji_dict = RomajiDictionary(self.config_dir)
        return self._romaji_dict

    def load_romaji_dictionary(self) -> set[str]:
        """Load romaji dictionary words."""
        return self._get_romaji_dictionary().load()

    def is_romaji_word(self, word: str) -> bool:
        """
        Check if a word is a valid romaji (Japanese romanization) word.

        Args:
            word: Word to check

        Returns:
            True if word is in romaji dictionary
        """
        return self._get_romaji_dictionary().is_valid_word(word)

    def build_romaji_dictionary(self, progress_callback=None) -> tuple[bool, str]:
        """
        Build romaji dictionary from JMdict.

        Downloads JMdict if not cached, parses it, and saves the romaji wordlist.

        Args:
            progress_callback: Optional callback(status, current, total)

        Returns:
            (success, message) tuple
        """
        return self._get_romaji_dictionary().build_dictionary(progress_callback)

    def get_romaji_stats(self) -> dict:
        """Get romaji dictionary statistics."""
        return self._get_romaji_dictionary().get_stats()


# Global instance for convenience
_dictionaries: OCRDictionaries | None = None


def get_dictionaries(config_dir: Path | None = None) -> OCRDictionaries:
    """Get or create the global dictionaries instance."""
    global _dictionaries
    if _dictionaries is None or config_dir is not None:
        _dictionaries = OCRDictionaries(config_dir)
    return _dictionaries
