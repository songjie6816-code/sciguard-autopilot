"""Read scientific-data context (search, schema, ownership, lineage) from DataHub.

Wraps the DataHub Python SDK graph client. All functions are read-only; they are
the "sensing" half of SciGuard's loop that turns a raw data change into an
accountable, multi-hop impact analysis.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
    OwnershipClass,
    UpstreamLineageClass,
)

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
    """Return owner identifiers for any entity type (dataset, model, ...).

    Reads the Ownership aspect directly, so it works regardless of the entity's
    GraphQL type; the id is the last segment of each owner urn.
    """
    aspect = graph.get_aspect(urn, OwnershipClass)
    if not aspect or not aspect.owners:
        return []
    return [owner.owner.split(":")[-1] for owner in aspect.owners]


def get_native_ml_model_context(
    graph: DataHubGraph,
    dataset_projection_urn: str,
) -> dict:
    """Resolve the native model/deployment behind a field-lineage dataset projection."""

    dataset = graph.get_aspect(dataset_projection_urn, DatasetPropertiesClass)
    if dataset is None:
        raise LookupError(f"dataset projection is missing: {dataset_projection_urn}")
    properties = dict(dataset.customProperties or {})
    model_urn = properties.get("sciguard:native_projection_urn")
    if not model_urn:
        raise LookupError(
            f"dataset projection has no native ML model: {dataset_projection_urn}"
        )
    model = graph.get_aspect(model_urn, MLModelPropertiesClass)
    if model is None:
        raise LookupError(f"native ML model is missing: {model_urn}")
    deployment_urns = list(model.deployments or [])
    configured_deployment = properties.get("sciguard:native_deployment_urn")
    if configured_deployment and configured_deployment not in deployment_urns:
        deployment_urns.append(configured_deployment)
    deployments = []
    for urn in deployment_urns:
        deployment = graph.get_aspect(urn, MLModelDeploymentPropertiesClass)
        if deployment is None:
            raise LookupError(f"native ML deployment is missing: {urn}")
        deployments.append(
            {
                "urn": urn,
                "status": deployment.status,
                "custom_properties": dict(deployment.customProperties or {}),
            }
        )
    ownership = graph.get_aspect(model_urn, OwnershipClass)
    return {
        "dataset_projection_urn": dataset_projection_urn,
        "native_model_urn": model_urn,
        "model_name": model.name,
        "model_version": model.version.versionTag if model.version else None,
        "model_type": model.type,
        "feature_urns": list(model.mlFeatures or []),
        "training_job_urns": list(model.trainingJobs or []),
        "inference_job_urns": list(model.downstreamJobs or []),
        "deployment_context": deployments,
        "owner_urns": [item.owner for item in ownership.owners] if ownership else [],
        "custom_properties": dict(model.customProperties or {}),
    }


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


_IMPACT_QUERY = """
query impact($input: SearchAcrossLineageInput!) {
  searchAcrossLineage(input: $input) {
    total
    searchResults {
      degree
      entity { urn type ... on Dataset { name } }
    }
  }
}
"""


def get_all_downstream(graph: DataHubGraph, urn: str, page_size: int = 100) -> list[DownstreamHit]:
    """Return every entity downstream of `urn`, multi-hop, with its hop distance.

    Uses searchAcrossLineage and paginates through `total`, so a large impact
    cone is never silently truncated.
    """
    return _get_all_lineage(graph, urn, "DOWNSTREAM", page_size)


def get_all_upstream(graph: DataHubGraph, urn: str, page_size: int = 100) -> list[DownstreamHit]:
    """Return every upstream entity, ordered by reverse-lineage distance."""

    return _get_all_lineage(graph, urn, "UPSTREAM", page_size)


def _get_all_lineage(
    graph: DataHubGraph,
    urn: str,
    direction: str,
    page_size: int,
) -> list[DownstreamHit]:
    out: list[DownstreamHit] = []
    start = 0
    while True:
        data = graph.execute_graphql(
            _IMPACT_QUERY,
            variables={
                "input": {
                    "urn": urn,
                    "direction": direction,
                    "query": "*",
                    "start": start,
                    "count": page_size,
                }
            },
        )
        block = data["searchAcrossLineage"] or {}
        results = block.get("searchResults") or []
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
        start += len(results)
        if not results or start >= (block.get("total") or 0):
            break
    out.sort(key=lambda h: h.degree)
    return out


def get_asset_context(graph: DataHubGraph, urn: str) -> dict:
    """Read governance and release context used by the WP3 Investigator.

    Assertion associations and their recent runs are returned when present. An empty
    list means DataHub was queried successfully and this asset currently has no runs.
    """

    data = graph.execute_graphql(
        """
        query context($urn: String!) {
          dataset(urn: $urn) {
            urn
            properties { name customProperties { key value } }
            tags { tags { tag { urn } } }
            glossaryTerms { terms { term { urn } } }
            assertions(start: 0, count: 20) {
              assertions {
                urn
                info { type description }
                runEvents(limit: 20) {
                  runEvents {
                    timestampMillis
                    status
                    result { type unexpectedCount }
                  }
                }
              }
            }
          }
        }
        """,
        variables={"urn": urn},
    )
    entity = data.get("dataset")
    if not entity:
        raise LookupError(f"DataHub dataset not found: {urn}")
    props = entity.get("properties") or {}
    custom = {item["key"]: item["value"] for item in props.get("customProperties") or []}
    tags = (entity.get("tags") or {}).get("tags") or []
    terms = (entity.get("glossaryTerms") or {}).get("terms") or []
    assertions = (entity.get("assertions") or {}).get("assertions") or []
    history = []
    for assertion in assertions:
        for run in (assertion.get("runEvents") or {}).get("runEvents") or []:
            history.append(
                {
                    "assertion_urn": assertion["urn"],
                    "type": (assertion.get("info") or {}).get("type"),
                    "description": (assertion.get("info") or {}).get("description"),
                    "timestamp_ms": run["timestampMillis"],
                    "status": run["status"],
                    "result": run.get("result"),
                }
            )
    history.sort(key=lambda item: item["timestamp_ms"], reverse=True)
    return {
        "urn": urn,
        "name": props.get("name") or urn,
        "owners": get_owners(graph, urn),
        "tags": [item["tag"]["urn"] for item in tags],
        "terms": [item["term"]["urn"] for item in terms],
        "properties": custom,
        "assertion_history": history,
        "assertions_supported": True,
    }


def get_fine_grained_lineage(graph: DataHubGraph, urn: str) -> list[tuple[str, str]]:
    """Return direct ``(upstream field URN, downstream field URN)`` mappings."""

    aspect = graph.get_aspect(urn, UpstreamLineageClass)
    if not aspect:
        return []
    return [
        (upstream, downstream)
        for mapping in aspect.fineGrainedLineages or []
        for upstream in mapping.upstreams
        for downstream in mapping.downstreams
    ]


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
