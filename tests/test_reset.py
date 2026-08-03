import json

import pytest
from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetPropertiesClass,
    DocumentContentsClass,
    DocumentInfoClass,
    DocumentStateClass,
    DocumentStatusClass,
    GlobalTagsClass,
    IncidentNotesClass,
    MLModelDeploymentPropertiesClass,
    MLModelPropertiesClass,
    TagAssociationClass,
)

from core.enforcement import enforce
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)
from core.reset import reset_incident_metadata
from datahub_client.incident_writer import (
    decision_log_urn,
    incident_urn,
    raise_incident,
)
from tests.test_enforcement import URN, StatefulGraph


def test_reset_removes_only_matching_sciguard_metadata_and_tags() -> None:
    graph = StatefulGraph()
    properties = graph.get_aspect(URN, DatasetPropertiesClass)
    properties.customProperties.update(
        {
            "sciguard:incident_id": "inc-reset",
            "sciguard:controlled_urns": json.dumps([URN]),
            "sciguard:status": "at_risk",
            "existing": "keep",
        }
    )
    graph.store[URN]["GlobalTagsClass"] = GlobalTagsClass(
        tags=[
            TagAssociationClass(tag="urn:li:tag:sciguard:at-risk"),
            TagAssociationClass(tag="urn:li:tag:domain:polymer"),
        ]
    )

    receipt = reset_incident_metadata(graph, URN, "inc-reset")

    assert receipt.reset_urns == [URN]
    remaining = graph.get_aspect(URN, DatasetPropertiesClass).customProperties
    assert remaining == {"existing": "keep"}
    tags = [item.tag for item in graph.get_aspect(URN, GlobalTagsClass).tags]
    assert tags == ["urn:li:tag:domain:polymer"]


def test_reset_refuses_to_touch_a_different_incident() -> None:
    graph = StatefulGraph()
    graph.get_aspect(URN, DatasetPropertiesClass).customProperties[
        "sciguard:incident_id"
    ] = "inc-other"
    with pytest.raises(LookupError, match="does not belong"):
        reset_incident_metadata(graph, URN, "inc-requested")


MODEL_DATASET_URN = make_dataset_urn(
    "polymer_rnd", "tg_prediction_model", "PROD"
)
NATIVE_MODEL_URN = (
    "urn:li:mlModel:(urn:li:dataPlatform:polymer_rnd,tg_prediction_model,PROD)"
)
DEPLOYMENT_URN = (
    "urn:li:mlModelDeployment:"
    "(urn:li:dataPlatform:polymer_rnd,tg-prediction-production,PROD)"
)


class ResetGraph(StatefulGraph):
    def __init__(self) -> None:
        super().__init__()
        self.deleted_entities: list[str] = []

    def delete_entity(self, urn: str, hard: bool = False) -> None:
        assert hard, "incident artifacts must be removed completely for a clean rerun"
        self.deleted_entities.append(urn)
        self.store.pop(urn, None)


def _seed_decision_log(
    graph: ResetGraph,
    incident_id: str,
    *,
    owner_incident_id: str | None = None,
) -> None:
    stamp = AuditStampClass(time=1, actor="urn:li:corpuser:sciguard")
    graph.emit(
        MetadataChangeProposalWrapper(
            entityUrn=decision_log_urn(incident_id),
            aspect=DocumentInfoClass(
                status=DocumentStatusClass(state=DocumentStateClass.PUBLISHED),
                contents=DocumentContentsClass(text="old run"),
                created=stamp,
                lastModified=stamp,
                customProperties={
                    "sciguard:incident_id": owner_incident_id or incident_id
                },
            ),
        )
    )


