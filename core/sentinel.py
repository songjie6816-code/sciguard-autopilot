"""Lightweight deterministic detection, triage, and incident escalation.

Sentinel may detect and escalate. It cannot write control state, block work,
declare a root cause, or authorize recovery.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from core.events import stable_evidence_id
from core.impact import AffectedEntity
from core.profiles import EscalationPolicy, Profile, Rule, rule_matches

SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


class ChangeKind(str, Enum):
    UNIT_CHANGE = "unit_change"
    FIELD_REMOVED = "field_removed"
    FIELD_ADDED = "field_added"
    TYPE_CHANGED = "type_changed"


class Snapshot(BaseModel):
    fields: dict[str, str] = {}
    units: dict[str, str] = {}


class Change(BaseModel):
    kind: ChangeKind
    field: str
    before: str | None = None
    after: str | None = None

    def describe(self) -> str:
        if self.kind is ChangeKind.UNIT_CHANGE:
            return f"unit of '{self.field}' changed {self.before} -> {self.after}"
        if self.kind is ChangeKind.FIELD_REMOVED:
            return f"field '{self.field}' was removed"
        if self.kind is ChangeKind.FIELD_ADDED:
            return f"field '{self.field}' was added"
        return f"type of '{self.field}' changed {self.before} -> {self.after}"


class RuleFinding(BaseModel):
    change: Change
    rule_id: str
    severity: str
    accepted_units: list[str] = []
    rationale: str


class RiskAssessment(BaseModel):
    overall_severity: str
    findings: list[RuleFinding] = []
    affected: list[AffectedEntity] = []
    responsible_owners: list[str] = []

    @property
    def is_actionable(self) -> bool:
        return SEVERITY_ORDER[self.overall_severity] >= SEVERITY_ORDER["medium"]


class DetectionSignal(BaseModel):
    signal_id: str
    changed_urn: str
    changes: list[Change]
    matched_rule_ids: list[str]
    severity: str
    initial_scope: list[AffectedEntity]
    decision_assets_reached: list[str]
    responsible_owners: list[str]
    evidence_ids: list[str]


class EscalationDecision(BaseModel):
    escalate: bool
    reason_code: str
    minimum_severity: str
    triggered_roles: list[str]
    evidence_ids: list[str]


def detect_changes(before: Snapshot, after: Snapshot) -> list[Change]:
    changes: list[Change] = []
    for field in before.fields:
        if field not in after.fields:
            changes.append(Change(kind=ChangeKind.FIELD_REMOVED, field=field))
        elif before.fields[field] != after.fields[field]:
            changes.append(
                Change(
                    kind=ChangeKind.TYPE_CHANGED,
                    field=field,
                    before=before.fields[field],
                    after=after.fields[field],
                )
            )
    for field in after.fields:
        if field not in before.fields:
            changes.append(Change(kind=ChangeKind.FIELD_ADDED, field=field))

    surviving = set(before.fields) & set(after.fields)
    for field in (set(before.units) | set(after.units)) & surviving:
        before_unit = before.units.get(field) or None
        after_unit = after.units.get(field) or None
        if before_unit != after_unit:
            changes.append(
                Change(
                    kind=ChangeKind.UNIT_CHANGE,
                    field=field,
                    before=before_unit or "(none)",
                    after=after_unit or "(none)",
                )
            )
    return changes


def _match_rule(profile: Profile, change: Change) -> Rule | None:
    return next(
        (
            rule
            for rule in profile.rules
            if rule_matches(rule, change.kind.value, change.field)
        ),
        None,
    )


def assess(
    profile: Profile,
    changes: list[Change],
    affected: list[AffectedEntity],
) -> RiskAssessment:
    findings: list[RuleFinding] = []
    worst = "none"
    for change in changes:
        rule = _match_rule(profile, change)
        if rule is None:
            continue
        findings.append(
            RuleFinding(
                change=change,
                rule_id=rule.id,
                severity=rule.severity,
                accepted_units=rule.accepted_units,
                rationale=(
                    f"{change.describe()}; matched rule '{rule.id}' "
                    f"({profile.name} profile) -> {rule.severity}"
                ),
            )
        )
        if SEVERITY_ORDER[rule.severity] > SEVERITY_ORDER[worst]:
            worst = rule.severity
    return RiskAssessment(
        overall_severity=worst,
        findings=findings,
        affected=affected,
        responsible_owners=sorted({owner for item in affected for owner in item.owners}),
    )


def build_signal(
    changed_urn: str,
    assessment: RiskAssessment,
) -> DetectionSignal:
    change_payload = [item.model_dump(mode="json") for item in assessment.findings]
    scope_payload = [item.model_dump(mode="json") for item in assessment.affected]
    evidence_ids = [
        stable_evidence_id("metadata-drift", change_payload),
        stable_evidence_id("initial-lineage-scope", scope_payload),
    ]
    decision_assets = [
        item.name or item.urn
        for item in assessment.affected
        if item.role in {"model", "decision_report"}
    ]
    payload = {
        "changed_urn": changed_urn,
        "severity": assessment.overall_severity,
        "matched_rule_ids": [item.rule_id for item in assessment.findings],
        "initial_scope_urns": [item.urn for item in assessment.affected],
        "decision_assets_reached": decision_assets,
        "evidence_ids": evidence_ids,
    }
    return DetectionSignal(
        signal_id=stable_evidence_id("detection-signal", payload),
        changed_urn=changed_urn,
        changes=[item.change for item in assessment.findings],
        matched_rule_ids=[item.rule_id for item in assessment.findings],
        severity=assessment.overall_severity,
        initial_scope=assessment.affected,
        decision_assets_reached=decision_assets,
        responsible_owners=assessment.responsible_owners,
        evidence_ids=evidence_ids,
    )


def decide_escalation(
    profile: Profile,
    signal: DetectionSignal,
) -> EscalationDecision:
    policy = profile.escalation_policy or EscalationPolicy()
    triggered_roles = sorted(
        {
            item.role
            for item in signal.initial_scope
            if item.role in policy.decision_roles
        }
    )
    severe_enough = (
        SEVERITY_ORDER[signal.severity]
        >= SEVERITY_ORDER[policy.minimum_severity]
    )
    decision_path_ok = bool(triggered_roles) or not policy.require_decision_path
    if not severe_enough:
        reason = "BELOW_ESCALATION_SEVERITY"
    elif not decision_path_ok:
        reason = "NO_DECISION_CRITICAL_PATH"
    else:
        reason = "SCIENTIFIC_CONTRACT_DRIFT_REACHES_DECISION"
    payload = {
        "signal_id": signal.signal_id,
        "escalate": severe_enough and decision_path_ok,
        "reason_code": reason,
        "minimum_severity": policy.minimum_severity,
        "triggered_roles": triggered_roles,
    }
    return EscalationDecision(
        **payload,
        evidence_ids=[*signal.evidence_ids, stable_evidence_id("escalation", payload)],
    )
