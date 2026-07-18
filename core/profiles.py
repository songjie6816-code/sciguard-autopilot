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


class Profile(BaseModel):
    name: str
    rules: list[Rule] = []


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _tokens(field: str) -> set[str]:
    """Split a field name into lowercase tokens on separators and camelCase."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", field)
    parts = re.split(r"[^a-zA-Z0-9]+", spaced)
    return {p.lower() for p in parts if p}


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
    for raw in reversed(chain):
        for r in raw.get("rules", []) or []:
            rule = Rule(**r)
            by_id[rule.id] = rule
    return Profile(name=name, rules=list(by_id.values()))


def rule_matches(rule: Rule, change_kind: str, field: str) -> bool:
    """A rule matches a change on kind and on a whole-token field name.

    Whole-token matching avoids a prefix false positive ('TGA' vs 'Tg') while
    still catching qualified names ('DSC_Tg', 'glassTransitionTg').
    """
    kind_ok = rule.change in (change_kind, change_kind.replace("_change", ""))
    field_ok = _norm(rule.field) in _tokens(field)
    return kind_ok and field_ok
