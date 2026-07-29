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
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from core.change_provider import ChangeReceipt, LocalGitChangePublisher
from core.events import Event, EventType, validate_event_stream
from core.github_provider import (
    GitHubChangePublisher,
    GitHubResponse,
    GitHubTransport,
    PublicReadOnlyGitHubTransport,
    UrllibGitHubTransport,
)
from core.github_verification import GitHubCheckRunVerifier
from core.repair import RepairBundle, RepairStatus
from core.verification import CheckExecutionStatus, VerificationError
from data.synthetic_polymer import native_ml
from datahub_client import metadata_reader
from datahub_client.incident_writer import decision_log_urn, incident_urn
from scripts.capture_datahub_live_receipt import (
    _aspect_digest,
    _server_config,
    _verify_entity,
)

INCIDENT_ID = "inc-sciguard-b042-unit-contract"
GITHUB_REPOSITORY = "songjie6816-code/sciguard-repair-sandbox"
GITHUB_REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
PUBLIC_REPOSITORY_LABEL = GITHUB_REPOSITORY_URL
DEMO_SIGNING_KEY = b"sciguard-b042-canonical-demo-key-not-production"
REPLAY_ROOTS = [
    ROOT / "examples" / "replays",
    ROOT / "web" / "public" / "replays",
]
DATAHUB_RECEIPTS = [
    ROOT / "examples" / "outputs" / "datahub_live_receipt.json",
    ROOT / "web" / "public" / "evidence" / "datahub_live_receipt.json",
]
GITHUB_RECEIPTS = [
    ROOT / "examples" / "outputs" / "github_live_evidence.json",
    ROOT / "web" / "public" / "evidence" / "github_live_evidence.json",
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
    subprocess.run(
        ["git", "clone", "--quiet", "--no-tags", f"{GITHUB_REPOSITORY_URL}.git", str(destination)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(destination, "config", "user.name", "SciGuard Canonical Capture")
    _git(destination, "config", "user.email", "sciguard@example.invalid")


def _github_transport() -> GitHubTransport:
    token = os.environ.get("SCIGUARD_GITHUB_TOKEN", "").strip()
    if token:
        return UrllibGitHubTransport(token=token)
    return PublicReadOnlyGitHubTransport()


def _github_adapters(
    transport: GitHubTransport,
) -> tuple[GitHubChangePublisher, GitHubCheckRunVerifier]:
    return (
        GitHubChangePublisher(
            repository=GITHUB_REPOSITORY,
            transport=transport,
        ),
        GitHubCheckRunVerifier(
            repository=GITHUB_REPOSITORY,
            transport=transport,
        ),
    )


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


def _runtime(
    *,
    repository: Path,
    workspace: Path,
    authority: ApprovalAuthority,
    transport: GitHubTransport,
) -> SciGuardRuntime:
    token_configured = bool(os.environ.get("SCIGUARD_GITHUB_TOKEN", "").strip())
    adapters: dict[str, object] = {}
    if not token_configured:
        publisher, verifier = _github_adapters(transport)
        adapters = {
            "change_publisher": publisher,
            "verification_engine": verifier,
        }
    return SciGuardRuntime(
        repair_repository=repository,
        repair_target_repository=GITHUB_REPOSITORY_URL,
        deployment_root=workspace / "deployments",
        approval_authority=authority,
        **adapters,
    )


def _wait_for_hosted_verification(
    runtime: SciGuardRuntime,
    store: RunStore,
    *,
    timeout_seconds: int,
) -> RepairBundle:
    deadline = time.monotonic() + timeout_seconds
    while True:
        published = runtime._latest_repair_bundle(store, INCIDENT_ID)
        change_receipt = ChangeReceipt.model_validate(
            published.external_action_receipt
        )
        try:
            observed = runtime._verifier_for(change_receipt).verify(
                published,
                change_receipt,
            )
            if observed.status is not CheckExecutionStatus.PASS:
                failed = [
                    check.check_id
                    for check in observed.checks
                    if check.status is not CheckExecutionStatus.PASS
                ]
                raise RuntimeError(f"hosted GitHub checks failed: {failed}")
            return runtime.verify_repair(store, INCIDENT_ID)
        except VerificationError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(5, max(0, deadline - time.monotonic())))


def _sync_repository_to_change(
    repository: Path,
    change_receipt: ChangeReceipt,
) -> None:
    _git(repository, "fetch", "--quiet", "--no-tags", "origin", change_receipt.branch)
    fetched_sha = _git(repository, "rev-parse", "FETCH_HEAD")
    if fetched_sha != change_receipt.commit_sha:
        raise RuntimeError("fetched GitHub branch does not match the publication receipt")
    _git(repository, "checkout", "--quiet", "--detach", change_receipt.commit_sha)
    if _git(repository, "status", "--porcelain"):
        raise RuntimeError("exact GitHub revision is dirty before staging application")


def _run_canonical_chain(
    *,
    source_commit: str,
    source_dirty: bool,
    workspace: Path,
    ci_timeout_seconds: int,
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
        key_id="sciguard-b042-demo-v1",
    )
    transport = _github_transport()
    runtime = _runtime(
        repository=repository,
        workspace=workspace,
        authority=authority,
        transport=transport,
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
        verified = _wait_for_hosted_verification(
            runtime,
            store,
            timeout_seconds=ci_timeout_seconds,
        )
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
        _sync_repository_to_change(
            repository,
            ChangeReceipt.model_validate(approved.external_action_receipt),
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


def _pull_body(bundle: RepairBundle) -> str:
    return "\n".join(
        [
            "## Proof-Carrying Repair",
            "",
            bundle.root_cause_summary,
            "",
            f"SciGuard-Incident: {bundle.incident_id}",
            f"SciGuard-Bundle: {bundle.bundle_id}",
            f"SciGuard-Evidence: {','.join(bundle.evidence_ids)}",
            "",
            "High-risk application remains locked until required checks pass "
            "and the accountable DataHub owner approves this exact commit.",
        ]
    )


def prepare_github_branch() -> dict[str, object]:
    """Create and push the deterministic repair branch before the final capture."""

    source_commit = current_source_commit(ROOT)
    source_dirty = current_worktree_dirty(ROOT)
    with tempfile.TemporaryDirectory(prefix="sciguard-b042-prepare-") as temporary:
        workspace = Path(temporary)
        repository = workspace / "repair-repository"
        _bootstrap_repository(repository)
        store = RunStore(
            workspace / "runs",
            source_commit=source_commit,
            source_worktree_dirty=source_dirty,
        )
        runtime = SciGuardRuntime(
            repair_repository=repository,
            repair_target_repository=GITHUB_REPOSITORY_URL,
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
            proposal = runtime._latest_repair_bundle(store, INCIDENT_ID)
            receipt = LocalGitChangePublisher(repository).publish(proposal)
            _git(
                repository,
                "push",
                "--set-upstream",
                "origin",
                receipt.branch,
            )
        except Exception as exc:
            store.fail_run(INCIDENT_ID, f"{type(exc).__name__}: {exc}")
            raise

    compare_url = (
        f"{GITHUB_REPOSITORY_URL}/compare/main...{receipt.branch}?expand=1"
    )
    return {
        "incident_id": INCIDENT_ID,
        "bundle_id": proposal.bundle_id,
        "branch": receipt.branch,
        "commit_sha": receipt.commit_sha,
        "pull_request_title": f"[SciGuard] {proposal.title}",
        "pull_request_body": _pull_body(proposal),
        "compare_url": compare_url,
    }


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


def _github_get(
    transport: GitHubTransport,
    path: str,
    *,
    expected_type: type,
) -> Any:
    response: GitHubResponse = transport.request("GET", path)
    if response.status != 200 or not isinstance(response.data, expected_type):
        raise RuntimeError(f"GitHub evidence read failed for {path}: HTTP {response.status}")
    return response.data


def _github_live_evidence(
    *,
    bundle: RepairBundle,
    transport: GitHubTransport,
) -> dict[str, object]:
    change = ChangeReceipt.model_validate(bundle.external_action_receipt)
    verification = bundle.verification_receipt or {}
    approval = bundle.approval_receipt or {}
    if (
        change.provider != "GITHUB"
        or change.remote_url is None
        or change.pull_request_number is None
        or verification.get("provider") != "GITHUB_CHECK_RUNS"
        or verification.get("commit_sha") != change.commit_sha
        or approval.get("commit_sha") != change.commit_sha
    ):
        raise RuntimeError("canonical bundle lacks a fully bound GitHub repair lifecycle")

    prefix = f"/repos/{GITHUB_REPOSITORY}"
    pull = _github_get(
        transport,
        f"{prefix}/pulls/{change.pull_request_number}",
        expected_type=dict,
    )
    commit = _github_get(
        transport,
        f"{prefix}/commits/{change.commit_sha}",
        expected_type=dict,
    )
    reviews = _github_get(
        transport,
        f"{prefix}/pulls/{change.pull_request_number}/reviews?per_page=100",
        expected_type=list,
    )
    head = pull.get("head") if isinstance(pull.get("head"), dict) else {}
    base = pull.get("base") if isinstance(pull.get("base"), dict) else {}
    author = pull.get("user") if isinstance(pull.get("user"), dict) else {}
    matching_reviews = [
        review
        for review in reviews
        if isinstance(review, dict)
        and review.get("commit_id") == change.commit_sha
        and isinstance(review.get("user"), dict)
        and review.get("state") in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"}
    ]
    if not matching_reviews:
        raise RuntimeError(
            "the exact GitHub commit has no public account-bound review evidence"
        )
    review = max(
        matching_reviews,
        key=lambda item: str(item.get("submitted_at") or ""),
    )
    reviewer = review["user"]
    commit_verification = (
        commit.get("commit", {}).get("verification", {})
        if isinstance(commit.get("commit"), dict)
        else {}
    )
    reviewer_login = str(reviewer.get("login") or "")
    author_login = str(author.get("login") or "")
    independent_reviewer = bool(
        reviewer_login and author_login and reviewer_login != author_login
    )
    evidence = {
        "schema_version": 2,
        "evidence_type": "GITHUB_REMOTE_REPAIR_AND_IDENTITY_BOUNDARY",
        "incident_id": bundle.incident_id,
        "bundle_id": bundle.bundle_id,
        "repository": GITHUB_REPOSITORY_URL,
        "boundary_statement": (
            "The canonical incident contains a real GitHub PR, a public account-bound "
            "review, and exact-SHA hosted CI. Enterprise SSO/OIDC is not asserted; "
            "production_authorized remains false."
        ),
        "pull_request": {
            "number": pull.get("number"),
            "state": pull.get("state"),
            "url": pull.get("html_url"),
            "author_login": author_login,
            "author_id": author.get("id"),
            "head_ref": head.get("ref"),
            "head_sha": head.get("sha"),
            "base_ref": base.get("ref"),
            "base_sha": base.get("sha"),
        },
        "commit": {
            "sha": commit.get("sha"),
            "url": commit.get("html_url"),
            "verified_signature": bool(commit_verification.get("verified")),
        },
        "authenticated_actor": {
            "login": reviewer_login,
            "id": reviewer.get("id"),
        },
        "authenticated_review": {
            "review_id": review.get("id"),
            "reviewer_login": reviewer_login,
            "reviewer_id": reviewer.get("id"),
            "commit_id": review.get("commit_id"),
            "state": review.get("state"),
            "submitted_at": review.get("submitted_at"),
            "url": review.get("html_url"),
            "identity_assurance": "GITHUB_ACCOUNT_REVIEW",
            "enterprise_sso_verified": False,
            "independent_reviewer": independent_reviewer,
            "production_authorized": False,
        },
        "change_receipt": change.model_dump(mode="json"),
        "verification_receipt": verification,
        "approval_binding": {
            "receipt_id": approval.get("receipt_id"),
            "commit_sha": approval.get("commit_sha"),
            "identity_assurance": approval.get("identity_assurance"),
            "production_authorized": approval.get("production_authorized"),
        },
        "canonical_bindings": {
            "incident_id": bundle.incident_id,
            "bundle_id": bundle.bundle_id,
            "publication_sha": change.commit_sha,
            "verification_sha": verification.get("commit_sha"),
            "approval_sha": approval.get("commit_sha"),
            "application_sha": (bundle.application_receipt or {}).get("commit_sha"),
        },
    }
    bindings = evidence["canonical_bindings"]
    bound_shas = [
        bindings["publication_sha"],
        bindings["verification_sha"],
        bindings["approval_sha"],
        bindings["application_sha"],
    ]
    if (
        pull.get("state") != "open"
        or pull.get("html_url") != change.remote_url
        or head.get("sha") != change.commit_sha
        or base.get("sha") != change.base_commit_sha
        or commit.get("sha") != change.commit_sha
        or bindings["incident_id"] != bundle.incident_id
        or bindings["bundle_id"] != bundle.bundle_id
        or len(set(bound_shas)) != 1
        or bound_shas[0] != change.commit_sha
    ):
        raise RuntimeError("GitHub evidence does not match the canonical repair receipts")
    return evidence


def capture(
    *,
    require_clean: bool = False,
    ci_timeout_seconds: int = 60,
) -> dict:
    source_commit = current_source_commit(ROOT)
    source_dirty = current_worktree_dirty(ROOT)
    evaluation_report = (
        ROOT / "web" / "public" / "evidence" / "evaluation_report.json"
    ).read_bytes()
    evaluation_report_sha256 = _sha256(evaluation_report)
    if require_clean and source_dirty:
        raise RuntimeError("official canonical capture requires a clean source worktree")
    with tempfile.TemporaryDirectory(prefix="sciguard-b042-capture-") as temporary:
        workspace = Path(temporary)
        store, _runtime, bundle, recovery_receipts, recovery_results = _run_canonical_chain(
            source_commit=source_commit,
            source_dirty=source_dirty,
            workspace=workspace,
            ci_timeout_seconds=ci_timeout_seconds,
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
        github_live_evidence = _github_live_evidence(
            bundle=bundle,
            transport=_github_transport(),
        )
        raw_github_live_evidence = _json_bytes(github_live_evidence)
        github_live_evidence_sha256 = _sha256(raw_github_live_evidence)

        public_bundle = copy.deepcopy(bundle.model_dump(mode="json"))
        for check in public_bundle["verification_receipt"]["checks"]:
            if check["executed_command"]:
                check["executed_command"][0] = "python"
        public_bundle["linked_capture"] = {
            "capture_type": "RECORDED_DATAHUB_END_TO_END",
            "canonical_single_run": True,
            "source_incident_id": INCIDENT_ID,
            "public_event_stream_sha256": public_events_sha256,
            "datahub_native_context_source": "LIVE_DATAHUB_END_TO_END_CLOSURE",
            "datahub_native_receipt_sha256": datahub_receipt_sha256,
            "github_live_evidence_sha256": github_live_evidence_sha256,
            "evaluation_report_sha256": evaluation_report_sha256,
            "datahub_server_version": datahub_receipt["server_version"],
            "change_provider": "GITHUB",
            "remote_pull_request_claimed": True,
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
            "github_live_evidence_sha256": github_live_evidence_sha256,
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
        for receipt_path in GITHUB_RECEIPTS:
            _atomic_bytes(receipt_path, raw_github_live_evidence)

    return {
        "incident_id": INCIDENT_ID,
        "event_count": len(events),
        "events_sha256": public_events_sha256,
        "bundle_id": public_bundle["bundle_id"],
        "commit_sha": repair_manifest["commit_sha"],
        "application_receipt_id": repair_manifest["application_receipt_id"],
        "datahub_receipt_sha256": datahub_receipt_sha256,
        "github_live_evidence_sha256": github_live_evidence_sha256,
        "pull_request_url": bundle.external_action_receipt["remote_url"],
        "source_commit": source_commit,
        "source_worktree_dirty": source_dirty,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare or capture the canonical B042 SciGuard repair closure."
    )
    parser.add_argument(
        "--prepare-github",
        action="store_true",
        help="Create and push the deterministic repair branch, then print PR details.",
    )
    parser.add_argument(
        "--require-clean",
        action="store_true",
        help="Fail unless the source worktree is clean before capture.",
    )
    parser.add_argument(
        "--ci-timeout-seconds",
        type=int,
        default=60,
        help="Maximum seconds to wait for the three exact-SHA GitHub checks.",
    )
    args = parser.parse_args()
    if args.ci_timeout_seconds < 1:
        parser.error("--ci-timeout-seconds must be positive")
    result = (
        prepare_github_branch()
        if args.prepare_github
        else capture(
            require_clean=args.require_clean,
            ci_timeout_seconds=args.ci_timeout_seconds,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
