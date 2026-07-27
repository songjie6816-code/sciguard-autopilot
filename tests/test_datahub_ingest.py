import json
from pathlib import Path

from data.synthetic_polymer import ingest_to_datahub as ingest
from data.synthetic_polymer import native_ml
from datahub.metadata.schema_classes import (
    DataProcessInstanceInputClass,
    DataProcessInstanceOutputClass,
    DatasetPropertiesClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelDeploymentPropertiesClass,
    MLModelGroupPropertiesClass,
    MLModelPropertiesClass,
)
from datahub_client.metadata_reader import get_native_ml_model_context


ROOT = Path(__file__).parents[1]


def _flagship() -> dict:
    return json.loads((ROOT / "evaluation" / "scenarios.json").read_text())["flagship"]


def test_datahub_graph_matches_frozen_flagship_contract() -> None:
    flagship = _flagship()
    assets = {asset["name"]: asset for asset in flagship["assets"]}
    edges = {
        (upstream, name)
        for name, node in ingest.NODES.items()
        for upstream in node.get("upstreams", [])
    }

    assert set(ingest.NODES) == set(assets)
    assert edges == {tuple(edge) for edge in flagship["lineage_edges"]}
    assert all(ingest.NODES[name]["owner"] == asset["owner"]
               for name, asset in assets.items())
    assert all(ingest.NODES[name]["criticality"] == asset["criticality"]
               for name, asset in assets.items())
    assert all(ingest.NODES[name]["tags"] for name in ingest.NODES)


def test_field_lineage_keeps_tg_out_of_molecular_weight_branch() -> None:
    tg_map = ingest.NODES["tg_feature_table"]["field_lineage"]
    mw_map = ingest.NODES["molecular_weight_feature_table"]["field_lineage"]

    assert any("tg" in upstream.lower() or "tg" in downstream.lower()
               for upstream, downstream in tg_map)
    assert not any("tg" in upstream.lower() or "tg" in downstream.lower()
                   for upstream, downstream in mw_map)
    assert {downstream for _, downstream in mw_map} == {
        "sample_id",
        "batch_id",
        "mn_g_mol",
        "mw_g_mol",
        "pdi",
    }


def test_ml_metadata_dual_projection_is_explicit_and_queryable() -> None:
    model = ingest.NODES["tg_prediction_model"]
    decision = ingest.ML_METADATA_DECISION

    assert decision["mode"] == "dual_native_projection"
    assert "fine-grained lineage" in decision["reason"]
    assert decision["native_projection_role"] == "production_ml_semantics_and_lifecycle"
    assert model["extra_props"]["entity_role"] == "model"
    assert model["extra_props"]["model_version"] == "tg-gbr-v3"
    assert model["extra_props"]["ml_metadata_mode"] == decision["mode"]


class FakeNativeGraph:
    def __init__(self) -> None:
        self.aspects: dict[tuple[str, type], object] = {}

    def get_aspect(self, urn: str, cls):
        return self.aspects.get((urn, cls))

    def emit(self, mcp) -> None:
        self.aspects[(mcp.entityUrn, type(mcp.aspect))] = mcp.aspect


