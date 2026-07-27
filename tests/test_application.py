from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core.application import (
    ApplicationError,
    LocalStagingApplicator,
    attach_application_receipt,
)
from core.approval import (
    ApprovalAuthority,
    ApprovalDecision,
    attach_approval_receipt,
)
from core.change_provider import LocalGitChangePublisher, attach_change_receipt
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import RepairStatus, create_unit_repair_bundle
from core.verification import LocalVerificationEngine, attach_verification_receipt


ROOT = Path(__file__).parents[1]


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _approved_bundle(tmp_path: Path):
    repository = tmp_path / "repair-repository"
    shutil.copytree(ROOT / "examples" / "repair_sandbox", repository)
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "SciGuard Test")
    _git(repository, "config", "user.email", "sciguard@example.invalid")
    _git(repository, "add", "--all")
    _git(repository, "commit", "-q", "-m", "baseline")
    proposal = create_unit_repair_bundle(
        incident_id="inc-application",
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
            unaffected_urns=["urn:safe"],
            unaffected_names=["safe"],
            tainted_field_urns=["urn:field:tg"],
        ),
        evidence_ids=["e-contract", "e-lineage"],
        approver_urn="urn:li:corpuser:research_lead",
    )
    change = LocalGitChangePublisher(repository).publish(proposal)
    published = attach_change_receipt(proposal, change)
    verification = LocalVerificationEngine().verify(published, change)
    verified = attach_verification_receipt(published, verification)
    authority = ApprovalAuthority(b"a" * 32)
    approval = authority.record(
        verified,
        authenticated_approver_urn=verified.approval.approver_urn,
        decision=ApprovalDecision.APPROVE,
        note="Reviewed exact-commit scientific and preserved-branch evidence.",
    )
    return (
        repository,
        attach_approval_receipt(verified, approval, authority),
    )


def test_local_application_materializes_exact_approved_tree_idempotently(
    tmp_path: Path,
) -> None:
    repository, approved = _approved_bundle(tmp_path)
    applicator = LocalStagingApplicator(repository, tmp_path / "deployments")

    receipt = applicator.apply(approved)
    repeated = applicator.apply(approved)
    applied = attach_application_receipt(approved, receipt)

    assert receipt == repeated
    assert receipt.provider == "LOCAL_STAGING"
    assert receipt.status == "APPLIED"
    assert receipt.commit_sha == approved.approval_receipt["commit_sha"]
    assert receipt.production_authorized is False
    assert applied.status is RepairStatus.APPLIED
    release = tmp_path / "deployments" / receipt.deployment_id.replace(":", "-")
    assert (release / "pipeline" / "normalize.py").is_file()
    assert "UnitContractError" in (
        release / "pipeline" / "normalize.py"
    ).read_text(encoding="utf-8")
    assert (release / "tests" / "test_scientific_decision.py").is_file()


def test_application_rejects_mutated_staging_release(tmp_path: Path) -> None:
    repository, approved = _approved_bundle(tmp_path)
    applicator = LocalStagingApplicator(repository, tmp_path / "deployments")
    receipt = applicator.apply(approved)
    release = tmp_path / "deployments" / receipt.deployment_id.replace(":", "-")
    (release / "pipeline" / "normalize.py").write_text(
        "tampered\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError, match="modified"):
        applicator.apply(approved)
