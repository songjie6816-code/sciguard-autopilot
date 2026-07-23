from datahub.metadata.schema_classes import DatasetPropertiesClass, GlobalTagsClass
from datahub.emitter.mce_builder import make_dataset_urn

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
