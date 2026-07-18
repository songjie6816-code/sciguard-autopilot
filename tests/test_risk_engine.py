from core.change_detector import Change, ChangeKind
from core.lineage_analyzer import AffectedEntity
from core.profiles import Profile, Rule, load_profile, rule_matches
from core.remediation import build_plan, render_report
from core.risk_engine import assess


def _unit_change(field: str) -> Change:
    return Change(kind=ChangeKind.UNIT_CHANGE, field=field, before="a", after="b")


def _tg_unit_change() -> Change:
    return Change(kind=ChangeKind.UNIT_CHANGE, field="tg_value", before="degC", after="K")


def test_polymer_profile_loads_tg_rule() -> None:
    profile = load_profile("polymer")
    ids = {r.id for r in profile.rules}
    assert "tg-unit-change" in ids


def test_rule_matches_normalizes_field_name() -> None:
    profile = load_profile("polymer")
    rule = next(r for r in profile.rules if r.id == "tg-unit-change")
    # profile field is "Tg"; incoming field is "tg_value"
    assert rule_matches(rule, "unit_change", "tg_value")
    assert not rule_matches(rule, "unit_change", "mn_g_mol")


def test_assess_flags_critical_and_collects_owners() -> None:
    profile = load_profile("polymer")
    affected = [
        AffectedEntity(urn="urn:a", name="polymer_feature_table", role="dataset",
                       degree=2, owners=["ml_engineer"]),
        AffectedEntity(urn="urn:b", name="tg_prediction_model", role="model",
                       degree=3, owners=["ml_engineer"]),
    ]
    a = assess(profile, [_tg_unit_change()], affected)
    assert a.overall_severity == "critical"
    assert a.is_actionable
    assert a.responsible_owners == ["ml_engineer"]


def test_overall_severity_is_worst_of_multiple_findings() -> None:
    profile = Profile(
        name="t",
        rules=[
            Rule(id="mw", field="Mw", change="unit", severity="medium"),
            Rule(id="tg", field="Tg", change="unit", severity="critical"),
        ],
    )
    changes = [_unit_change("Mw_g_mol"), _unit_change("tg_value")]
    a = assess(profile, changes, affected=[])
    assert a.overall_severity == "critical"
    assert len(a.findings) == 2


def test_no_matching_rule_is_none_and_not_actionable() -> None:
    profile = load_profile("polymer")
    a = assess(profile, [_unit_change("pressure_kPa")], affected=[])
    assert a.overall_severity == "none"
    assert not a.is_actionable
    assert a.findings == []


def test_plan_tags_models_and_report_mentions_owners() -> None:
    profile = load_profile("polymer")
    affected = [
        AffectedEntity(urn="urn:model", name="tg_prediction_model", role="model",
                       degree=3, owners=["ml_engineer"]),
    ]
    a = assess(profile, [_tg_unit_change()], affected)
    plan = build_plan(profile, a, "raw_polymer_experiments")
    assert plan.tag_targets == ["urn:model"]
    assert plan.notify_owners == ["ml_engineer"]
    report = render_report("raw_polymer_experiments", a, plan)
    assert "CRITICAL" in report
    assert "tg_prediction_model" in report
