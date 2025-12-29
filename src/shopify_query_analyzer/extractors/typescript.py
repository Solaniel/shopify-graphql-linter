"""Typescript extractor - handles GraphQL queries in Typescript files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .base import BaseExtractor, ExtractedQuery


@dataclass
class ImportedFragment:
    """Represents an imported fragment from another TypeScript file."""

    name: str
    """The imported variable name."""

    source_path: str
    """The import path as written in the source (e.g., '~/data/shopify/seo')."""

    resolved_path: Optional[Path] = None
    """The resolved absolute path to the source file."""


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
    # Captures: variable name, content
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

    # Pattern to match TypeScript import statements
    # Captures: imported names (comma-separated), source path
    IMPORT_PATTERN = re.compile(
        r"import\s*\{([^}]+)\}\s*from\s*['\"]([^'\"]+)['\"]",
    )

    # Pattern to match template literal interpolations: ${VARIABLE_NAME}
    INTERPOLATION_PATTERN = re.compile(r"\$\{(\w+)\}")

    # Pattern to detect GraphQL operations (query, mutation, subscription)
    # These indicate a "complete" document that should be validated
    OPERATION_PATTERN = re.compile(
        r"^\s*(?:query|mutation|subscription)\s+\w*\s*(?:\(|{|@)",
        re.MULTILINE,
    )

    def parse_imports(self, content: str) -> list[ImportedFragment]:
        """
        Parse TypeScript import statements to extract imported fragment names and paths.

        Args:
            content: TypeScript file content

        Returns:
            List of ImportedFragment objects with name and source path
        """
        imports: list[ImportedFragment] = []

        for match in self.IMPORT_PATTERN.finditer(content):
            imported_names_str = match.group(1)
            source_path = match.group(2)

            # Parse comma-separated import names, handling potential aliases
            # e.g., "SEO_FIELDS, OTHER as Alias" -> ["SEO_FIELDS", "OTHER"]
            for name_part in imported_names_str.split(","):
                name_part = name_part.strip()
                if not name_part:
                    continue

                # Handle "Name as Alias" syntax - we want the alias (local name)
                if " as " in name_part:
                    _, alias = name_part.split(" as ", 1)
                    name = alias.strip()
                else:
                    name = name_part.strip()

                imports.append(ImportedFragment(name=name, source_path=source_path))

        return imports

    def resolve_import_path(
        self, import_path: str, current_file: Path, project_root: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Resolve a TypeScript import path to an actual file path.

        Handles:
        - Relative paths: ./foo, ../bar
        - Alias paths: ~/foo (maps to project root or app/)
        - Tries .ts and .tsx extensions

        Args:
            import_path: The import path as written in source
            current_file: Path to the file containing the import
            project_root: Optional project root for alias resolution

        Returns:
            Resolved Path if found, None otherwise
        """
        # Ensure we're working with absolute paths
        abs_current_file = current_file.resolve()
        current_dir = abs_current_file.parent

        # Determine project root if not provided
        if project_root is None:
            project_root = self._find_project_root(abs_current_file)

        # Handle relative paths
        if import_path.startswith("./") or import_path.startswith("../"):
            base_path = (current_dir / import_path).resolve()
            return self._try_resolve_extensions(base_path)

        # Handle tilde alias (~/...) - common in Remix/Next.js projects
        if import_path.startswith("~/"):
            path_suffix = import_path[2:]

            # Try app/ directory first (common in Remix)
            app_path = (project_root / "app" / path_suffix).resolve()
            resolved = self._try_resolve_extensions(app_path)
            if resolved:
                return resolved

            # Try src/ directory
            src_path = (project_root / "src" / path_suffix).resolve()
            resolved = self._try_resolve_extensions(src_path)
            if resolved:
                return resolved

            # Try project root directly
            root_path = (project_root / path_suffix).resolve()
            return self._try_resolve_extensions(root_path)

        # Handle @ alias (common in many projects)
        if import_path.startswith("@/"):
            path_suffix = import_path[2:]

            # Try src/ directory first
            src_path = (project_root / "src" / path_suffix).resolve()
            resolved = self._try_resolve_extensions(src_path)
            if resolved:
                return resolved

            # Try project root
            root_path = (project_root / path_suffix).resolve()
            return self._try_resolve_extensions(root_path)

        # For bare imports (node_modules), we don't resolve them
        return None

    def _try_resolve_extensions(self, base_path: Path) -> Optional[Path]:
        """
        Try to resolve a path with different TypeScript extensions.

        Args:
            base_path: Base path without extension

        Returns:
            Resolved path if found, None otherwise
        """
        # If path already has extension and exists
        if base_path.suffix in [".ts", ".tsx"] and base_path.exists():
            return base_path

        # Try adding extensions
        for ext in [".ts", ".tsx"]:
            candidate = base_path.with_suffix(ext)
            if candidate.exists():
                return candidate

        # Try as directory with index file
        if base_path.is_dir():
            for ext in [".ts", ".tsx"]:
                index_path = base_path / f"index{ext}"
                if index_path.exists():
                    return index_path

        # Try without modifying if it's already a valid path
        base_with_no_suffix = Path(str(base_path).rstrip("/"))
        for ext in [".ts", ".tsx"]:
            candidate = Path(str(base_with_no_suffix) + ext)
            if candidate.exists():
                return candidate

        return None

    def _find_project_root(self, start_path: Path) -> Path:
        """
        Find the project root by looking for package.json or tsconfig.json.

        Args:
            start_path: Starting path to search from

        Returns:
            Project root path (absolute), or parent of start_path if not found
        """
        # Ensure we're working with absolute paths
        abs_start = start_path.resolve()
        current = abs_start.parent if abs_start.is_file() else abs_start

        while current != current.parent:
            if (current / "package.json").exists() or (current / "tsconfig.json").exists():
                return current
            current = current.parent

        # Fallback to the starting directory's parent
        return abs_start.parent if abs_start.is_file() else abs_start

    def build_fragment_map(
        self,
        file_path: Path,
        content: str,
        project_root: Optional[Path] = None,
        visited: Optional[set[Path]] = None,
    ) -> dict[str, str]:
        """
        Build a map of variable names to their GraphQL content.

        Recursively follows imports to collect all fragment definitions.

        Args:
            file_path: Path to the TypeScript file
            content: File content
            project_root: Optional project root for import resolution
            visited: Set of already visited files to prevent cycles

        Returns:
            Dictionary mapping variable names to GraphQL content
        """
        if visited is None:
            visited = set()

        # Ensure we're working with absolute paths
        abs_file_path = file_path.resolve()

        # Prevent circular imports
        if abs_file_path in visited:
            return {}

        # Create a new visited set for this branch to avoid sibling interference
        # Each recursive call gets its own copy with the current file added
        branch_visited = visited | {abs_file_path}

        # Determine project root once if not provided
        if project_root is None:
            project_root = self._find_project_root(abs_file_path)

        fragment_map: dict[str, str] = {}

        # First, process imports to get fragments from other files
        imports = self.parse_imports(content)
        for imp in imports:
            resolved_import_path = self.resolve_import_path(
                imp.source_path, abs_file_path, project_root
            )
            if resolved_import_path and resolved_import_path.exists():
                try:
                    imported_content = resolved_import_path.read_text(encoding="utf-8")
                    imported_fragments = self.build_fragment_map(
                        resolved_import_path,
                        imported_content,
                        project_root,
                        branch_visited,
                    )
                    # Only add the specifically imported names
                    if imp.name in imported_fragments:
                        fragment_map[imp.name] = imported_fragments[imp.name]
                except (OSError, UnicodeDecodeError):
                    # Skip files that can't be read
                    pass

        # Extract fragments from current file
        for pattern in [self.GRAPHQL_TEMPLATE_PATTERN, self.GRAPHQL_GQL_PATTERN]:
            for match in pattern.finditer(content):
                var_name = match.group(1)
                graphql_content = match.group(2)
                if var_name and graphql_content:
                    fragment_map[var_name] = graphql_content

        # Resolve all internal interpolations within this file's fragments
        # This ensures that when a fragment is imported, it's already fully resolved
        resolved_map: dict[str, str] = {}
        for var_name, graphql_content in fragment_map.items():
            resolved_map[var_name] = self.resolve_interpolations(
                graphql_content, fragment_map
            )

        return resolved_map

    def resolve_interpolations(
        self,
        graphql_content: str,
        fragment_map: dict[str, str],
        max_depth: int = 10,
    ) -> str:
        """
        Resolve ${VARIABLE_NAME} interpolations in GraphQL content.

        Recursively resolves nested interpolations up to max_depth.

        Args:
            graphql_content: The GraphQL content with potential interpolations
            fragment_map: Map of variable names to their GraphQL content
            max_depth: Maximum recursion depth to prevent infinite loops

        Returns:
            Resolved GraphQL content with interpolations replaced
        """
        if max_depth <= 0:
            return graphql_content

        def replace_interpolation(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name in fragment_map:
                # Recursively resolve any nested interpolations
                resolved = self.resolve_interpolations(
                    fragment_map[var_name],
                    fragment_map,
                    max_depth - 1,
                )
                return resolved
            # If variable not found, leave the interpolation as-is
            # This will cause a validation error which is appropriate
            return match.group(0)

        return self.INTERPOLATION_PATTERN.sub(replace_interpolation, graphql_content)

    def _find_referenced_variables(self, content: str) -> set[str]:
        """
        Find all variable names that are referenced via ${...} in the content.

        These are "building block" fragments that shouldn't be extracted standalone.

        Args:
            content: TypeScript file content

        Returns:
            Set of variable names that are referenced as interpolations
        """
        referenced: set[str] = set()

        # Find all ${VAR_NAME} references in all template literals
        for pattern in [self.GRAPHQL_TEMPLATE_PATTERN, self.GRAPHQL_GQL_PATTERN]:
            for match in pattern.finditer(content):
                query_content = match.group(2)
                # Find all interpolations in this template
                for interp_match in self.INTERPOLATION_PATTERN.finditer(query_content):
                    referenced.add(interp_match.group(1))

        return referenced

    def _contains_operation(self, graphql_content: str) -> bool:
        """
        Check if GraphQL content contains an operation (query/mutation/subscription).

        Templates that only contain fragment definitions are building blocks
        and should not be validated standalone.

        Args:
            graphql_content: The GraphQL content to check

        Returns:
            True if content contains an operation, False if it's fragment-only
        """
        return bool(self.OPERATION_PATTERN.search(graphql_content))

    def extract(
        self,
        file_path: Path,
        content: str,
        resolve_fragments: bool = True,
    ) -> list[ExtractedQuery]:
        """
        Extract all GraphQL queries from Typescript template syntax.

        Uses a multi-pass approach:
        1. Find all variable names that are referenced via ${...} (building blocks)
        2. Build fragment map from current file and imports
        3. Extract only "leaf" queries (not referenced elsewhere) and resolve interpolations

        Args:
            file_path: Path to the Typescript file
            content: Typescript file content
            resolve_fragments: Whether to resolve fragment interpolations (default True)

        Returns:
            List of ExtractedQuery objects for each template found
        """
        queries: list[ExtractedQuery] = []

        # Ensure we're working with absolute paths
        abs_file_path = file_path.resolve()

        # Pass 1: Find variables that are used as building blocks
        # These are referenced via ${...} in other templates and shouldn't be extracted standalone
        referenced_vars = self._find_referenced_variables(content)

        # Pass 2: Build fragment map if resolution is enabled
        fragment_map: dict[str, str] = {}
        if resolve_fragments:
            fragment_map = self.build_fragment_map(abs_file_path, content)

        # Pass 3: Find all template matches, skip building blocks, resolve interpolations
        for pattern in [self.GRAPHQL_TEMPLATE_PATTERN, self.GRAPHQL_GQL_PATTERN]:
            for match in pattern.finditer(content):
                var_name = match.group(1)
                query_content = match.group(2)

                # Skip templates that are only used as building blocks for other queries
                # They will be inlined into the final queries via interpolation resolution
                if var_name in referenced_vars:
                    continue

                # Resolve interpolations first to check the complete content
                if resolve_fragments and fragment_map:
                    resolved_content = self.resolve_interpolations(
                        query_content, fragment_map
                    )
                else:
                    resolved_content = query_content

                # Skip templates that only contain fragment definitions
                # These are building blocks meant to be imported by other files
                if not self._contains_operation(resolved_content):
                    continue

                # Calculate line number by counting newlines before the match
                start_pos = match.start()
                line_number = content[:start_pos].count("\n") + 1

                # The actual query content starts on the line after the opening
                query_start_line = line_number + 1

                # Calculate column (position within the line)
                line_start = content.rfind("\n", 0, start_pos) + 1
                start_col = start_pos - line_start + 1

                if resolved_content:
                    queries.append(
                        ExtractedQuery(
                            content=resolved_content,
                            source_file=file_path,
                            start_line=query_start_line,
                            start_col=1,  # After dedent, effective column is 1
                            identifier=var_name,
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
