"""Register the deterministic flagship graph in DataHub.

All ten assets use dataset URNs so the current DataHub MCP Server and SDK readers expose
the same schema, ownership, custom properties, and multi-hop lineage. Model/report roles,
versions, criticality, and governance tags are explicit metadata—not name-only claims.

Dataset-level edges are always emitted. Fine-grained lineage is also emitted for the
single-upstream transformations, allowing later investigation to prove that ``tg_degC``
feeds only the Tg branch while the molecular-weight branch remains unaffected.
"""

from __future__ import annotations

from datahub.emitter.mce_builder import make_dataset_urn, make_schema_field_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    FineGrainedLineageClass,
    FineGrainedLineageDownstreamTypeClass,
    FineGrainedLineageUpstreamTypeClass,
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

from datahub_client import metadata_writer
from datahub_client.metadata_reader import connect

PLATFORM = "polymer_rnd"
ENV = "PROD"
SYNTHETIC_TAG = "urn:li:tag:sciguard:synthetic-data"

ML_METADATA_DECISION = {
    "mode": "dataset_entity_fallback",
    "reason": (
        "DataHub SDK 1.6 exposes native MLModel classes, but the current MCP/SDK parity "
        "contract reads schema, custom units, and lineage consistently through dataset URNs. "
        "A split native-model graph would weaken MCP parity for the competition demo."
    ),
    "revisit": "Add a native MLModel projection after verified MCP lineage parity exists.",
}


def _tags(role: str) -> list[str]:
    return [SYNTHETIC_TAG, f"urn:li:tag:sciguard:role-{role}"]


