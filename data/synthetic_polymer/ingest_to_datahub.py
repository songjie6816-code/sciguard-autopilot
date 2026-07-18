"""Register the synthetic polymer tables into DataHub as datasets with schemas
and lineage. Idempotent: re-running updates the same entities.

Creates this graph on the custom `polymer_rnd` platform:
  raw_polymer_experiments -> cleaned_polymer_dataset -> polymer_feature_table
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

# (column, kind) — "num" -> NumberType, "str" -> StringType.
SCHEMAS: dict[str, list[tuple[str, str]]] = {
    "raw_polymer_experiments": [
        ("sample_id", "str"), ("polymer_name", "str"), ("polymer_class", "str"),
        ("smiles", "str"), ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
        ("tg_value", "num"), ("tg_unit", "str"), ("measurement_method", "str"),
        ("gpc_calibration", "str"), ("test_protocol", "str"), ("measured_on", "str"),
    ],
    "cleaned_polymer_dataset": [
        ("sample_id", "str"), ("polymer_name", "str"), ("polymer_class", "str"),
        ("smiles", "str"), ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
        ("tg_degC", "num"),
    ],
    "polymer_feature_table": [
        ("sample_id", "str"), ("log10_mn", "num"), ("pdi", "num"),
        ("class_code", "num"), ("tg_degC", "num"),
    ],
}

DESCRIPTIONS = {
    "raw_polymer_experiments": "Raw synthetic polymer measurements (GPC + DSC).",
    "cleaned_polymer_dataset": "Cleaned polymer records with Tg in Celsius.",
    "polymer_feature_table": "Numeric feature table feeding the Tg model.",
}

# child -> parent (upstream) edges.
LINEAGE = {
    "cleaned_polymer_dataset": "raw_polymer_experiments",
    "polymer_feature_table": "cleaned_polymer_dataset",
}


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env=ENV)


def _schema_aspect(name: str, cols: list[tuple[str, str]]) -> SchemaMetadataClass:
    fields = []
    for col, kind in cols:
        dtype = NumberTypeClass() if kind == "num" else StringTypeClass()
        native = "double" if kind == "num" else "string"
        fields.append(
            SchemaFieldClass(
                fieldPath=col,
                type=SchemaFieldDataTypeClass(type=dtype),
                nativeDataType=native,
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


def main() -> None:
    graph = connect()

    for name, cols in SCHEMAS.items():
        urn = _urn(name)
        graph.emit(
            MetadataChangeProposalWrapper(
                entityUrn=urn,
                aspect=DatasetPropertiesClass(name=name, description=DESCRIPTIONS[name]),
            )
        )
        graph.emit(
            MetadataChangeProposalWrapper(entityUrn=urn, aspect=_schema_aspect(name, cols))
        )
        print(f"[dataset] {name}  ({len(cols)} fields)")

    for child, parent in LINEAGE.items():
        graph.emit(
            MetadataChangeProposalWrapper(
                entityUrn=_urn(child),
                aspect=UpstreamLineageClass(
                    upstreams=[
                        UpstreamClass(
                            dataset=_urn(parent),
                            type=DatasetLineageTypeClass.TRANSFORMED,
                        )
                    ]
                ),
            )
        )
        print(f"[lineage] {parent} -> {child}")

    print("done")


if __name__ == "__main__":
    main()
