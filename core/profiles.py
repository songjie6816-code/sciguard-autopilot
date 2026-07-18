"""Load configurable domain profiles (generic -> materials -> polymer).

Rules live in YAML so a new scientific domain is a config change, not code. Each
profile may `extends` another; rules are merged child-last.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

PROFILE_DIR = Path(__file__).resolve().parents[1] / "domain_profiles"


class Rule(BaseModel):
    id: str
    field: str                 # domain field name, matched by normalized prefix
    change: str                # matches ChangeKind value, e.g. "unit_change" or "unit"
    severity: str              # low | medium | high | critical
    accepted_units: list[str] = []
    remediation: list[str] = []


class Profile(BaseModel):
    name: str
    rules: list[Rule] = []


def _normalize(field: str) -> str:
    return re.sub(r"[^a-z0-9]", "", field.lower())


def load_profile(name: str) -> Profile:
    """Load a profile and all profiles it extends, merging their rules."""
    merged: list[Rule] = []
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
    merged = list(by_id.values())
    return Profile(name=name, rules=merged)


def rule_matches(rule: Rule, change_kind: str, field: str) -> bool:
    """A rule matches a change on kind and field (normalized prefix)."""
    kind_ok = rule.change in (change_kind, change_kind.replace("_change", ""))
    field_ok = _normalize(field).startswith(_normalize(rule.field))
    return kind_ok and field_ok
