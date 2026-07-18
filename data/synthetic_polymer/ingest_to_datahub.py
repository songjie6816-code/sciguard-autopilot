"""Register the synthetic polymer pipeline into DataHub as a lineage graph:
datasets with schemas, per-field units (as custom properties), ownership, and
TRANSFORMED lineage edges. Idempotent: re-running updates the same entities.

Graph (all on the custom `polymer_rnd` platform):
  raw_polymer_experiments
    -> cleaned_polymer_dataset
    -> polymer_feature_table
    -> tg_prediction_model
    -> candidate_report

Units live in DataHub as dataset custom properties (e.g. "unit:tg_value" ->
"degC"). SciGuard's change detector reads them, so a silent unit change becomes
a metadata change it can catch.
"""

from __future__ import annotations

from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    NumberTypeClass,
    OtherSchemaClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    SchemaFieldClass,
    SchemaFieldDataTypeClass,
    SchemaMetadataClass,
    StringTypeClass,
    UpstreamClass,
    UpstreamLineageClass,
)

from datahub_client.metadata_reader import connect

PLATFORM = "polymer_rnd"
ENV = "PROD"


# Each node: schema (col, kind), description, units, owner, upstream.
NODES: dict[str, dict] = {
    "raw_polymer_experiments": {
        "schema": [
            ("sample_id", "str"), ("polymer_name", "str"), ("polymer_class", "str"),
            ("smiles", "str"), ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
            ("tg_value", "num"), ("tg_unit", "str"), ("measurement_method", "str"),
            ("gpc_calibration", "str"), ("test_protocol", "str"), ("measured_on", "str"),
        ],
        "description": "Raw synthetic polymer measurements (GPC + DSC).",
        "units": {"tg_value": "degC", "mn_g_mol": "g/mol", "mw_g_mol": "g/mol", "pdi": "dimensionless"},
        "owner": "lab_experimentalist",
        "upstream": None,
    },
    "cleaned_polymer_dataset": {
        "schema": [
            ("sample_id", "str"), ("polymer_name", "str"), ("polymer_class", "str"),
            ("smiles", "str"), ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
            ("tg_degC", "num"),
        ],
        "description": "Cleaned polymer records; Tg normalized to Celsius.",
        "units": {"tg_degC": "degC", "mn_g_mol": "g/mol", "mw_g_mol": "g/mol", "pdi": "dimensionless"},
        "owner": "data_engineer",
        "upstream": "raw_polymer_experiments",
    },
    "polymer_feature_table": {
        "schema": [
            ("sample_id", "str"), ("log10_mn", "num"), ("pdi", "num"),
            ("class_code", "num"), ("tg_degC", "num"),
        ],
        "description": "Numeric feature table feeding the Tg model; target is tg_degC.",
        "units": {"tg_degC": "degC", "log10_mn": "log10(g/mol)", "pdi": "dimensionless"},
        "owner": "ml_engineer",
        "upstream": "cleaned_polymer_dataset",
    },
    "tg_prediction_model": {
        "schema": [("sample_id", "str"), ("predicted_tg_degC", "num")],
        "description": "Gradient-boosted regressor predicting polymer Tg in Celsius.",
        "units": {"predicted_tg_degC": "degC"},
        "owner": "ml_engineer",
        "upstream": "polymer_feature_table",
        "extra_props": {
            "algorithm": "gradient_boosting",
            "target": "tg_degC",
            "expected_target_unit": "degC",
            "training_rows": "180",
            "validation_mae_degC": "6.4",
        },
    },
    "candidate_report": {
        "schema": [("rank", "num"), ("sample_id", "str"), ("predicted_tg_degC", "num")],
        "description": "Ranked polymer candidates by predicted Tg for R&D review.",
        "units": {"predicted_tg_degC": "degC"},
        "owner": "research_lead",
        "upstream": "tg_prediction_model",
    },
}


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env=ENV)


def _schema_aspect(name: str, cols: list[tuple[str, str]]) -> SchemaMetadataClass:
    fields = []
    for col, kind in cols:
        dtype = NumberTypeClass() if kind == "num" else StringTypeClass()
        fields.append(
            SchemaFieldClass(
                fieldPath=col,
                type=SchemaFieldDataTypeClass(type=dtype),
                nativeDataType="double" if kind == "num" else "string",
            )
        )
    stamp = AuditStampClass(time=0, actor="urn:li:corpuser:sciguard")
    return SchemaMetadataClass(
        schemaName=name,
        platform=f"urn:li:dataPlatform:{PLATFORM}",
        version=0,
        hash="",
        created=stamp,
        lastModified=stamp,
        platformSchema=OtherSchemaClass(rawSchema=""),
        fields=fields,
    )


def _props_aspect(name: str, node: dict) -> DatasetPropertiesClass:
    custom = {f"unit:{field}": unit for field, unit in node.get("units", {}).items()}
    custom.update(node.get("extra_props", {}))
    return DatasetPropertiesClass(
        name=name, description=node["description"], customProperties=custom
    )


def _ownership_aspect(owner: str) -> OwnershipClass:
    return OwnershipClass(
        owners=[
            OwnerClass(
                owner=f"urn:li:corpuser:{owner}",
                type=OwnershipTypeClass.TECHNICAL_OWNER,
            )
        ]
    )


def main() -> None:
    graph = connect()

    for name, node in NODES.items():
        urn = _urn(name)
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=_props_aspect(name, node)))
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=_schema_aspect(name, node["schema"])))
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=_ownership_aspect(node["owner"])))
        if node["upstream"]:
            graph.emit(
                MetadataChangeProposalWrapper(
                    entityUrn=urn,
                    aspect=UpstreamLineageClass(
                        upstreams=[
                            UpstreamClass(
                                dataset=_urn(node["upstream"]),
                                type=DatasetLineageTypeClass.TRANSFORMED,
                            )
                        ]
                    ),
                )
            )
        up = node["upstream"] or "(source)"
        print(f"[node] {name:26} owner={node['owner']:16} upstream={up}")

    print("done")


if __name__ == "__main__":
    main()
