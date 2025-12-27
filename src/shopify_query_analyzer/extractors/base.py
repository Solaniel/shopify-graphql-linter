"""Base extractor interface for extracting GraphQL queries from files."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ExtractedQuery:
    """Represents a GraphQL query extracted from a source file."""

    content: str
    """Raw GraphQL query text."""

    source_file: Path
    """Path to the original source file."""

    start_line: int
    """1-based line number where the query starts in the source file."""

    start_col: int = 1
    """1-based column number where the query starts."""

    identifier: str = ""
    """Optional identifier (e.g., variable name or heredoc label)."""

    end_line: int = field(default=0)
    """1-based line number where the query ends (0 = calculated from content)."""

    def __post_init__(self) -> None:
        """Calculate end_line if not provided."""
        if self.end_line == 0:
            self.end_line = self.start_line + self.content.count("\n")

    def get_absolute_line(self, relative_line: int) -> int:
        """
        Convert a line number relative to the query content to an absolute line
        number in the source file.

        Args:
            relative_line: 1-based line number within the query content

        Returns:
            1-based line number in the source file
        """
        return self.start_line + relative_line - 1

    def get_location_str(self, relative_line: int = 1, relative_col: int = 1) -> str:
        """
        Get a formatted location string for error reporting.

        Args:
            relative_line: Line number within the query (1-based)
            relative_col: Column number within that line (1-based)

        Returns:
            Formatted string like "path/to/file.php:45:10"
        """
        abs_line = self.get_absolute_line(relative_line)
        abs_col = relative_col if relative_line > 1 else self.start_col + relative_col - 1
        return f"{self.source_file}:{abs_line}:{abs_col}"


class BaseExtractor(ABC):
    """Abstract base class for query extractors."""

    extensions: list[str] = []
    """File extensions this extractor handles (e.g., ['.php'])."""

    @abstractmethod
    def extract(self, file_path: Path, content: str) -> list[ExtractedQuery]:
        """
        Extract all GraphQL queries from file content.

        Args:
            file_path: Path to the source file
            content: Raw content of the file

        Returns:
            List of extracted queries with location information
        """
        ...

    def can_handle(self, file_path: Path) -> bool:
        """
        Check if this extractor can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if this extractor should handle the file
        """
        return file_path.suffix.lower() in self.extensions

