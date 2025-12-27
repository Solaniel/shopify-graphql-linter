"""Setup file for backwards compatibility with older pip versions."""

from setuptools import setup, find_packages

setup(
    name="shopify-query-analyzer",
    version="0.1.0",
    description="CLI tool to validate Shopify GraphQL queries against schema introspection",
    author="Branimir Petkov",
    python_requires=">=3.9",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    install_requires=[
        "typer>=0.9.0",
        "graphql-core>=3.2.0",
        "httpx>=0.25.0",
        "rich>=13.0.0",
        "pydantic>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "shopify-query-analyzer=shopify_query_analyzer.cli:app",
        ],
    },
)
