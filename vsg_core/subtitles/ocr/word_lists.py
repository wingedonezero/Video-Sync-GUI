# vsg_core/subtitles/ocr/word_lists.py
"""
Unified Word List Management System

Provides a central system for managing word lists used in OCR validation:
- User dictionary, names, romaji, SE dictionaries all unified
- Configurable behavior per list (validate, protect, accept fixes)
- Reorderable priority
- Single ValidationManager used by all OCR components

Config stored in .config/ocr/ocr_config.json
"""

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class WordListSource(Enum):
    """Source type for word lists."""
    USER = "user"           # User-created lists (editable)
    SUBTITLE_EDIT = "se"    # From SubtitleEdit files (read-only, overridable)
    BUILT = "built"         # Generated/built lists like romaji
    SYSTEM = "system"       # System spell checker (Enchant/Hunspell)


@dataclass
class WordListConfig:
    """Configuration for a word list."""
    name: str                           # Display name
    source: str                         # WordListSource value
    enabled: bool = True

    # Behavior flags
    validates_known: bool = True        # Words won't show as "unknown"
    protects_from_fix: bool = True      # Won't try to "fix" these words
    accepts_as_fix_result: bool = True  # Accept fixes that produce these words

    # For ordering (lower = higher priority)
    order: int = 100

    # File reference (for file-backed lists)
    file_path: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "source": self.source,
            "enabled": self.enabled,
            "validates_known": self.validates_known,
            "protects_from_fix": self.protects_from_fix,
            "accepts_as_fix_result": self.accepts_as_fix_result,
            "order": self.order,
            "file_path": self.file_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WordListConfig":
        """Create from dictionary."""
        return cls(
            name=data.get("name", "Unknown"),
            source=data.get("source", "user"),
            enabled=data.get("enabled", True),
            validates_known=data.get("validates_known", True),
            protects_from_fix=data.get("protects_from_fix", True),
            accepts_as_fix_result=data.get("accepts_as_fix_result", True),
            order=data.get("order", 100),
            file_path=data.get("file_path"),
        )


@dataclass
class WordList:
    """A word list with its configuration and loaded words."""
    config: WordListConfig
    words: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def word_count(self) -> int:
        return len(self.words)

    def contains(self, word: str) -> bool:
        """Check if word is in this list (case-insensitive)."""
        return word.lower() in self.words or word in self.words


