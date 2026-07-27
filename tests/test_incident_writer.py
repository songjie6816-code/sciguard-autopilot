from datahub.metadata.schema_classes import (
    DocumentInfoClass,
    IncidentInfoClass,
    IncidentNotesClass,
    IncidentStageClass,
    IncidentStateClass,
)

from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import NativeMLDecisionContext, create_unit_repair_bundle
from datahub_client.incident_writer import (
    decision_log_urn,
    incident_urn,
    raise_incident,
    update_incident_status,
    write_decision_log,
)


class Graph:
    def __init__(self) -> None:
        self.aspects: dict[tuple[str, type], object] = {}

    def get_aspect(self, urn: str, cls):
        return self.aspects.get((urn, cls))

    def emit(self, mcp) -> None:
        self.aspects[(mcp.entityUrn, type(mcp.aspect))] = mcp.aspect


def _bundle():
    return create_unit_repair_bundle(
        incident_id="inc-native-lifecycle",
        root_cause=RootCause(
            batch_id="B042",
            instrument_firmware_before="v4.1",
            instrument_firmware_after="v4.2",
            expected_unit="degC",
            observed_units=["degC", "K"],
            normalization_version="tg-normalizer-v1",
            affected_rows=187,
            explanation="Firmware emitted Kelvin while the normalizer assumed Celsius.",
        ),
        impact=FieldImpact(
            source_urn="urn:raw",
            source_fields=["tg_value"],
            affected_urns=[
                "urn:raw",
                "urn:rank",
                "urn:li:dataProcessInstance:rank-production",
            ],
            affected_names=["raw", "rank", "rank-production"],
            unaffected_urns=["urn:safe"],
            unaffected_names=["safe"],
            tainted_field_urns=["urn:field:tg"],
        ),
        evidence_ids=["e-contract", "e-lineage"],
        approver_urn="urn:li:corpuser:research_lead",
        native_ml_context=[
            NativeMLDecisionContext(
                dataset_projection_urn="urn:model-dataset",
                native_model_urn="urn:native-model",
                model_name="Tg Model v3",
                model_version="tg-gbr-v3",
                model_type="gradient_boosting_regressor",
                feature_urns=["urn:feature:tg"],
                training_job_urns=["urn:training"],
                inference_job_urns=["urn:inference"],
                deployment_context=[
                    {"urn": "urn:deployment", "status": "IN_SERVICE"}
                ],
                owner_urns=["urn:li:corpuser:ml_engineer"],
                criticality="CRITICAL",
                expected_target_unit="degC",
                affected=True,
            )
        ],
    )


def test_native_incident_and_decision_log_preserve_linked_lifecycle() -> None:
    graph = Graph()
    bundle = _bundle()
    opened = raise_incident(
        graph,
        incident_id=bundle.incident_id,
        entities=[*bundle.affected_urns, *bundle.preserved_urns],
        assignee_urn=bundle.approval.approver_urn,
        title="Unsafe scientific candidate ranking",
        description=bundle.root_cause_summary,
        evidence_ids=bundle.evidence_ids,
    )
    repeated = raise_incident(
        graph,
        incident_id=bundle.incident_id,
        entities=[*bundle.affected_urns, *bundle.preserved_urns],
        assignee_urn=bundle.approval.approver_urn,
        title="Unsafe scientific candidate ranking",
        description=bundle.root_cause_summary,
        evidence_ids=bundle.evidence_ids,
    )
    log = write_decision_log(graph, bundle=bundle, incident_state="QUARANTINED")

    assert opened == repeated
    assert opened.state == IncidentStateClass.ACTIVE
    assert opened.stage == IncidentStageClass.WORK_IN_PROGRESS
    notes = graph.get_aspect(incident_urn(bundle.incident_id), IncidentNotesClass)
    assert len(notes.notes) == 1
    document = graph.get_aspect(decision_log_urn(bundle.incident_id), DocumentInfoClass)
    assert document.customProperties["sciguard:repair_bundle_id"] == bundle.bundle_id
    assert {item.asset for item in document.relatedAssets} == {
        "urn:raw",
        "urn:rank",
        "urn:safe",
        "urn:native-model",
    }
    assert document.customProperties["sciguard:native_deployment_urns"] == (
        "urn:deployment"
    )
    assert document.customProperties[
        "sciguard:server_unsupported_related_asset_urns"
    ] == "urn:li:dataProcessInstance:rank-production"
    assert "Native Production ML context" in document.contents.text
    assert log.related_asset_count == 4
    assert len(log.content_sha256) == 64

    resolved = update_incident_status(
        graph,
        incident_id=bundle.incident_id,
        resolved=True,
        message="Verified repair and recovery evidence accepted.",
        evidence_ids=["e-recovery"],
    )
    incident = graph.get_aspect(incident_urn(bundle.incident_id), IncidentInfoClass)
    assert resolved.state == IncidentStateClass.RESOLVED
    assert resolved.stage == IncidentStageClass.FIXED
    assert incident.title == "Unsafe scientific candidate ranking"
    assert incident.entities == [
        "urn:raw",
        "urn:rank",
        "urn:li:dataProcessInstance:rank-production",
        "urn:safe",
    ]
    assert len(graph.get_aspect(incident_urn(bundle.incident_id), IncidentNotesClass).notes) == 2
