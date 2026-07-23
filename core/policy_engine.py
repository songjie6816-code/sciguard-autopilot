"""Deterministic per-asset policy decisions for confirmed incidents."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from core.events import EventActor, EventRecorder, EventType
from core.profiles import Profile


class PolicyDecision(str, Enum):
    HALT = "HALT"
    WARN = "WARN"
    ALLOW = "ALLOW"


class CatalogStatus(str, Enum):
    HEALTHY = "HEALTHY"
    AT_RISK = "AT_RISK"
    QUARANTINED = "QUARANTINED"
    RESOLVED = "RESOLVED"


class EnforcementAction(str, Enum):
    QUARANTINE = "QUARANTINE"
    BLOCK_EXECUTION = "BLOCK_EXECUTION"
    BLOCK_PUBLISH = "BLOCK_PUBLISH"
    WRITE_BACK = "WRITE_BACK"
    NOTIFY = "NOTIFY"
    RESUME = "RESUME"


class AssetPolicyContext(BaseModel):
    urn: str
    name: str
    role: str
    criticality: str
    affected: bool


class AssetPolicyDecision(AssetPolicyContext):
    decision: PolicyDecision
    catalog_status: CatalogStatus
    actions: list[EnforcementAction]
    reason_code: str
    evidence_ids: list[str]


class PolicyPlan(BaseModel):
    incident_id: str
    decisions: list[AssetPolicyDecision]


def decide(
    profile: Profile,
    incident_id: str,
    assets: list[AssetPolicyContext],
    *,
    root_cause_evidence_ids: list[str],
    recorder: EventRecorder | None = None,
) -> PolicyPlan:
    """Map affected status and asset role to configured, reproducible controls."""

    if profile.action_policy is None:
        raise ValueError(f"profile '{profile.name}' has no action_policy")
    decisions = []
    for asset in assets:
        if asset.affected:
            try:
                rule = profile.action_policy.affected_roles[asset.role]
            except KeyError as exc:
                raise ValueError(f"no affected-role policy for '{asset.role}'") from exc
            reason_code = f"AFFECTED_{asset.role.upper()}"
        else:
            rule = profile.action_policy.unaffected
            reason_code = "UNAFFECTED_BRANCH"
        decision = AssetPolicyDecision(
            **asset.model_dump(),
            decision=PolicyDecision(rule.decision),
            catalog_status=CatalogStatus(rule.catalog_status),
            actions=[EnforcementAction(action) for action in rule.actions],
            reason_code=reason_code,
            evidence_ids=root_cause_evidence_ids,
        )
        decisions.append(decision)
        if recorder:
            recorder.emit(
                actor=EventActor.POLICY_GUARDIAN,
                event_type=EventType.POLICY_DECIDED,
                summary=f"{asset.name}: {decision.decision.value} ({reason_code})",
                evidence_ids=root_cause_evidence_ids,
                payload=decision.model_dump(mode="json"),
            )
    return PolicyPlan(incident_id=incident_id, decisions=decisions)
