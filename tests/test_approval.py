from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core.approval import (
    ApprovalAuthority,
    ApprovalDecision,
    ApprovalError,
    ApprovalReceipt,
    attach_approval_receipt,
)
from core.change_provider import LocalGitChangePublisher, attach_change_receipt
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import ApprovalStatus, RepairStatus, create_unit_repair_bundle
from core.verification import LocalVerificationEngine, attach_verification_receipt

ROOT = Path(__file__).parents[1]
SIGNING_KEY = b"sciguard-test-approval-key-32-bytes-minimum"


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _verified_bundle(tmp_path: Path):
    repository = tmp_path / "repair-repository"
    shutil.copytree(ROOT / "examples" / "repair_sandbox", repository)
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "SciGuard Test")
    _git(repository, "config", "user.email", "sciguard@example.invalid")
    _git(repository, "add", "--all")
    _git(repository, "commit", "-q", "-m", "baseline")
    proposal = create_unit_repair_bundle(
        incident_id="inc-approval",
        root_cause=RootCause(
            batch_id="B042",
            instrument_firmware_before="v4.1",
            instrument_firmware_after="v4.2",
            expected_unit="degC",
            observed_units=["degC", "K"],
            normalization_version="tg-normalizer-v1",
            affected_rows=187,
            explanation="Verified mixed-unit root cause.",
        ),
        impact=FieldImpact(
            source_urn="urn:raw",
            source_fields=["tg_value"],
            affected_urns=["urn:raw", "urn:rank"],
            affected_names=["raw", "rank"],
            unaffected_urns=["urn:formulation"],
            unaffected_names=["formulation"],
            tainted_field_urns=["urn:field:tg"],
        ),
        evidence_ids=["e-contract", "e-lineage"],
        approver_urn="urn:li:corpuser:research_lead",
    )
    change = LocalGitChangePublisher(repository).publish(proposal)
    published = attach_change_receipt(proposal, change)
    verification = LocalVerificationEngine().verify(published, change)
    return attach_verification_receipt(published, verification)


def test_signed_owner_approval_is_bound_to_verified_commit(tmp_path) -> None:
    verified = _verified_bundle(tmp_path)
    authority = ApprovalAuthority(SIGNING_KEY)
    receipt = authority.record(
        verified,
        authenticated_approver_urn="urn:li:corpuser:research_lead",
        decision=ApprovalDecision.APPROVE,
        note="Reviewed unit contract, ranking regression, and safe branch evidence.",
    )
    approved = attach_approval_receipt(verified, receipt, authority)

    assert authority.verify(receipt) is True
    assert receipt.commit_sha == verified.verification_receipt["commit_sha"]
    assert receipt.production_authorized is False
    assert receipt.identity_assurance == "DEMO_SIGNED_NOT_SSO"
    assert approved.status is RepairStatus.APPROVED
    assert approved.approval.status is ApprovalStatus.APPROVED
    assert approved.approval_receipt["receipt_id"] == receipt.receipt_id


def test_wrong_owner_and_tampered_receipt_fail_closed(tmp_path) -> None:
    verified = _verified_bundle(tmp_path)
    authority = ApprovalAuthority(SIGNING_KEY)
    with pytest.raises(ApprovalError, match="accountable approver"):
        authority.record(
            verified,
            authenticated_approver_urn="urn:li:corpuser:untrusted",
            decision=ApprovalDecision.APPROVE,
            note="Attempted approval by the wrong accountable owner.",
        )

    receipt = authority.record(
        verified,
        authenticated_approver_urn="urn:li:corpuser:research_lead",
        decision=ApprovalDecision.REJECT,
        note="Reject until an additional calibrated instrument run is available.",
    )
    tampered = ApprovalReceipt.model_validate(
        {**receipt.model_dump(mode="python"), "decision": ApprovalDecision.APPROVE}
    )
    assert authority.verify(tampered) is False
    with pytest.raises(ApprovalError, match="signature"):
        attach_approval_receipt(verified, tampered, authority)
