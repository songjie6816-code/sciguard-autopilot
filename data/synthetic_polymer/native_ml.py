"""Emit SciGuard's native Production ML projection into DataHub.

The dataset projection remains the source of truth for schema and fine-grained
lineage because DataHub's dataset aspects provide the strongest field-level
contract. This module adds a second, linked native projection for Production ML
semantics: features, feature tables, model groups, versioned models,
deployments, training runs, and inference runs.

Keeping both projections is deliberate. The dataset graph answers "which
field changed and which decision path is affected?" while the native graph
answers "which feature, model version, deployment, and training run must be
reviewed?".
"""

from __future__ import annotations

from dataclasses import dataclass

from datahub.emitter.mce_builder import make_dataset_urn
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    BaseDataClass,
    CaveatDetailsClass,
    CaveatsAndRecommendationsClass,
    DataProcessInstanceInputClass,
    DataProcessInstanceOutputClass,
    DataProcessInstancePropertiesClass,
    DataProcessInstanceRunEventClass,
    DataProcessInstanceRunResultClass,
    DataProcessRunStatusClass,
    DataProcessTypeClass,
    DeploymentStatusClass,
    EvaluationDataClass,
    GlobalTagsClass,
    IntendedUseClass,
    MLFeatureDataTypeClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLHyperParamClass,
    MLMetricClass,
    MLModelDeploymentPropertiesClass,
    MLModelGroupPropertiesClass,
    MLModelPropertiesClass,
    MLTrainingRunPropertiesClass,
    OwnerClass,
    OwnershipClass,
    OwnershipTypeClass,
    RunResultTypeClass,
    SourceCodeClass,
    SourceCodeUrlClass,
    SourceCodeUrlTypeClass,
    TagAssociationClass,
    TrainingDataClass,
    VersionTagClass,
)
from datahub.metadata.urns import (
    DataProcessInstanceUrn,
    MlFeatureTableUrn,
    MlFeatureUrn,
    MlModelDeploymentUrn,
    MlModelGroupUrn,
    MlModelUrn,
)

PLATFORM = "polymer_rnd"
ENV = "PROD"
ACTOR = "urn:li:corpuser:sciguard"
REPOSITORY_URL = "https://github.com/songjie6816-code/sciguard-autopilot"
SYNTHETIC_TAG = "urn:li:tag:sciguard:synthetic-data"
NATIVE_ML_TAG = "urn:li:tag:sciguard:native-production-ml"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    data_type: str
    description: str
    source_dataset: str
    source_field: str
    unit: str


@dataclass(frozen=True)
class ModelSpec:
    name: str
    display_name: str
    group: str
    version: str
    model_type: str
    feature_table: str
    features: tuple[str, ...]
    training_run: str
    deployment: str
    inference_run: str
    output_dataset: str
    owner: str
    criticality: str
    training_metric_name: str
    training_metric_value: str
    expected_target_unit: str | None = None


FEATURE_TABLES: dict[str, tuple[FeatureSpec, ...]] = {
    "tg_feature_table": (
        FeatureSpec(
            name="log10_mn",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Log-scaled number-average molecular weight.",
            source_dataset="cleaned_polymer_dataset",
            source_field="mn_g_mol",
            unit="log10(g/mol)",
        ),
        FeatureSpec(
            name="pdi",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Polymer dispersity index.",
            source_dataset="cleaned_polymer_dataset",
            source_field="pdi",
            unit="dimensionless",
        ),
        FeatureSpec(
            name="class_code",
            data_type=MLFeatureDataTypeClass.NOMINAL,
            description="Encoded polymer class.",
            source_dataset="cleaned_polymer_dataset",
            source_field="polymer_class",
            unit="category",
        ),
        FeatureSpec(
            name="tg_degC",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Glass-transition temperature normalized to degrees Celsius.",
            source_dataset="cleaned_polymer_dataset",
            source_field="tg_degC",
            unit="degC",
        ),
    ),
    "molecular_weight_feature_table": (
        FeatureSpec(
            name="mn_g_mol",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Number-average molecular weight.",
            source_dataset="cleaned_polymer_dataset",
            source_field="mn_g_mol",
            unit="g/mol",
        ),
        FeatureSpec(
            name="mw_g_mol",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Weight-average molecular weight.",
            source_dataset="cleaned_polymer_dataset",
            source_field="mw_g_mol",
            unit="g/mol",
        ),
        FeatureSpec(
            name="pdi",
            data_type=MLFeatureDataTypeClass.CONTINUOUS,
            description="Polymer dispersity index.",
            source_dataset="cleaned_polymer_dataset",
            source_field="pdi",
            unit="dimensionless",
        ),
    ),
}


