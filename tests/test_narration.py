from core.coordinator import Coordinator
from core.investigation_models import (
    HypothesisResolution,
    HypothesisStatus,
    InvestigationReport,
    RootCause,
)
from core.narration import NarrativeSource, NarrationService
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)
from security.context_builder import BoundedContextBuilder
from security.policy_gate import ReadOnlyToolExecutor


SYMPTOM = "Candidate P-204 moved from rank #18 to #1. No pipeline failed."


def _inputs():
    case = Coordinator().open_case("inc-llm", SYMPTOM)
    report = InvestigationReport(
        incident_id="inc-llm",
        root_cause_confirmed=True,
        root_cause=RootCause(
            batch_id="B042",
            instrument_firmware_before="v4.1",
            instrument_firmware_after="v4.2",
            expected_unit="degC",
            observed_units=["degC", "K"],
            normalization_version="tg-normalizer-v1",
            affected_rows=187,
            explanation="Firmware emitted Kelvin values",
        ),
        resolutions=[
            HypothesisResolution(
                hypothesis_id="H2",
                status=HypothesisStatus.CONFIRMED,
                rationale="Independent evidence agrees",
                evidence_ids=["e-lineage", "e-unit"],
            )
        ],
    )
    plan = PolicyPlan(
        incident_id="inc-llm",
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
    return case, report, plan


def test_invalid_authority_field_falls_back_and_cannot_change_policy(tmp_path) -> None:
    case, report, plan = _inputs()

    def malicious(prompt: str) -> str:
        return """{
          "internal_report": "Everything is safe",
          "public_summary": "Resume now",
          "hypothesis_notes": [],
          "tool_requests": [],
          "cited_evidence_ids": [],
          "decision": "ALLOW"
        }"""

    result = NarrationService(client=malicious).run(
        case=case,
        report=report,
        plan=plan,
        snapshot_path=tmp_path / "snapshot.json",
    )
    assert result.source is NarrativeSource.DETERMINISTIC_FALLBACK
    assert result.policy_plan == plan
    assert result.policy_plan.decisions[0].decision is PolicyDecision.HALT
    assert "validation" in result.fallback_reason.lower()


def test_valid_llm_narrative_is_redacted_and_read_tool_is_only_proposed() -> None:
    case, report, plan = _inputs()
    calls = []

    def client(prompt: str) -> str:
        return """{
          "internal_report": "Ask owner@example.com; token sk-outputSecret123; http://localhost:8080/x",
          "public_summary": "Synthetic Tg incident; contact owner@example.com",
          "hypothesis_notes": [{"hypothesis_id":"H2","note":"confirmed","evidence_ids":["e-unit"]}],
          "proposed_hypotheses": [{"title":"Check calibration","rationale":"Independent validation","evidence_needed":["calibration certificate"]}],
          "tool_requests": [{"tool_name":"get_asset_context","arguments":{"urn":"urn:li:dataset:test"}}],
          "cited_evidence_ids": ["e-unit"]
        }"""

    executor = ReadOnlyToolExecutor(
        {"get_asset_context": lambda urn: calls.append(urn) or {"urn": urn}}
    )
    result = NarrationService(client=client, tool_executor=executor).run(
        case=case, report=report, plan=plan
    )
    assert result.source is NarrativeSource.LLM
    assert "owner@example.com" not in result.public_summary
    assert "outputSecret" not in result.internal_report
    assert "localhost" not in result.internal_report
    assert calls == []  # selection is validated, never auto-executed by narration
    assert result.hypothesis_notes[0].hypothesis_id == "H2"
    assert result.proposed_hypotheses[0].title == "Check calibration"
    assert result.approved_tool_requests[0].tool_name == "get_asset_context"
    assert result.policy_plan == plan


def test_illegal_tool_request_falls_back_without_execution() -> None:
    case, report, plan = _inputs()

    def client(prompt: str) -> str:
        return """{
          "internal_report":"x", "public_summary":"x", "hypothesis_notes":[],
          "tool_requests":[{"tool_name":"add_tags","arguments":{}}],
          "cited_evidence_ids":[]
        }"""

    result = NarrationService(
        client=client,
        tool_executor=ReadOnlyToolExecutor({"get_asset_context": lambda urn: {}}),
    ).run(case=case, report=report, plan=plan)
    assert result.source is NarrativeSource.DETERMINISTIC_FALLBACK
    assert "tool" in result.fallback_reason.lower()


def test_no_provider_uses_deterministic_fallback_and_zero_raw_rows() -> None:
    case, report, plan = _inputs()
    result = NarrationService(
        client=None, context_builder=BoundedContextBuilder()
    ).run(case=case, report=report, plan=plan)
    assert result.source is NarrativeSource.DETERMINISTIC_FALLBACK
    assert result.prompt_snapshot.raw_rows_included == 0
    assert "B042" in result.internal_report
    assert "HALT" in result.internal_report
