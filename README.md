# Shopify Query Analyzer

A Python CLI tool that validates Shopify GraphQL queries against schema introspection, detects deprecations, and reports breaking changes between API versions.

## Features

- **Multi-format support**: Extracts GraphQL queries from `.graphql`, `.gql`, and `.php` files (heredoc syntax)
- **Version comparison**: Compare queries against current and target API versions
- **Deprecation detection**: Identifies deprecated fields, arguments, and enum values
- **Breaking change detection**: Reports queries that will break on API upgrade
- **Schema caching**: Caches downloaded schemas for faster subsequent runs
- **CI-friendly**: JSON output format for integration with CI/CD pipelines

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/shopify-query-analyzer.git
cd shopify-query-analyzer

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install the package in development mode
pip install -e .
```

## Usage

### Basic Usage

```bash
# Scan a directory with direct proxy (no auth needed)
# Note: Direct proxy only supports versions 2025-01 and newer
shopify-query-analyzer analyze ./queries --api admin --current-version 2025-01 --target 2025-04 --use-direct-proxy

# Scan PHP Laravel project
shopify-query-analyzer analyze app/GraphQL/ --api admin --current-version 2025-01 --target 2025-10 --use-direct-proxy

# List available API versions
shopify-query-analyzer versions --use-direct-proxy
```

### With Authentication

```bash
# Admin API with token
shopify-query-analyzer analyze queries/ \
  --api admin \
  --shop myshop.myshopify.com \
  --admin-token $SHOPIFY_ADMIN_TOKEN \
  --target latest

# Storefront API
shopify-query-analyzer analyze queries/ \
  --api storefront \
  --shop myshop.myshopify.com \
  --storefront-token $SHOPIFY_STOREFRONT_TOKEN
```

### CI Mode

```bash
# JSON output for CI pipelines
shopify-query-analyzer analyze app/ --api admin --use-direct-proxy --output-format json

# Filter by file extension
shopify-query-analyzer analyze . --ext .php --ext .graphql --api admin --use-direct-proxy
```

### Using Local Schema Files

If the direct proxy doesn't work or you want offline analysis, you can provide pre-downloaded schema files:

```bash
# Download schemas first (e.g., from Hydrogen packages or manual introspection)
# Then analyze using local files
shopify-query-analyzer analyze app/GraphQL/ \
  --current-schema-file ./schemas/admin-2024-10.json \
  --target-schema-file ./schemas/admin-2025-01.json
```

## Options

| Option | Description |
|--------|-------------|
| `--api` | API type: `admin` or `storefront` (default: `admin`) |
| `--current-version` | The API version your code currently targets (e.g., `2024-10`) |
| `--target` | Target version to compare against: `latest`, version string, or `unstable` |
| `--shop` | Shop domain (e.g., `myshop.myshopify.com`) |
| `--admin-token` | Admin API access token (or set `SHOPIFY_ADMIN_TOKEN` env var) |
| `--storefront-token` | Storefront API token (or set `SHOPIFY_STOREFRONT_TOKEN` env var) |
| `--use-direct-proxy` | Use Shopify's direct proxy (no authentication required) |
| `--format` | Output format: `human` or `json` (default: `human`) |
| `--ext` | Filter files by extension (can be used multiple times) |
| `--current-schema-file` | Path to local schema JSON file for current version |
| `--target-schema-file` | Path to local schema JSON file for target version |
| `--cache-dir` | Directory for caching schemas (default: `.cache/shopify-schema`) |
| `--force-refresh` | Force re-download of schemas (ignore cache) |

## Output

### Human-readable Output

```
app/GraphQL/Queries/Products.php:45:5
  ⚠ Order.billingAddress is deprecated
    Reason: Use Order.shopAddress instead
    Status: Deprecated in 2024-10, removed in 2025-01

app/GraphQL/Queries/Orders.php:23:3
  ✗ Order.legacyField does not exist
    Status: Breaks on upgrade to 2025-01
```

### JSON Output

```json
{
  "summary": {
    "total_queries": 15,
    "valid": 12,
    "deprecated": 2,
    "breaking": 1
  },
  "issues": [
    {
      "file": "app/GraphQL/Queries/Products.php",
      "line": 45,
      "column": 5,
      "severity": "warning",
      "type": "deprecated",
      "field": "Order.billingAddress",
      "reason": "Use Order.shopAddress instead"
    }
  ]
}
```

## Supported File Types

| Extension | Extraction Method |
|-----------|-------------------|
| `.graphql`, `.gql` | Entire file content |
| `.php` | Heredoc syntax: `<<<QUERY ... QUERY;` |

## License

MIT