def _seed_native_projection(graph: ResetGraph, incident_id: str) -> None:
    graph.store[MODEL_DATASET_URN] = {
        "DatasetPropertiesClass": DatasetPropertiesClass(
            name="tg_prediction_model",
            customProperties={
                "sciguard:criticality": "CRITICAL",
                "sciguard:synthetic": "true",
                "sciguard:native_projection_urn": NATIVE_MODEL_URN,
                "sciguard:native_projection_aspect": "MLModelPropertiesClass",
                "sciguard:native_deployment_urn": DEPLOYMENT_URN,
                "sciguard:incident_id": incident_id,
                "sciguard:incident_state": "RESOLVED",
                "sciguard:recovery_history": '[{"clean":true}]',
            },
        ),
        "GlobalTagsClass": GlobalTagsClass(
            tags=[
                TagAssociationClass(tag="urn:li:tag:sciguard:synthetic-data"),
                TagAssociationClass(tag="urn:li:tag:sciguard:resolved"),
            ]
        ),
    }
    graph.store[NATIVE_MODEL_URN] = {
        "MLModelPropertiesClass": MLModelPropertiesClass(
            name="Tg Model v3",
            mlFeatures=["urn:feature:tg"],
            deployments=[DEPLOYMENT_URN],
            customProperties={
                "keep": "model",
                "sciguard:native_projection": "true",
                "sciguard:incident_id": incident_id,
                "sciguard:incident_state": "RESOLVED",
                "sciguard:recovery_history": '[{"clean":true}]',
            },
        ),
        "GlobalTagsClass": GlobalTagsClass(
            tags=[
                TagAssociationClass(
                    tag="urn:li:tag:sciguard:native-production-ml"
                ),
                TagAssociationClass(tag="urn:li:tag:sciguard:resolved"),
            ]
        ),
    }
    graph.store[DEPLOYMENT_URN] = {
        "MLModelDeploymentPropertiesClass": MLModelDeploymentPropertiesClass(
            status="IN_SERVICE",
            customProperties={
                "keep": "deployment",
                "sciguard:model_urn": NATIVE_MODEL_URN,
                "sciguard:incident_id": incident_id,
                "sciguard:incident_state": "RESOLVED",
            },
        ),
        "GlobalTagsClass": GlobalTagsClass(
            tags=[
                TagAssociationClass(
                    tag="urn:li:tag:sciguard:native-production-ml"
                ),
                TagAssociationClass(tag="urn:li:tag:sciguard:resolved"),
            ]
        ),
    }


def _seed_control(graph: ResetGraph, incident_id: str) -> None:
    graph.get_aspect(URN, DatasetPropertiesClass).customProperties.update(
        {
            "sciguard:incident_id": incident_id,
            "sciguard:controlled_urns": json.dumps([URN, MODEL_DATASET_URN]),
            "sciguard:incident_state": "RESOLVED",
            "sciguard:recovery_history": '[{"clean":true}]',
        }
    )


def _rerun_plan(incident_id: str) -> PolicyPlan:
    return PolicyPlan(
        incident_id=incident_id,
        decisions=[
            AssetPolicyDecision(
                urn=URN,
                name="candidate_ranking_report",
                role="decision_report",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[
                    EnforcementAction.BLOCK_PUBLISH,
                    EnforcementAction.WRITE_BACK,
                ],
                reason_code="AFFECTED_DECISION_REPORT",
                evidence_ids=["e-rerun"],
            ),
            AssetPolicyDecision(
                urn=MODEL_DATASET_URN,
                name="tg_prediction_model",
                role="model",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[
                    EnforcementAction.BLOCK_EXECUTION,
                    EnforcementAction.WRITE_BACK,
                ],
                reason_code="AFFECTED_MODEL",
                evidence_ids=["e-rerun"],
            ),
        ],
    )