def test_native_ml_projection_connects_features_models_deployments_and_decisions() -> None:
    graph = FakeNativeGraph()
    receipt = native_ml.emit_native_ml_graph(graph)

    assert len(receipt["feature_tables"]) == 2
    assert len(receipt["features"]) == 7
    assert len(receipt["model_groups"]) == 2
    assert len(receipt["models"]) == 2
    assert len(receipt["deployments"]) == 2
    assert len(receipt["training_runs"]) == 2
    assert len(receipt["inference_runs"]) == 2

    tg_table_urn = native_ml.feature_table_urn("tg_feature_table")
    tg_feature_urn = native_ml.feature_urn("tg_feature_table", "tg_degC")
    tg_model_urn = native_ml.model_urn("tg_prediction_model")
    tg_deployment_urn = native_ml.deployment_urn("tg-prediction-production")
    training_run_urn = native_ml.process_urn("train-tg-gbr-v3")
    inference_run_urn = native_ml.process_urn("rank-candidates-production")

    table = graph.aspects[(tg_table_urn, MLFeatureTablePropertiesClass)]
    feature = graph.aspects[(tg_feature_urn, MLFeaturePropertiesClass)]
    model = graph.aspects[(tg_model_urn, MLModelPropertiesClass)]
    deployment = graph.aspects[(tg_deployment_urn, MLModelDeploymentPropertiesClass)]
    training_inputs = graph.aspects[(training_run_urn, DataProcessInstanceInputClass)]
    training_outputs = graph.aspects[(training_run_urn, DataProcessInstanceOutputClass)]
    inference_inputs = graph.aspects[(inference_run_urn, DataProcessInstanceInputClass)]
    inference_outputs = graph.aspects[(inference_run_urn, DataProcessInstanceOutputClass)]

    assert tg_feature_urn in table.mlFeatures
    assert feature.sources == [native_ml.dataset_urn("cleaned_polymer_dataset")]
    assert feature.customProperties["sciguard:source_field"] == "tg_degC"
    assert model.version.versionTag == "tg-gbr-v3"
    assert tg_feature_urn in model.mlFeatures
    assert training_run_urn in model.trainingJobs
    assert inference_run_urn in model.downstreamJobs
    assert tg_deployment_urn in model.deployments
    assert deployment.status == "IN_SERVICE"
    assert native_ml.dataset_urn("cleaned_polymer_dataset") in training_inputs.inputs
    assert native_ml.dataset_urn("tg_feature_table") in training_inputs.inputs
    assert all("mlFeature:" not in urn for urn in training_inputs.inputs)
    assert training_outputs.outputs == [tg_model_urn]
    assert tg_model_urn in inference_inputs.inputs
    assert native_ml.dataset_urn("tg_feature_table") in inference_inputs.inputs
    assert inference_outputs.outputs == [native_ml.dataset_urn("candidate_ranking_report")]


def test_native_ml_projection_preserves_independent_molecular_weight_branch() -> None:
    graph = FakeNativeGraph()
    native_ml.emit_native_ml_graph(graph)

    durability_model_urn = native_ml.model_urn("durability_model")
    model = graph.aspects[(durability_model_urn, MLModelPropertiesClass)]
    feature_urns = set(model.mlFeatures)

    assert native_ml.feature_urn("molecular_weight_feature_table", "mn_g_mol") in feature_urns
    assert native_ml.feature_urn("molecular_weight_feature_table", "mw_g_mol") in feature_urns
    assert all("tg_feature_table" not in urn for urn in feature_urns)


def test_native_ml_model_groups_are_real_entities_not_display_labels() -> None:
    graph = FakeNativeGraph()
    native_ml.emit_native_ml_graph(graph)

    for spec in native_ml.MODELS.values():
        urn = native_ml.model_group_urn(spec.group)
        aspect = graph.aspects[(urn, MLModelGroupPropertiesClass)]
        assert aspect.trainingJobs == [native_ml.process_urn(spec.training_run)]
        assert aspect.downstreamJobs == [native_ml.process_urn(spec.inference_run)]


def test_native_model_context_is_read_through_dataset_projection() -> None:
    graph = FakeNativeGraph()
    native_ml.emit_native_ml_graph(graph)
    dataset_urn = native_ml.dataset_urn("tg_prediction_model")
    model_urn = native_ml.model_urn("tg_prediction_model")
    deployment_urn = native_ml.deployment_urn("tg-prediction-production")
    graph.aspects[(dataset_urn, DatasetPropertiesClass)] = DatasetPropertiesClass(
        name="tg_prediction_model",
        customProperties={
            "sciguard:native_projection_urn": model_urn,
            "sciguard:native_deployment_urn": deployment_urn,
        },
    )

    context = get_native_ml_model_context(graph, dataset_urn)

    assert context["native_model_urn"] == model_urn
    assert context["model_version"] == "tg-gbr-v3"
    assert context["deployment_context"][0]["status"] == "IN_SERVICE"
    assert native_ml.feature_urn("tg_feature_table", "tg_degC") in context["feature_urns"]
    assert context["owner_urns"] == ["urn:li:corpuser:ml_engineer"]
