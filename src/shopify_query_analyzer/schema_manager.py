"""Schema manager - downloads, caches, and manages Shopify GraphQL schemas."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from graphql import build_client_schema, GraphQLSchema, IntrospectionQuery

from .config import ApiType, AuthConfig


# Standard GraphQL introspection query
INTROSPECTION_QUERY = """
query IntrospectionQuery {
  __schema {
    queryType { name }
    mutationType { name }
    subscriptionType { name }
    types {
      ...FullType
    }
    directives {
      name
      description
      locations
      args {
        ...InputValue
      }
    }
  }
}

fragment FullType on __Type {
  kind
  name
  description
  fields(includeDeprecated: true) {
    name
    description
    args {
      ...InputValue
    }
    type {
      ...TypeRef
    }
    isDeprecated
    deprecationReason
  }
  inputFields {
    ...InputValue
  }
  interfaces {
    ...TypeRef
  }
  enumValues(includeDeprecated: true) {
    name
    description
    isDeprecated
    deprecationReason
  }
  possibleTypes {
    ...TypeRef
  }
}

fragment InputValue on __InputValue {
  name
  description
  type {
    ...TypeRef
  }
  defaultValue
  isDeprecated
  deprecationReason
}

fragment TypeRef on __Type {
  kind
  name
  ofType {
    kind
    name
    ofType {
      kind
      name
      ofType {
        kind
        name
        ofType {
          kind
          name
          ofType {
            kind
            name
            ofType {
              kind
              name
              ofType {
                kind
                name
              }
            }
          }
        }
      }
    }
  }
}
"""

# Query to get available API versions
PUBLIC_API_VERSIONS_QUERY = """
query {
  publicApiVersions {
    handle
    displayName
    supported
  }
}
"""


@dataclass
class CacheMetadata:
    """Metadata for cached schema files."""

    version: str
    api: str
    fetched_at: str
    etag: Optional[str] = None
    ttl_hours: int = 24

    def is_expired(self) -> bool:
        """Check if the cached schema has expired."""
        fetched = datetime.fromisoformat(self.fetched_at)
        age_hours = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        return age_hours > self.ttl_hours


@dataclass
class ApiVersion:
    """Represents a Shopify API version."""

    handle: str  # e.g., "2024-10"
    display_name: str  # e.g., "October 2024"
    supported: bool


class SchemaManager:
    """
    Manages downloading and caching of Shopify GraphQL schemas.

    Handles:
    - Version discovery via publicApiVersions query
    - Schema introspection
    - Disk caching with TTL
    - Building GraphQL schema objects
    """

    def __init__(
        self,
        auth: AuthConfig,
        cache_dir: Path = Path(".cache/shopify-schema"),
        timeout: float = 30.0,
    ) -> None:
        """
        Initialize the schema manager.

        Args:
            auth: Authentication configuration
            cache_dir: Directory for caching schemas
            timeout: HTTP request timeout in seconds
        """
        self.auth = auth
        self.cache_dir = cache_dir
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "SchemaManager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_cache_path(self, api: ApiType, version: str) -> Path:
        """Get the cache file path for a schema."""
        return self.cache_dir / api.value / f"{version}.json"

    def get_metadata_path(self, api: ApiType, version: str) -> Path:
        """Get the metadata file path for a cached schema."""
        return self.cache_dir / api.value / f"{version}.meta.json"

    def get_available_versions(self, api: ApiType) -> list[ApiVersion]:
        """
        Fetch available API versions from Shopify.

        Args:
            api: The API type (admin or storefront)

        Returns:
            List of available versions
        """
        # For direct proxy, we need to use a valid version to query
        # The direct proxy only supports 2025-01 and newer
        query_version = "2025-01" if self.auth.use_direct_proxy else "2024-10"
        endpoint = self.auth.get_endpoint(api, query_version)
        headers = self.auth.get_headers(api)

        response = self.client.post(
            endpoint,
            json={"query": PUBLIC_API_VERSIONS_QUERY},
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {data['errors']}")

        versions = []
        for v in data.get("data", {}).get("publicApiVersions", []):
            versions.append(
                ApiVersion(
                    handle=v["handle"],
                    display_name=v["displayName"],
                    supported=v["supported"],
                )
            )

        return versions

    def resolve_version(self, api: ApiType, version_spec: str) -> str:
        """
        Resolve a version specification to an actual version string.

        Args:
            api: The API type
            version_spec: Version specification (e.g., "latest", "2024-10", "unstable")

        Returns:
            Resolved version string
        """
        if version_spec in ("unstable",):
            return version_spec

        if version_spec == "latest":
            versions = self.get_available_versions(api)
            # Find the latest supported version (not unstable)
            supported = [v for v in versions if v.supported and v.handle != "unstable"]
            if not supported:
                raise RuntimeError("No supported versions found")
            # Versions are typically sorted newest first
            return supported[0].handle

        # Assume it's a specific version string
        return version_spec

    def fetch_schema(self, api: ApiType, version: str) -> dict[str, Any]:
        """
        Fetch schema via introspection query.

        Args:
            api: The API type
            version: API version string

        Returns:
            Introspection result data
        """
        endpoint = self.auth.get_endpoint(api, version)
        headers = self.auth.get_headers(api)

        response = self.client.post(
            endpoint,
            json={"query": INTROSPECTION_QUERY},
            headers=headers,
        )

        # Handle non-2xx responses
        if response.status_code != 200:
            # Check if it's an invalid version error from the direct proxy
            try:
                error_data = response.json()
                if error_data.get("error") == "Invalid API version":
                    if self.auth.use_direct_proxy:
                        raise RuntimeError(
                            f"API version '{version}' is not supported by the direct proxy. "
                            f"The direct proxy only supports recent versions (2025-01 and newer). "
                            f"Try using --current-version 2025-01 --target 2025-04, "
                            f"or use shop credentials instead of --use-direct-proxy."
                        )
                    raise RuntimeError(f"Invalid API version: {version}")
            except (ValueError, KeyError):
                pass
            response.raise_for_status()

        data = response.json()

        # Check for error field (direct proxy returns this instead of HTTP error)
        if "error" in data:
            error_msg = data["error"]
            if error_msg == "Invalid API version" and self.auth.use_direct_proxy:
                raise RuntimeError(
                    f"API version '{version}' is not supported by the direct proxy. "
                    f"The direct proxy only supports recent versions (2025-01 and newer). "
                    f"Try using --current-version 2025-01 --target 2025-04, "
                    f"or use shop credentials instead of --use-direct-proxy."
                )
            raise RuntimeError(f"API error: {error_msg}")

        if "errors" in data:
            raise RuntimeError(f"Introspection errors: {data['errors']}")

        return data.get("data", {})

    def load_cached_schema(self, api: ApiType, version: str) -> Optional[dict[str, Any]]:
        """
        Load a schema from cache if available and not expired.

        Args:
            api: The API type
            version: API version

        Returns:
            Cached schema data, or None if not cached/expired
        """
        cache_path = self.get_cache_path(api, version)
        meta_path = self.get_metadata_path(api, version)

        if not cache_path.exists() or not meta_path.exists():
            return None

        try:
            meta_data = json.loads(meta_path.read_text())
            metadata = CacheMetadata(**meta_data)

            if metadata.is_expired():
                return None

            return json.loads(cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def save_to_cache(
        self,
        api: ApiType,
        version: str,
        schema_data: dict[str, Any],
        etag: Optional[str] = None,
    ) -> None:
        """
        Save schema data to cache.

        Args:
            api: The API type
            version: API version
            schema_data: Introspection data to cache
            etag: Optional ETag from response
        """
        cache_path = self.get_cache_path(api, version)
        meta_path = self.get_metadata_path(api, version)

        # Ensure directory exists
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        # Save schema
        cache_path.write_text(json.dumps(schema_data, indent=2))

        # Save metadata
        metadata = CacheMetadata(
            version=version,
            api=api.value,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            etag=etag,
        )
        meta_path.write_text(
            json.dumps(
                {
                    "version": metadata.version,
                    "api": metadata.api,
                    "fetched_at": metadata.fetched_at,
                    "etag": metadata.etag,
                    "ttl_hours": metadata.ttl_hours,
                }
            )
        )

    def get_schema(
        self,
        api: ApiType,
        version: str,
        force_refresh: bool = False,
    ) -> GraphQLSchema:
        """
        Get a GraphQL schema, using cache when available.

        Args:
            api: The API type
            version: API version (can be "latest", specific version, or "unstable")
            force_refresh: Force re-fetch even if cached

        Returns:
            Built GraphQL schema object
        """
        # Resolve version specification
        resolved_version = self.resolve_version(api, version)

        # Try cache first
        if not force_refresh:
            cached = self.load_cached_schema(api, resolved_version)
            if cached:
                return build_client_schema(cached)

        # Fetch fresh schema
        schema_data = self.fetch_schema(api, resolved_version)

        # Cache it
        self.save_to_cache(api, resolved_version, schema_data)

        return build_client_schema(schema_data)

    def get_schema_hash(self, api: ApiType, version: str) -> str:
        """
        Get a hash of the schema for comparison purposes.

        Args:
            api: The API type
            version: API version

        Returns:
            SHA256 hash of the schema
        """
        cache_path = self.get_cache_path(api, version)
        if cache_path.exists():
            content = cache_path.read_bytes()
        else:
            schema_data = self.fetch_schema(api, version)
            content = json.dumps(schema_data, sort_keys=True).encode()

        return hashlib.sha256(content).hexdigest()[:16]

    def load_schema_from_file(self, schema_file: Path) -> GraphQLSchema:
        """
        Load a schema from a local JSON file.

        This is useful when the direct proxy doesn't work or when you have
        pre-downloaded schema files (e.g., from Hydrogen packages).

        Args:
            schema_file: Path to the schema JSON file (introspection result)

        Returns:
            Built GraphQL schema object
        """
        content = schema_file.read_text(encoding="utf-8")
        schema_data = json.loads(content)

        # Handle both wrapped and unwrapped introspection results
        if "data" in schema_data:
            schema_data = schema_data["data"]
        if "__schema" not in schema_data:
            raise ValueError(
                f"Invalid schema file: {schema_file}. "
                "Expected introspection result with __schema key."
            )

        return build_client_schema(schema_data)

