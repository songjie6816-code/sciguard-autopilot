"""Capture a truthful local repair action artifact linked to the DataHub replay.

This does not rewrite history or claim that the original DataHub run opened a
remote PR. It reuses the original run's immutable evidence IDs, performs a new
local Git commit plus real pytest verification, records a demo-signed owner
decision, scrubs machine-specific paths, and emits a separately labelled
artifact with its own SHA-256 manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from core.approval import (
    ApprovalAuthority,
    ApprovalDecision,
    attach_approval_receipt,
)
from core.change_provider import LocalGitChangePublisher, attach_change_receipt
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import create_unit_repair_bundle
from core.verification import LocalVerificationEngine, attach_verification_receipt

ROOT = Path(__file__).resolve().parents[1]
INCIDENT_ID = "inc-wp6-flagship"
SOURCE_REPLAY = ROOT / "examples" / "replays" / INCIDENT_ID
DESTINATIONS = [
    SOURCE_REPLAY,
    ROOT / "web" / "public" / "replays" / INCIDENT_ID,
]
PUBLIC_REPOSITORY_LABEL = "EPHEMERAL_REPRODUCIBLE_GIT_SANDBOX"


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _source_commit() -> str:
    return _git(ROOT, "rev-parse", "HEAD")


def _worktree_dirty() -> bool:
    return bool(_git(ROOT, "status", "--porcelain", "--untracked-files=normal"))


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    os.replace(temporary, path)


def _source_facts() -> tuple[
    RootCause,
    FieldImpact,
    list[str],
    str,
    dict,
    str,
]:
    scenarios = json.loads(
        (ROOT / "evaluation" / "scenarios.json").read_text(encoding="utf-8")
    )
    root_cause = RootCause.model_validate(scenarios["flagship"]["root_cause"])
    raw_events = (SOURCE_REPLAY / "events.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in raw_events.splitlines() if line]
    impact_event = next(
        event for event in events if event["event_type"] == "IMPACT_MAPPED"
    )
    confirmed = next(
        event
        for event in events
        if event["event_type"] == "HYPOTHESIS_RESOLVED"
        and event["payload"]["status"] == "CONFIRMED"
    )
    evidence_ids = list(
        dict.fromkeys([*impact_event["evidence_ids"], *confirmed["evidence_ids"]])
    )
    live_receipt_path = (
        ROOT / "examples" / "outputs" / "datahub_live_receipt.json"
    )
    raw_live_receipt = live_receipt_path.read_text(encoding="utf-8")
    live_receipt = json.loads(raw_live_receipt)
    if not live_receipt.get("all_verified"):
        raise RuntimeError("native DataHub live receipt is not verified")
    live_receipt_sha256 = hashlib.sha256(
        raw_live_receipt.encode("utf-8")
    ).hexdigest()
    evidence_ids.append(f"datahub-live-receipt:{live_receipt_sha256[:16]}")
    return (
        root_cause,
        FieldImpact.model_validate(impact_event["payload"]),
        evidence_ids,
        hashlib.sha256(raw_events.encode("utf-8")).hexdigest(),
        live_receipt,
        live_receipt_sha256,
    )


def _public_bundle(bundle, live_receipt: dict, live_receipt_sha256: str) -> dict:
    payload = bundle.model_dump(mode="json")
    change = payload["external_action_receipt"]
    verification = payload["verification_receipt"]
    change["repository"] = PUBLIC_REPOSITORY_LABEL
    verification["repository"] = PUBLIC_REPOSITORY_LABEL
    for check in verification["checks"]:
        check["executed_command"][0] = "python"
    payload["linked_capture"] = {
        "capture_type": "RECORDED_LOCAL_REPAIR_ACTION",
        "datahub_context_source": (
            "Immutable evidence IDs from the separately verified DATAHUB_SDK replay"
        ),
        "change_provider": "LOCAL_GIT",
        "remote_pull_request_claimed": False,
        "identity_boundary": "DEMO_SIGNED_NOT_SSO",
        "production_authorized": False,
        "datahub_native_context_source": "LIVE_DATAHUB_NATIVE_READBACK",
        "datahub_native_receipt_sha256": live_receipt_sha256,
        "datahub_server_version": live_receipt["server_version"],
    }
    return payload


def capture() -> tuple[dict, dict]:
    (
        root_cause,
        impact,
        evidence_ids,
        source_events_sha256,
        live_receipt,
        live_receipt_sha256,
    ) = _source_facts()
    with tempfile.TemporaryDirectory(prefix="sciguard-repair-capture-") as directory:
        repository = Path(directory) / "repair-repository"
        shutil.copytree(ROOT / "examples" / "repair_sandbox", repository)
        _git(repository, "init", "-q", "-b", "main")
        _git(repository, "config", "user.name", "SciGuard Replay Capture")
        _git(repository, "config", "user.email", "sciguard@example.invalid")
        _git(repository, "add", "--all")
        _git(repository, "commit", "-q", "-m", "baseline scientific normalizer")

        proposal = create_unit_repair_bundle(
            incident_id=INCIDENT_ID,
            root_cause=root_cause,
            impact=impact,
            evidence_ids=evidence_ids,
            approver_urn="urn:li:corpuser:research_lead",
            native_ml_context=live_receipt["native_model_context"],
            datahub_incident_urn=live_receipt["incident_lifecycle"]["resolved"][
                "incident_urn"
            ],
            datahub_decision_log_urn=live_receipt["decision_log_lifecycle"]["final"][
                "document_urn"
            ],
        )
        change = LocalGitChangePublisher(repository).publish(proposal)
        published = attach_change_receipt(proposal, change)
        verification = LocalVerificationEngine().verify(published, change)
        verified = attach_verification_receipt(published, verification)
        authority = ApprovalAuthority(
            b"sciguard-public-demo-capture-key-not-production",
            key_id="sciguard-public-demo-v1",
        )
        approval = authority.record(
            verified,
            authenticated_approver_urn="urn:li:corpuser:research_lead",
            decision=ApprovalDecision.APPROVE,
            note=(
                "Reviewed commit-bound unit contract, P-204 ranking restoration, "
                "safe-branch preservation, and rollback evidence."
            ),
        )
        reviewed = attach_approval_receipt(verified, approval, authority)

    public_bundle = _public_bundle(reviewed, live_receipt, live_receipt_sha256)
    raw_bundle = json.dumps(
        public_bundle,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": 1,
        "capture_type": "RECORDED_LOCAL_REPAIR_ACTION",
        "source_incident_id": INCIDENT_ID,
        "source_events_sha256": source_events_sha256,
        "datahub_native_receipt_sha256": live_receipt_sha256,
        "repair_bundle_sha256": hashlib.sha256(raw_bundle.encode("utf-8")).hexdigest(),
        "bundle_id": public_bundle["bundle_id"],
        "commit_sha": public_bundle["external_action_receipt"]["commit_sha"],
        "verification_receipt_id": public_bundle["verification_receipt"]["receipt_id"],
        "approval_receipt_id": public_bundle["approval_receipt"]["receipt_id"],
        "generated_at": generated_at,
        "source_commit": _source_commit(),
        "source_worktree_dirty": _worktree_dirty(),
        "boundaries": public_bundle["linked_capture"],
    }
    raw_manifest = json.dumps(
        manifest,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"
    for destination in DESTINATIONS:
        _atomic_text(destination / "repair-bundle.json", raw_bundle)
        _atomic_text(destination / "repair-manifest.json", raw_manifest)
    return public_bundle, manifest


def main() -> None:
    bundle, manifest = capture()
    print(f"bundle:       {bundle['bundle_id']}")
    print(f"local commit: {manifest['commit_sha']}")
    print(f"verification: {manifest['verification_receipt_id']}")
    print(f"approval:     {manifest['approval_receipt_id']}")
    print("remote PR:    not claimed")
    print("identity:     DEMO_SIGNED_NOT_SSO / production authorization false")


if __name__ == "__main__":
    main()
