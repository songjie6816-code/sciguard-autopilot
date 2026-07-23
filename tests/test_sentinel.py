from types import SimpleNamespace

from core.impact import AffectedEntity, trace_initial_scope
from core.profiles import Profile, Rule, load_profile
from core.sentinel import (
    Change,
    ChangeKind,
    Snapshot,
    assess,
    build_signal,
    decide_escalation,
    detect_changes,
)


def test_detects_structured_schema_and_unit_changes() -> None:
    before = Snapshot(
        fields={"sample_id": "str", "tg_value": "double"},
        units={"tg_value": "degC"},
    )
    after = Snapshot(
        fields={"sample_id": "str", "tg_value": "float", "batch_id": "str"},
        units={"tg_value": "mixed:degC|K"},
    )
    changes = detect_changes(before, after)
    assert {(item.kind, item.field) for item in changes} == {
        (ChangeKind.TYPE_CHANGED, "tg_value"),
        (ChangeKind.FIELD_ADDED, "batch_id"),
        (ChangeKind.UNIT_CHANGE, "tg_value"),
    }


def test_unit_presence_changes_are_detected_without_double_reporting_fields() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "degC"})
    after = Snapshot(fields={"tg_value": "double"}, units={})
    assert detect_changes(before, after)[0].after == "(none)"

    before = Snapshot(fields={"tg_value": "double"}, units={})
    after = Snapshot(fields={"tg_value": "double"}, units={"tg_value": "K"})
    assert detect_changes(before, after)[0].before == "(none)"

    removed = detect_changes(
        Snapshot(fields={"tg_value": "double"}, units={"tg_value": "degC"}),
        Snapshot(fields={}, units={}),
    )
    assert [item.kind for item in removed] == [ChangeKind.FIELD_REMOVED]


def test_blank_unit_and_unchanged_snapshot_are_noops() -> None:
    before = Snapshot(fields={"tg_value": "double"}, units={"tg_value": ""})
    after = Snapshot(fields={"tg_value": "double"}, units={})
    assert detect_changes(before, after) == []
    assert detect_changes(after, after) == []


def test_signal_escalates_only_when_severity_reaches_a_decision_path() -> None:
    profile = load_profile("polymer")
    scope = [
        AffectedEntity(
            urn="urn:model",
            name="tg_prediction_model",
            role="model",
            degree=1,
            owners=["ml_engineer"],
        ),
        AffectedEntity(
            urn="urn:report",
            name="candidate_ranking_report",
            role="decision_report",
            degree=2,
            owners=["research_lead"],
        ),
    ]
    changes = [
        Change(
            kind=ChangeKind.UNIT_CHANGE,
            field="tg_value",
            before="degC",
            after="mixed:degC|K",
        )
    ]
    signal = build_signal("urn:source", assess(profile, changes, scope))
    decision = decide_escalation(profile, signal)
    assert decision.escalate
    assert decision.reason_code == "SCIENTIFIC_CONTRACT_DRIFT_REACHES_DECISION"
    assert signal.decision_assets_reached == [
        "tg_prediction_model",
        "candidate_ranking_report",
    ]
    assert signal.responsible_owners == ["ml_engineer", "research_lead"]


def test_signal_does_not_escalate_benign_or_non_decision_change() -> None:
    profile = Profile(
        name="test",
        rules=[Rule(id="pressure", field="pressure", change="unit", severity="low")],
    )
    change = Change(
        kind=ChangeKind.UNIT_CHANGE,
        field="pressure",
        before="Pa",
        after="kPa",
    )
    signal = build_signal("urn:source", assess(profile, [change], []))
    decision = decide_escalation(profile, signal)
    assert not decision.escalate
    assert decision.reason_code == "BELOW_ESCALATION_SEVERITY"


def test_assessment_uses_worst_rule_and_collects_unique_owners() -> None:
    profile = Profile(
        name="test",
        rules=[
            Rule(id="mw", field="Mw", change="unit", severity="medium"),
            Rule(id="tg", field="Tg", change="unit", severity="critical"),
        ],
    )
    scope = [
        AffectedEntity(
            urn="urn:model",
            name="model",
            role="model",
            degree=1,
            owners=["owner", "owner"],
        )
    ]
    result = assess(
        profile,
        [
            Change(kind=ChangeKind.UNIT_CHANGE, field="Mw_g_mol", before="a", after="b"),
            Change(kind=ChangeKind.UNIT_CHANGE, field="tg_value", before="a", after="b"),
        ],
        scope,
    )
    assert result.overall_severity == "critical"
    assert result.responsible_owners == ["owner"]


def test_unmatched_change_is_not_actionable() -> None:
    result = assess(
        load_profile("polymer"),
        [
            Change(
                kind=ChangeKind.UNIT_CHANGE,
                field="pressure_kPa",
                before="Pa",
                after="kPa",
            )
        ],
        [],
    )
    assert result.overall_severity == "none"
    assert not result.is_actionable
    assert result.findings == []


class BroadGraph:
    def get_all_downstream(self, urn):
        return [
            SimpleNamespace(
                urn="urn:model",
                name="tg_prediction_model",
                entity_type="DATASET",
                degree=1,
            ),
            SimpleNamespace(
                urn="urn:report",
                name="candidate_ranking_report",
                entity_type="DATASET",
                degree=2,
            ),
        ]

    def get_owners(self, urn):
        return ["ml_engineer"] if urn == "urn:model" else ["research_lead"]


def test_initial_scope_is_conservative_and_role_aware() -> None:
    scope = trace_initial_scope(BroadGraph(), "urn:source")
    assert [item.role for item in scope] == ["model", "decision_report"]
