"""PHP heredoc extractor - handles GraphQL queries in PHP files."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

from .base import BaseExtractor, ExtractedQuery


class PHPExtractor(BaseExtractor):
    """
    Extractor for PHP files containing GraphQL queries in heredoc syntax.

    Supports heredoc patterns like:
        Traditional (PHP < 7.3):
            <<<QUERY
            query { ... }
            QUERY;

        Flexible/indented (PHP 7.3+):
            <<<QUERY
                query { ... }
            QUERY;

        Nowdoc:
            <<<'QUERY'
            query { ... }
            QUERY;
    """

    extensions = [".php"]

    # Regex pattern for PHP heredoc with common GraphQL delimiters
    # Supports both traditional and PHP 7.3+ flexible heredoc syntax (indented closing)
    # Captures: delimiter name, content
    HEREDOC_PATTERN = re.compile(
        r"<<<\s*['\"]?(QUERY|GRAPHQL|GQL)['\"]?\s*\n"  # Opening: <<<QUERY or <<<'QUERY'
        r"(.*?)\n"  # Content (non-greedy, captures everything)
        r"[ \t]*\1;",  # Closing: optional whitespace + QUERY;
        re.DOTALL | re.IGNORECASE,
    )

    # Alternative pattern for nowdoc syntax: <<<'QUERY'
    NOWDOC_PATTERN = re.compile(
        r"<<<\s*'(QUERY|GRAPHQL|GQL)'\s*\n"
        r"(.*?)\n"
        r"[ \t]*\1;",  # Closing: optional whitespace + QUERY;
        re.DOTALL | re.IGNORECASE,
    )

    def extract(self, file_path: Path, content: str) -> list[ExtractedQuery]:
        """
        Extract all GraphQL queries from PHP heredoc syntax.

        Args:
            file_path: Path to the PHP file
            content: PHP file content

        Returns:
            List of ExtractedQuery objects for each heredoc found
        """
        queries: list[ExtractedQuery] = []

        # Find all heredoc matches
        for pattern in [self.HEREDOC_PATTERN, self.NOWDOC_PATTERN]:
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

                # Dedent the query content (remove common leading whitespace)
                # This handles PHP 7.3+ flexible heredoc with indented content
                dedented_content = textwrap.dedent(query_content)

                # Unescape PHP variable escaping: \$ -> $
                # In PHP heredocs, variables are escaped with backslash
                dedented_content = dedented_content.replace("\\$", "$")

                # Strip leading/trailing empty lines but preserve internal structure
                dedented_content = dedented_content.strip()

                if dedented_content:
                    queries.append(
                        ExtractedQuery(
                            content=dedented_content,
                            source_file=file_path,
                            start_line=query_start_line,
                            start_col=1,  # After dedent, effective column is 1
                            identifier=delimiter.upper(),
                        )
                    )

        return queries

    def extract_with_context(
        self, file_path: Path, content: str
    ) -> list[tuple[ExtractedQuery, str]]:
        """
        Extract queries with surrounding PHP context for better error messages.

        Args:
            file_path: Path to the PHP file
            content: PHP file content

        Returns:
            List of tuples: (ExtractedQuery, variable_name or context)
        """
        queries = self.extract(file_path, content)
        results: list[tuple[ExtractedQuery, str]] = []

        lines = content.split("\n")

        for query in queries:
            # Try to find the constant or variable name this heredoc is assigned to
            # Look for patterns like:
            #   $varName = <<<QUERY
            #   public const NAME = <<<QUERY
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