def test_reset_cleans_native_context_and_allows_same_incident_id_rerun() -> None:
    incident_id = "inc-native-reset"
    graph = ResetGraph()
    _seed_control(graph, incident_id)
    _seed_native_projection(graph, incident_id)
    raise_incident(
        graph,
        incident_id=incident_id,
        entities=[URN, MODEL_DATASET_URN],
        assignee_urn="urn:li:corpuser:research_lead",
        title="Old run",
        description="Old evidence must not survive reset.",
        evidence_ids=["e-old"],
    )
    _seed_decision_log(graph, incident_id)

    receipt = reset_incident_metadata(graph, URN, incident_id)

    assert receipt.reset_urns == [MODEL_DATASET_URN, URN]
    assert receipt.reset_native_projection_urns == [
        NATIVE_MODEL_URN,
        DEPLOYMENT_URN,
    ]
    assert receipt.deleted_incident_artifact_urns == [
        incident_urn(incident_id),
        decision_log_urn(incident_id),
    ]
    assert graph.get_aspect(incident_urn(incident_id), IncidentNotesClass) is None
    assert graph.get_aspect(decision_log_urn(incident_id), DocumentInfoClass) is None

    dataset_properties = graph.get_aspect(
        MODEL_DATASET_URN, DatasetPropertiesClass
    ).customProperties
    assert dataset_properties == {
        "sciguard:criticality": "CRITICAL",
        "sciguard:synthetic": "true",
        "sciguard:native_projection_urn": NATIVE_MODEL_URN,
        "sciguard:native_projection_aspect": "MLModelPropertiesClass",
        "sciguard:native_deployment_urn": DEPLOYMENT_URN,
    }
    native_model = graph.get_aspect(NATIVE_MODEL_URN, MLModelPropertiesClass)
    assert native_model.customProperties == {
        "keep": "model",
        "sciguard:native_projection": "true",
    }
    assert native_model.mlFeatures == ["urn:feature:tg"]
    deployment = graph.get_aspect(
        DEPLOYMENT_URN, MLModelDeploymentPropertiesClass
    )
    assert deployment.customProperties == {
        "keep": "deployment",
        "sciguard:model_urn": NATIVE_MODEL_URN,
    }
    assert deployment.status == "IN_SERVICE"
    assert {
        item.tag
        for item in graph.get_aspect(NATIVE_MODEL_URN, GlobalTagsClass).tags
    } == {"urn:li:tag:sciguard:native-production-ml"}

    # A same-ID rerun can still discover the native projection and starts with
    # fresh recovery history and incident notes.
    enforce(graph, _rerun_plan(incident_id))
    assert graph.get_aspect(
        NATIVE_MODEL_URN, MLModelPropertiesClass
    ).customProperties["sciguard:incident_state"] == "AT_RISK"
    assert graph.get_aspect(
        NATIVE_MODEL_URN, MLModelPropertiesClass
    ).customProperties["sciguard:recovery_history"] == "[]"
    raise_incident(
        graph,
        incident_id=incident_id,
        entities=[URN, MODEL_DATASET_URN],
        assignee_urn="urn:li:corpuser:research_lead",
        title="Fresh rerun",
        description="Fresh evidence.",
        evidence_ids=["e-fresh"],
    )
    _seed_decision_log(graph, incident_id)
    assert len(
        graph.get_aspect(incident_urn(incident_id), IncidentNotesClass).notes
    ) == 1

    second = reset_incident_metadata(graph, URN, incident_id)
    assert second.reset_native_projection_urns == [
        NATIVE_MODEL_URN,
        DEPLOYMENT_URN,
    ]
    assert second.deleted_incident_artifact_urns == [
        incident_urn(incident_id),
        decision_log_urn(incident_id),
    ]


def test_reset_preflights_native_artifact_ownership_before_any_write() -> None:
    incident_id = "inc-owned-reset"
    graph = ResetGraph()
    _seed_control(graph, incident_id)
    _seed_decision_log(graph, incident_id, owner_incident_id="inc-other")
    before = dict(
        graph.get_aspect(URN, DatasetPropertiesClass).customProperties
    )

    with pytest.raises(LookupError, match="not owned by this incident"):
        reset_incident_metadata(graph, URN, incident_id)

    assert graph.get_aspect(URN, DatasetPropertiesClass).customProperties == before
    assert graph.deleted_entities == []
