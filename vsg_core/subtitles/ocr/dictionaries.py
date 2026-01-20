# vsg_core/subtitles/ocr/dictionaries.py
# -*- coding: utf-8 -*-
"""
OCR Dictionary Management

Manages three databases for OCR text correction:
    1. replacements.json - Pattern-based character/word replacements
    2. user_dictionary.txt - User's custom valid words
    3. names.txt - Proper names (characters, places, etc.)

Features:
    - Atomic writes (write to temp, then rename)
    - Automatic backups before changes
    - Duplicate prevention
    - Import/export functions
"""

import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class RuleType(Enum):
    """Types of replacement rules."""
    LITERAL = "literal"          # Exact match anywhere in text
    WORD = "word"                # Match whole word only (word boundaries)
    WORD_START = "word_start"    # Match at start of word
    WORD_END = "word_end"        # Match at end of word
    WORD_MIDDLE = "word_middle"  # Match inside word only
    REGEX = "regex"              # Full regex pattern


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


# Default replacement rules - migrated from hardcoded postprocess.py
DEFAULT_REPLACEMENT_RULES = [
    # I/l confusion in contractions - always safe
    ReplacementRule("l'm", "I'm", "literal", description="l→I in I'm"),
    ReplacementRule("l've", "I've", "literal", description="l→I in I've"),
    ReplacementRule("l'll", "I'll", "literal", description="l→I in I'll"),
    ReplacementRule("l'd", "I'd", "literal", description="l→I in I'd"),
    ReplacementRule("lt's", "It's", "literal", description="l→I in It's"),
    ReplacementRule("lt'II", "It'll", "literal", description="II→ll in It'll"),
    ReplacementRule("lt'Il", "It'll", "literal", description="Il→ll in It'll"),
    ReplacementRule("l'II", "I'll", "literal", description="II→ll in I'll"),
    ReplacementRule("l'Il", "I'll", "literal", description="Il→ll in I'll"),
    ReplacementRule("lsn't", "Isn't", "literal", description="l→I in Isn't"),

    # Double-I confusion
    ReplacementRule("IIl", "Ill", "literal", description="II→Il in Ill"),
    ReplacementRule("IIi", "Ili", "literal", description="II→Il"),

    # Pipe confusion
    ReplacementRule("|", "I", "literal", description="pipe→I"),
    ReplacementRule("||", "ll", "literal", description="double pipe→ll"),

    # Word boundary fixes - match whole word only
    ReplacementRule("lf", "If", "word", description="l→I at word start"),
    ReplacementRule("ln", "In", "word", description="l→I at word start"),
    ReplacementRule("ls", "Is", "word", description="l→I at word start"),
    ReplacementRule("lt", "It", "word", description="l→I at word start"),
    ReplacementRule("lts", "Its", "word", description="l→I at word start"),
    ReplacementRule("l", "I", "word", description="Standalone l→I"),

    # Confidence-gated fixes - only apply when OCR confidence is low
    ReplacementRule("rn", "m", "word_middle", confidence_gated=True, description="rn→m confusion"),
]


