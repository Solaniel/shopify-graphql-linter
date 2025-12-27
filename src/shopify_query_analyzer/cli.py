"""CLI entry point for Shopify Query Analyzer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console

from .analyzer import QueryAnalyzer
from .config import ApiType, AuthConfig, OutputFormat
from .diff import VersionDiffer
from .output import get_exit_code, get_formatter
from .query_collector import QueryCollector
from .schema_manager import SchemaManager

app = typer.Typer(
    name="shopify-query-analyzer",
    help="Validate Shopify GraphQL queries against schema versions, detect deprecations and breaking changes.",
    no_args_is_help=True,
)

console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        from . import __version__
        console.print(f"shopify-query-analyzer v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version", "-v",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = None,
) -> None:
    """Shopify Query Analyzer - Validate GraphQL queries against Shopify schemas."""
    pass


@app.command()
def analyze(
    paths: Annotated[
        list[Path],
        typer.Argument(
            help="Files or directories to scan for GraphQL queries.",
            exists=True,
        ),
    ],
    api: Annotated[
        str,
        typer.Option(
            "--api",
            help="Shopify API type: 'admin' or 'storefront'.",
        ),
    ] = "admin",
    current_version: Annotated[
        Optional[str],
        typer.Option(
            "--current-version",
            help="The API version your code currently targets (e.g., '2024-10').",
        ),
    ] = None,
    target: Annotated[
        str,
        typer.Option(
            "--target",
            help="Target version to compare against: 'latest', specific version, or 'unstable'.",
        ),
    ] = "latest",
    shop: Annotated[
        Optional[str],
        typer.Option(
            "--shop",
            help="Shop domain (e.g., 'myshop.myshopify.com').",
        ),
    ] = None,
    admin_token: Annotated[
        Optional[str],
        typer.Option(
            "--admin-token",
            envvar="SHOPIFY_ADMIN_TOKEN",
            help="Admin API access token.",
        ),
    ] = None,
    storefront_token: Annotated[
        Optional[str],
        typer.Option(
            "--storefront-token",
            envvar="SHOPIFY_STOREFRONT_TOKEN",
            help="Storefront API token.",
        ),
    ] = None,
    use_direct_proxy: Annotated[
        bool,
        typer.Option(
            "--use-direct-proxy",
            help="Use Shopify's direct proxy (no authentication required).",
        ),
    ] = False,
    output_format: Annotated[
        str,
        typer.Option(
            "--format", "-f",
            help="Output format: 'human' or 'json'.",
        ),
    ] = "human",
    extensions: Annotated[
        Optional[list[str]],
        typer.Option(
            "--ext", "-e",
            help="Filter files by extension (can be used multiple times, e.g., --ext .php --ext .graphql).",
        ),
    ] = None,
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            help="Directory for caching schemas.",
        ),
    ] = Path(".cache/shopify-schema"),
    force_refresh: Annotated[
        bool,
        typer.Option(
            "--force-refresh",
            help="Force re-download of schemas (ignore cache).",
        ),
    ] = False,
    current_schema_file: Annotated[
        Optional[Path],
        typer.Option(
            "--current-schema-file",
            help="Path to local schema JSON file for current version (skips API fetch).",
            exists=True,
        ),
    ] = None,
    target_schema_file: Annotated[
        Optional[Path],
        typer.Option(
            "--target-schema-file",
            help="Path to local schema JSON file for target version (skips API fetch).",
            exists=True,
        ),
    ] = None,
) -> None:
    """
    Analyze GraphQL queries for deprecations and breaking changes.

    Scans the specified files/directories for GraphQL queries, validates them
    against the current and target Shopify API schema versions, and reports
    any deprecations or breaking changes.

    Note: The direct proxy only supports API versions 2025-01 and newer.
    For older versions, use shop credentials.

    Examples:

        # Scan a Laravel project using direct proxy
        shopify-query-analyzer analyze app/GraphQL/ --api admin --current-version 2025-01 --target 2025-04 --use-direct-proxy

        # Scan with authentication (supports all versions)
        shopify-query-analyzer analyze queries/ --api admin --shop myshop.myshopify.com --admin-token $TOKEN

        # JSON output for CI
        shopify-query-analyzer analyze . --api admin --use-direct-proxy --output-format json
    """
    # Validate API type
    try:
        api_type = ApiType(api.lower())
    except ValueError:
        console.print(f"[red]Error: Invalid API type '{api}'. Use 'admin' or 'storefront'.[/red]")
        raise typer.Exit(1)

    # Validate output format
    try:
        fmt = OutputFormat(output_format.lower())
    except ValueError:
        console.print(f"[red]Error: Invalid format '{output_format}'. Use 'human' or 'json'.[/red]")
        raise typer.Exit(1)

    # Validate authentication (only required if not using schema files)
    using_schema_files = current_schema_file is not None and target_schema_file is not None
    if not use_direct_proxy and not using_schema_files:
        if not shop:
            console.print("[red]Error: --shop is required when not using --use-direct-proxy or schema files[/red]")
            console.print("[dim]Tip: Use --current-schema-file and --target-schema-file for offline analysis[/dim]")
            raise typer.Exit(1)
        if api_type == ApiType.ADMIN and not admin_token:
            console.print("[red]Error: --admin-token is required for Admin API[/red]")
            raise typer.Exit(1)
        if api_type == ApiType.STOREFRONT and not storefront_token:
            console.print("[red]Error: --storefront-token is required for Storefront API[/red]")
            raise typer.Exit(1)

    # Build auth config
    auth = AuthConfig(
        shop=shop,
        admin_token=admin_token,
        storefront_token=storefront_token,
        use_direct_proxy=use_direct_proxy,
    )

    # Collect queries
    if fmt == OutputFormat.HUMAN:
        console.print("[dim]Scanning for GraphQL queries...[/dim]")

    collector = QueryCollector()
    queries = collector.collect(paths, extensions)

    if not queries:
        console.print("[yellow]No GraphQL queries found in the specified paths.[/yellow]")
        raise typer.Exit(0)

    if fmt == OutputFormat.HUMAN:
        console.print(f"[dim]Found {len(queries)} queries in {len(set(q.source_file for q in queries))} files[/dim]")

    # Initialize schema manager
    with SchemaManager(auth, cache_dir) as schema_manager:
        # Handle schema files or fetch from API
        if using_schema_files:
            # Use local schema files
            resolved_current = current_version or "local"
            resolved_target = target if target != "latest" else "local-target"

            if fmt == OutputFormat.HUMAN:
                console.print(f"[dim]Using local schema files[/dim]")
                console.print(f"[dim]Current: {current_schema_file}[/dim]")
                console.print(f"[dim]Target: {target_schema_file}[/dim]")

            try:
                current_schema = schema_manager.load_schema_from_file(current_schema_file)
                target_schema = schema_manager.load_schema_from_file(target_schema_file)
            except Exception as e:
                console.print(f"[red]Error loading schema files: {e}[/red]")
                raise typer.Exit(1)
        else:
            # Resolve versions from API
            if fmt == OutputFormat.HUMAN:
                console.print("[dim]Resolving API versions...[/dim]")

            try:
                resolved_current = current_version or schema_manager.resolve_version(api_type, "latest")
                print(f"Resolved current version: {resolved_current}")
                resolved_target = schema_manager.resolve_version(api_type, target)
            except Exception as e:
                console.print(f"[red]Error resolving versions: {e}[/red]")
                raise typer.Exit(1)

            if fmt == OutputFormat.HUMAN:
                console.print(f"[dim]Current version: {resolved_current}[/dim]")
                console.print(f"[dim]Target version: {resolved_target}[/dim]")
                console.print()

            # Fetch schemas from API
            if fmt == OutputFormat.HUMAN:
                console.print("[dim]Fetching schemas...[/dim]")

            try:
                current_schema = schema_manager.get_schema(api_type, resolved_current, force_refresh)
                target_schema = schema_manager.get_schema(api_type, resolved_target, force_refresh)
            except Exception as e:
                console.print(f"[red]Error fetching schemas: {e}[/red]")
                raise typer.Exit(1)

        # Analyze against both schemas
        if fmt == OutputFormat.HUMAN:
            console.print("[dim]Analyzing queries...[/dim]")
            console.print()

        current_analyzer = QueryAnalyzer(current_schema, resolved_current)
        target_analyzer = QueryAnalyzer(target_schema, resolved_target)

        current_results = current_analyzer.analyze_many(queries)
        target_results = target_analyzer.analyze_many(queries)

        # Compute diff
        differ = VersionDiffer(resolved_current, resolved_target)
        diff_result = differ.diff(current_results, target_results)

        # Format output
        formatter = get_formatter(fmt.value)
        formatter.format(diff_result)

        # Exit with appropriate code
        exit_code = get_exit_code(diff_result)
        raise typer.Exit(exit_code)


@app.command()
def versions(
    api: Annotated[
        str,
        typer.Option(
            "--api",
            help="Shopify API type: 'admin' or 'storefront'.",
        ),
    ] = "admin",
    shop: Annotated[
        Optional[str],
        typer.Option(
            "--shop",
            help="Shop domain (e.g., 'myshop.myshopify.com').",
        ),
    ] = None,
    admin_token: Annotated[
        Optional[str],
        typer.Option(
            "--admin-token",
            envvar="SHOPIFY_ADMIN_TOKEN",
            help="Admin API access token.",
        ),
    ] = None,
    use_direct_proxy: Annotated[
        bool,
        typer.Option(
            "--use-direct-proxy",
            help="Use Shopify's direct proxy.",
        ),
    ] = False,
) -> None:
    """
    List available Shopify API versions.

    Examples:

        shopify-query-analyzer versions --use-direct-proxy
        shopify-query-analyzer versions --shop myshop.myshopify.com --admin-token $TOKEN
    """
    try:
        api_type = ApiType(api.lower())
    except ValueError:
        console.print(f"[red]Error: Invalid API type '{api}'[/red]")
        raise typer.Exit(1)

    auth = AuthConfig(
        shop=shop,
        admin_token=admin_token,
        use_direct_proxy=use_direct_proxy,
    )

    with SchemaManager(auth) as schema_manager:
        try:
            versions_list = schema_manager.get_available_versions(api_type)
        except Exception as e:
            console.print(f"[red]Error fetching versions: {e}[/red]")
            raise typer.Exit(1)

        console.print(f"\n[bold]Available {api_type.value.title()} API Versions:[/bold]\n")

        for v in versions_list:
            status = "[green]✓ Supported[/green]" if v.supported else "[yellow]⚠ Unsupported[/yellow]"
            console.print(f"  {v.handle:12} {v.display_name:20} {status}")

        console.print()


@app.command()
def cache(
    action: Annotated[
        str,
        typer.Argument(
            help="Cache action: 'clear' or 'info'.",
        ),
    ],
    cache_dir: Annotated[
        Path,
        typer.Option(
            "--cache-dir",
            help="Cache directory path.",
        ),
    ] = Path(".cache/shopify-schema"),
) -> None:
    """
    Manage the schema cache.

    Examples:

        shopify-query-analyzer cache info
        shopify-query-analyzer cache clear
    """
    if action == "info":
        if not cache_dir.exists():
            console.print("[dim]Cache directory does not exist.[/dim]")
            raise typer.Exit(0)

        # Count cached schemas
        schema_files = list(cache_dir.rglob("*.json"))
        meta_files = [f for f in schema_files if f.name.endswith(".meta.json")]
        schema_files = [f for f in schema_files if not f.name.endswith(".meta.json")]

        console.print(f"\n[bold]Cache Info:[/bold]")
        console.print(f"  Location: {cache_dir.absolute()}")
        console.print(f"  Cached schemas: {len(schema_files)}")

        # Show details
        for schema_file in sorted(schema_files):
            api = schema_file.parent.name
            version = schema_file.stem
            size_kb = schema_file.stat().st_size / 1024
            console.print(f"    {api}/{version}: {size_kb:.1f} KB")

        console.print()

    elif action == "clear":
        if not cache_dir.exists():
            console.print("[dim]Cache directory does not exist.[/dim]")
            raise typer.Exit(0)

        import shutil
        shutil.rmtree(cache_dir)
        console.print("[green]Cache cleared successfully.[/green]")

    else:
        console.print(f"[red]Unknown action: {action}. Use 'info' or 'clear'.[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()

