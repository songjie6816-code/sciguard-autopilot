"""Read DataHub context through the DataHub MCP Server.

This is SciGuard's use of the DataHub MCP Server: instead of hand-written GraphQL,
context reads (search, lineage, schema, ownership, units) go through the MCP
Server's tools — the same tools an LLM agent would call. It exposes the same
method surface as the SDK reader (see datahub_client.backends.SdkReader) so the
two are interchangeable backends.

The MCP server speaks stdio; we keep one long-lived session on a background event
loop and drive it with blocking, sync methods.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import threading
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from datahub_client import metadata_reader
from datahub_client.metadata_reader import DatasetHit, DownstreamHit

DEFAULT_GMS_URL = "http://localhost:8080"


def _server_command() -> str:
    found = shutil.which("mcp-server-datahub")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/mcp-server-datahub")
    if os.path.exists(fallback):
        return fallback
    raise RuntimeError(
        "mcp-server-datahub not found. Install it with: "
        "uv tool install mcp-server-datahub@latest"
    )


def _platform_of(urn: str) -> str | None:
    # urn:li:dataset:(urn:li:dataPlatform:<platform>,<name>,<env>)
    marker = "urn:li:dataPlatform:"
    if marker in urn:
        return urn.split(marker, 1)[1].split(",", 1)[0]
    return None


class DataHubMCP:
    """A blocking client over the DataHub MCP Server (one persistent session)."""

    def __init__(self, gms_url: str | None = None, token: str | None = None) -> None:
        env = dict(os.environ)
        env["DATAHUB_GMS_URL"] = gms_url or os.environ.get("DATAHUB_GMS_URL", DEFAULT_GMS_URL)
        # The local Quickstart has auth disabled, so any token value is accepted.
        env["DATAHUB_GMS_TOKEN"] = token or os.environ.get("DATAHUB_GMS_TOKEN", "local-quickstart")
        self._params = StdioServerParameters(command=_server_command(), args=[], env=env)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._fine_lineage_graph = None
        self._run(self._start(), timeout=180)

    async def _start(self) -> None:
        self._stack = AsyncExitStack()
        errlog = open(os.devnull, "w")  # noqa: SIM115 - kept open for the session's life
        read, write = await self._stack.enter_async_context(stdio_client(self._params, errlog=errlog))
        self._session = await self._stack.enter_async_context(ClientSession(read, write))
        await self._session.initialize()

    def _run(self, coro, timeout: float = 60):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout=timeout)

    def _call(self, tool: str, args: dict) -> object:
        res = self._run(self._session.call_tool(tool, args))
        body = "".join(getattr(c, "text", "") for c in res.content)
        return json.loads(body) if body else None

    def close(self) -> None:
        if self._stack is not None:
            try:
                self._run(self._stack.aclose())
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
            self._stack = None
        self._loop.call_soon_threadsafe(self._loop.stop)

    def __enter__(self) -> "DataHubMCP":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- reader interface (mirrors datahub_client.backends.SdkReader) ---

    def search_datasets(self, query: str = "*", count: int = 100) -> list[DatasetHit]:
        data = self._call("search", {"query": query, "num_results": count})
        out: list[DatasetHit] = []
        for r in (data or {}).get("searchResults", []):
            ent = r.get("entity", {})
            out.append(
                DatasetHit(
                    urn=ent["urn"],
                    name=(ent.get("properties") or {}).get("name"),
                    platform=_platform_of(ent["urn"]),
                )
            )
        return out

    def get_all_downstream(self, urn: str) -> list[DownstreamHit]:
        return self._get_all_lineage(urn, upstream=False)

    def get_all_upstream(self, urn: str) -> list[DownstreamHit]:
        return self._get_all_lineage(urn, upstream=True)

    def _get_all_lineage(self, urn: str, *, upstream: bool) -> list[DownstreamHit]:
        data = self._call("get_lineage", {"urn": urn, "upstream": upstream, "max_hops": 20})
        block_name = "upstreams" if upstream else "downstreams"
        results = ((data or {}).get(block_name) or {}).get("searchResults") or []
        out: list[DownstreamHit] = []
        for r in results:
            ent = r.get("entity", {})
            out.append(
                DownstreamHit(
                    urn=ent["urn"],
                    name=(ent.get("properties") or {}).get("name"),
                    entity_type=ent.get("type"),
                    degree=r.get("degree", 0),
                )
            )
        out.sort(key=lambda h: h.degree)
        return out

    def get_schema_fields(self, urn: str) -> list[dict]:
        data = self._call("list_schema_fields", {"urn": urn})
        return [
            {"path": f["fieldPath"], "type": None, "nativeType": f.get("nativeDataType")}
            for f in (data or {}).get("fields", [])
        ]

    def _entity(self, urn: str) -> dict:
        data = self._call("get_entities", {"urns": [urn]})
        return (data or [{}])[0] if data else {}

    def get_units(self, urn: str) -> dict[str, str]:
        custom = ((self._entity(urn).get("properties") or {}).get("customProperties")) or []
        return {c["key"][len("unit:"):]: c["value"] for c in custom if c["key"].startswith("unit:")}

    def get_owners(self, urn: str) -> list[str]:
        owners = (self._entity(urn).get("ownership") or {}).get("owners") or []
        return [o["owner"]["urn"].split(":")[-1] for o in owners]

    def get_asset_context(self, urn: str) -> dict:
        """Read MCP-exposed governance context without claiming unsupported history.

        The current DataHub MCP Server's ``get_entities`` tool does not expose assertion
        run events. ``assertions_supported=False`` makes that limitation visible instead
        of presenting an empty fabricated history as an observed fact.
        """

        entity = self._entity(urn)
        if not entity:
            raise LookupError(f"DataHub dataset not found through MCP: {urn}")
        props = entity.get("properties") or {}
        custom = {item["key"]: item["value"] for item in props.get("customProperties") or []}
        owners = (entity.get("ownership") or {}).get("owners") or []
        tags = (entity.get("tags") or {}).get("tags") or []
        terms = (entity.get("glossaryTerms") or {}).get("terms") or []
        return {
            "urn": urn,
            "name": props.get("name") or entity.get("name") or urn,
            "owners": [item["owner"]["urn"].split(":")[-1] for item in owners],
            "tags": [item["tag"]["urn"] for item in tags],
            "terms": [item["term"]["urn"] for item in terms],
            "properties": custom,
            "assertion_history": [],
            "assertions_supported": False,
        }

    def get_fine_grained_lineage(self, urn: str) -> list[tuple[str, str]]:
        """Read field mappings through the SDK until MCP exposes that aspect.

        The DataHub MCP Server currently exposes directed dataset lineage but not the
        ``fineGrainedLineages`` aspect. Keeping this fallback inside the reader makes
        the limitation explicit while preserving real MCP influence over schema,
        units, ownership, governance context, and the initial decision-path gate.
        """

        if self._fine_lineage_graph is None:
            self._fine_lineage_graph = metadata_reader.connect()
        return metadata_reader.get_fine_grained_lineage(self._fine_lineage_graph, urn)

    def capability_receipt(self) -> dict[str, object]:
        """Return the honest backend boundary for event provenance and UI receipts."""

        return {
            "required_component": "DATAHUB_MCP_SERVER",
            "mcp_tools": [
                "search",
                "get_lineage",
                "list_schema_fields",
                "get_entities",
            ],
            "decision_inputs_via_mcp": [
                "schema",
                "units",
                "dataset_lineage",
                "ownership",
                "governance_context",
            ],
            "sdk_fallbacks": ["fine_grained_lineage", "metadata_write_back"],
            "assertion_history_observable_via_mcp": False,
        }
