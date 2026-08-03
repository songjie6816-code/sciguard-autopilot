from datahub.emitter.mce_builder import make_dataset_urn
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
)

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
from core.recovery import (
    CheckStatus,
    HumanApprovalEvidence,
    RecoveryCheck,
    RecoveryController,
)
from tests.test_enforcement import StatefulGraph

URN = make_dataset_urn("polymer_rnd", "candidate_ranking_report", "PROD")
REQUIRED = [
    "unit_contract",
    "candidate_ranking_stability",
    "safe_branch_preservation",
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


def _approval(*, production_authorized: bool = False) -> HumanApprovalEvidence:
    return HumanApprovalEvidence(
        receipt_id="approval-receipt:test",
        approver_urn="urn:li:corpuser:research_lead",
        identity_assurance=(
            "OIDC_MFA_AUTHENTICATED"
            if production_authorized
            else "DEMO_SIGNED_NOT_SSO"
        ),
        production_authorized=production_authorized,
    )


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

    missing = controller.evaluate(_checks()[:-1], human_approval=_approval())
    assert not missing.resume_allowed
    assert "safe_branch_preservation" in missing.missing_checks


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


def test_demo_signed_approval_cannot_shorten_the_recovery_gate() -> None:
    graph = StatefulGraph()
    enforce(graph, _plan())
    result = RecoveryController(graph, URN, load_profile("polymer")).evaluate(
        _checks(), human_approval=_approval()
    )
    assert not result.resume_allowed
    assert result.incident_state == "RECOVERY_PENDING"
    assert not result.human_approval_used
    assert result.approval_receipt_id is None
    assert result.approval_identity_assurance is None
    assert result.approval_production_authorized is False


def test_one_clean_run_plus_production_authorized_approval_can_resume() -> None:
    graph = StatefulGraph()
    enforce(graph, _plan())
    result = RecoveryController(graph, URN, load_profile("polymer")).evaluate(
        _checks(), human_approval=_approval(production_authorized=True)
    )
    assert result.resume_allowed
    assert result.approval_receipt_id == "approval-receipt:test"
    assert result.approval_identity_assurance == "OIDC_MFA_AUTHENTICATED"
    assert result.approval_production_authorized is True
    assert graph.get_aspect(URN, DatasetPropertiesClass).customProperties[
        "sciguard:incident_state"
    ] == "RESOLVED"
    assert graph.get_aspect(URN, GlobalTagsClass).tags


def test_recovery_resolves_native_model_and_deployment_projections() -> None:
    model_dataset_urn = make_dataset_urn("polymer_rnd", "tg_prediction_model", "PROD")
    native_model_urn = (
        "urn:li:mlModel:(urn:li:dataPlatform:polymer_rnd,tg_prediction_model,PROD)"
    )
    deployment_urn = (
        "urn:li:mlModelDeployment:"
        "(urn:li:dataPlatform:polymer_rnd,tg-prediction-production,PROD)"
    )
    graph = StatefulGraph()
    graph.store[model_dataset_urn] = {
        "DatasetPropertiesClass": DatasetPropertiesClass(
            name="tg_prediction_model",
            customProperties={
                "sciguard:native_projection_urn": native_model_urn,
                "sciguard:native_projection_aspect": "MLModelPropertiesClass",
                "sciguard:native_deployment_urn": deployment_urn,
            },
        ),
        "GlobalTagsClass": GlobalTagsClass(tags=[]),
    }
    graph.store[native_model_urn] = {
        "MLModelPropertiesClass": MLModelPropertiesClass(
            name="Tg Model v3",
            mlFeatures=["urn:feature:tg"],
            deployments=[deployment_urn],
            customProperties={},
        ),
        "GlobalTagsClass": GlobalTagsClass(tags=[]),
    }
    graph.store[deployment_urn] = {
        "MLModelDeploymentPropertiesClass": MLModelDeploymentPropertiesClass(
            status="IN_SERVICE",
            customProperties={},
        ),
        "GlobalTagsClass": GlobalTagsClass(tags=[]),
    }
    plan = PolicyPlan(
        incident_id="inc-native-recovery",
        decisions=[
            _plan().decisions[0],
            AssetPolicyDecision(
                urn=model_dataset_urn,
                name="tg_prediction_model",
                role="model",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[EnforcementAction.BLOCK_EXECUTION, EnforcementAction.WRITE_BACK],
                reason_code="AFFECTED_MODEL",
                evidence_ids=["e-root"],
            ),
        ],
    )
    enforce(graph, plan)

    result = RecoveryController(graph, URN, load_profile("polymer")).evaluate(
        _checks(), human_approval=_approval(production_authorized=True)
    )

    assert result.resume_allowed
    native_model = graph.get_aspect(native_model_urn, MLModelPropertiesClass)
    deployment = graph.get_aspect(
        deployment_urn, MLModelDeploymentPropertiesClass
    )
    assert native_model.customProperties["sciguard:incident_state"] == "RESOLVED"
    assert native_model.customProperties["sciguard:policy_decision"] == "ALLOW"
    assert deployment.customProperties["sciguard:incident_state"] == "RESOLVED"
    assert deployment.status == "IN_SERVICE"