MODELS: dict[str, ModelSpec] = {
    "tg_prediction_model": ModelSpec(
        name="tg_prediction_model",
        display_name="Tg Prediction Model v3",
        group="tg_prediction_models",
        version="tg-gbr-v3",
        model_type="gradient_boosting_regressor",
        feature_table="tg_feature_table",
        features=("log10_mn", "pdi", "class_code", "tg_degC"),
        training_run="train-tg-gbr-v3",
        deployment="tg-prediction-production",
        inference_run="rank-candidates-production",
        output_dataset="candidate_ranking_report",
        owner="ml_engineer",
        criticality="CRITICAL",
        training_metric_name="validation_mae_degC",
        training_metric_value="6.4",
        expected_target_unit="degC",
    ),
    "durability_model": ModelSpec(
        name="durability_model",
        display_name="Durability Model v2",
        group="durability_models",
        version="durability-rf-v2",
        model_type="random_forest_regressor",
        feature_table="molecular_weight_feature_table",
        features=("mn_g_mol", "mw_g_mol", "pdi"),
        training_run="train-durability-rf-v2",
        deployment="durability-production",
        inference_run="formulation-production",
        output_dataset="formulation_report",
        owner="ml_engineer",
        criticality="HIGH",
        training_metric_name="validation_r2",
        training_metric_value="0.91",
    ),
}


def dataset_urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env=ENV)


def feature_table_urn(name: str) -> str:
    return str(MlFeatureTableUrn(platform=PLATFORM, name=name))


def feature_urn(table: str, name: str) -> str:
    return str(MlFeatureUrn(feature_namespace=table, name=name))


def model_group_urn(name: str) -> str:
    return str(MlModelGroupUrn(platform=PLATFORM, name=name, env=ENV))


def model_urn(name: str) -> str:
    return str(MlModelUrn(platform=PLATFORM, name=name, env=ENV))


def deployment_urn(name: str) -> str:
    return str(MlModelDeploymentUrn(platform=PLATFORM, name=name, env=ENV))


def process_urn(name: str) -> str:
    return str(DataProcessInstanceUrn(id=f"sciguard-{name}"))


def _emit(graph, urn: str, aspect) -> None:
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def _merge_owner(graph, urn: str, owner: str) -> None:
    existing = graph.get_aspect(urn, OwnershipClass)
    owners = list(existing.owners) if existing else []
    owner_urn = f"urn:li:corpuser:{owner}"
    if owner_urn not in {item.owner for item in owners}:
        owners.append(OwnerClass(owner=owner_urn, type=OwnershipTypeClass.TECHNICAL_OWNER))
        _emit(graph, urn, OwnershipClass(owners=owners))


def _merge_tags(graph, urn: str, tags: list[str]) -> None:
    existing = graph.get_aspect(urn, GlobalTagsClass)
    associations = list(existing.tags) if existing else []
    have = {item.tag for item in associations}
    associations.extend(TagAssociationClass(tag=tag) for tag in tags if tag not in have)
    if existing is None or {item.tag for item in associations} != have:
        _emit(graph, urn, GlobalTagsClass(tags=associations))


