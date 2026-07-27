"""Incident-scoped cleanup that preserves shared and baseline metadata."""

from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    DocumentInfoClass,
    IncidentInfoClass,
    MLModelDeploymentPropertiesClass,
)
from pydantic import BaseModel, Field

from core.enforcement import NATIVE_ASPECT_TYPES, STATUS_TAGS
from datahub_client.incident_writer import decision_log_urn, incident_urn
from datahub_client.metadata_writer import (
    remove_aspect_custom_properties,
    remove_custom_properties,
    remove_tags,
)


# Baseline projection metadata is also namespaced with ``sciguard:``. Reset
# must remove only the keys written by incident enforcement/recovery, otherwise
# rerunning the same incident loses the pointers needed to reach native ML
# entities.
INCIDENT_PROPERTY_KEYS = frozenset(
    {
        "sciguard:incident_id",
        "sciguard:incident_state",
        "sciguard:status",
        "sciguard:policy_decision",
        "sciguard:catalog_status",
        "sciguard:enforcement_actions",
        "sciguard:evidence_ids",
        "sciguard:evidence_summary",
        "sciguard:reason_code",
        "sciguard:controlled_urns",
        "sciguard:recovery_history",
        "sciguard:recovery_evidence_ids",
        "sciguard:resume_authorized",
    }
)


class ResetReceipt(BaseModel):
    incident_id: str
    reset_urns: list[str]
    skipped_urns: list[str]
    removed_property_count: int
    reset_native_projection_urns: list[str] = Field(default_factory=list)
    skipped_native_projection_urns: list[str] = Field(default_factory=list)
    deleted_incident_artifact_urns: list[str] = Field(default_factory=list)


def _validate_incident_artifact_ownership(
    graph,
    *,
    incident_id: str,
) -> list[tuple[str, object]]:
    """Resolve only native entities demonstrably owned by this incident."""

    native_incident_urn = incident_urn(incident_id)
    native_incident = graph.get_aspect(native_incident_urn, IncidentInfoClass)
    if (
        native_incident is not None
        and native_incident.customType != "SCIENTIFIC_DECISION_INTEGRITY"
    ):
        raise LookupError(
            "refusing to delete a native Incident not owned by SciGuard: "
            f"{native_incident_urn}"
        )

    native_decision_log_urn = decision_log_urn(incident_id)
    native_decision_log = graph.get_aspect(
        native_decision_log_urn, DocumentInfoClass
    )
    if native_decision_log is not None and (
        native_decision_log.customProperties or {}
    ).get("sciguard:incident_id") != incident_id:
        raise LookupError(
            "refusing to delete a native Decision Log not owned by this incident: "
            f"{native_decision_log_urn}"
        )

    return [
        (native_incident_urn, native_incident),
        (native_decision_log_urn, native_decision_log),
    ]


def reset_incident_metadata(graph, control_urn: str, incident_id: str) -> ResetReceipt:
    """Remove one incident and its overlays while preserving seeded context.

    Incident and Decision Log entities are hard-deleted because they are
    incident-owned and may contain notes or creation timestamps from an earlier
    run. Shared dataset and native Production ML entities are retained; only
    the exact enforcement/recovery keys and status tags are removed.
    """

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
    if not all(isinstance(urn, str) and urn for urn in controlled_urns):
        raise ValueError("persisted controlled URNs must contain non-empty strings")
    controlled_urns = list(dict.fromkeys([control_urn, *controlled_urns]))

    reset_urns: list[str] = []
    skipped_urns: list[str] = []
    removed_property_count = 0
    sciguard_tags = list(STATUS_TAGS.values())

    # Build and validate the complete cleanup plan before making any writes.
    # The control asset is deliberately cleaned last so a failed partial reset
    # can be retried using its persisted incident ownership and target list.
    datasets_to_reset: list[tuple[str, dict[str, str]]] = []
    native_targets: list[tuple[str, type]] = []
    for urn in controlled_urns:
        aspect = graph.get_aspect(urn, DatasetPropertiesClass)
        properties = dict(aspect.customProperties or {}) if aspect else {}
        if properties.get("sciguard:incident_id") != incident_id:
            skipped_urns.append(urn)
            continue
        datasets_to_reset.append((urn, properties))
        projection_urn = properties.get("sciguard:native_projection_urn")
        projection_aspect = properties.get("sciguard:native_projection_aspect")
        if projection_urn and projection_aspect:
            try:
                aspect_type = NATIVE_ASPECT_TYPES[projection_aspect]
            except KeyError as exc:
                raise ValueError(
                    f"unsupported native projection aspect {projection_aspect!r}"
                ) from exc
            native_targets.append((projection_urn, aspect_type))
        deployment_urn = properties.get("sciguard:native_deployment_urn")
        if deployment_urn:
            native_targets.append(
                (deployment_urn, MLModelDeploymentPropertiesClass)
            )

    native_targets = list(dict.fromkeys(native_targets))
    incident_artifacts = _validate_incident_artifact_ownership(
        graph,
        incident_id=incident_id,
    )

    reset_native_projection_urns: list[str] = []
    skipped_native_projection_urns: list[str] = []
    for urn, aspect_type in native_targets:
        aspect = graph.get_aspect(urn, aspect_type)
        properties = (
            dict(getattr(aspect, "customProperties", None) or {}) if aspect else {}
        )
        if properties.get("sciguard:incident_id") != incident_id:
            skipped_native_projection_urns.append(urn)
            continue
        keys = sorted(INCIDENT_PROPERTY_KEYS.intersection(properties))
        remove_aspect_custom_properties(graph, urn, aspect_type, keys)
        remove_tags(graph, urn, sciguard_tags)
        removed_property_count += len(keys)
        reset_native_projection_urns.append(urn)

    deleted_incident_artifact_urns: list[str] = []
    for urn, aspect in incident_artifacts:
        if aspect is None:
            continue
        graph.delete_entity(urn, hard=True)
        deleted_incident_artifact_urns.append(urn)

    reset_order = [
        *(item for item in datasets_to_reset if item[0] != control_urn),
        *(item for item in datasets_to_reset if item[0] == control_urn),
    ]
    for urn, properties in reset_order:
        keys = sorted(INCIDENT_PROPERTY_KEYS.intersection(properties))
        remove_custom_properties(graph, urn, keys)
        remove_tags(graph, urn, sciguard_tags)
        removed_property_count += len(keys)
        reset_urns.append(urn)

    return ResetReceipt(
        incident_id=incident_id,
        reset_urns=reset_urns,
        skipped_urns=skipped_urns,
        removed_property_count=removed_property_count,
        reset_native_projection_urns=reset_native_projection_urns,
        skipped_native_projection_urns=skipped_native_projection_urns,
        deleted_incident_artifact_urns=deleted_incident_artifact_urns,
    )
