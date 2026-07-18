"""Read scientific-data context (search, schema, ownership, lineage) from DataHub.

Wraps the DataHub Python SDK graph client. All functions are read-only; they are
the "sensing" half of SciGuard's loop that turns a raw data change into an
accountable, multi-hop impact analysis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig

DEFAULT_GMS_URL = "http://localhost:8080"


def _gms_url() -> str:
    return os.environ.get("DATAHUB_GMS_URL", DEFAULT_GMS_URL)


def connect() -> DataHubGraph:
    """Open a graph client to GMS. Raises if the server is unreachable."""
    token = os.environ.get("DATAHUB_TOKEN") or None
    graph = DataHubGraph(DatahubClientConfig(server=_gms_url(), token=token))
    graph.test_connection()
    return graph


@dataclass(frozen=True)
class DatasetHit:
    urn: str
    name: str | None
    platform: str | None


def search_datasets(graph: DataHubGraph, query: str = "*", count: int = 20) -> list[DatasetHit]:
    """Full-text search over datasets. `query='*'` returns everything."""
    data = graph.execute_graphql(
        """
        query search($input: SearchAcrossEntitiesInput!) {
          searchAcrossEntities(input: $input) {
            total
            searchResults {
              entity {
                urn
                ... on Dataset { name platform { name } }
              }
            }
          }
        }
        """,
        variables={"input": {"types": ["DATASET"], "query": query, "start": 0, "count": count}},
    )
    hits = data["searchAcrossEntities"]["searchResults"]
    out: list[DatasetHit] = []
    for h in hits:
        ent = h["entity"]
        out.append(
            DatasetHit(
                urn=ent["urn"],
                name=ent.get("name"),
                platform=(ent.get("platform") or {}).get("name"),
            )
        )
    return out


def get_schema_fields(graph: DataHubGraph, urn: str) -> list[dict]:
    """Return each schema field as {path, type, nativeType}."""
    data = graph.execute_graphql(
        """
        query schema($urn: String!) {
          dataset(urn: $urn) {
            schemaMetadata { fields { fieldPath type nativeDataType } }
          }
        }
        """,
        variables={"urn": urn},
    )
    fields = ((data["dataset"] or {}).get("schemaMetadata") or {}).get("fields") or []
    return [
        {"path": f["fieldPath"], "type": f.get("type"), "nativeType": f.get("nativeDataType")}
        for f in fields
    ]


def get_owners(graph: DataHubGraph, urn: str) -> list[str]:
    """Return owner identifiers (usernames or group names) for an entity."""
    data = graph.execute_graphql(
        """
        query owners($urn: String!) {
          dataset(urn: $urn) {
            ownership { owners { owner {
              ... on CorpUser { username }
              ... on CorpGroup { name }
            } } }
          }
        }
        """,
        variables={"urn": urn},
    )
    owners = ((data["dataset"] or {}).get("ownership") or {}).get("owners") or []
    return [o["owner"].get("username") or o["owner"].get("name") for o in owners]


def get_dataset_properties(graph: DataHubGraph, urn: str) -> dict:
    """Return {name, description, customProperties} for a dataset.

    Units are stored as custom properties keyed "unit:<field>", so this is how
    SciGuard reads a dataset's declared units.
    """
    data = graph.execute_graphql(
        """
        query props($urn: String!) {
          dataset(urn: $urn) {
            properties { name description customProperties { key value } }
          }
        }
        """,
        variables={"urn": urn},
    )
    props = (data["dataset"] or {}).get("properties") or {}
    custom = {p["key"]: p["value"] for p in (props.get("customProperties") or [])}
    return {
        "name": props.get("name"),
        "description": props.get("description"),
        "customProperties": custom,
    }


def get_units(graph: DataHubGraph, urn: str) -> dict[str, str]:
    """Return {field: unit} parsed from the dataset's "unit:<field>" properties."""
    custom = get_dataset_properties(graph, urn)["customProperties"]
    return {k[len("unit:"):]: v for k, v in custom.items() if k.startswith("unit:")}


@dataclass(frozen=True)
class DownstreamHit:
    urn: str
    name: str | None
    entity_type: str | None
    degree: int


def get_all_downstream(graph: DataHubGraph, urn: str, count: int = 100) -> list[DownstreamHit]:
    """Return every entity downstream of `urn`, multi-hop, with its hop distance.

    Uses searchAcrossLineage, so a single call walks the whole impact cone
    instead of hopping one edge at a time.
    """
    data = graph.execute_graphql(
        """
        query impact($input: SearchAcrossLineageInput!) {
          searchAcrossLineage(input: $input) {
            total
            searchResults {
              degree
              entity { urn type ... on Dataset { name } }
            }
          }
        }
        """,
        variables={
            "input": {
                "urn": urn,
                "direction": "DOWNSTREAM",
                "query": "*",
                "start": 0,
                "count": count,
            }
        },
    )
    results = (data["searchAcrossLineage"] or {}).get("searchResults") or []
    out: list[DownstreamHit] = []
    for r in results:
        ent = r["entity"]
        out.append(
            DownstreamHit(
                urn=ent["urn"],
                name=ent.get("name"),
                entity_type=ent.get("type"),
                degree=r.get("degree", 0),
            )
        )
    out.sort(key=lambda h: h.degree)
    return out


def get_lineage(graph: DataHubGraph, urn: str, direction: str = "DOWNSTREAM") -> list[str]:
    """Return URNs one hop up- or downstream of `urn`.

    `direction` is "DOWNSTREAM" (what this feeds) or "UPSTREAM" (what feeds it).
    """
    data = graph.execute_graphql(
        """
        query lineage($urn: String!, $dir: LineageDirection!) {
          entity(urn: $urn) {
            ... on Dataset {
              lineage(input: { direction: $dir, start: 0, count: 100 }) {
                relationships { entity { urn } }
              }
            }
          }
        }
        """,
        variables={"urn": urn, "dir": direction},
    )
    ent = data.get("entity") or {}
    rels = (ent.get("lineage") or {}).get("relationships") or []
    return [r["entity"]["urn"] for r in rels]
