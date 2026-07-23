"""Load configurable domain profiles (generic -> materials -> polymer).

Rules live in YAML so a new scientific domain is a config change, not code. Each
profile may `extends` another; rules are merged child-last.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, field_validator

PROFILE_DIR = Path(__file__).resolve().parents[1] / "domain_profiles"
ALLOWED_SEVERITY = {"low", "medium", "high", "critical"}
ALLOWED_DECISIONS = {"HALT", "WARN", "ALLOW"}
ALLOWED_CATALOG_STATUSES = {"HEALTHY", "AT_RISK", "QUARANTINED", "RESOLVED"}
ALLOWED_ACTIONS = {
    "QUARANTINE", "BLOCK_EXECUTION", "BLOCK_PUBLISH", "WRITE_BACK", "NOTIFY", "RESUME"
}


class Rule(BaseModel):
    id: str
    field: str                 # domain field name, matched as a whole token
    change: str                # matches ChangeKind value, e.g. "unit_change" or "unit"
    severity: str              # low | medium | high | critical
    accepted_units: list[str] = []
    remediation: list[str] = []

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, v: str) -> str:
        if v not in ALLOWED_SEVERITY:
            raise ValueError(
                f"severity '{v}' is not one of {sorted(ALLOWED_SEVERITY)}"
            )
        return v


class ActionPolicyRule(BaseModel):
    decision: str
    catalog_status: str
    actions: list[str] = []

    @field_validator("decision")
    @classmethod
    def _known_decision(cls, value: str) -> str:
        if value not in ALLOWED_DECISIONS:
            raise ValueError(f"unknown policy decision: {value}")
        return value

    @field_validator("catalog_status")
    @classmethod
    def _known_catalog_status(cls, value: str) -> str:
        if value not in ALLOWED_CATALOG_STATUSES:
            raise ValueError(f"unknown catalog status: {value}")
        return value

    @field_validator("actions")
    @classmethod
    def _known_actions(cls, value: list[str]) -> list[str]:
        unknown = set(value) - ALLOWED_ACTIONS
        if unknown:
            raise ValueError(f"unknown enforcement actions: {sorted(unknown)}")
        return value


class ActionPolicy(BaseModel):
    affected_roles: dict[str, ActionPolicyRule]
    unaffected: ActionPolicyRule


class RecoveryPolicy(BaseModel):
    required_checks: list[str]
    consecutive_clean_runs: int = 2
    allow_one_clean_with_human_approval: bool = True


class EscalationPolicy(BaseModel):
    """Deterministic boundary between lightweight detection and incident response."""

    minimum_severity: str = "high"
    decision_roles: list[str] = ["model", "decision_report"]
    require_decision_path: bool = True

    @field_validator("minimum_severity")
    @classmethod
    def _known_minimum_severity(cls, value: str) -> str:
        if value not in ALLOWED_SEVERITY:
            raise ValueError(f"unknown escalation severity: {value}")
        return value


class Profile(BaseModel):
    name: str
    rules: list[Rule] = []
    action_policy: ActionPolicy | None = None
    recovery_policy: RecoveryPolicy | None = None
    escalation_policy: EscalationPolicy | None = None


def _tokens(field: str) -> list[str]:
    """Split a field name into ordered lowercase tokens on separators and camelCase."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    parts = re.split(r"[^a-zA-Z0-9]+", spaced)
    return [p.lower() for p in parts if p]


def _is_contiguous_sublist(needle: list[str], haystack: list[str]) -> bool:
    n = len(needle)
    if n == 0:
        return False
    return any(haystack[i : i + n] == needle for i in range(len(haystack) - n + 1))


def load_profile(name: str) -> Profile:
    """Load a profile and all profiles it extends, merging their rules."""
    seen_files: set[str] = set()
    current: str | None = name

    chain: list[dict] = []
    while current and current not in seen_files:
        seen_files.add(current)
        raw = yaml.safe_load((PROFILE_DIR / f"{current}.yaml").read_text()) or {}
        chain.append(raw)
        current = raw.get("extends")

    # Parent-first so child rules can override by id.
    by_id: dict[str, Rule] = {}
    action_policy: ActionPolicy | None = None
    recovery_policy: RecoveryPolicy | None = None
    escalation_policy: EscalationPolicy | None = None
    for raw in reversed(chain):
        for r in raw.get("rules", []) or []:
            rule = Rule(**r)
            by_id[rule.id] = rule
        if raw.get("action_policy") is not None:
            action_policy = ActionPolicy.model_validate(raw["action_policy"])
        if raw.get("recovery_policy") is not None:
            recovery_policy = RecoveryPolicy.model_validate(raw["recovery_policy"])
        if raw.get("escalation_policy") is not None:
            escalation_policy = EscalationPolicy.model_validate(raw["escalation_policy"])
    return Profile(
        name=name,
        rules=list(by_id.values()),
        action_policy=action_policy,
        recovery_policy=recovery_policy,
        escalation_policy=escalation_policy,
    )


def rule_matches(rule: Rule, change_kind: str, field: str) -> bool:
    """A rule matches a change on kind and on a whole-token field name.

    The rule's token sequence must appear as a contiguous run of tokens in the
    field. This avoids a prefix false positive ('TGA' vs 'Tg'), catches qualified
    names ('DSC_Tg', 'glassTransitionTg'), and supports multi-word rule fields
    ('melting point' matching 'melting_point_value').
    """
    kind_ok = rule.change in (change_kind, change_kind.replace("_change", ""))
    field_ok = _is_contiguous_sublist(_tokens(rule.field), _tokens(field))
    return kind_ok and field_ok
