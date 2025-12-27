"""GraphQL file extractor - handles .graphql and .gql files."""

from __future__ import annotations

from pathlib import Path

from .base import BaseExtractor, ExtractedQuery


class GraphQLExtractor(BaseExtractor):
    """
    Extractor for native GraphQL files.

    This is a passthrough extractor - the entire file content is treated
    as a single GraphQL document.
    """

    extensions = [".graphql", ".gql"]

    def extract(self, file_path: Path, content: str) -> list[ExtractedQuery]:
        """
        Extract the GraphQL query from a .graphql or .gql file.

        The entire file content is treated as a single query document.

        Args:
            file_path: Path to the GraphQL file
            content: File content

        Returns:
            List containing a single ExtractedQuery for the whole file
        """
        if not content.strip():
            return []

        return [
            ExtractedQuery(
                content=content,
                source_file=file_path,
                start_line=1,
                start_col=1,
                identifier=file_path.stem,
            )
        ]

