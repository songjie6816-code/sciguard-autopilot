"""Capture one canonical DataHub-backed SciGuard incident from signal to recovery.

The public artifact is produced from one live run and one repair revision. Only
machine-local repository and Python executable paths are redacted; the action,
verification, approval, application, recovery, and DataHub read-back receipts
remain bound by their original IDs and SHA-256 digests.
"""

from __future__ import annotations

# Direct execution adds the repository root before importing project modules.
# ruff: noqa: E402

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datahub.metadata.schema_classes import (
    DatasetPropertiesClass,
    DocumentInfoClass,
    IncidentInfoClass,
)

from api.run_store import (
    RunMode,
    RunStatus,
    RunStore,
    current_source_commit,
    current_worktree_dirty,
)
from api.runtime import CONTROL_URN, DEFAULT_SYMPTOM, SciGuardRuntime
from core.approval import ApprovalAuthority, ApprovalDecision
from core.events import Event, EventType, validate_event_stream
from core.repair import RepairBundle, RepairStatus
from data.synthetic_polymer import native_ml
from datahub_client import metadata_reader
from datahub_client.incident_writer import decision_log_urn, incident_urn
from scripts.capture_datahub_live_receipt import (
    _aspect_digest,
    _server_config,
    _verify_entity,
)

INCIDENT_ID = "inc-sciguard-champion"
PUBLIC_REPOSITORY_LABEL = "EPHEMERAL_REPRODUCIBLE_GIT_SANDBOX"
DEMO_SIGNING_KEY = b"sciguard-champion-public-demo-key-not-production"
REPLAY_ROOTS = [
    ROOT / "examples" / "replays",
    ROOT / "web" / "public" / "replays",
]
DATAHUB_RECEIPTS = [
    ROOT / "examples" / "outputs" / "datahub_live_receipt.json",
    ROOT / "web" / "public" / "evidence" / "datahub_live_receipt.json",
]


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    os.replace(temporary, path)


def _bootstrap_repository(destination: Path) -> None:
    shutil.copytree(ROOT / "examples" / "repair_sandbox", destination)
    _git(destination, "init", "-q", "-b", "main")
    _git(destination, "config", "user.name", "SciGuard Canonical Capture")
    _git(destination, "config", "user.email", "sciguard@example.invalid")
    _git(destination, "add", "--all")
    _git(destination, "commit", "-q", "-m", "baseline scientific normalizer")


def _redact(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, dict):
        return {key: _redact(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, replacements) for item in value]
    if isinstance(value, str):
        redacted = value
        for original, replacement in replacements.items():
            redacted = redacted.replace(original, replacement)
        return redacted
    return value


