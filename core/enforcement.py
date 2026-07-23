"""Persist deterministic policy controls to DataHub without clobbering metadata."""

from __future__ import annotations

import json

from datahub.metadata.schema_classes import DatasetPropertiesClass
from pydantic import BaseModel

from core.events import EventActor, EventRecorder, EventType
from core.policy_engine import CatalogStatus, EnforcementAction, PolicyPlan
from datahub_client.metadata_writer import (
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
        properties = add_custom_properties(
            graph,
            decision.urn,
            {
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
            },
        )
        receipt = EnforcementReceipt(
            incident_id=plan.incident_id,
            urn=decision.urn,
            decision=decision.decision.value,
            catalog_status=decision.catalog_status.value,
            tags=tags,
            properties=properties,
            evidence_ids=decision.evidence_ids,
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
