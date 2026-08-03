from datahub.emitter.mce_builder import make_dataset_urn
from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    GlobalTagsClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
)

from core.enforcement import enforce
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)

URN = make_dataset_urn("polymer_rnd", "candidate_ranking_report", "PROD")


class StatefulGraph:
    def __init__(self) -> None:
        self.store = {
            URN: {
                "DatasetPropertiesClass": DatasetPropertiesClass(
                    name="candidate_ranking_report",
                    description="keep me",
                    customProperties={"existing": "keep"},
                ),
                "GlobalTagsClass": GlobalTagsClass(tags=[]),
            }
        }
        self.emitted = []

    def get_aspect(self, urn, cls):
        return self.store.setdefault(urn, {}).get(cls.__name__)

    def emit(self, proposal):
        self.emitted.append(proposal.aspect)
        self.store.setdefault(proposal.entityUrn, {})[type(proposal.aspect).__name__] = proposal.aspect


def _plan() -> PolicyPlan:
    return PolicyPlan(
        incident_id="inc-enforce",
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
                evidence_ids=["e-lineage", "e-unit"],
            )
        ],
    )


def test_enforcement_writeback_is_idempotent_and_preserves_metadata() -> None:
    graph = StatefulGraph()
    first = enforce(graph, _plan())
    writes_after_first = len(graph.emitted)
    second = enforce(graph, _plan())

    assert first == second
    assert len(graph.emitted) == writes_after_first
    props = graph.get_aspect(URN, DatasetPropertiesClass)
    assert props.name == "candidate_ranking_report"
    assert props.description == "keep me"
    assert props.customProperties["existing"] == "keep"
    assert props.customProperties["sciguard:incident_id"] == "inc-enforce"
    assert props.customProperties["sciguard:incident_state"] == "AT_RISK"
    assert "e-unit" in props.customProperties["sciguard:evidence_ids"]
    tags = graph.get_aspect(URN, GlobalTagsClass).tags
    assert len(tags) == len({item.tag for item in tags}) == 1


def test_new_incident_clears_old_recovery_history_and_replaces_status_tag() -> None:
    graph = StatefulGraph()
    first = _plan()
    enforce(graph, first)
    properties = graph.get_aspect(URN, DatasetPropertiesClass).customProperties
    properties["sciguard:recovery_history"] = '[{"clean":true}]'
    graph.get_aspect(URN, GlobalTagsClass).tags.append(
        type(graph.get_aspect(URN, GlobalTagsClass).tags[0])(
            tag="urn:li:tag:sciguard:resolved"
        )
    )
    next_plan = first.model_copy(update={"incident_id": "inc-recurrence"})

    enforce(graph, next_plan)

    properties = graph.get_aspect(URN, DatasetPropertiesClass).customProperties
    assert properties["sciguard:incident_id"] == "inc-recurrence"
    assert properties["sciguard:recovery_history"] == "[]"
    tags = {item.tag for item in graph.get_aspect(URN, GlobalTagsClass).tags}
    assert "urn:li:tag:sciguard:at-risk" in tags
    assert "urn:li:tag:sciguard:resolved" not in tags


def test_model_control_is_mirrored_to_native_model_and_deployment() -> None:
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
            customProperties={"keep": "model"},
        ),
        "GlobalTagsClass": GlobalTagsClass(tags=[]),
    }
    graph.store[deployment_urn] = {
        "MLModelDeploymentPropertiesClass": MLModelDeploymentPropertiesClass(
            description="Production Tg deployment",
            status="IN_SERVICE",
            customProperties={"keep": "deployment"},
        ),
        "GlobalTagsClass": GlobalTagsClass(tags=[]),
    }
    plan = PolicyPlan(
        incident_id="inc-native-enforce",
        decisions=[
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
                evidence_ids=["e-native-lineage"],
            )
        ],
    )

    receipt = enforce(graph, plan)[0]

    assert receipt.native_projection_urns == [native_model_urn, deployment_urn]
    native_model = graph.get_aspect(native_model_urn, MLModelPropertiesClass)
    deployment = graph.get_aspect(
        deployment_urn, MLModelDeploymentPropertiesClass
    )
    assert native_model.customProperties["keep"] == "model"
    assert native_model.customProperties["sciguard:incident_state"] == "AT_RISK"
    assert native_model.mlFeatures == ["urn:feature:tg"]
    assert deployment.customProperties["keep"] == "deployment"
    assert deployment.customProperties["sciguard:policy_decision"] == "HALT"
    assert deployment.status == "IN_SERVICE"
