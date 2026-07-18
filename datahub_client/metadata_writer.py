"""Write reviewed risk tags and incident context back to DataHub.

This is the "acting" half of SciGuard's loop. Every write is read-modify-write
on the *whole* aspect: DataHub aspects (GlobalTags, DatasetProperties) are
replace-on-write, so we fetch the full existing aspect with get_aspect, change
only the field we mean to, and re-emit it. Reading back a subset of fields (as
an earlier version did) would silently null the fields left out.
"""

from __future__ import annotations

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.ingestion.graph.client import DataHubGraph
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    TagAssociationClass,
)


def current_tag_urns(graph: DataHubGraph, urn: str) -> list[str]:
    existing = graph.get_aspect(urn, GlobalTagsClass)
    return [a.tag for a in existing.tags] if existing else []


def add_tags(graph: DataHubGraph, urn: str, tag_urns: list[str]) -> list[str]:
    """Attach tags to an entity without dropping tags already present or their
    per-tag attribution. Returns the full tag set after the write. Idempotent."""
    existing = graph.get_aspect(urn, GlobalTagsClass)
    associations = list(existing.tags) if existing else []
    have = {a.tag for a in associations}
    to_add = [t for t in tag_urns if t not in have]
    if not to_add:
        return [a.tag for a in associations]
    associations.extend(TagAssociationClass(tag=t) for t in to_add)
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=GlobalTagsClass(tags=associations)))
    return [a.tag for a in associations]


def remove_tags(graph: DataHubGraph, urn: str, tag_urns: list[str]) -> list[str]:
    """Remove specific tags, leaving all others (and their attribution) intact."""
    existing = graph.get_aspect(urn, GlobalTagsClass)
    if not existing:
        return []
    drop = set(tag_urns)
    remaining = [a for a in existing.tags if a.tag not in drop]
    if len(remaining) == len(existing.tags):
        return [a.tag for a in existing.tags]
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=GlobalTagsClass(tags=remaining)))
    return [a.tag for a in remaining]


def add_custom_properties(graph: DataHubGraph, urn: str, new_props: dict[str, str]) -> dict[str, str]:
    """Merge custom properties onto a dataset, preserving the entire existing
    DatasetProperties aspect (name, externalUrl, description, ...). Returns the
    merged custom-property map."""
    existing = graph.get_aspect(urn, DatasetPropertiesClass)
    if existing is None:
        existing = DatasetPropertiesClass(customProperties={})
    current = dict(existing.customProperties or {})
    merged = {**current, **new_props}
    if merged == current:
        return current
    existing.customProperties = merged
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=existing))
    return merged
