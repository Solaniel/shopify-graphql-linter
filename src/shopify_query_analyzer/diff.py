"""Diff logic - compares analysis results across schema versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .analyzer import Issue, IssueSeverity, IssueType, QueryAnalysisResult
from .extractors import ExtractedQuery


class DiffCategory(str, Enum):
    """Category of difference between versions."""

    DEPRECATED_NOW = "deprecated_now"
    """Field/argument is deprecated in the current schema version."""

    BECOMES_DEPRECATED = "becomes_deprecated"
    """Not deprecated in current, but deprecated in target version."""

    BREAKS_ON_UPGRADE = "breaks_on_upgrade"
    """Valid in current schema, but invalid in target schema."""

    ALREADY_BROKEN = "already_broken"
    """Invalid in current schema (already broken)."""

    STILL_VALID = "still_valid"
    """Valid in both current and target schemas."""


@dataclass
class DiffItem:
    """Represents a single difference between schema versions."""

    category: DiffCategory
    query: ExtractedQuery
    issue: Optional[Issue] = None
    current_issue: Optional[Issue] = None
    target_issue: Optional[Issue] = None
    message: str = ""

    @property
    def severity(self) -> IssueSeverity:
        """Get the severity level for this diff."""
        if self.category in (DiffCategory.BREAKS_ON_UPGRADE, DiffCategory.ALREADY_BROKEN):
            return IssueSeverity.ERROR
        elif self.category in (DiffCategory.DEPRECATED_NOW, DiffCategory.BECOMES_DEPRECATED):
            return IssueSeverity.WARNING
        return IssueSeverity.INFO

    @property
    def source_file(self) -> Path:
        """Get the source file path."""
        return self.query.source_file

    @property
    def line(self) -> int:
        """Get the line number."""
        if self.issue:
            return self.issue.line
        if self.target_issue:
            return self.target_issue.line
        if self.current_issue:
            return self.current_issue.line
        return self.query.start_line

    @property
    def column(self) -> int:
        """Get the column number."""
        if self.issue:
            return self.issue.column
        if self.target_issue:
            return self.target_issue.column
        if self.current_issue:
            return self.current_issue.column
        return self.query.start_col

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        result = {
            "category": self.category.value,
            "severity": self.severity.value,
            "file": str(self.source_file),
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "query_identifier": self.query.identifier,
        }

        if self.issue:
            result["issue"] = self.issue.to_dict()
        if self.current_issue:
            result["current_issue"] = self.current_issue.to_dict()
        if self.target_issue:
            result["target_issue"] = self.target_issue.to_dict()

        return result


@dataclass
class DiffSummary:
    """Summary of differences between schema versions."""

    total_queries: int = 0
    still_valid: int = 0
    deprecated_now: int = 0
    becomes_deprecated: int = 0
    breaks_on_upgrade: int = 0
    already_broken: int = 0

    @property
    def has_issues(self) -> bool:
        """Check if there are any issues requiring attention."""
        return (
            self.deprecated_now > 0
            or self.becomes_deprecated > 0
            or self.breaks_on_upgrade > 0
            or self.already_broken > 0
        )

    @property
    def has_breaking_changes(self) -> bool:
        """Check if there are any breaking changes."""
        return self.breaks_on_upgrade > 0 or self.already_broken > 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "total_queries": self.total_queries,
            "still_valid": self.still_valid,
            "deprecated_now": self.deprecated_now,
            "becomes_deprecated": self.becomes_deprecated,
            "breaks_on_upgrade": self.breaks_on_upgrade,
            "already_broken": self.already_broken,
        }


@dataclass
class DiffResult:
    """Result of comparing analysis across schema versions."""

    current_version: str
    target_version: str
    items: list[DiffItem] = field(default_factory=list)
    summary: DiffSummary = field(default_factory=DiffSummary)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON output."""
        return {
            "current_version": self.current_version,
            "target_version": self.target_version,
            "summary": self.summary.to_dict(),
            "items": [item.to_dict() for item in self.items if item.category != DiffCategory.STILL_VALID],
        }


