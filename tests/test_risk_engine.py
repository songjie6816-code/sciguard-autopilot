from core.change_detector import Change, ChangeKind
from core.lineage_analyzer import AffectedEntity
from core.profiles import load_profile, rule_matches
from core.remediation import build_plan, render_report
from core.risk_engine import assess


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
