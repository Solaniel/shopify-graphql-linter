"""Configuration models for the Shopify Query Analyzer."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ApiType(str, Enum):
    """Supported Shopify API types."""

    ADMIN = "admin"
    STOREFRONT = "storefront"


class OutputFormat(str, Enum):
    """Output format options."""

    HUMAN = "human"
    JSON = "json"


class AuthConfig(BaseModel):
    """Authentication configuration."""

    shop: Optional[str] = Field(None, description="Shop domain (e.g., myshop.myshopify.com)")
    admin_token: Optional[str] = Field(None, description="Admin API access token")
    storefront_token: Optional[str] = Field(None, description="Storefront API token")
    use_direct_proxy: bool = Field(False, description="Use Shopify's direct proxy (no auth)")

    def get_endpoint(self, api: ApiType, version: str) -> str:
        """Get the GraphQL endpoint URL for the given API and version."""
        if self.use_direct_proxy:
            if api == ApiType.ADMIN:
                return f"https://shopify.dev/admin-graphql-direct-proxy/{version}"
            else:
                return f"https://shopify.dev/storefront-graphql-direct-proxy/{version}"

        if not self.shop:
            raise ValueError("Shop domain is required when not using direct proxy")

        shop = self.shop.rstrip("/")
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"

        if api == ApiType.ADMIN:
            return f"https://{shop}/admin/api/{version}/graphql.json"
        else:
            return f"https://{shop}/api/{version}/graphql.json"

    def get_headers(self, api: ApiType) -> dict[str, str]:
        """Get authentication headers for the given API type."""
        headers = {"Content-Type": "application/json"}

        if self.use_direct_proxy:
            return headers

        if api == ApiType.ADMIN:
            if not self.admin_token:
                raise ValueError("Admin token is required for Admin API")
            headers["X-Shopify-Access-Token"] = self.admin_token
        else:
            if not self.storefront_token:
                raise ValueError("Storefront token is required for Storefront API")
            headers["X-Shopify-Storefront-Access-Token"] = self.storefront_token

        return headers


class AnalyzerConfig(BaseModel):
    """Main configuration for the analyzer."""

    paths: list[Path] = Field(..., description="Paths to scan for GraphQL queries")
    api: ApiType = Field(ApiType.ADMIN, description="Shopify API type")
    current_version: Optional[str] = Field(
        None, description="Current API version (e.g., 2024-10)"
    )
    target: str = Field("latest", description="Target version to compare against")
    auth: AuthConfig = Field(default_factory=AuthConfig)
    output_format: OutputFormat = Field(OutputFormat.HUMAN, description="Output format")
    extensions: Optional[list[str]] = Field(
        None, description="File extensions to filter (e.g., ['.php', '.graphql'])"
    )
    cache_dir: Path = Field(
        Path(".cache/shopify-schema"), description="Directory for caching schemas"
    )

    class Config:
        arbitrary_types_allowed = True

