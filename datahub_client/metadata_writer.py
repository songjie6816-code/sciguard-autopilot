"""Write reviewed risk tags and incident context back to DataHub.

This is the "acting" half of SciGuard's loop. It always uses read-modify-write:
DataHub aspects like GlobalTags are replace-on-write, so writing our tag without
merging the existing ones would silently erase other teams' metadata.
"""

from __future__ import annotations

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph
from datahub.metadata.schema_classes import GlobalTagsClass, TagAssociationClass


def _current_tag_urns(graph: DataHubGraph, urn: str) -> list[str]:
    data = graph.execute_graphql(
        "query t($urn:String!){dataset(urn:$urn){globalTags{tags{tag{urn}}}}}",
        variables={"urn": urn},
    )
    tags = ((data["dataset"] or {}).get("globalTags") or {}).get("tags") or []
    return [t["tag"]["urn"] for t in tags]


def add_tags(graph: DataHubGraph, urn: str, tag_urns: list[str]) -> list[str]:
    """Attach tags to an entity without dropping tags already present.

    Returns the full tag set after the write. Idempotent: re-adding an existing
    tag is a no-op.
    """
    existing = _current_tag_urns(graph, urn)
    merged = list(dict.fromkeys([*existing, *tag_urns]))  # union, order-stable
    if merged == existing:
        return existing
    graph.emit(
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=t) for t in merged]),
        )
    )
    return merged


def remove_tags(graph: DataHubGraph, urn: str, tag_urns: list[str]) -> list[str]:
    """Remove specific tags, leaving all others intact. Returns the remaining set."""
    drop = set(tag_urns)
    existing = _current_tag_urns(graph, urn)
    remaining = [t for t in existing if t not in drop]
    if remaining == existing:
        return existing
    graph.emit(
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=t) for t in remaining]),
        )
    )
    return remaining
