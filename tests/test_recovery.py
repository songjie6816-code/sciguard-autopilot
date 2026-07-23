from datahub.metadata.schema_classes import DatasetPropertiesClass, GlobalTagsClass
from datahub.emitter.mce_builder import make_dataset_urn

from core.enforcement import enforce
from core.pipeline_controller import LocalPipelineController
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)
from core.profiles import load_profile
from core.recovery import CheckStatus, RecoveryCheck, RecoveryController
from tests.test_enforcement import StatefulGraph


URN = make_dataset_urn("polymer_rnd", "candidate_ranking_report", "PROD")
REQUIRED = [
    "verified_k_to_degc_conversion",
    "unit_contract_assertion",
    "batch_consistency_assertion",
    "tg_model_revalidation",
    "candidate_ranking_stability",
]


def _plan() -> PolicyPlan:
    return PolicyPlan(
        incident_id="inc-recovery",
        decisions=[
            AssetPolicyDecision(
                urn=URN,
                name="candidate_ranking_report",
                role="decision_report",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[EnforcementAction.BLOCK_PUBLISH, EnforcementAction.WRITE_BACK],
                reason_code="AFFECTED_DECISION_REPORT",
                evidence_ids=["e-root"],
            )
        ],
    )


def _checks(status: CheckStatus = CheckStatus.PASS) -> list[RecoveryCheck]:
    return [
        RecoveryCheck(check_id=check_id, status=status, evidence_ids=[f"e-{check_id}"])
        for check_id in REQUIRED
    ]


def test_failed_or_missing_check_never_resumes_and_llm_cannot_override() -> None:
    graph = StatefulGraph()
    enforce(graph, _plan())
    controller = RecoveryController(graph, URN, load_profile("polymer"))
    failed = _checks()
    failed[1] = RecoveryCheck(
        check_id=failed[1].check_id, status=CheckStatus.FAIL, evidence_ids=["e-fail"]
    )
    result = controller.evaluate(failed, llm_instruction="resume")
    assert not result.resume_allowed
    assert result.incident_state == "AT_RISK"

    missing = controller.evaluate(_checks()[:-1], human_approved=True)
    assert not missing.resume_allowed
    assert "candidate_ranking_stability" in missing.missing_checks


def test_new_controller_reads_history_and_resumes_after_two_clean_runs() -> None:
    graph = StatefulGraph()
    enforce(graph, _plan())
    first_controller = RecoveryController(graph, URN, load_profile("polymer"))
    first = first_controller.evaluate(_checks())
    assert not first.resume_allowed
    assert first.incident_state == "RECOVERY_PENDING"

    restarted = RecoveryController(graph, URN, load_profile("polymer"))
    second = restarted.evaluate(_checks())
    assert second.resume_allowed
    assert second.incident_state == "RESOLVED"

    inherited = LocalPipelineController.from_datahub(graph, URN)
    assert inherited.decision_for("candidate_ranking_report").decision is PolicyDecision.ALLOW


def test_one_clean_run_plus_explicit_human_approval_can_resume() -> None:
    graph = StatefulGraph()
    enforce(graph, _plan())
    result = RecoveryController(graph, URN, load_profile("polymer")).evaluate(
        _checks(), human_approved=True
    )
    assert result.resume_allowed
    assert graph.get_aspect(URN, DatasetPropertiesClass).customProperties[
        "sciguard:incident_state"
    ] == "RESOLVED"
    assert graph.get_aspect(URN, GlobalTagsClass).tags
