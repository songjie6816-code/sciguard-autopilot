import json
from pathlib import Path

from data.synthetic_polymer import ingest_to_datahub as ingest


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


def test_ml_metadata_fallback_is_explicit_and_queryable() -> None:
    model = ingest.NODES["tg_prediction_model"]
    fallback = ingest.ML_METADATA_DECISION

    assert fallback["mode"] == "dataset_entity_fallback"
    assert "MCP" in fallback["reason"]
    assert model["extra_props"]["entity_role"] == "model"
    assert model["extra_props"]["model_version"] == "tg-gbr-v3"
    assert model["extra_props"]["ml_metadata_mode"] == fallback["mode"]