# Default word list configurations
DEFAULT_WORD_LISTS = [
    # System dictionary (Enchant/Hunspell) - highest priority
    WordListConfig(
        name="System Dictionary",
        source="system",
        order=0,
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    # User lists
    WordListConfig(
        name="User Dictionary",
        source="user",
        order=10,
        file_path="user_dictionary.txt",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    WordListConfig(
        name="Names",
        source="user",
        order=20,
        file_path="names.txt",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    # SE lists
    WordListConfig(
        name="SE Spell Words",
        source="se",
        order=30,
        file_path="subtitleedit/en_US_se.xml",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    WordListConfig(
        name="SE Names",
        source="se",
        order=40,
        file_path="subtitleedit/en_names.xml",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    WordListConfig(
        name="SE Interjections",
        source="se",
        order=50,
        file_path="subtitleedit/en_interjections_se.xml",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=True,
    ),
    # Romaji - validates but doesn't accept as fix result
    WordListConfig(
        name="Romaji",
        source="built",
        order=60,
        file_path="romaji_dictionary.txt",
        validates_known=True,
        protects_from_fix=True,
        accepts_as_fix_result=False,  # Don't accept romaji as valid fix target
    ),
    # Word split list - only used for splitting, not validation
    WordListConfig(
        name="SE Word Split",
        source="se",
        order=70,
        file_path="subtitleedit/eng_WordSplitList.txt",
        validates_known=False,   # Not used for validation
        protects_from_fix=False, # Not used for protection
        accepts_as_fix_result=False,  # Not used for fix acceptance
    ),
]


@dataclass
class ValidationResult:
    """Result of a word validation check."""
    is_known: bool
    source_name: str | None = None  # Which list it was found in
    is_protected: bool = False         # Should not be "fixed"


@dataclass
class ValidationStats:
    """Statistics for logging."""
    total_validated: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    unknown_words: list[str] = field(default_factory=list)

    def add_validated(self, source_name: str):
        self.total_validated += 1
        self.by_source[source_name] = self.by_source.get(source_name, 0) + 1

    def add_unknown(self, word: str):
        if word not in self.unknown_words:
            self.unknown_words.append(word)

    def get_summary(self) -> str:
        """Get summary string for logging."""
        if not self.by_source:
            return "0 words validated"

        parts = [f"{count} {source}" for source, count in sorted(self.by_source.items())]
        summary = f"{self.total_validated} words validated ({', '.join(parts)})"

        if self.unknown_words:
            unknown_preview = self.unknown_words[:5]
            if len(self.unknown_words) > 5:
                unknown_preview.append(f"...+{len(self.unknown_words) - 5} more")
            summary += f", {len(self.unknown_words)} unknown: {', '.join(unknown_preview)}"

        return summary


class ValidationManager:
    """
    Central manager for word validation across all OCR components.

    Provides a single source of truth for:
    - Is a word "known" (shouldn't be flagged as unknown)?
    - Is a word "protected" (shouldn't be auto-fixed)?
    - Is a word a valid fix result (acceptable correction target)?
    """

    def __init__(self, config_dir: Path):
        """
        Initialize with config directory.

        Args:
            config_dir: Path to .config/ocr/ directory
        """
        self.config_dir = Path(config_dir)
        self.config_path = self.config_dir / "ocr_config.json"

        self.word_lists: list[WordList] = []
        self.spell_checker = None  # Enchant dictionary, set externally

        self._stats = ValidationStats()

    def set_spell_checker(self, spell_checker):
        """Set the system spell checker (Enchant/Hunspell)."""
        self.spell_checker = spell_checker

    def load_config(self) -> list[WordListConfig]:
        """Load word list configurations from JSON."""
        if not self.config_path.exists():
            logger.info("[WordLists] No config found, using defaults")
            return [WordListConfig(**asdict(c)) for c in DEFAULT_WORD_LISTS]

        try:
            with open(self.config_path, encoding='utf-8') as f:
                data = json.load(f)

            configs = []
            for item in data.get("word_lists", []):
                configs.append(WordListConfig.from_dict(item))

            logger.info(f"[WordLists] Loaded {len(configs)} word list configs")
            return configs

        except Exception as e:
            logger.error(f"[WordLists] Error loading config: {e}")
            return [WordListConfig(**asdict(c)) for c in DEFAULT_WORD_LISTS]

    def save_config(self):
        """Save word list configurations to JSON."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)

            data = {
                "word_lists": [wl.config.to_dict() for wl in self.word_lists]
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            logger.info(f"[WordLists] Saved config to {self.config_path}")

        except Exception as e:
            logger.error(f"[WordLists] Error saving config: {e}")

    def get_word_lists(self) -> list[WordList]:
        """Get all word lists sorted by order."""
        return sorted(self.word_lists, key=lambda wl: wl.config.order)

    def add_word_list(self, config: WordListConfig, words: set[str]):
        """Add a word list."""
        word_list = WordList(config=config, words=words)
        self.word_lists.append(word_list)
        logger.debug(f"[WordLists] Added '{config.name}' with {len(words)} words")

    def get_word_list_by_name(self, name: str) -> WordList | None:
        """Get a word list by name."""
        for wl in self.word_lists:
            if wl.name == name:
                return wl
        return None

    def reorder_word_list(self, name: str, new_order: int):
        """Change the order of a word list."""
        wl = self.get_word_list_by_name(name)
        if wl:
            wl.config.order = new_order
            self.save_config()

    def update_word_list_config(self, name: str, **kwargs):
        """Update configuration for a word list."""
        wl = self.get_word_list_by_name(name)
        if wl:
            for key, value in kwargs.items():
                if hasattr(wl.config, key):
                    setattr(wl.config, key, value)
            self.save_config()

    # =========================================================================
    # Validation Methods - Used by all OCR components
    # =========================================================================

    def is_known_word(self, word: str, track_stats: bool = False) -> ValidationResult:
        """
        Check if a word is "known" (shouldn't be flagged as unknown).

        Checks all enabled word lists with validates_known=True,
        in priority order.

        Args:
            word: Word to check
            track_stats: Whether to track statistics

        Returns:
            ValidationResult with is_known and source info
        """
        word_lower = word.lower()

        # Check system spell checker first (if available and enabled)
        system_list = self.get_word_list_by_name("System Dictionary")
        if (system_list and system_list.enabled and
            system_list.config.validates_known and self.spell_checker):
            if self.spell_checker.check(word) or self.spell_checker.check(word_lower):
                if track_stats:
                    self._stats.add_validated("System")
                return ValidationResult(is_known=True, source_name="System Dictionary",
                                        is_protected=system_list.config.protects_from_fix)

        # Check word lists in order
        for wl in self.get_word_lists():
            if not wl.enabled or not wl.config.validates_known:
                continue
            if wl.config.source == "system":
                continue  # Already checked above

            if wl.contains(word):
                if track_stats:
                    self._stats.add_validated(wl.name)
                return ValidationResult(
                    is_known=True,
                    source_name=wl.name,
                    is_protected=wl.config.protects_from_fix
                )

        # Not found
        if track_stats:
            self._stats.add_unknown(word)
        return ValidationResult(is_known=False)

    def is_protected_word(self, word: str) -> bool:
        """
        Check if a word is "protected" (shouldn't be auto-fixed).

        Used to prevent valid words from being corrupted by replacement rules.

        Args:
            word: Word to check

        Returns:
            True if word should not be fixed
        """
        word_lower = word.lower()

        # Check system spell checker
        system_list = self.get_word_list_by_name("System Dictionary")
        if (system_list and system_list.enabled and
            system_list.config.protects_from_fix and self.spell_checker):
            if self.spell_checker.check(word) or self.spell_checker.check(word_lower):
                return True

        # Check word lists
        for wl in self.get_word_lists():
            if not wl.enabled or not wl.config.protects_from_fix:
                continue
            if wl.config.source == "system":
                continue

            if wl.contains(word):
                return True

        return False

    def is_valid_fix_result(self, word: str) -> bool:
        """
        Check if a word is a valid result for an OCR fix.

        Used to validate that replacement rules produce sensible output.
        More restrictive than is_known_word - e.g., romaji words are "known"
        but not valid fix results (OCR wouldn't produce Japanese from English).

        Args:
            word: Word to check

        Returns:
            True if word is acceptable as a fix result
        """
        word_lower = word.lower()

        # Check system spell checker
        system_list = self.get_word_list_by_name("System Dictionary")
        if (system_list and system_list.enabled and
            system_list.config.accepts_as_fix_result and self.spell_checker):
            if self.spell_checker.check(word) or self.spell_checker.check(word_lower):
                return True

        # Check word lists
        for wl in self.get_word_lists():
            if not wl.enabled or not wl.config.accepts_as_fix_result:
                continue
            if wl.config.source == "system":
                continue

            if wl.contains(word):
                return True

        return False

    # =========================================================================
    # Statistics and Logging
    # =========================================================================

    def reset_stats(self):
        """Reset validation statistics."""
        self._stats = ValidationStats()

    def get_stats(self) -> ValidationStats:
        """Get current validation statistics."""
        return self._stats

    def log_summary(self):
        """Log a summary of validation statistics."""
        logger.info(f"[OCR] Validation: {self._stats.get_summary()}")

    def get_list_summary(self) -> str:
        """Get summary of loaded word lists."""
        lines = []
        for wl in self.get_word_lists():
            status = "enabled" if wl.enabled else "disabled"
            flags = []
            if wl.config.validates_known:
                flags.append("V")
            if wl.config.protects_from_fix:
                flags.append("P")
            if wl.config.accepts_as_fix_result:
                flags.append("A")
            flags_str = "".join(flags) if flags else "-"
            lines.append(f"  [{wl.config.order:02d}] {wl.name}: {wl.word_count:,} words ({status}) [{flags_str}]")
        return "\n".join(lines)


# Global instance
_validation_manager: ValidationManager | None = None


def get_validation_manager(config_dir: Path | None = None) -> ValidationManager:
    """Get or create the global ValidationManager instance."""
    global _validation_manager

    if _validation_manager is None or config_dir is not None:
        if config_dir is None:
            # Default to project .config/ocr/
            config_dir = Path.cwd() / ".config" / "ocr"
        _validation_manager = ValidationManager(config_dir)

    return _validation_manager


# =============================================================================
# Word List Loaders
# =============================================================================

def load_text_wordlist(path: Path) -> set[str]:
    """
    Load words from a text file (one word per line).

    Handles:
    - user_dictionary.txt
    - names.txt
    - romaji_dictionary.txt
    - eng_WordSplitList.txt
    """
    words = set()
    if not path.exists():
        return words

    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                word = line.strip()
                if word and not word.startswith('#'):
                    words.add(word.lower())
        logger.debug(f"[WordLists] Loaded {len(words)} words from {path.name}")
    except Exception as e:
        logger.error(f"[WordLists] Error loading {path}: {e}")

    return words


def load_se_xml_wordlist(path: Path, element_name: str = "word") -> set[str]:
    """
    Load words from a SubtitleEdit XML file.

    Handles:
    - en_US_se.xml (<words><word>...</word></words>)
    - en_interjections_se.xml (<interjections><word>...</word></interjections>)
    """
    import xml.etree.ElementTree as ET

    words = set()
    if not path.exists():
        return words

    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # Find all word elements anywhere in the document
        for elem in root.iter(element_name):
            if elem.text:
                words.add(elem.text.strip().lower())

        logger.debug(f"[WordLists] Loaded {len(words)} words from {path.name}")
    except Exception as e:
        logger.error(f"[WordLists] Error loading {path}: {e}")

    return words


def load_se_names_xml(path: Path) -> tuple[set[str], set[str]]:
    """
    Load names from SubtitleEdit names XML file.

    Returns:
        (names_set, blacklist_set)
    """
    import xml.etree.ElementTree as ET

    names = set()
    blacklist = set()

    if not path.exists():
        return names, blacklist

    try:
        tree = ET.parse(path)
        root = tree.getroot()

        # Parse blacklist section
        blacklist_elem = root.find('blacklist')
        if blacklist_elem is not None:
            for name_elem in blacklist_elem.findall('name'):
                if name_elem.text:
                    blacklist.add(name_elem.text.strip())

        # Parse names (direct children of root, not in blacklist section)
        for name_elem in root.findall('name'):
            if name_elem.text:
                name = name_elem.text.strip()
                if name not in blacklist:
                    names.add(name.lower())

        logger.debug(f"[WordLists] Loaded {len(names)} names ({len(blacklist)} blacklisted) from {path.name}")
    except Exception as e:
        logger.error(f"[WordLists] Error loading {path}: {e}")

    return names, blacklist


def initialize_validation_manager(config_dir: Path, spell_checker=None) -> ValidationManager:
    """
    Initialize and populate the ValidationManager with all word lists.

    This is the main entry point for setting up the validation system.

    Args:
        config_dir: Path to .config/ocr/ directory
        spell_checker: Optional Enchant spell checker instance

    Returns:
        Fully initialized ValidationManager
    """
    manager = get_validation_manager(config_dir)
    manager.word_lists.clear()  # Reset if re-initializing

    # Set spell checker
    if spell_checker:
        manager.set_spell_checker(spell_checker)

    # Load configurations (from JSON or defaults)
    configs = manager.load_config()

    # Load words for each configured list
    for config in configs:
        words = set()

        if config.source == "system":
            # System dictionary handled via spell_checker, no words to load
            pass

        elif config.file_path:
            file_path = config_dir / config.file_path

            if config.file_path.endswith('.txt'):
                words = load_text_wordlist(file_path)

            elif 'names.xml' in config.file_path.lower():
                names, _ = load_se_names_xml(file_path)
                words = names

            elif config.file_path.endswith('.xml'):
                # Try 'word' element first, common in SE files
                words = load_se_xml_wordlist(file_path, 'word')

        manager.add_word_list(config, words)

    # Log summary
    logger.info(f"[WordLists] Initialized {len(manager.word_lists)} word lists:")
    logger.info(manager.get_list_summary())

    return manager