def _public_event_bytes(
    events: list[Event],
    *,
    repository: Path,
) -> tuple[bytes, list[dict[str, str]]]:
    redactions = [
        {
            "field_class": "machine_local_repository_path",
            "replacement": PUBLIC_REPOSITORY_LABEL,
        },
        {
            "field_class": "machine_local_python_executable",
            "replacement": "python",
        },
    ]
    replacements = {
        str(repository.resolve()): PUBLIC_REPOSITORY_LABEL,
        str(repository): PUBLIC_REPOSITORY_LABEL,
        sys.executable: "python",
    }
    projected = [
        Event.model_validate(_redact(event.model_dump(mode="json"), replacements))
        for event in events
    ]
    validate_event_stream(projected)
    raw = "".join(
        json.dumps(
            event.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
        for event in projected
    ).encode("utf-8")
    return raw, redactions


def _native_entities(graph) -> list[dict]:
    from datahub.metadata.schema_classes import (
        DataProcessInstanceInputClass,
        DataProcessInstanceOutputClass,
        DataProcessInstancePropertiesClass,
        DataProcessInstanceRunEventClass,
        MLFeaturePropertiesClass,
        MLFeatureTablePropertiesClass,
        MLModelDeploymentPropertiesClass,
        MLModelGroupPropertiesClass,
        MLModelPropertiesClass,
        MLTrainingRunPropertiesClass,
    )

    entities: list[dict] = []
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
    return entities


def _reset_active_overlay_if_needed(runtime: SciGuardRuntime) -> None:
    graph = metadata_reader.connect()
    control = graph.get_aspect(CONTROL_URN, DatasetPropertiesClass)
    properties = dict(control.customProperties or {}) if control else {}
    persisted_incident = properties.get("sciguard:incident_id")
    if persisted_incident:
        runtime.reset(persisted_incident)


def _run_canonical_chain(
    *,
    source_commit: str,
    source_dirty: bool,
    workspace: Path,
) -> tuple[RunStore, SciGuardRuntime, RepairBundle, list[dict], list[dict]]:
    repository = workspace / "repair-repository"
    _bootstrap_repository(repository)
    store = RunStore(
        workspace / "runs",
        source_commit=source_commit,
        source_worktree_dirty=source_dirty,
    )
    authority = ApprovalAuthority(
        DEMO_SIGNING_KEY,
        key_id="sciguard-champion-demo-v1",
    )
    runtime = SciGuardRuntime(
        repair_repository=repository,
        deployment_root=workspace / "deployments",
        approval_authority=authority,
    )
    _reset_active_overlay_if_needed(runtime)

    store.start_run(INCIDENT_ID)
    try:
        result = runtime.run_live(
            INCIDENT_ID,
            DEFAULT_SYMPTOM,
            store.append_event,
        )
        store.finish_run(
            INCIDENT_ID,
            incident_state=result.incident_state,
            datahub_backend=result.datahub_backend,
        )
        published = runtime.publish_repair(store, INCIDENT_ID)
        verified = runtime.verify_repair(store, INCIDENT_ID)
        approved = runtime.approve_repair(
            store,
            INCIDENT_ID,
            reviewer_urn=verified.approval.approver_urn,
            decision=ApprovalDecision.APPROVE,
            note=(
                "Reviewed the commit-bound unit contract, P-204 rank restoration, "
                "safe-branch digest, rollback plan, and exact target revision."
            ),
        )
        applied = runtime.apply_repair(store, INCIDENT_ID)
        first_recovery = runtime.recover(
            store,
            INCIDENT_ID,
            approval_receipt_id=None,
        )
        second_recovery = runtime.recover(
            store,
            INCIDENT_ID,
            approval_receipt_id=None,
        )
    except Exception as exc:
        store.fail_run(INCIDENT_ID, f"{type(exc).__name__}: {exc}")
        raise

    if published.status is not RepairStatus.PUBLISHED:
        raise RuntimeError("canonical change was not published")
    if verified.status is not RepairStatus.VERIFIED:
        raise RuntimeError("canonical change was not verified")
    if approved.status is not RepairStatus.APPROVED:
        raise RuntimeError("canonical change was not approved")
    if applied.status is not RepairStatus.APPLIED:
        raise RuntimeError("canonical change was not applied")
    if (
        first_recovery.resume_allowed
        or first_recovery.clean_run_count != 1
        or not second_recovery.resume_allowed
        or second_recovery.clean_run_count != 2
        or second_recovery.incident_state != "RESOLVED"
    ):
        raise RuntimeError("canonical two-clean-run recovery policy was not enforced")

    events = store.get_events(INCIDENT_ID)
    recovery_receipts = [
        event.payload
        for event in events
        if event.event_type is EventType.RECOVERY_EVIDENCE_REFRESHED
    ]
    if len(recovery_receipts) != 2:
        raise RuntimeError("canonical run did not record two fresh recovery receipts")
    recovery_results = [
        event.payload
        for event in events
        if event.event_type
        in {
            EventType.RECOVERY_CHECKED,
            EventType.INCIDENT_RESOLVED,
        }
    ]
    if len(recovery_results) != 2:
        raise RuntimeError("canonical run did not record both recovery decisions")
    return store, runtime, applied, recovery_receipts, recovery_results


def _datahub_receipt(
    *,
    bundle: RepairBundle,
    events: list[Event],
    public_events_sha256: str,
    evaluation_report_sha256: str,
    redactions: list[dict[str, str]],
    recovery_receipts: list[dict],
    recovery_results: list[dict],
    source_commit: str,
    source_dirty: bool,
) -> dict:
    graph = metadata_reader.connect()
    native_incident = graph.get_aspect(incident_urn(INCIDENT_ID), IncidentInfoClass)
    decision_log = graph.get_aspect(decision_log_urn(INCIDENT_ID), DocumentInfoClass)
    control = graph.get_aspect(CONTROL_URN, DatasetPropertiesClass)
    if native_incident is None or decision_log is None or control is None:
        raise LookupError("canonical DataHub Incident, Decision Log, or control is missing")

    application = bundle.application_receipt or {}
    change = bundle.external_action_receipt or {}
    verification = bundle.verification_receipt or {}
    approval = bundle.approval_receipt or {}
    required_tokens = {
        "commit_sha": str(change.get("commit_sha", "")),
        "verification_receipt_id": str(verification.get("receipt_id", "")),
        "approval_receipt_id": str(approval.get("receipt_id", "")),
        "application_receipt_id": str(application.get("receipt_id", "")),
        "recovery_verification_receipt_id": str(recovery_receipts[-1].get("receipt_id", "")),
    }
    document_text = decision_log.contents.text
    missing_tokens = [
        name for name, token in required_tokens.items() if not token or token not in document_text
    ]
    if missing_tokens:
        raise RuntimeError(
            f"DataHub Decision Log is missing canonical receipt tokens: {missing_tokens}"
        )

    control_properties = dict(control.customProperties or {})
    if (
        native_incident.status.state != "RESOLVED"
        or native_incident.status.stage != "FIXED"
        or decision_log.status.state != "PUBLISHED"
        or control_properties.get("sciguard:incident_id") != INCIDENT_ID
        or control_properties.get("sciguard:resume_authorized") != "true"
    ):
        raise RuntimeError("DataHub read-back did not prove the resolved canonical state")

    native_entities = _native_entities(graph)
    counts = {
        entity_type: sum(entity["entity_type"] == entity_type for entity in native_entities)
        for entity_type in sorted({entity["entity_type"] for entity in native_entities})
    }
    incident_events = [
        event for event in events if event.event_type is EventType.DATAHUB_INCIDENT_WRITTEN
    ]
    decision_events = [
        event for event in events if event.event_type is EventType.DECISION_LOG_WRITTEN
    ]
    config = _server_config()
    receipt = {
        "schema_version": 2,
        "capture_type": "LIVE_DATAHUB_END_TO_END_CLOSURE",
        "capture_location": "LOCAL_DATAHUB_GMS",
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "incident_id": INCIDENT_ID,
        "server_type": config["datahub"]["serverType"],
        "server_version": config["versions"]["acryldata/datahub"]["version"],
        "cli_version": config["managedIngestion"]["defaultCliVersion"],
        "source_commit": source_commit,
        "source_worktree_dirty": source_dirty,
        "public_event_stream_sha256": public_events_sha256,
        "evaluation_report_sha256": evaluation_report_sha256,
        "public_projection": {
            "canonical_single_run": True,
            "redactions": redactions,
            "decision_fields_redacted": False,
            "receipt_ids_preserved": True,
        },
        "entity_count": len(native_entities),
        "entity_counts": counts,
        "entities": native_entities,
        "native_model_context": [
            context.model_dump(mode="json") for context in bundle.native_ml_context
        ],
        "repair_lifecycle": {
            "bundle_id": bundle.bundle_id,
            "status": bundle.status.value,
            "change_provider": change.get("provider"),
            "commit_sha": change.get("commit_sha"),
            "remote_pull_request_claimed": bool(change.get("remote_url")),
            "verification_receipt_id": verification.get("receipt_id"),
            "verification_status": verification.get("status"),
            "approval_receipt_id": approval.get("receipt_id"),
            "identity_assurance": approval.get("identity_assurance"),
            "approval_production_authorized": approval.get("production_authorized"),
            "application_receipt_id": application.get("receipt_id"),
            "application_environment": application.get("target_environment"),
            "application_production_authorized": application.get("production_authorized"),
            "recovery_verification_receipts": [
                {
                    "receipt_id": receipt["receipt_id"],
                    "commit_sha": receipt["commit_sha"],
                    "status": receipt["status"],
                    "checks": [
                        {
                            "check_id": check["check_id"],
                            "status": check["status"],
                            "result_sha256": check["result_sha256"],
                        }
                        for check in receipt["checks"]
                    ],
                }
                for receipt in recovery_receipts
            ],
            "recovery_results": recovery_results,
        },
        "incident_lifecycle": {
            "opened": incident_events[0].payload,
            "resolved": incident_events[-1].payload,
            "readback_state": native_incident.status.state,
            "readback_stage": native_incident.status.stage,
            "aspect_sha256": _aspect_digest(native_incident),
        },
        "decision_log_lifecycle": {
            "initial": decision_events[0].payload,
            "final": decision_events[-1].payload,
            "readback_state": decision_log.status.state,
            "related_asset_count": len(decision_log.relatedAssets or []),
            "aspect_sha256": _aspect_digest(decision_log),
            "content_sha256": hashlib.sha256(document_text.encode("utf-8")).hexdigest(),
            "required_receipts_present": required_tokens,
            "custom_properties": {
                key: value
                for key, value in (decision_log.customProperties or {}).items()
                if key.startswith("sciguard:")
            },
        },
        "all_verified": (
            len(native_entities) == 19
            and all(entity["verified"] for entity in native_entities)
            and bundle.status is RepairStatus.APPLIED
            and native_incident.status.state == "RESOLVED"
            and decision_log.status.state == "PUBLISHED"
            and recovery_results[-1]["resume_allowed"] is True
            and recovery_results[-1]["clean_run_count"] == 2
            and not missing_tokens
        ),
    }
    if not receipt["all_verified"]:
        raise RuntimeError("canonical DataHub receipt did not close every proof obligation")
    return receipt


def capture(*, require_clean: bool = False) -> dict:
    source_commit = current_source_commit(ROOT)
    source_dirty = current_worktree_dirty(ROOT)
    evaluation_report = (
        ROOT / "web" / "public" / "evidence" / "evaluation_report.json"
    ).read_bytes()
    evaluation_report_sha256 = _sha256(evaluation_report)
    if require_clean and source_dirty:
        raise RuntimeError("official canonical capture requires a clean source worktree")
    with tempfile.TemporaryDirectory(prefix="sciguard-champion-capture-") as temporary:
        workspace = Path(temporary)
        store, _runtime, bundle, recovery_receipts, recovery_results = _run_canonical_chain(
            source_commit=source_commit,
            source_dirty=source_dirty,
            workspace=workspace,
        )
        events = store.get_events(INCIDENT_ID)
        public_events, redactions = _public_event_bytes(
            events,
            repository=workspace / "repair-repository",
        )
        public_events_sha256 = _sha256(public_events)
        datahub_receipt = _datahub_receipt(
            bundle=bundle,
            events=events,
            public_events_sha256=public_events_sha256,
            evaluation_report_sha256=evaluation_report_sha256,
            redactions=redactions,
            recovery_receipts=recovery_receipts,
            recovery_results=recovery_results,
            source_commit=source_commit,
            source_dirty=source_dirty,
        )
        raw_datahub_receipt = _json_bytes(datahub_receipt)
        datahub_receipt_sha256 = _sha256(raw_datahub_receipt)

        public_bundle = copy.deepcopy(bundle.model_dump(mode="json"))
        public_bundle["external_action_receipt"]["repository"] = PUBLIC_REPOSITORY_LABEL
        public_bundle["verification_receipt"]["repository"] = PUBLIC_REPOSITORY_LABEL
        for check in public_bundle["verification_receipt"]["checks"]:
            check["executed_command"][0] = "python"
        public_bundle["linked_capture"] = {
            "capture_type": "RECORDED_DATAHUB_END_TO_END",
            "canonical_single_run": True,
            "source_incident_id": INCIDENT_ID,
            "public_event_stream_sha256": public_events_sha256,
            "datahub_native_context_source": "LIVE_DATAHUB_END_TO_END_CLOSURE",
            "datahub_native_receipt_sha256": datahub_receipt_sha256,
            "evaluation_report_sha256": evaluation_report_sha256,
            "datahub_server_version": datahub_receipt["server_version"],
            "change_provider": "LOCAL_GIT",
            "remote_pull_request_claimed": False,
            "identity_boundary": "DEMO_SIGNED_NOT_SSO",
            "production_authorized": False,
            "application_environment": "SCIGUARD_SYNTHETIC_STAGING",
            "public_safe_redactions": redactions,
        }
        raw_bundle = _json_bytes(public_bundle)

        live_manifest = store.get_manifest(INCIDENT_ID)
        replay_manifest = live_manifest.model_copy(
            update={
                "mode": RunMode.RECORDED_REPLAY,
                "status": RunStatus.COMPLETED,
                "incident_state": "RESOLVED",
                "source_run_id": INCIDENT_ID,
                "event_count": len(events),
                "events_sha256": public_events_sha256,
            }
        )
        raw_replay_manifest = (replay_manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
        repair_manifest = {
            "schema_version": 2,
            "capture_type": "RECORDED_DATAHUB_END_TO_END",
            "canonical_single_run": True,
            "source_incident_id": INCIDENT_ID,
            "source_events_sha256": public_events_sha256,
            "datahub_native_receipt_sha256": datahub_receipt_sha256,
            "evaluation_report_sha256": evaluation_report_sha256,
            "repair_bundle_sha256": _sha256(raw_bundle),
            "bundle_id": public_bundle["bundle_id"],
            "commit_sha": public_bundle["external_action_receipt"]["commit_sha"],
            "verification_receipt_id": public_bundle["verification_receipt"]["receipt_id"],
            "approval_receipt_id": public_bundle["approval_receipt"]["receipt_id"],
            "application_receipt_id": public_bundle["application_receipt"]["receipt_id"],
            "recovery_verification_receipt_ids": [
                receipt["receipt_id"] for receipt in recovery_receipts
            ],
            "final_incident_state": "RESOLVED",
            "clean_run_count": 2,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "source_commit": source_commit,
            "source_worktree_dirty": source_dirty,
            "boundaries": public_bundle["linked_capture"],
        }
        raw_repair_manifest = _json_bytes(repair_manifest)

        for replay_root in REPLAY_ROOTS:
            destination = replay_root / INCIDENT_ID
            _atomic_bytes(destination / "events.jsonl", public_events)
            _atomic_bytes(destination / "manifest.json", raw_replay_manifest)
            _atomic_bytes(destination / "repair-bundle.json", raw_bundle)
            _atomic_bytes(
                destination / "repair-manifest.json",
                raw_repair_manifest,
            )
        for receipt_path in DATAHUB_RECEIPTS:
            _atomic_bytes(receipt_path, raw_datahub_receipt)

    return {
        "incident_id": INCIDENT_ID,
        "event_count": len(events),
        "events_sha256": public_events_sha256,
        "bundle_id": public_bundle["bundle_id"],
        "commit_sha": repair_manifest["commit_sha"],
        "application_receipt_id": repair_manifest["application_receipt_id"],
        "datahub_receipt_sha256": datahub_receipt_sha256,
        "source_commit": source_commit,
        "source_worktree_dirty": source_dirty,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture the canonical one-incident SciGuard champion replay."
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Fail unless the source worktree is clean before capture.",
    )
    args = parser.parse_args()
    result = capture(require_clean=args.require_clean)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