# field_lineage entries are (upstream field, downstream field). Every transformation in
# the flagship has one upstream dataset, keeping the contract explicit and testable.
NODES: dict[str, dict] = {
    "instrument_batch_B042": {
        "schema": [
            ("batch_id", "str"), ("instrument_id", "str"), ("instrument_firmware", "str"),
            ("expected_tg_unit", "str"), ("observed_tg_units", "str"),
            ("affected_rows", "num"),
        ],
        "description": "Synthetic DSC batch B042; firmware v4.2 emitted 187 Tg rows in Kelvin.",
        "units": {},
        "owner": "lab_experimentalist",
        "criticality": "HIGH",
        "tags": _tags("source-batch"),
        "upstreams": [],
        "field_lineage": [],
        "extra_props": {
            "entity_role": "source_batch",
            "batch_id": "B042",
            "instrument_id": "DSC-07",
            "instrument_firmware": "v4.2",
            "expected_tg_unit": "degC",
            "observed_tg_units": "degC,K",
            "affected_rows": "187",
        },
    },
    "raw_polymer_experiments": {
        "schema": [
            ("sample_id", "str"), ("batch_id", "str"), ("instrument_id", "str"),
            ("instrument_firmware", "str"), ("normalization_version", "str"),
            ("polymer_name", "str"), ("polymer_class", "str"), ("smiles", "str"),
            ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
            ("tg_value", "num"), ("tg_unit", "str"), ("measurement_method", "str"),
            ("gpc_calibration", "str"), ("test_protocol", "str"), ("measured_on", "str"),
        ],
        "description": "Raw synthetic polymer measurements including batch and instrument provenance.",
        "units": {
            "tg_value": "mixed:degC|K", "mn_g_mol": "g/mol", "mw_g_mol": "g/mol",
            "pdi": "dimensionless",
        },
        "owner": "lab_experimentalist",
        "criticality": "HIGH",
        "tags": _tags("dataset"),
        "upstreams": ["instrument_batch_B042"],
        "field_lineage": [
            ("batch_id", "batch_id"),
            ("instrument_id", "instrument_id"),
            ("instrument_firmware", "instrument_firmware"),
            ("expected_tg_unit", "tg_unit"),
        ],
        "extra_props": {"entity_role": "dataset", "row_count": "420"},
    },
    "cleaned_polymer_dataset": {
        "schema": [
            ("sample_id", "str"), ("batch_id", "str"), ("instrument_id", "str"),
            ("instrument_firmware", "str"), ("normalization_version", "str"),
            ("polymer_name", "str"), ("polymer_class", "str"), ("smiles", "str"),
            ("mn_g_mol", "num"), ("mw_g_mol", "num"), ("pdi", "num"),
            ("tg_degC", "num"),
        ],
        "description": "Buggy v1 normalization output; mixed-unit values are labelled as Celsius.",
        "units": {
            "tg_degC": "degC", "mn_g_mol": "g/mol", "mw_g_mol": "g/mol",
            "pdi": "dimensionless",
        },
        "owner": "data_engineer",
        "criticality": "HIGH",
        "tags": _tags("dataset"),
        "upstreams": ["raw_polymer_experiments"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("batch_id", "batch_id"),
            ("instrument_id", "instrument_id"),
            ("instrument_firmware", "instrument_firmware"),
            ("normalization_version", "normalization_version"),
            ("polymer_name", "polymer_name"), ("polymer_class", "polymer_class"),
            ("smiles", "smiles"), ("mn_g_mol", "mn_g_mol"),
            ("mw_g_mol", "mw_g_mol"), ("pdi", "pdi"), ("tg_value", "tg_degC"),
        ],
        "extra_props": {
            "entity_role": "dataset",
            "normalization_version": "tg-normalizer-v1",
            "unit_contract_status": "FAILED_ON_B042",
        },
    },
    "tg_feature_table": {
        "schema": [
            ("sample_id", "str"), ("batch_id", "str"), ("log10_mn", "num"),
            ("pdi", "num"), ("class_code", "num"), ("tg_degC", "num"),
        ],
        "description": "Tg model features; directly consumes the contaminated tg_degC field.",
        "units": {
            "log10_mn": "log10(g/mol)", "pdi": "dimensionless", "tg_degC": "degC",
        },
        "owner": "ml_engineer",
        "criticality": "HIGH",
        "tags": _tags("feature-table"),
        "upstreams": ["cleaned_polymer_dataset"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("batch_id", "batch_id"),
            ("mn_g_mol", "log10_mn"), ("pdi", "pdi"),
            ("polymer_class", "class_code"), ("tg_degC", "tg_degC"),
        ],
        "extra_props": {"entity_role": "feature_table", "feature_branch": "tg"},
    },
    "molecular_weight_feature_table": {
        "schema": [
            ("sample_id", "str"), ("batch_id", "str"), ("mn_g_mol", "num"),
            ("mw_g_mol", "num"), ("pdi", "num"),
        ],
        "description": "Molecular-weight features; intentionally does not consume Tg.",
        "units": {
            "mn_g_mol": "g/mol", "mw_g_mol": "g/mol", "pdi": "dimensionless",
        },
        "owner": "ml_engineer",
        "criticality": "HIGH",
        "tags": _tags("feature-table"),
        "upstreams": ["cleaned_polymer_dataset"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("batch_id", "batch_id"),
            ("mn_g_mol", "mn_g_mol"), ("mw_g_mol", "mw_g_mol"), ("pdi", "pdi"),
        ],
        "extra_props": {"entity_role": "feature_table", "feature_branch": "molecular_weight"},
    },
    "tg_prediction_model": {
        "schema": [("sample_id", "str"), ("predicted_tg_degC", "num")],
        "description": "Tg gradient-boosting model represented as a dataset for MCP parity.",
        "units": {"predicted_tg_degC": "degC"},
        "owner": "ml_engineer",
        "criticality": "CRITICAL",
        "tags": _tags("model"),
        "upstreams": ["tg_feature_table"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("tg_degC", "predicted_tg_degC"),
        ],
        "extra_props": {
            "entity_role": "model",
            "model_version": "tg-gbr-v3",
            "code_version": "ranker-2026.07",
            "algorithm": "gradient_boosting",
            "target": "tg_degC",
            "expected_target_unit": "degC",
            "training_rows": "420",
            "validation_mae_degC": "6.4",
            "ml_metadata_mode": ML_METADATA_DECISION["mode"],
        },
    },
    "exploratory_dashboard": {
        "schema": [("sample_id", "str"), ("tg_degC", "num")],
        "description": "Internal exploratory Tg dashboard; warning only during the incident.",
        "units": {"tg_degC": "degC"},
        "owner": "research_analyst",
        "criticality": "MEDIUM",
        "tags": _tags("dashboard"),
        "upstreams": ["tg_feature_table"],
        "field_lineage": [("sample_id", "sample_id"), ("tg_degC", "tg_degC")],
        "extra_props": {"entity_role": "dashboard", "audience": "internal_exploration"},
    },
    "durability_model": {
        "schema": [("sample_id", "str"), ("durability_score", "num")],
        "description": "Durability model using only molecular-weight features.",
        "units": {"durability_score": "dimensionless"},
        "owner": "ml_engineer",
        "criticality": "HIGH",
        "tags": _tags("model"),
        "upstreams": ["molecular_weight_feature_table"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("mn_g_mol", "durability_score"),
            ("mw_g_mol", "durability_score"), ("pdi", "durability_score"),
        ],
        "extra_props": {
            "entity_role": "model",
            "model_version": "durability-rf-v2",
            "algorithm": "random_forest",
            "ml_metadata_mode": ML_METADATA_DECISION["mode"],
        },
    },
    "candidate_ranking_report": {
        "schema": [
            ("rank", "num"), ("candidate_id", "str"), ("predicted_tg_degC", "num"),
            ("pipeline_status", "str"),
        ],
        "description": "Decision-critical candidate ranking used by the morning selection meeting.",
        "units": {"predicted_tg_degC": "degC"},
        "owner": "research_lead",
        "criticality": "CRITICAL",
        "tags": _tags("decision-report"),
        "upstreams": ["tg_prediction_model"],
        "field_lineage": [
            ("sample_id", "candidate_id"), ("predicted_tg_degC", "predicted_tg_degC"),
        ],
        "extra_props": {
            "entity_role": "decision_report",
            "decision_meeting": "morning_candidate_selection",
            "publish_guard": "required",
        },
    },
    "formulation_report": {
        "schema": [("sample_id", "str"), ("durability_score", "num")],
        "description": "Formulation report produced from the unaffected durability branch.",
        "units": {"durability_score": "dimensionless"},
        "owner": "research_lead",
        "criticality": "HIGH",
        "tags": _tags("report"),
        "upstreams": ["durability_model"],
        "field_lineage": [
            ("sample_id", "sample_id"), ("durability_score", "durability_score"),
        ],
        "extra_props": {"entity_role": "report", "decision_scope": "formulation"},
    },
}

