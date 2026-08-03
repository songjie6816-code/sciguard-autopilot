"""Verify live native DataHub entities and capture a public-safe receipt."""

from __future__ import annotations

# Direct execution adds the repository root before importing project modules.
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datahub.metadata.schema_classes import (
    DataProcessInstanceInputClass,
    DataProcessInstanceOutputClass,
    DataProcessInstancePropertiesClass,
    DataProcessInstanceRunEventClass,
    DocumentInfoClass,
    IncidentInfoClass,
    MLFeaturePropertiesClass,
    MLFeatureTablePropertiesClass,
    MLModelDeploymentPropertiesClass,
    MLModelGroupPropertiesClass,
    MLModelPropertiesClass,
    MLTrainingRunPropertiesClass,
)

from core.impact import trace_field_impact
from core.investigation_models import RootCause
from core.repair import NativeMLDecisionContext, create_unit_repair_bundle
from data.synthetic_polymer import native_ml
from datahub_client import metadata_reader
from datahub_client.backends import SdkReader
from datahub_client.incident_writer import (
    decision_log_urn,
    incident_urn,
    raise_incident,
    update_incident_status,
    write_decision_log,
)

OUTPUTS = [
    ROOT / "examples" / "outputs" / "datahub_live_receipt.json",
    ROOT / "web" / "public" / "evidence" / "datahub_live_receipt.json",
]
INCIDENT_ID = "inc-native-live-receipt"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _aspect_digest(aspect) -> str:
    payload = json.dumps(
        aspect.to_obj(),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_entity(graph, urn: str, entity_type: str, aspects: list[type]) -> dict:
    observed = []
    for aspect_type in aspects:
        try:
            aspect = graph.get_aspect(urn, aspect_type)
        except TypeError as exc:
            if "timeseries aspect" not in str(exc):
                raise
            aspect = graph.get_latest_timeseries_value(urn, aspect_type, {})
        if aspect is None:
            raise LookupError(f"{urn} is missing {aspect_type.__name__}")
        observed.append(
            {
                "aspect": aspect_type.__name__,
                "sha256": _aspect_digest(aspect),
            }
        )
    return {
        "urn": urn,
        "entity_type": entity_type,
        "required_aspects": [aspect.__name__ for aspect in aspects],
        "observed_aspects": observed,
        "verified": True,
    }


def _server_config() -> dict:
    with urlopen("http://localhost:8080/config", timeout=5) as response:
        return json.loads(response.read())


def capture() -> dict:
    graph = metadata_reader.connect()
    entities = []
    for name in native_ml.FEATURE_TABLES:
        entities.append(
            _verify_entity(
                graph,
                native_ml.feature_table_urn(name),
                "MLFeatureTable",
                [MLFeatureTablePropertiesClass],
            )
        )
        for feature in native_ml.FEATURE_TABLES[name]:
            entities.append(
                _verify_entity(
                    graph,
                    native_ml.feature_urn(name, feature.name),
                    "MLFeature",
                    [MLFeaturePropertiesClass],
                )
            )
    for spec in native_ml.MODELS.values():
        entities.extend(
            [
                _verify_entity(
                    graph,
                    native_ml.model_group_urn(spec.group),
                    "MLModelGroup",
                    [MLModelGroupPropertiesClass],
                ),
                _verify_entity(
                    graph,
                    native_ml.model_urn(spec.name),
                    "MLModel",
                    [MLModelPropertiesClass],
                ),
                _verify_entity(
                    graph,
                    native_ml.deployment_urn(spec.deployment),
                    "MLModelDeployment",
                    [MLModelDeploymentPropertiesClass],
                ),
                _verify_entity(
                    graph,
                    native_ml.process_urn(spec.training_run),
                    "DataProcessInstance",
                    [
                        DataProcessInstancePropertiesClass,
                        DataProcessInstanceInputClass,
                        DataProcessInstanceOutputClass,
                        DataProcessInstanceRunEventClass,
                        MLTrainingRunPropertiesClass,
                    ],
                ),
                _verify_entity(
                    graph,
                    native_ml.process_urn(spec.inference_run),
                    "DataProcessInstance",
                    [
                        DataProcessInstancePropertiesClass,
                        DataProcessInstanceInputClass,
                        DataProcessInstanceOutputClass,
                        DataProcessInstanceRunEventClass,
                    ],
                ),
            ]
        )

    source_urn = native_ml.dataset_urn("raw_polymer_experiments")
    impact = trace_field_impact(SdkReader(graph), source_urn, ["tg_value"])
    contexts = []
    for urn, name in [
        *zip(impact.affected_urns, impact.affected_names, strict=True),
        *zip(impact.unaffected_urns, impact.unaffected_names, strict=True),
    ]:
        if not name.endswith("_model"):
            continue
        raw = metadata_reader.get_native_ml_model_context(graph, urn)
        properties = raw.pop("custom_properties")
        contexts.append(
            NativeMLDecisionContext(
                **raw,
                criticality=properties.get("sciguard:criticality", "UNKNOWN"),
                expected_target_unit=properties.get("sciguard:expected_target_unit"),
                affected=urn in impact.affected_urns,
            )
        )

    root_cause = RootCause.model_validate(
        json.loads(
            (ROOT / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
        )["flagship"]["root_cause"]
    )
    evidence_ids = [
        "live:datahub-native-entity-readback",
        "live:datahub-field-lineage-readback",
    ]
    incident_entities = [
        urn
        for urn in [*impact.affected_urns, *impact.unaffected_urns]
        if urn.startswith("urn:li:dataset:")
    ]
    opened = raise_incident(
        graph,
        incident_id=INCIDENT_ID,
        # DataHub GMS 1.5 IncidentInfo accepts dataset projections but rejects
        # native MLFeature, MLModel, and DataProcessInstance destinations. The
        # full native decision cone remains linked in the Decision Log.
        entities=incident_entities,
        assignee_urn="urn:li:corpuser:research_lead",
        title="SciGuard native lifecycle verification",
        description=root_cause.explanation,
        evidence_ids=evidence_ids,
    )
    bundle = create_unit_repair_bundle(
        incident_id=INCIDENT_ID,
        root_cause=root_cause,
        impact=impact,
        evidence_ids=evidence_ids,
        approver_urn="urn:li:corpuser:research_lead",
        native_ml_context=contexts,
        datahub_incident_urn=incident_urn(INCIDENT_ID),
        datahub_decision_log_urn=decision_log_urn(INCIDENT_ID),
    )
    initial_log = write_decision_log(
        graph,
        bundle=bundle,
        incident_state="QUARANTINED",
    )
    resolved = update_incident_status(
        graph,
        incident_id=INCIDENT_ID,
        resolved=True,
        message="Live native entity, Incident, and Decision Log verification passed.",
        evidence_ids=evidence_ids,
    )
    final_log = write_decision_log(
        graph,
        bundle=bundle,
        incident_state="RESOLVED",
    )
    incident_aspect = graph.get_aspect(incident_urn(INCIDENT_ID), IncidentInfoClass)
    document_aspect = graph.get_aspect(decision_log_urn(INCIDENT_ID), DocumentInfoClass)
    if incident_aspect is None or document_aspect is None:
        raise LookupError("native Incident or Decision Log could not be read back")

    config = _server_config()
    counts = {
        entity_type: sum(
            item["entity_type"] == entity_type for item in entities
        )
        for entity_type in sorted({item["entity_type"] for item in entities})
    }
    receipt = {
        "schema_version": 1,
        "capture_type": "LIVE_DATAHUB_NATIVE_READBACK",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "capture_location": "LOCAL_DATAHUB_GMS",
        "server_type": config["datahub"]["serverType"],
        "server_version": config["versions"]["acryldata/datahub"]["version"],
        "cli_version": config["managedIngestion"]["defaultCliVersion"],
        "source_commit": _git("rev-parse", "HEAD"),
        "source_worktree_dirty": bool(
            _git("status", "--porcelain", "--untracked-files=normal")
        ),
        "entity_count": len(entities),
        "entity_counts": counts,
        "entities": entities,
        "native_model_context": [
            context.model_dump(mode="json") for context in contexts
        ],
        "incident_lifecycle": {
            "opened": opened.model_dump(mode="json"),
            "resolved": resolved.model_dump(mode="json"),
            "readback_state": incident_aspect.status.state,
            "readback_stage": incident_aspect.status.stage,
            "aspect_sha256": _aspect_digest(incident_aspect),
        },
        "decision_log_lifecycle": {
            "initial": initial_log.model_dump(mode="json"),
            "final": final_log.model_dump(mode="json"),
            "readback_state": document_aspect.status.state,
            "related_asset_count": len(document_aspect.relatedAssets or []),
            "aspect_sha256": _aspect_digest(document_aspect),
        },
        "all_verified": all(item["verified"] for item in entities)
        and incident_aspect.status.state == "RESOLVED"
        and document_aspect.status.state == "PUBLISHED",
    }
    raw = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    for output in OUTPUTS:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(raw, encoding="utf-8")
    return receipt


def main() -> None:
    receipt = capture()
    print(
        f"verified {receipt['entity_count']} native entities on "
        f"DataHub {receipt['server_version']}"
    )
    print(f"entity counts: {receipt['entity_counts']}")
    print(
        "incident: "
        f"{receipt['incident_lifecycle']['readback_state']} / "
        f"{receipt['incident_lifecycle']['readback_stage']}"
    )
    print(
        "decision log: "
        f"{receipt['decision_log_lifecycle']['readback_state']} / "
        f"{receipt['decision_log_lifecycle']['related_asset_count']} assets"
    )
    print(f"all verified: {receipt['all_verified']}")


if __name__ == "__main__":
    main()
