"""Incident-scoped cleanup that preserves every non-SciGuard metadata field."""

from __future__ import annotations

import json

from datahub.metadata.schema_classes import DatasetPropertiesClass
from pydantic import BaseModel

from core.enforcement import STATUS_TAGS
from datahub_client.metadata_writer import remove_custom_properties, remove_tags


class ResetReceipt(BaseModel):
    incident_id: str
    reset_urns: list[str]
    skipped_urns: list[str]
    removed_property_count: int


def reset_incident_metadata(graph, control_urn: str, incident_id: str) -> ResetReceipt:
    """Remove only metadata owned by the requested SciGuard incident."""

    control = graph.get_aspect(control_urn, DatasetPropertiesClass)
    control_properties = dict(control.customProperties or {}) if control else {}
    persisted_incident = control_properties.get("sciguard:incident_id")
    if persisted_incident != incident_id:
        raise LookupError(
            f"control asset does not belong to incident {incident_id!r}"
        )
    try:
        controlled_urns = json.loads(
            control_properties.get("sciguard:controlled_urns", "[]")
        )
    except json.JSONDecodeError as exc:
        raise ValueError("persisted controlled URNs are invalid JSON") from exc
    if not isinstance(controlled_urns, list):
        raise ValueError("persisted controlled URNs must be a list")
    controlled_urns = list(dict.fromkeys([control_urn, *controlled_urns]))

    reset_urns: list[str] = []
    skipped_urns: list[str] = []
    removed_property_count = 0
    sciguard_tags = list(STATUS_TAGS.values())
    for urn in controlled_urns:
        aspect = graph.get_aspect(urn, DatasetPropertiesClass)
        properties = dict(aspect.customProperties or {}) if aspect else {}
        if properties.get("sciguard:incident_id") != incident_id:
            skipped_urns.append(urn)
            continue
        keys = [key for key in properties if key.startswith("sciguard:")]
        remove_custom_properties(graph, urn, keys)
        remove_tags(graph, urn, sciguard_tags)
        removed_property_count += len(keys)
        reset_urns.append(urn)

    return ResetReceipt(
        incident_id=incident_id,
        reset_urns=reset_urns,
        skipped_urns=skipped_urns,
        removed_property_count=removed_property_count,
    )
