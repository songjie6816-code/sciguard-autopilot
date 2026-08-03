"""Persist deterministic policy controls to DataHub without clobbering metadata."""

from __future__ import annotations

import json

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
)
from pydantic import BaseModel, Field

from core.events import EventActor, EventRecorder, EventType
from core.policy_engine import CatalogStatus, EnforcementAction, PolicyPlan
from datahub_client.metadata_writer import (
    add_aspect_custom_properties,
    add_custom_properties,
    add_tags,
    remove_tags,
)

STATUS_TAGS = {
    CatalogStatus.AT_RISK: "urn:li:tag:sciguard:at-risk",
    CatalogStatus.QUARANTINED: "urn:li:tag:sciguard:quarantined",
    CatalogStatus.RESOLVED: "urn:li:tag:sciguard:resolved",
}


class EnforcementReceipt(BaseModel):
    incident_id: str
    urn: str
    decision: str
    catalog_status: str
    tags: list[str]
    properties: dict[str, str]
    evidence_ids: list[str]
    native_projection_urns: list[str] = Field(default_factory=list)


NATIVE_ASPECT_TYPES = {
    "MLFeatureTablePropertiesClass": MLFeatureTablePropertiesClass,
    "MLModelPropertiesClass": MLModelPropertiesClass,
}


def mirror_native_projection_state(
    graph,
    *,
    existing_properties: dict[str, str],
    updates: dict[str, str],
    status_tag: str | None,
) -> list[str]:
    """Mirror incident state onto native ML entities named by the dataset projection."""

    targets: list[tuple[str, type]] = []
    projection_urn = existing_properties.get("sciguard:native_projection_urn")
    projection_aspect = existing_properties.get("sciguard:native_projection_aspect")
    if projection_urn and projection_aspect:
        try:
            aspect_type = NATIVE_ASPECT_TYPES[projection_aspect]
        except KeyError as exc:
            raise ValueError(
                f"unsupported native projection aspect {projection_aspect!r}"
            ) from exc
        targets.append((projection_urn, aspect_type))
    deployment_urn = existing_properties.get("sciguard:native_deployment_urn")
    if deployment_urn:
        targets.append((deployment_urn, MLModelDeploymentPropertiesClass))

    written = []
    for urn, aspect_type in targets:
        if status_tag:
            remove_tags(
                graph,
                urn,
                [tag for tag in STATUS_TAGS.values() if tag != status_tag],
            )
            add_tags(graph, urn, [status_tag])
        add_aspect_custom_properties(graph, urn, aspect_type, updates)
        written.append(urn)
    return written


def enforce(
    graph,
    plan: PolicyPlan,
    recorder: EventRecorder | None = None,
) -> list[EnforcementReceipt]:
    receipts = []
    controlled_urns = [
        item.urn
        for item in plan.decisions
        if EnforcementAction.WRITE_BACK in item.actions
    ]
    for decision in plan.decisions:
        if EnforcementAction.WRITE_BACK not in decision.actions:
            continue
        existing = graph.get_aspect(decision.urn, DatasetPropertiesClass)
        existing_properties = dict(existing.customProperties or {}) if existing else {}
        status_tag = STATUS_TAGS.get(decision.catalog_status)
        if status_tag:
            remove_tags(
                graph,
                decision.urn,
                [tag for tag in STATUS_TAGS.values() if tag != status_tag],
            )
        tags = add_tags(graph, decision.urn, [status_tag] if status_tag else [])
        existing_history = (
            existing_properties.get("sciguard:recovery_history", "[]")
            if existing_properties.get("sciguard:incident_id") == plan.incident_id
            else "[]"
        )
        updates = {
            "sciguard:incident_id": plan.incident_id,
            "sciguard:incident_state": decision.catalog_status.value,
            "sciguard:status": decision.catalog_status.value.lower(),
            "sciguard:policy_decision": decision.decision.value,
            "sciguard:catalog_status": decision.catalog_status.value,
            "sciguard:enforcement_actions": json.dumps(
                [action.value for action in decision.actions], separators=(",", ":")
            ),
            "sciguard:evidence_ids": json.dumps(
                decision.evidence_ids, separators=(",", ":")
            ),
            "sciguard:evidence_summary": (
                f"{len(decision.evidence_ids)} validated evidence item(s)"
            ),
            "sciguard:reason_code": decision.reason_code,
            "sciguard:controlled_urns": json.dumps(
                controlled_urns, separators=(",", ":")
            ),
            "sciguard:recovery_history": existing_history,
        }
        properties = add_custom_properties(graph, decision.urn, updates)
        native_projection_urns = mirror_native_projection_state(
            graph,
            existing_properties=existing_properties,
            updates=updates,
            status_tag=status_tag,
        )
        receipt = EnforcementReceipt(
            incident_id=plan.incident_id,
            urn=decision.urn,
            decision=decision.decision.value,
            catalog_status=decision.catalog_status.value,
            tags=tags,
            properties=properties,
            evidence_ids=decision.evidence_ids,
            native_projection_urns=native_projection_urns,
        )
        receipts.append(receipt)
        if recorder:
            recorder.emit(
                actor=EventActor.ENFORCER,
                event_type=EventType.ENFORCEMENT_APPLIED,
                summary=f"Persisted {decision.decision.value} control on {decision.name}",
                evidence_ids=decision.evidence_ids,
                payload=receipt.model_dump(mode="json"),
            )
    return receipts
