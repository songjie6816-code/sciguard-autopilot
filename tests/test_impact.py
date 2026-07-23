from types import SimpleNamespace

from datahub.emitter.mce_builder import make_dataset_urn, make_schema_field_urn

from core.impact import trace_field_impact


def _urn(name: str) -> str:
    return make_dataset_urn("polymer_rnd", name, "PROD")


def _edge(up_name: str, up_field: str, down_name: str, down_field: str):
    return (
        make_schema_field_urn(_urn(up_name), up_field),
        make_schema_field_urn(_urn(down_name), down_field),
    )


class FieldGraph:
    names = [
        "cleaned_polymer_dataset",
        "tg_feature_table",
        "molecular_weight_feature_table",
        "tg_prediction_model",
        "durability_model",
        "candidate_ranking_report",
        "formulation_report",
    ]
    lineage = {
        "cleaned_polymer_dataset": [
            _edge("raw_polymer_experiments", "tg_value", "cleaned_polymer_dataset", "tg_degC")
        ],
        "tg_feature_table": [
            _edge("cleaned_polymer_dataset", "tg_degC", "tg_feature_table", "tg_degC")
        ],
        "molecular_weight_feature_table": [
            _edge("cleaned_polymer_dataset", "mw_g_mol", "molecular_weight_feature_table", "mw_g_mol")
        ],
        "tg_prediction_model": [
            _edge("tg_feature_table", "tg_degC", "tg_prediction_model", "predicted_tg_degC")
        ],
        "durability_model": [
            _edge("molecular_weight_feature_table", "mw_g_mol", "durability_model", "durability_score")
        ],
        "candidate_ranking_report": [
            _edge("tg_prediction_model", "predicted_tg_degC", "candidate_ranking_report", "predicted_tg_degC")
        ],
        "formulation_report": [
            _edge("durability_model", "durability_score", "formulation_report", "durability_score")
        ],
    }

    def get_all_downstream(self, urn):
        return [
            SimpleNamespace(urn=_urn(name), name=name, degree=index)
            for index, name in enumerate(self.names, 1)
        ]

    def get_fine_grained_lineage(self, urn):
        return self.lineage[urn.rsplit(",", 2)[-2]]


def test_field_proof_preserves_the_unrelated_branch() -> None:
    result = trace_field_impact(FieldGraph(), _urn("raw_polymer_experiments"), ["tg_value"])
    assert set(result.affected_names) == {
        "raw_polymer_experiments",
        "cleaned_polymer_dataset",
        "tg_feature_table",
        "tg_prediction_model",
        "candidate_ranking_report",
    }
    assert set(result.unaffected_names) == {
        "molecular_weight_feature_table",
        "durability_model",
        "formulation_report",
    }
