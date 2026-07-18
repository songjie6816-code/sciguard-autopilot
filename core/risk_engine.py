"""Evaluate domain-profile rules and assign structured risk levels.

Deterministic: each detected change is matched against the active domain profile
to get a severity and rationale; the overall risk is the worst matched severity.
No LLM is involved, so results are reproducible and directly testable.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.change_detector import Change
from core.lineage_analyzer import AffectedEntity
from core.profiles import Profile, Rule, rule_matches

SEVERITY_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


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


def _match_rule(profile: Profile, change: Change) -> Rule | None:
    for rule in profile.rules:
        if rule_matches(rule, change.kind.value, change.field):
            return rule
    return None


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

    owners = sorted({o for e in affected for o in e.owners})
    return RiskAssessment(
        overall_severity=worst,
        findings=findings,
        affected=affected,
        responsible_owners=owners,
    )
