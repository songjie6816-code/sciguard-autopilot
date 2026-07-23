import json

from core.coordinator import Coordinator
from core.investigation_models import (
    HypothesisResolution,
    HypothesisStatus,
    InvestigationReport,
    RootCause,
)
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)
from security.context_builder import BoundedContextBuilder, save_prompt_snapshot


SYMPTOM = "Candidate P-204 moved from rank #18 to #1. No pipeline failed."


def _report() -> InvestigationReport:
    return InvestigationReport(
        incident_id="inc-context",
        root_cause_confirmed=True,
        root_cause=RootCause(
            batch_id="B042",
            instrument_firmware_before="v4.1",
            instrument_firmware_after="v4.2",
            expected_unit="degC",
            observed_units=["degC", "K"],
            normalization_version="tg-normalizer-v1",
            affected_rows=187,
            explanation="Mixed units",
        ),
        resolutions=[
            HypothesisResolution(
                hypothesis_id="H2",
                status=HypothesisStatus.CONFIRMED,
                rationale="Unit drift confirmed",
                evidence_ids=["e-lineage", "e-unit"],
            )
        ],
    )


def _plan() -> PolicyPlan:
    return PolicyPlan(
        incident_id="inc-context",
        decisions=[
            AssetPolicyDecision(
                urn="urn:li:dataset:test",
                name="candidate_ranking_report",
                role="decision_report",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[EnforcementAction.BLOCK_PUBLISH],
                reason_code="AFFECTED_DECISION_REPORT",
                evidence_ids=["e-lineage", "e-unit"],
            )
        ],
    )


def test_context_is_bounded_metadata_only_and_prompt_is_sanitized(tmp_path) -> None:
    case = Coordinator().open_case("inc-context", SYMPTOM)
    result = BoundedContextBuilder(max_assets=2, max_events=2).build(
        case=case,
        report=_report(),
        plan=_plan(),
        extra_context={
            "owner_email": "owner@example.com",
            "token": "sk-superSecret123456",
            "internal": "http://localhost:8080/entity",
            "records": [
                {"sample_id": "P-204", "tg_value": 412.1},
                {"sample_id": "P-205", "tg_value": 98.0},
            ],
        },
    )
    prompt = result.render_prompt()

    assert result.context.raw_rows_included == 0
    assert result.redactions.raw_rows_removed == 2
    assert "owner@example.com" not in prompt
    assert "superSecret" not in prompt
    assert "localhost" not in prompt
    assert '"tg_value"' not in prompt
    assert "HALT" in prompt
    assert len(result.context.assets) <= 2
    assert len(result.context.events) <= 2

    path = tmp_path / "prompt.json"
    snapshot = save_prompt_snapshot(path, result)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["snapshot_id"] == snapshot.snapshot_id
    assert saved["raw_rows_included"] == 0
    assert "owner@example.com" not in path.read_text(encoding="utf-8")


def test_context_never_accepts_policy_from_untrusted_extra_context() -> None:
    result = BoundedContextBuilder().build(
        case=Coordinator().open_case("inc-context", SYMPTOM),
        report=_report(),
        plan=_plan(),
        extra_context={"policy_decision": "ALLOW", "resume": True},
    )
    assert result.context.policy[0]["decision"] == "HALT"
    assert "policy_decision" not in result.context.extra_context
    assert "resume" not in result.context.extra_context


def test_rendered_prompt_never_exceeds_hard_character_bound() -> None:
    result = BoundedContextBuilder(max_prompt_chars=800).build(
        case=Coordinator().open_case("inc-context", SYMPTOM),
        report=_report(),
        plan=_plan(),
        extra_context={"large_note": "x" * 20_000},
    )
    prompt = result.render_prompt({"type": "object"})
    assert len(prompt) == 800
    assert prompt.endswith("[CONTEXT_TRUNCATED]")