def _emit_feature_graph(graph) -> None:
    for table_name, specs in FEATURE_TABLES.items():
        table_urn = feature_table_urn(table_name)
        feature_urns = [feature_urn(table_name, spec.name) for spec in specs]
        _emit(
            graph,
            table_urn,
            MLFeatureTablePropertiesClass(
                description=(
                    "Native Production ML feature projection for SciGuard. "
                    "The paired dataset entity retains field-level transform lineage."
                ),
                mlFeatures=feature_urns,
                customProperties={
                    "sciguard:dataset_projection_urn": dataset_urn(table_name),
                    "sciguard:projection_mode": "native_ml_plus_dataset_lineage",
                    "sciguard:feature_branch": (
                        "tg" if table_name == "tg_feature_table" else "molecular_weight"
                    ),
                },
            ),
        )
        _merge_owner(graph, table_urn, "ml_engineer")
        _merge_tags(
            graph,
            table_urn,
            [SYNTHETIC_TAG, NATIVE_ML_TAG, "urn:li:tag:sciguard:role-feature-table"],
        )

        for spec in specs:
            urn = feature_urn(table_name, spec.name)
            _emit(
                graph,
                urn,
                MLFeaturePropertiesClass(
                    description=spec.description,
                    dataType=spec.data_type,
                    sources=[dataset_urn(spec.source_dataset)],
                    customProperties={
                        "sciguard:source_field": spec.source_field,
                        "sciguard:unit": spec.unit,
                        "sciguard:feature_table_urn": table_urn,
                        "sciguard:dataset_projection_urn": dataset_urn(table_name),
                    },
                ),
            )
            _merge_owner(graph, urn, "ml_engineer")
            _merge_tags(
                graph,
                urn,
                [SYNTHETIC_TAG, NATIVE_ML_TAG, "urn:li:tag:sciguard:role-feature"],
            )


def _emit_process(
    graph,
    *,
    name: str,
    display_name: str,
    inputs: list[str],
    outputs: list[str],
    process_type: str,
    properties: dict[str, str],
) -> str:
    urn = process_urn(name)
    stamp = AuditStampClass(time=0, actor=ACTOR)
    _emit(
        graph,
        urn,
        DataProcessInstancePropertiesClass(
            name=display_name,
            created=stamp,
            type=process_type,
            customProperties={
                **properties,
                "sciguard:owner_urn": "urn:li:corpuser:ml_engineer",
                "sciguard:synthetic": "true",
                "sciguard:native_projection": "true",
            },
            externalUrl=REPOSITORY_URL,
        ),
    )
    _emit(graph, urn, DataProcessInstanceInputClass(inputs=inputs))
    _emit(graph, urn, DataProcessInstanceOutputClass(outputs=outputs))
    _emit(
        graph,
        urn,
        DataProcessInstanceRunEventClass(
            timestampMillis=0,
            status=DataProcessRunStatusClass.COMPLETE,
            result=DataProcessInstanceRunResultClass(
                type=RunResultTypeClass.SUCCESS,
                nativeResultType="SCIGUARD_SYNTHETIC_BASELINE",
            ),
            externalUrl=REPOSITORY_URL,
        ),
    )
    return urn