class VersionDiffer:
    """Compares query analysis results between schema versions."""

    def __init__(
        self,
        current_version: str,
        target_version: str,
    ) -> None:
        """
        Initialize the differ.

        Args:
            current_version: The version the code currently targets
            target_version: The version to upgrade to
        """
        self.current_version = current_version
        self.target_version = target_version

    def diff(
        self,
        current_results: list[QueryAnalysisResult],
        target_results: list[QueryAnalysisResult],
    ) -> DiffResult:
        """
        Compare analysis results between current and target schemas.

        Args:
            current_results: Analysis results against current schema
            target_results: Analysis results against target schema

        Returns:
            DiffResult with categorized differences
        """
        result = DiffResult(
            current_version=self.current_version,
            target_version=self.target_version,
        )

        # Build lookup maps by query content hash for matching
        target_by_content = {
            self._query_key(r.query): r for r in target_results
        }

        for current in current_results:
            key = self._query_key(current.query)
            target = target_by_content.get(key)

            if not target:
                # This shouldn't happen if we're analyzing the same queries
                continue

            result.summary.total_queries += 1

            # Categorize this query
            items = self._categorize_query(current, target)
            result.items.extend(items)

            # Update summary
            for item in items:
                if item.category == DiffCategory.STILL_VALID:
                    result.summary.still_valid += 1
                elif item.category == DiffCategory.DEPRECATED_NOW:
                    result.summary.deprecated_now += 1
                elif item.category == DiffCategory.BECOMES_DEPRECATED:
                    result.summary.becomes_deprecated += 1
                elif item.category == DiffCategory.BREAKS_ON_UPGRADE:
                    result.summary.breaks_on_upgrade += 1
                elif item.category == DiffCategory.ALREADY_BROKEN:
                    result.summary.already_broken += 1

        return result

    def _query_key(self, query: ExtractedQuery) -> str:
        """Generate a unique key for a query."""
        return f"{query.source_file}:{query.start_line}:{query.content[:100]}"

    def _categorize_query(
        self,
        current: QueryAnalysisResult,
        target: QueryAnalysisResult,
    ) -> list[DiffItem]:
        """Categorize differences for a single query."""
        items: list[DiffItem] = []

        # Check for breaking changes (valid in current, invalid in target)
        current_errors = {
            self._issue_key(i) for i in current.issues
            if i.severity == IssueSeverity.ERROR
        }
        target_errors = {
            self._issue_key(i): i for i in target.issues
            if i.severity == IssueSeverity.ERROR
        }

        # Already broken in current
        for issue in current.issues:
            if issue.severity == IssueSeverity.ERROR:
                items.append(
                    DiffItem(
                        category=DiffCategory.ALREADY_BROKEN,
                        query=current.query,
                        issue=issue,
                        message=f"Already broken in {self.current_version}: {issue.message}",
                    )
                )

        # Breaks on upgrade (new errors in target)
        for key, issue in target_errors.items():
            if key not in current_errors:
                items.append(
                    DiffItem(
                        category=DiffCategory.BREAKS_ON_UPGRADE,
                        query=current.query,
                        target_issue=issue,
                        message=f"Will break in {self.target_version}: {issue.message}",
                    )
                )

        # Check deprecations
        current_deprecations = self._get_deprecation_keys(current)
        target_deprecations = self._get_deprecation_map(target)

        # Deprecated now (in current schema)
        for issue in current.issues:
            if issue.type in (
                IssueType.DEPRECATED_FIELD,
                IssueType.DEPRECATED_ARGUMENT,
                IssueType.DEPRECATED_ENUM_VALUE,
            ):
                items.append(
                    DiffItem(
                        category=DiffCategory.DEPRECATED_NOW,
                        query=current.query,
                        issue=issue,
                        message=f"Deprecated in {self.current_version}: {issue.field_path}",
                    )
                )

        # Becomes deprecated (not in current, but in target)
        for key, issue in target_deprecations.items():
            if key not in current_deprecations:
                items.append(
                    DiffItem(
                        category=DiffCategory.BECOMES_DEPRECATED,
                        query=current.query,
                        target_issue=issue,
                        message=f"Will be deprecated in {self.target_version}: {issue.field_path}",
                    )
                )

        # If no issues, it's still valid
        if not items:
            items.append(
                DiffItem(
                    category=DiffCategory.STILL_VALID,
                    query=current.query,
                    message="Valid in both versions",
                )
            )

        return items

    def _issue_key(self, issue: Issue) -> str:
        """Generate a unique key for an issue."""
        return f"{issue.type.value}:{issue.field_path}:{issue.message}"

    def _get_deprecation_keys(self, result: QueryAnalysisResult) -> set[str]:
        """Get set of deprecation issue keys."""
        return {
            self._deprecation_key(i)
            for i in result.issues
            if i.type in (
                IssueType.DEPRECATED_FIELD,
                IssueType.DEPRECATED_ARGUMENT,
                IssueType.DEPRECATED_ENUM_VALUE,
            )
        }

    def _get_deprecation_map(self, result: QueryAnalysisResult) -> dict[str, Issue]:
        """Get map of deprecation issues by key."""
        return {
            self._deprecation_key(i): i
            for i in result.issues
            if i.type in (
                IssueType.DEPRECATED_FIELD,
                IssueType.DEPRECATED_ARGUMENT,
                IssueType.DEPRECATED_ENUM_VALUE,
            )
        }

    def _deprecation_key(self, issue: Issue) -> str:
        """Generate key for deprecation deduplication."""
        return f"{issue.type.value}:{issue.field_path}"

