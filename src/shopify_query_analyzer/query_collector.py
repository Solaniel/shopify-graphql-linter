"""Query collector - scans files and extracts GraphQL queries."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .extractors import BaseExtractor, ExtractedQuery, GraphQLExtractor, PHPExtractor


class QueryCollector:
    """
    Collects GraphQL queries from various file types.

    Uses a registry of extractors to handle different file formats.
    """

    def __init__(self) -> None:
        """Initialize with default extractors."""
        self._extractors: dict[str, BaseExtractor] = {}
        self._register_default_extractors()

    def _register_default_extractors(self) -> None:
        """Register the built-in extractors."""
        graphql_extractor = GraphQLExtractor()
        php_extractor = PHPExtractor()

        for ext in graphql_extractor.extensions:
            self._extractors[ext.lower()] = graphql_extractor

        for ext in php_extractor.extensions:
            self._extractors[ext.lower()] = php_extractor

    def register_extractor(self, extractor: BaseExtractor) -> None:
        """
        Register a custom extractor.

        Args:
            extractor: Extractor instance to register
        """
        for ext in extractor.extensions:
            self._extractors[ext.lower()] = extractor

    def get_extractor(self, file_path: Path) -> Optional[BaseExtractor]:
        """
        Get the appropriate extractor for a file.

        Args:
            file_path: Path to the file

        Returns:
            Extractor if one is registered for this file type, None otherwise
        """
        return self._extractors.get(file_path.suffix.lower())

    def collect(
        self,
        paths: list[Path],
        extensions: Optional[list[str]] = None,
    ) -> list[ExtractedQuery]:
        """
        Collect all GraphQL queries from the given paths.

        Args:
            paths: List of files or directories to scan
            extensions: Optional list of extensions to filter by (e.g., ['.php', '.graphql'])

        Returns:
            List of extracted queries from all matching files
        """
        queries: list[ExtractedQuery] = []

        # Normalize extensions
        if extensions:
            extensions = [ext.lower() if ext.startswith(".") else f".{ext}".lower() for ext in extensions]

        for path in paths:
            if path.is_file():
                queries.extend(self._process_file(path, extensions))
            elif path.is_dir():
                queries.extend(self._process_directory(path, extensions))

        return queries

    def _process_file(
        self,
        file_path: Path,
        extensions: Optional[list[str]] = None,
    ) -> list[ExtractedQuery]:
        """
        Process a single file.

        Args:
            file_path: Path to the file
            extensions: Optional extension filter

        Returns:
            List of extracted queries
        """
        # Check extension filter
        if extensions and file_path.suffix.lower() not in extensions:
            return []

        extractor = self.get_extractor(file_path)
        if not extractor:
            return []

        try:
            content = file_path.read_text(encoding="utf-8")
            return extractor.extract(file_path, content)
        except UnicodeDecodeError:
            # Skip binary files
            return []
        except OSError as e:
            # Log error but continue processing
            print(f"Warning: Could not read {file_path}: {e}")
            return []

    def _process_directory(
        self,
        directory: Path,
        extensions: Optional[list[str]] = None,
    ) -> list[ExtractedQuery]:
        """
        Recursively process a directory.

        Args:
            directory: Directory to scan
            extensions: Optional extension filter

        Returns:
            List of extracted queries from all files in directory
        """
        queries: list[ExtractedQuery] = []

        # Determine which extensions to scan for
        target_extensions = extensions or list(self._extractors.keys())

        for ext in target_extensions:
            # Normalize extension format
            ext_pattern = ext if ext.startswith(".") else f".{ext}"

            # Use glob to find matching files
            for file_path in directory.rglob(f"*{ext_pattern}"):
                if file_path.is_file():
                    queries.extend(self._process_file(file_path, extensions))

        return queries

    def collect_from_content(
        self,
        content: str,
        file_path: Path,
    ) -> list[ExtractedQuery]:
        """
        Extract queries from provided content (useful for testing or piped input).

        Args:
            content: File content
            file_path: Virtual path for the content (used to determine extractor)

        Returns:
            List of extracted queries
        """
        extractor = self.get_extractor(file_path)
        if not extractor:
            # Default to GraphQL extractor for unknown types
            extractor = GraphQLExtractor()

        return extractor.extract(file_path, content)

    @property
    def supported_extensions(self) -> list[str]:
        """Get list of supported file extensions."""
        return list(self._extractors.keys())