def _emit_model_graph(graph) -> None:
    for spec in MODELS.values():
        group_urn = model_group_urn(spec.group)
        model_entity_urn = model_urn(spec.name)
        deployment_entity_urn = deployment_urn(spec.deployment)
        feature_urns = [feature_urn(spec.feature_table, name) for name in spec.features]

        training_run_urn = _emit_process(
            graph,
            name=spec.training_run,
            display_name=f"Training Run · {spec.version}",
            inputs=[
                dataset_urn("cleaned_polymer_dataset"),
                dataset_urn(spec.feature_table),
            ],
            outputs=[model_entity_urn],
            process_type=DataProcessTypeClass.BATCH_SCHEDULED,
            properties={
                "sciguard:run_role": "training",
                "sciguard:model_version": spec.version,
                "sciguard:reproducible": "true",
                "sciguard:source_commit": "synthetic-baseline",
            },
        )
        _emit(
            graph,
            training_run_urn,
            MLTrainingRunPropertiesClass(
                id=spec.training_run,
                externalUrl=REPOSITORY_URL,
                outputUrls=[model_entity_urn],
                hyperParams=[
                    MLHyperParamClass(name="training_rows", value="420"),
                    MLHyperParamClass(name="deterministic_seed", value="42"),
                ],
                trainingMetrics=[
                    MLMetricClass(
                        name=spec.training_metric_name,
                        value=spec.training_metric_value,
                    )
                ],
                customProperties={
                    "sciguard:training_dataset_urn": dataset_urn(
                        "cleaned_polymer_dataset"
                    ),
                    "sciguard:feature_table_urn": feature_table_urn(
                        spec.feature_table
                    ),
                },
            ),
        )
        inference_run_urn = _emit_process(
            graph,
            name=spec.inference_run,
            display_name=f"Inference Run · {spec.display_name}",
            inputs=[model_entity_urn, dataset_urn(spec.feature_table)],
            outputs=[dataset_urn(spec.output_dataset)],
            process_type=DataProcessTypeClass.BATCH_SCHEDULED,
            properties={
                "sciguard:run_role": "scientific_decision_inference",
                "sciguard:model_version": spec.version,
                "sciguard:output_decision_urn": dataset_urn(spec.output_dataset),
            },
        )

        _emit(
            graph,
            group_urn,
            MLModelGroupPropertiesClass(
                name=spec.group.replace("_", " ").title(),
                description=f"Version family for {spec.display_name}.",
                trainingJobs=[training_run_urn],
                downstreamJobs=[inference_run_urn],
                customProperties={
                    "sciguard:scientific_domain": "polymer_rnd",
                    "sciguard:criticality": spec.criticality,
                },
            ),
        )
        _merge_owner(graph, group_urn, spec.owner)
        _merge_tags(
            graph,
            group_urn,
            [SYNTHETIC_TAG, NATIVE_ML_TAG, "urn:li:tag:sciguard:role-model-group"],
        )

        custom_properties = {
            "sciguard:dataset_projection_urn": dataset_urn(spec.name),
            "sciguard:feature_table_urn": feature_table_urn(spec.feature_table),
            "sciguard:criticality": spec.criticality,
            "sciguard:deployment_stage": "production",
            "sciguard:last_validated_state": "trusted_baseline",
            "sciguard:projection_mode": "native_ml_plus_dataset_lineage",
        }
        if spec.expected_target_unit:
            custom_properties["sciguard:expected_target_unit"] = spec.expected_target_unit

        _emit(
            graph,
            model_entity_urn,
            MLModelPropertiesClass(
                name=spec.display_name,
                description=(
                    f"Native Production ML entity for {spec.display_name}. "
                    "Its paired dataset projection retains output schema and field lineage."
                ),
                version=VersionTagClass(versionTag=spec.version),
                type=spec.model_type,
                trainingJobs=[training_run_urn],
                downstreamJobs=[inference_run_urn],
                mlFeatures=feature_urns,
                deployments=[deployment_entity_urn],
                groups=[group_urn],
                hyperParams=[
                    MLHyperParamClass(
                        name="training_rows",
                        value="420",
                        description="Deterministic synthetic training-set size.",
                    )
                ],
                trainingMetrics=[
                    MLMetricClass(
                        name=spec.training_metric_name,
                        value=spec.training_metric_value,
                    )
                ],
                customProperties=custom_properties,
                externalUrl=REPOSITORY_URL,
            ),
        )
        _emit(
            graph,
            model_entity_urn,
            TrainingDataClass(
                trainingData=[
                    BaseDataClass(
                        dataset=dataset_urn("cleaned_polymer_dataset"),
                        motivation="Deterministic trusted training snapshot for the flagship.",
                        preProcessing=["scientific-unit normalization", "feature projection"],
                    )
                ]
            ),
        )
        _emit(
            graph,
            model_entity_urn,
            EvaluationDataClass(
                evaluationData=[
                    BaseDataClass(
                        dataset=dataset_urn("trusted_polymer_baseline"),
                        motivation="Counterfactual scientific-decision validation baseline.",
                    )
                ]
            ),
        )
        _emit(
            graph,
            model_entity_urn,
            SourceCodeClass(
                sourceCode=[
                    SourceCodeUrlClass(
                        type=SourceCodeUrlTypeClass.ML_MODEL_SOURCE_CODE,
                        sourceCodeUrl=f"{REPOSITORY_URL}/tree/main/data/synthetic_polymer",
                    )
                ]
            ),
        )
        _emit(
            graph,
            model_entity_urn,
            IntendedUseClass(
                primaryUses=[
                    (
                        "Rank candidate polymers for expert review."
                        if spec.name == "tg_prediction_model"
                        else "Estimate formulation durability for expert review."
                    )
                ],
                outOfScopeUses=[
                    "Autonomous scientific publication without contract validation.",
                    "Automatic production release without accountable-owner approval.",
                ],
            ),
        )
        _emit(
            graph,
            model_entity_urn,
            CaveatsAndRecommendationsClass(
                caveats=CaveatDetailsClass(
                    needsFurtherTesting=True,
                    caveatDescription=(
                        "Model validity depends on unit-consistent experimental inputs."
                    ),
                ),
                recommendations=(
                    "Require SciGuard contract checks and evidence-gated recovery "
                    "before decision publication."
                ),
                idealDatasetCharacteristics=[
                    "Explicit scientific units",
                    "Instrument and firmware provenance",
                    "Stable sample identifiers",
                ],
            ),
        )
        _merge_owner(graph, model_entity_urn, spec.owner)
        _merge_tags(
            graph,
            model_entity_urn,
            [SYNTHETIC_TAG, NATIVE_ML_TAG, "urn:li:tag:sciguard:role-model"],
        )

        _emit(
            graph,
            deployment_entity_urn,
            MLModelDeploymentPropertiesClass(
                description=f"Production deployment for {spec.display_name}.",
                version=VersionTagClass(versionTag=spec.version),
                status=DeploymentStatusClass.IN_SERVICE,
                externalUrl=REPOSITORY_URL,
                customProperties={
                    "sciguard:model_urn": model_entity_urn,
                    "sciguard:inference_run_urn": inference_run_urn,
                    "sciguard:decision_output_urn": dataset_urn(spec.output_dataset),
                    "sciguard:approval_policy": (
                        "SCIENTIFIC_DECISION_CRITICAL"
                        if spec.criticality == "CRITICAL"
                        else "SCIENTIFIC_MODEL_STANDARD"
                    ),
                },
            ),
        )
        _merge_owner(graph, deployment_entity_urn, spec.owner)
        _merge_tags(
            graph,
            deployment_entity_urn,
            [SYNTHETIC_TAG, NATIVE_ML_TAG, "urn:li:tag:sciguard:role-deployment"],
        )


def emit_native_ml_graph(graph) -> dict[str, list[str]]:
    """Emit every native ML entity and return a stable, inspectable receipt."""

    _emit_feature_graph(graph)
    _emit_model_graph(graph)
    return {
        "feature_tables": sorted(feature_table_urn(name) for name in FEATURE_TABLES),
        "features": sorted(
            feature_urn(table, spec.name)
            for table, specs in FEATURE_TABLES.items()
            for spec in specs
        ),
        "model_groups": sorted(model_group_urn(spec.group) for spec in MODELS.values()),
        "models": sorted(model_urn(spec.name) for spec in MODELS.values()),
        "deployments": sorted(deployment_urn(spec.deployment) for spec in MODELS.values()),
        "training_runs": sorted(process_urn(spec.training_run) for spec in MODELS.values()),
        "inference_runs": sorted(process_urn(spec.inference_run) for spec in MODELS.values()),
    }