LEGACY_LINEAGE_CHILDREN = ("polymer_feature_table", "candidate_report")


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env=ENV)


def _schema_aspect(name: str, cols: list[tuple[str, str]]) -> SchemaMetadataClass:
    fields = []
    for column, kind in cols:
        dtype = NumberTypeClass() if kind == "num" else StringTypeClass()
        fields.append(
            SchemaFieldClass(
                fieldPath=column,
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


def _seed_properties(graph, urn: str, name: str, node: dict) -> None:
    existing = graph.get_aspect(urn, DatasetPropertiesClass)
    aspect = existing or DatasetPropertiesClass(customProperties={})
    aspect.name = name
    aspect.description = node["description"]
    seeded = {f"unit:{field}": unit for field, unit in node.get("units", {}).items()}
    seeded.update(
        {
            "sciguard:criticality": node["criticality"],
            "sciguard:synthetic": "true",
            **node.get("extra_props", {}),
        }
    )
    aspect.customProperties = {**dict(aspect.customProperties or {}), **seeded}
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _merge_owner(graph, urn: str, owner: str) -> None:
    existing = graph.get_aspect(urn, OwnershipClass)
    owners = list(existing.owners) if existing else []
    owner_urn = f"urn:li:corpuser:{owner}"
    if owner_urn not in {item.owner for item in owners}:
        owners.append(OwnerClass(owner=owner_urn, type=OwnershipTypeClass.TECHNICAL_OWNER))
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=OwnershipClass(owners=owners)))


def _lineage_aspect(name: str, node: dict) -> UpstreamLineageClass:
    upstreams = [
        UpstreamClass(dataset=_urn(upstream), type=DatasetLineageTypeClass.TRANSFORMED)
        for upstream in node["upstreams"]
    ]
    fine_grained = []
    if node["upstreams"]:
        upstream_name = node["upstreams"][0]
        fine_grained = [
            FineGrainedLineageClass(
                upstreamType=FineGrainedLineageUpstreamTypeClass.FIELD_SET,
                downstreamType=FineGrainedLineageDownstreamTypeClass.FIELD,
                upstreams=[make_schema_field_urn(_urn(upstream_name), upstream_field)],
                downstreams=[make_schema_field_urn(_urn(name), downstream_field)],
                transformOperation=f"sciguard:{upstream_field}->{downstream_field}",
                confidenceScore=1.0,
            )
            for upstream_field, downstream_field in node["field_lineage"]
        ]
    return UpstreamLineageClass(upstreams=upstreams, fineGrainedLineages=fine_grained)


def main() -> None:
    graph = connect()

    for name, node in NODES.items():
        urn = _urn(name)
        _seed_properties(graph, urn, name, node)
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=_schema_aspect(name, node["schema"])))
        _merge_owner(graph, urn, node["owner"])
        metadata_writer.add_tags(graph, urn, node["tags"])
        graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=_lineage_aspect(name, node)))
        upstream = ",".join(node["upstreams"]) or "(source)"
        print(
            f"[node] {name:32} owner={node['owner']:18} "
            f"criticality={node['criticality']:8} upstream={upstream}"
        )

    # These two SciGuard-owned demo nodes belonged to the pre-WP1 linear graph. Emptying
    # only their lineage avoids stale branches without deleting entities or other metadata.
    for legacy_name in LEGACY_LINEAGE_CHILDREN:
        graph.emit(
            MetadataChangeProposalWrapper(
                entityUrn=_urn(legacy_name),
                aspect=UpstreamLineageClass(upstreams=[], fineGrainedLineages=[]),
            )
        )
        print(f"[migrate] detached legacy lineage for {legacy_name}")

    print(f"done: {len(NODES)} flagship assets; field lineage enabled")


if __name__ == "__main__":
    main()
