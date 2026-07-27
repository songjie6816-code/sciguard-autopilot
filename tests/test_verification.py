from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from core.change_provider import LocalGitChangePublisher, attach_change_receipt
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import RepairStatus, create_unit_repair_bundle
from core.verification import (
    CheckExecutionStatus,
    LocalVerificationEngine,
    VerificationError,
    attach_verification_receipt,
)


ROOT = Path(__file__).parents[1]


def _git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repair-repository"
    shutil.copytree(ROOT / "examples" / "repair_sandbox", repository)
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "SciGuard Test")
    _git(repository, "config", "user.email", "sciguard@example.invalid")
    _git(repository, "add", "--all")
    _git(repository, "commit", "-q", "-m", "baseline")
    return repository


def _bundle():
    return create_unit_repair_bundle(
        incident_id="inc-verification",
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


def test_local_verifier_executes_all_declared_checks_and_binds_commit(tmp_path) -> None:
    repository = _repository(tmp_path)
    proposal = _bundle()
    change_receipt = LocalGitChangePublisher(repository).publish(proposal)
    published = attach_change_receipt(proposal, change_receipt)

    receipt = LocalVerificationEngine().verify(published, change_receipt)
    verified = attach_verification_receipt(published, receipt)

    assert receipt.status is CheckExecutionStatus.PASS
    assert receipt.commit_sha == change_receipt.commit_sha
    assert receipt.source_tree_clean is True
    assert [check.status for check in receipt.checks] == [
        CheckExecutionStatus.PASS,
        CheckExecutionStatus.PASS,
        CheckExecutionStatus.PASS,
    ]
    assert all(check.exit_code == 0 for check in receipt.checks)
    assert all(len(check.output_sha256) == 64 for check in receipt.checks)
    assert all(len(check.result_sha256) == 64 for check in receipt.checks)
    assert len({check.result_sha256 for check in receipt.checks}) == 3
    assert verified.status is RepairStatus.VERIFIED
    assert verified.verification_receipt["receipt_id"] == receipt.receipt_id


def test_local_verifier_fails_closed_when_published_tree_is_modified(tmp_path) -> None:
    repository = _repository(tmp_path)
    proposal = _bundle()
    change_receipt = LocalGitChangePublisher(repository).publish(proposal)
    published = attach_change_receipt(proposal, change_receipt)
    (repository / "pipeline" / "normalize.py").write_text(
        "def normalize_tg(value, unit): return value\n",
        encoding="utf-8",
    )

    with pytest.raises(VerificationError, match="dirty"):
        LocalVerificationEngine().verify(published, change_receipt)


def test_attachment_rejects_an_incomplete_pass_receipt(tmp_path) -> None:
    repository = _repository(tmp_path)
    proposal = _bundle()
    change_receipt = LocalGitChangePublisher(repository).publish(proposal)
    published = attach_change_receipt(proposal, change_receipt)
    receipt = LocalVerificationEngine().verify(published, change_receipt)
    incomplete = receipt.model_copy(update={"checks": receipt.checks[:1]})

    with pytest.raises(ValueError, match="exactly the declared check IDs"):
        attach_verification_receipt(published, incomplete)
