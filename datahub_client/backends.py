"""Pluggable read backends: the SDK reader and the MCP reader are interchangeable.

Both expose the same methods (search_datasets, get_all_downstream,
get_schema_fields, get_units, get_owners), so the loop reads context the same way
whether it goes through the DataHub SDK or the DataHub MCP Server. Choose with the
`SCIGUARD_USE_MCP` environment variable.
"""

from __future__ import annotations

import os

from datahub_client import metadata_reader as reader


class SdkReader:
    """Read backend backed by the DataHub Python SDK (GraphQL / get_aspect)."""

    def __init__(self, graph) -> None:
        self.graph = graph

    def search_datasets(self, query: str = "*", count: int = 100):
        return reader.search_datasets(self.graph, query, count)

    def get_all_downstream(self, urn: str):
        return reader.get_all_downstream(self.graph, urn)

    def get_all_upstream(self, urn: str):
        return reader.get_all_upstream(self.graph, urn)

    def get_schema_fields(self, urn: str):
        return reader.get_schema_fields(self.graph, urn)

    def get_units(self, urn: str):
        return reader.get_units(self.graph, urn)

    def get_owners(self, urn: str):
        return reader.get_owners(self.graph, urn)

    def get_asset_context(self, urn: str):
        return reader.get_asset_context(self.graph, urn)

    def get_fine_grained_lineage(self, urn: str):
        return reader.get_fine_grained_lineage(self.graph, urn)

    def close(self) -> None:  # symmetry with the MCP backend
        pass


def open_reader(use_mcp: bool | None = None):
    """Return a read backend. Uses the MCP Server when `use_mcp` (or the
    SCIGUARD_USE_MCP env var) is set, otherwise the SDK."""
    if use_mcp is None:
        use_mcp = os.environ.get("SCIGUARD_USE_MCP", "").lower() in {"1", "true", "yes"}
    if use_mcp:
        from datahub_client.mcp_client import DataHubMCP

        return DataHubMCP()
    return SdkReader(reader.connect())
