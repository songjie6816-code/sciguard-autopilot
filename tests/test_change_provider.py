import shutil
import subprocess
from pathlib import Path

import pytest

from core.change_provider import (
    ChangePublicationError,
    LocalGitChangePublisher,
    attach_change_receipt,
)
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import RepairStatus, create_unit_repair_bundle


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
        incident_id="inc-change-provider",
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


def test_local_git_publisher_creates_real_commit_and_is_idempotent(tmp_path) -> None:
    repository = _repository(tmp_path)
    publisher = LocalGitChangePublisher(repository)

    receipt = publisher.publish(_bundle())
    repeated = publisher.publish(_bundle())

    assert receipt == repeated
    assert receipt.provider == "LOCAL_GIT"
    assert receipt.status == "COMMITTED"
    assert receipt.remote_url is None
    assert _git(repository, "rev-parse", "HEAD") == receipt.commit_sha
    assert {
        "pipeline/normalize.py",
        "tests/test_unit_contract.py",
        "tests/test_scientific_decision.py",
        "tests/test_safe_branch.py",
        "SCIGUARD_ROLLBACK.md",
    }.issubset(receipt.changed_files)
    normalized = (repository / "pipeline" / "normalize.py").read_text()
    assert "UnitContractError" in normalized
    assert "- 273.15" in normalized
    message = _git(repository, "show", "-s", "--format=%B", receipt.commit_sha)
    assert f"SciGuard-Bundle: {_bundle().bundle_id}" in message


def test_change_receipt_never_claims_a_remote_pr(tmp_path) -> None:
    receipt = LocalGitChangePublisher(_repository(tmp_path)).publish(_bundle())
    published = attach_change_receipt(_bundle(), receipt)

    assert published.status is RepairStatus.PUBLISHED
    assert published.external_action_receipt["provider"] == "LOCAL_GIT"
    assert published.external_action_receipt["remote_url"] is None
    assert receipt.pull_request_number is None


def test_dirty_repository_is_rejected_without_mutation(tmp_path) -> None:
    repository = _repository(tmp_path)
    (repository / "unrelated.txt").write_text("user work", encoding="utf-8")
    before_branch = _git(repository, "branch", "--show-current")

    try:
        LocalGitChangePublisher(repository).publish(_bundle())
    except ChangePublicationError as exc:
        assert "must be clean" in str(exc)
    else:
        raise AssertionError("dirty user work must not be overwritten")

    assert _git(repository, "branch", "--show-current") == before_branch
    assert (repository / "unrelated.txt").read_text() == "user work"


def test_existing_branch_rejects_a_marker_only_followup_commit(tmp_path) -> None:
    repository = _repository(tmp_path)
    publisher = LocalGitChangePublisher(repository)
    bundle = _bundle()
    publisher.publish(bundle)
    _git(
        repository,
        "commit",
        "--allow-empty",
        "-m",
        f"fake retry\n\nSciGuard-Bundle: {bundle.bundle_id}",
    )

    with pytest.raises(ChangePublicationError, match="materialize|unexpected file set"):
        publisher.publish(bundle)


def test_idempotent_receipt_preserves_the_original_base_parent(tmp_path) -> None:
    repository = _repository(tmp_path)
    publisher = LocalGitChangePublisher(repository)
    bundle = _bundle()
    receipt = publisher.publish(bundle)
    _git(repository, "checkout", "--quiet", "main")
    (repository / "later.txt").write_text("later base work\n", encoding="utf-8")
    _git(repository, "add", "later.txt")
    _git(repository, "commit", "--quiet", "-m", "advance base")

    repeated = publisher.publish(bundle)

    assert repeated.base_commit_sha == receipt.base_commit_sha
    assert repeated.commit_sha == receipt.commit_sha


def test_artifact_destination_cannot_escape_through_repository_symlink(tmp_path) -> None:
    repository = _repository(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repository / "tests").symlink_to(outside, target_is_directory=True)
    _git(repository, "add", "tests")
    _git(repository, "commit", "--quiet", "-m", "malicious baseline symlink")

    with pytest.raises(ChangePublicationError, match="symlink|outside"):
        LocalGitChangePublisher(repository).publish(_bundle())
    assert not list(outside.iterdir())
