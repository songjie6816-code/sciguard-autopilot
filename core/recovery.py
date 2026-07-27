"""Evidence-gated recovery that re-reads state from DataHub on every decision."""

from __future__ import annotations

import json
from enum import Enum

from datahub.metadata.schema_classes import DatasetPropertiesClass
from pydantic import BaseModel, field_validator

from core.enforcement import STATUS_TAGS, mirror_native_projection_state
from core.events import EventActor, EventRecorder, EventType
from core.policy_engine import CatalogStatus
from core.profiles import Profile
from datahub_client.metadata_writer import add_custom_properties, add_tags, remove_tags


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RecoveryCheck(BaseModel):
    check_id: str
    status: CheckStatus
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def _evidence_required(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("a recovery check requires evidence")
        return value


class HumanApprovalEvidence(BaseModel):
    receipt_id: str
    approver_urn: str
    identity_assurance: str
    production_authorized: bool


class RecoveryResult(BaseModel):
    incident_id: str
    resume_allowed: bool
    incident_state: str
    missing_checks: list[str]
    failed_checks: list[str]
    clean_run_count: int
    human_approval_used: bool
    approval_receipt_id: str | None
    approval_identity_assurance: str | None
    approval_production_authorized: bool
    llm_instruction_ignored: bool


class RecoveryController:
    def __init__(
        self,
        graph,
        control_urn: str,
        profile: Profile,
        recorder: EventRecorder | None = None,
    ) -> None:
        if profile.recovery_policy is None:
            raise ValueError(f"profile '{profile.name}' has no recovery_policy")
        self.graph = graph
        self.control_urn = control_urn
        self.policy = profile.recovery_policy
        self.recorder = recorder

    def evaluate(
        self,
        checks: list[RecoveryCheck],
        *,
        human_approval: HumanApprovalEvidence | None = None,
        llm_instruction: str | None = None,
        expected_incident_id: str | None = None,
    ) -> RecoveryResult:
        """Read persisted history, append this run, and deterministically gate RESUME."""

        aspect = self.graph.get_aspect(self.control_urn, DatasetPropertiesClass)
        if aspect is None:
            raise LookupError(f"no persisted incident state for {self.control_urn}")
        props = dict(aspect.customProperties or {})
        incident_id = props.get("sciguard:incident_id")
        if not incident_id:
            raise LookupError("persisted DataHub state has no incident ID")
        if expected_incident_id is not None and incident_id != expected_incident_id:
            raise LookupError(
                "persisted DataHub incident does not match the requested recovery"
            )

        by_id = {check.check_id: check for check in checks}
        required = self.policy.required_checks
        missing = [check_id for check_id in required if check_id not in by_id]
        failed = [
            check_id
            for check_id in required
            if check_id in by_id and by_id[check_id].status is CheckStatus.FAIL
        ]
        clean = not missing and not failed
        history = json.loads(props.get("sciguard:recovery_history", "[]"))
        run = {
            "clean": clean,
            "human_approval": (
                human_approval.model_dump(mode="json") if human_approval else None
            ),
            "checks": [check.model_dump(mode="json") for check in checks],
        }
        history.append(run)
        consecutive = 0
        for prior in reversed(history):
            if not prior.get("clean"):
                break
            consecutive += 1

        approved_by_history = clean and consecutive >= self.policy.consecutive_clean_runs
        approved_by_human = (
            clean
            and human_approval is not None
            and human_approval.production_authorized
            and self.policy.allow_one_clean_with_human_approval
        )
        resume = approved_by_history or approved_by_human
        previous_state = props.get("sciguard:incident_state", "AT_RISK")
        if resume:
            state = "RESOLVED"
        elif clean:
            state = "RECOVERY_PENDING"
        elif previous_state == "QUARANTINED":
            state = "QUARANTINED"
        else:
            state = "AT_RISK"

        evidence_ids = list(
            dict.fromkeys(
                [
                    *(
                        evidence_id
                        for check in checks
                        for evidence_id in check.evidence_ids
                    ),
                    *([human_approval.receipt_id] if human_approval else []),
                ]
            )
        )
        updates = {
            "sciguard:incident_state": state,
            "sciguard:status": state.lower(),
            "sciguard:recovery_history": json.dumps(history, separators=(",", ":")),
            "sciguard:recovery_evidence_ids": json.dumps(
                evidence_ids, separators=(",", ":")
            ),
            "sciguard:resume_authorized": "true" if resume else "false",
        }
        if resume:
            updates.update(
                {
                    "sciguard:policy_decision": "ALLOW",
                    "sciguard:catalog_status": "RESOLVED",
                    "sciguard:enforcement_actions": "[]",
                }
            )
        add_custom_properties(self.graph, self.control_urn, updates)
        if resume:
            controlled_urns = json.loads(
                props.get("sciguard:controlled_urns", json.dumps([self.control_urn]))
            )
            for urn in controlled_urns:
                controlled_aspect = self.graph.get_aspect(
                    urn, DatasetPropertiesClass
                )
                controlled_properties = (
                    dict(controlled_aspect.customProperties or {})
                    if controlled_aspect
                    else {}
                )
                resolved_updates = {
                    "sciguard:incident_state": "RESOLVED",
                    "sciguard:status": "resolved",
                    "sciguard:policy_decision": "ALLOW",
                    "sciguard:catalog_status": "RESOLVED",
                    "sciguard:enforcement_actions": "[]",
                    "sciguard:resume_authorized": "true",
                    "sciguard:recovery_evidence_ids": json.dumps(
                        evidence_ids, separators=(",", ":")
                    ),
                }
                if urn != self.control_urn:
                    add_custom_properties(
                        self.graph,
                        urn,
                        resolved_updates,
                    )
                remove_tags(
                    self.graph,
                    urn,
                    [
                        STATUS_TAGS[CatalogStatus.AT_RISK],
                        STATUS_TAGS[CatalogStatus.QUARANTINED],
                    ],
                )
                add_tags(self.graph, urn, [STATUS_TAGS[CatalogStatus.RESOLVED]])
                mirror_native_projection_state(
                    self.graph,
                    existing_properties=controlled_properties,
                    updates=resolved_updates,
                    status_tag=STATUS_TAGS[CatalogStatus.RESOLVED],
                )

        result = RecoveryResult(
            incident_id=incident_id,
            resume_allowed=resume,
            incident_state=state,
            missing_checks=missing,
            failed_checks=failed,
            clean_run_count=consecutive,
            human_approval_used=approved_by_human,
            approval_receipt_id=(
                human_approval.receipt_id if approved_by_human else None
            ),
            approval_identity_assurance=(
                human_approval.identity_assurance if approved_by_human else None
            ),
            approval_production_authorized=(
                human_approval.production_authorized if approved_by_human else False
            ),
            llm_instruction_ignored=llm_instruction is not None,
        )
        if self.recorder:
            self.recorder.emit(
                actor=EventActor.RECOVERY_CONTROLLER,
                event_type=(
                    EventType.INCIDENT_RESOLVED if resume else EventType.RECOVERY_CHECKED
                ),
                summary=("Recovery authorized" if resume else "Recovery remains locked"),
                evidence_ids=evidence_ids,
                payload=result.model_dump(mode="json"),
            )
        return result
