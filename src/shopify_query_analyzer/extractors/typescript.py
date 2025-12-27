"""Typescript extractor - handles GraphQL queries in Typescript files."""

from __future__ import annotations

import re
from pathlib import Path

from .base import BaseExtractor, ExtractedQuery


class TypescriptExtractor(BaseExtractor):
    """
    Extractor for Typescript files containing GraphQL queries in template syntax.

    Supports template patterns like:
        const export const QUERY = `#graphql
            query { ... }
        `;

    Supports gql patterns like:
        const QUERY = gql`
            query { ... }
        `;

        const QUERY = graphql`
            query { ... }
        ` as const;
    """

    extensions = [".ts", ".tsx"]

    # Regex pattern for Typescript with common GraphQL delimiters
    # Captures: delimiter name, content
    GRAPHQL_TEMPLATE_PATTERN = re.compile(
        r"(?:export\s+)?const\s+(\w+)\s*=\s*`#graphql\s*\n"
        r"(.*?)"
        r"`(?:\s*as\s+const)?;",
        re.DOTALL,
    )

    GRAPHQL_GQL_PATTERN = re.compile(
        r"(?:gql|graphql)\s*`[ \t]*\n"
        r"(.*?)"
        r"`[ \t]*(?:as\s+const)?",
        re.DOTALL,
    )

    def extract(self, file_path: Path, content: str) -> list[ExtractedQuery]:
        """
        Extract all GraphQL queries from Typescript template syntax.

        Args:
            file_path: Path to the Typescript file
            content: Typescript file content

        Returns:
            List of ExtractedQuery objects for each template found
        """
        queries: list[ExtractedQuery] = []

        # Find all template matches
        for pattern in [self.GRAPHQL_TEMPLATE_PATTERN, self.GRAPHQL_GQL_PATTERN]:
            for match in pattern.finditer(content):
                delimiter = match.group(1)
                query_content = match.group(2)

                # Calculate line number by counting newlines before the match
                start_pos = match.start()
                line_number = content[:start_pos].count("\n") + 1

                # The actual query content starts on the line after <<<QUERY
                query_start_line = line_number + 1

                # Calculate column (position within the line)
                line_start = content.rfind("\n", 0, start_pos) + 1
                start_col = start_pos - line_start + 1

                dedented_content = query_content

                if dedented_content:
                    queries.append(
                        ExtractedQuery(
                            content=dedented_content,
                            source_file=file_path,
                            start_line=query_start_line,
                            start_col=1,  # After dedent, effective column is 1
                            identifier=delimiter,
                        )
                    )

        return queries

    def extract_with_context(
        self, file_path: Path, content: str
    ) -> list[tuple[ExtractedQuery, str]]:
        """
        Extract queries with surrounding Typescript context for better error messages.

        Args:
            file_path: Path to the Typescript file
            content: Typescript file content

        Returns:
            List of tuples: (ExtractedQuery, variable_name or context)
        """
        queries = self.extract(file_path, content)
        results: list[tuple[ExtractedQuery, str]] = []

        lines = content.split("\n")

        for query in queries:
            # Try to find the constant or variable name this template is assigned to
            # Look for patterns like:
            #   export const QUERY = `#graphql
            #   query { ... }
            #   `;
            context_name = query.identifier

            # Search in the lines before the query start
            for i in range(max(0, query.start_line - 5), query.start_line):
                if i < len(lines):
                    line = lines[i]
                    # Match variable assignment
                    var_match = re.search(r"\$(\w+)\s*=\s*<<<", line)
                    if var_match:
                        context_name = var_match.group(1)
                        break
                    # Match constant definition
                    const_match = re.search(r"const\s+(\w+)\s*=\s*<<<", line, re.IGNORECASE)
                    if const_match:
                        context_name = const_match.group(1)
                        break

            results.append((query, context_name))

        return results
