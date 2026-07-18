import pytest
from pydantic import ValidationError

from core import profiles
from core.profiles import Rule, load_profile, rule_matches


def _tg_rule() -> Rule:
    return Rule(id="tg-unit-change", field="Tg", change="unit", severity="critical")


def test_whole_token_match_avoids_prefix_false_positive() -> None:
    rule = _tg_rule()
    assert rule_matches(rule, "unit_change", "tg_value")      # plain
    assert rule_matches(rule, "unit_change", "DSC_Tg")        # qualified prefix
    assert rule_matches(rule, "unit_change", "glassTransitionTg")  # camelCase
    assert not rule_matches(rule, "unit_change", "TGA_residual_mass")  # not Tg
    assert not rule_matches(rule, "unit_change", "mn_g_mol")


def test_change_kind_alias_matches() -> None:
    rule = _tg_rule()
    assert rule_matches(rule, "unit_change", "tg_value")
    assert not rule_matches(rule, "type_changed", "tg_value")


def test_bad_severity_is_rejected_at_load() -> None:
    with pytest.raises(ValidationError):
        Rule(id="x", field="Tg", change="unit", severity="blocker")


def test_polymer_profile_extends_chain() -> None:
    assert load_profile("generic").rules == []
    assert load_profile("materials").rules == []
    assert any(r.id == "tg-unit-change" for r in load_profile("polymer").rules)


def test_child_rule_overrides_parent_by_id(tmp_path, monkeypatch) -> None:
    (tmp_path / "base.yaml").write_text(
        "name: base\nrules:\n  - {id: r1, field: Tg, change: unit, severity: low}\n"
    )
    (tmp_path / "child.yaml").write_text(
        "name: child\nextends: base\n"
        "rules:\n  - {id: r1, field: Tg, change: unit, severity: critical}\n"
    )
    monkeypatch.setattr(profiles, "PROFILE_DIR", tmp_path)
    prof = load_profile("child")
    assert len(prof.rules) == 1
    assert prof.rules[0].severity == "critical"