class OCRDictionaries:
    """
    Manages OCR correction dictionaries.

    Provides atomic file operations, backups, and duplicate prevention.
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        Initialize dictionary manager.

        Args:
            config_dir: Directory for database files. Defaults to .config/ocr/
        """
        if config_dir is None:
            # Default to project .config/ocr/
            project_root = Path(__file__).parent.parent.parent.parent
            config_dir = project_root / ".config" / "ocr"

        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # File paths
        self.replacements_path = self.config_dir / "replacements.json"
        self.user_dict_path = self.config_dir / "user_dictionary.txt"
        self.names_path = self.config_dir / "names.txt"

        # Cached data
        self._replacements: List[ReplacementRule] = []
        self._user_words: Set[str] = set()
        self._names: Set[str] = set()

        # Load or create defaults
        self._ensure_defaults()

    def _ensure_defaults(self):
        """Ensure default files exist."""
        # Create replacements.json with defaults if not exists
        if not self.replacements_path.exists():
            self._save_replacements_internal(DEFAULT_REPLACEMENT_RULES)
            logger.info(f"Created default replacements.json with {len(DEFAULT_REPLACEMENT_RULES)} rules")

        # Create empty dictionary files if not exist
        if not self.user_dict_path.exists():
            self.user_dict_path.write_text("# User Dictionary - one word per line\n# Words here won't be flagged as unknown\n", encoding="utf-8")

        if not self.names_path.exists():
            self.names_path.write_text("# Names Dictionary - one name per line\n# Character names, places, etc.\n", encoding="utf-8")

    # =========================================================================
    # Replacements
    # =========================================================================

    def load_replacements(self) -> List[ReplacementRule]:
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

    def save_replacements(self, rules: List[ReplacementRule]) -> bool:
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

    def _save_replacements_internal(self, rules: List[ReplacementRule]) -> bool:
        """Internal save without backup (for initial creation)."""
        try:
            data = {
                "version": 1,
                "rules": [r.to_dict() for r in rules]
            }

            # Atomic write: write to temp, then rename
            fd, temp_path = tempfile.mkstemp(suffix=".json", dir=self.config_dir)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
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

    def add_replacement(self, rule: ReplacementRule) -> Tuple[bool, str]:
        """
        Add a replacement rule.

        Returns:
            (success, message) tuple
        """
        rules = self.load_replacements()

        # Check for duplicate pattern
        for existing in rules:
            if existing.pattern == rule.pattern and existing.rule_type == rule.rule_type:
                return False, f"Rule for pattern '{rule.pattern}' already exists"

        rules.append(rule)
        if self.save_replacements(rules):
            return True, "Rule added successfully"
        return False, "Failed to save rules"

    def remove_replacement(self, pattern: str, rule_type: str = None) -> Tuple[bool, str]:
        """Remove a replacement rule by pattern."""
        rules = self.load_replacements()
        original_count = len(rules)

        if rule_type:
            rules = [r for r in rules if not (r.pattern == pattern and r.rule_type == rule_type)]
        else:
            rules = [r for r in rules if r.pattern != pattern]

        if len(rules) == original_count:
            return False, f"Pattern '{pattern}' not found"

        if self.save_replacements(rules):
            return True, "Rule removed successfully"
        return False, "Failed to save rules"

    def update_replacement(self, old_pattern: str, new_rule: ReplacementRule) -> Tuple[bool, str]:
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

    def load_user_dictionary(self) -> Set[str]:
        """Load user dictionary words."""
        if self._user_words:
            return self._user_words

        self._user_words = self._load_wordlist(self.user_dict_path)
        return self._user_words

    def save_user_dictionary(self, words: Set[str]) -> bool:
        """Save user dictionary."""
        self._backup_file(self.user_dict_path)
        success = self._save_wordlist(self.user_dict_path, words, "User Dictionary")
        if success:
            self._user_words = words
        return success

    def add_user_word(self, word: str) -> Tuple[bool, str]:
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

    def remove_user_word(self, word: str) -> Tuple[bool, str]:
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

    def load_names(self) -> Set[str]:
        """Load names dictionary."""
        if self._names:
            return self._names

        self._names = self._load_wordlist(self.names_path)
        return self._names

    def save_names(self, names: Set[str]) -> bool:
        """Save names dictionary."""
        self._backup_file(self.names_path)
        success = self._save_wordlist(self.names_path, names, "Names Dictionary")
        if success:
            self._names = names
        return success

    def add_name(self, name: str) -> Tuple[bool, str]:
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

    def remove_name(self, name: str) -> Tuple[bool, str]:
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

    def import_replacements(self, file_path: Path) -> Tuple[int, int, List[str]]:
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
                    errors.append(f"Line {line_num}: Invalid format (need at least pattern|replacement)")
                    continue

                pattern = parts[0]
                replacement = parts[1]
                rule_type = parts[2] if len(parts) > 2 else "literal"
                confidence_gated = parts[3].lower() == "true" if len(parts) > 3 else False

                # Validate rule type
                valid_types = [t.value for t in RuleType]
                if rule_type not in valid_types:
                    errors.append(f"Line {line_num}: Invalid type '{rule_type}' (use: {', '.join(valid_types)})")
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
            lines = ["# OCR Replacement Rules", "# Format: pattern|replacement|type|confidence_gated", ""]

            for rule in rules:
                if rule.enabled:
                    lines.append(f"{rule.pattern}|{rule.replacement}|{rule.rule_type}|{str(rule.confidence_gated).lower()}")

            Path(file_path).write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception as e:
            logger.error(f"Error exporting replacements: {e}")
            return False

    def import_wordlist(self, file_path: Path, target: str = "user") -> Tuple[int, int]:
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

    def _load_wordlist(self, path: Path) -> Set[str]:
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

    def _save_wordlist(self, path: Path, words: Set[str], header: str) -> bool:
        """Save a wordlist to file with atomic write."""
        try:
            lines = [f"# {header} - one word per line", ""]
            lines.extend(sorted(words, key=str.lower))

            # Atomic write
            fd, temp_path = tempfile.mkstemp(suffix=".txt", dir=self.config_dir)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
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
        self.load_replacements()
        self.load_user_dictionary()
        self.load_names()

    def is_known_word(self, word: str) -> bool:
        """Check if a word is in user dictionary or names."""
        word_lower = word.lower()
        user_words = self.load_user_dictionary()
        names = self.load_names()

        return (
            word_lower in {w.lower() for w in user_words} or
            word_lower in {n.lower() for n in names}
        )


# Global instance for convenience
_dictionaries: Optional[OCRDictionaries] = None


def get_dictionaries(config_dir: Optional[Path] = None) -> OCRDictionaries:
    """Get or create the global dictionaries instance."""
    global _dictionaries
    if _dictionaries is None or config_dir is not None:
        _dictionaries = OCRDictionaries(config_dir)
    return _dictionaries
