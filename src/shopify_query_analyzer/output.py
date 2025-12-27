"""Output formatters - human-readable and JSON output."""

from __future__ import annotations

import json
import sys
from typing import Optional, TextIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .analyzer import IssueSeverity
from .diff import DiffCategory, DiffItem, DiffResult, DiffSummary


class OutputFormatter:
    """Base class for output formatters."""

    def format(self, result: DiffResult, output: TextIO = sys.stdout) -> None:
        """Format and write the diff result."""
        raise NotImplementedError


class HumanFormatter(OutputFormatter):
    """Human-readable colored terminal output using Rich."""

    CATEGORY_STYLES = {
        DiffCategory.DEPRECATED_NOW: ("yellow", "⚠"),
        DiffCategory.BECOMES_DEPRECATED: ("yellow", "⚠"),
        DiffCategory.BREAKS_ON_UPGRADE: ("red", "✗"),
        DiffCategory.ALREADY_BROKEN: ("red", "✗"),
        DiffCategory.STILL_VALID: ("green", "✓"),
    }

    CATEGORY_LABELS = {
        DiffCategory.DEPRECATED_NOW: "Deprecated Now",
        DiffCategory.BECOMES_DEPRECATED: "Becomes Deprecated",
        DiffCategory.BREAKS_ON_UPGRADE: "Breaks on Upgrade",
        DiffCategory.ALREADY_BROKEN: "Already Broken",
        DiffCategory.STILL_VALID: "Valid",
    }

    def __init__(self, console: Optional[Console] = None) -> None:
        """Initialize formatter."""
        self.console = console or Console()

    def format(self, result: DiffResult, output: TextIO = sys.stdout) -> None:
        """Format and print the diff result."""
        # Print header
        self._print_header(result)

        # Print summary table
        self._print_summary(result.summary)

        # Print issues grouped by file
        if result.items:
            self._print_issues(result)

        # Print footer with exit suggestion
        self._print_footer(result)

    def _print_header(self, result: DiffResult) -> None:
        """Print the header panel."""
        title = Text("Shopify Query Analyzer", style="bold blue")
        subtitle = Text(
            f"Comparing {result.current_version} → {result.target_version}",
            style="dim",
        )
        self.console.print()
        self.console.print(Panel(subtitle, title=title, border_style="blue"))
        self.console.print()

    def _print_summary(self, summary: DiffSummary) -> None:
        """Print the summary table."""
        table = Table(title="Summary", show_header=True, header_style="bold")
        table.add_column("Category", style="dim")
        table.add_column("Count", justify="right")
        table.add_column("Status")

        # Add rows
        self._add_summary_row(table, "Total Queries", summary.total_queries, "blue", "📊")
        self._add_summary_row(table, "Still Valid", summary.still_valid, "green", "✓")
        self._add_summary_row(
            table,
            "Deprecated Now",
            summary.deprecated_now,
            "yellow" if summary.deprecated_now > 0 else "dim",
            "⚠" if summary.deprecated_now > 0 else "-",
        )
        self._add_summary_row(
            table,
            "Becomes Deprecated",
            summary.becomes_deprecated,
            "yellow" if summary.becomes_deprecated > 0 else "dim",
            "⚠" if summary.becomes_deprecated > 0 else "-",
        )
        self._add_summary_row(
            table,
            "Breaks on Upgrade",
            summary.breaks_on_upgrade,
            "red" if summary.breaks_on_upgrade > 0 else "dim",
            "✗" if summary.breaks_on_upgrade > 0 else "-",
        )
        self._add_summary_row(
            table,
            "Already Broken",
            summary.already_broken,
            "red" if summary.already_broken > 0 else "dim",
            "✗" if summary.already_broken > 0 else "-",
        )

        self.console.print(table)
        self.console.print()

    def _add_summary_row(
        self,
        table: Table,
        label: str,
        count: int,
        style: str,
        icon: str,
    ) -> None:
        """Add a row to the summary table."""
        table.add_row(label, str(count), Text(icon, style=style))

    def _print_issues(self, result: DiffResult) -> None:
        """Print issues grouped by file."""
        # Filter out STILL_VALID items
        issues = [
            item for item in result.items
            if item.category != DiffCategory.STILL_VALID
        ]

        if not issues:
            self.console.print("[green]No issues found![/green]")
            return

        # Group by file
        by_file: dict[str, list[DiffItem]] = {}
        for item in issues:
            key = str(item.source_file)
            if key not in by_file:
                by_file[key] = []
            by_file[key].append(item)

        self.console.print("[bold]Issues:[/bold]")
        self.console.print()

        for file_path, file_issues in sorted(by_file.items()):
            self._print_file_issues(file_path, file_issues)

    def _print_file_issues(self, file_path: str, issues: list[DiffItem]) -> None:
        """Print issues for a single file."""
        self.console.print(f"[bold cyan]{file_path}[/bold cyan]")

        for item in sorted(issues, key=lambda i: (i.line, i.column)):
            style, icon = self.CATEGORY_STYLES.get(
                item.category, ("white", "•")
            )
            label = self.CATEGORY_LABELS.get(item.category, "Unknown")

            # Location
            loc = f"  {item.line}:{item.column}"
            self.console.print(f"[dim]{loc}[/dim]", end=" ")

            # Icon and category
            self.console.print(f"[{style}]{icon} {label}[/{style}]")

            # Message
            self.console.print(f"       {item.message}")

            # Deprecation reason if available
            issue = item.issue or item.target_issue or item.current_issue
            if issue and issue.deprecation_reason:
                reason = issue.deprecation_reason
                self.console.print(f"       [dim]Reason: {reason}[/dim]")

            self.console.print()

    def _print_footer(self, result: DiffResult) -> None:
        """Print footer with exit code suggestion."""
        summary = result.summary

        if summary.has_breaking_changes:
            self.console.print(
                "[red bold]✗ Breaking changes detected![/red bold]"
            )
            self.console.print(
                "[dim]Fix breaking changes before upgrading to "
                f"{result.target_version}[/dim]"
            )
        elif summary.deprecated_now > 0 or summary.becomes_deprecated > 0:
            self.console.print(
                "[yellow bold]⚠ Deprecation warnings detected[/yellow bold]"
            )
            self.console.print(
                "[dim]Consider updating deprecated fields before they are removed[/dim]"
            )
        else:
            self.console.print(
                "[green bold]✓ All queries are compatible![/green bold]"
            )


class JSONFormatter(OutputFormatter):
    """JSON output for CI/CD integration."""

    def __init__(self, pretty: bool = True) -> None:
        """Initialize formatter."""
        self.pretty = pretty

    def format(self, result: DiffResult, output: TextIO = sys.stdout) -> None:
        """Format and write the diff result as JSON."""
        data = result.to_dict()

        if self.pretty:
            json_str = json.dumps(data, indent=2, default=str)
        else:
            json_str = json.dumps(data, default=str)

        output.write(json_str)
        output.write("\n")


def get_formatter(format_name: str) -> OutputFormatter:
    """Get a formatter by name."""
    formatters = {
        "human": HumanFormatter,
        "json": JSONFormatter,
    }

    formatter_class = formatters.get(format_name.lower())
    if not formatter_class:
        raise ValueError(f"Unknown format: {format_name}")

    return formatter_class()


def get_exit_code(result: DiffResult) -> int:
    """
    Determine the exit code based on analysis results.

    Returns:
        0: No issues
        1: Breaking changes detected
        2: Deprecation warnings only
    """
    if result.summary.has_breaking_changes:
        return 1
    if result.summary.deprecated_now > 0 or result.summary.becomes_deprecated > 0:
        return 2
    return 0

