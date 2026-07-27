"""Local, tamper-evident verification for proof-carrying repairs.

The verifier executes only the narrow pytest commands declared by SciGuard's
deterministic repair planner. It never invokes a shell, never accepts arbitrary
flags or paths, and binds every result to the published Git commit and bundle.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from core.change_provider import ChangeReceipt
from core.events import stable_evidence_id
from core.repair import RepairBundle, RepairStatus


class VerificationError(RuntimeError):
    pass


class CheckExecutionStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class VerificationCheckReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str
    name: str
    status: CheckExecutionStatus
    declared_command: str
    executed_command: list[str]
    exit_code: int
    duration_ms: int
    output_sha256: str
    result_sha256: str
    output_excerpt: str
    evidence_ids: list[str]
    details_url: str | None = None
    external_run_id: int | None = None
    external_app_id: int | None = None
    external_app_slug: str | None = None
    check_suite_id: int | None = None
    workflow_run_id: int | None = None
    workflow_run_attempt: int | None = None
    workflow_id: int | None = None
    workflow_path: str | None = None
    workflow_conclusion: str | None = None


class VerificationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    provider: str
    status: CheckExecutionStatus
    bundle_id: str
    repository: str
    branch: str
    commit_sha: str
    source_tree_clean: bool | None
    checks: list[VerificationCheckReceipt]
    created_at: datetime

    @model_validator(mode="after")
    def _check_set_is_complete_and_consistent(self) -> VerificationReceipt:
        if not self.checks:
            raise ValueError("verification receipt must contain at least one check")
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("verification receipt check IDs must be unique")
        expected = (
            CheckExecutionStatus.PASS
            if all(check.status is CheckExecutionStatus.PASS for check in self.checks)
            else CheckExecutionStatus.FAIL
        )
        if self.status is not expected:
            raise ValueError("verification receipt status does not match its checks")
        if self.provider == "GITHUB_CHECK_RUNS":
            external_run_ids = [check.external_run_id for check in self.checks]
            if len(external_run_ids) != len(set(external_run_ids)):
                raise ValueError("GitHub verification Check Run IDs must be unique")
            for check in self.checks:
                if (
                    not isinstance(check.external_run_id, int)
                    or check.external_run_id <= 0
                    or not isinstance(check.external_app_id, int)
                    or check.external_app_id <= 0
                    or not check.external_app_slug
                    or not isinstance(check.check_suite_id, int)
                    or check.check_suite_id <= 0
                    or not isinstance(check.workflow_run_id, int)
                    or check.workflow_run_id <= 0
                    or not isinstance(check.workflow_run_attempt, int)
                    or check.workflow_run_attempt <= 0
                    or not isinstance(check.workflow_id, int)
                    or check.workflow_id <= 0
                    or not check.workflow_path
                    or check.workflow_conclusion
                    not in {
                        "success",
                        "failure",
                        "neutral",
                        "cancelled",
                        "skipped",
                        "timed_out",
                        "action_required",
                        "stale",
                        "startup_failure",
                    }
                    or not check.details_url
                ):
                    raise ValueError(
                        "GitHub verification checks require complete provider provenance"
                    )
        return self


class VerificationEngine(Protocol):
    def verify(
        self,
        bundle: RepairBundle,
        change_receipt: ChangeReceipt,
    ) -> VerificationReceipt: ...


def _git(repository: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise VerificationError(f"git {' '.join(args)} failed: {detail}") from exc
    return result.stdout.strip()


def _trusted_pytest_command(command: str, repository: Path) -> list[str]:
    tokens = shlex.split(command)
    if len(tokens) != 3 or tokens[:2] != ["pytest", "-q"]:
        raise VerificationError(f"unsupported verification command: {command!r}")
    relative = PurePosixPath(tokens[2])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or len(relative.parts) < 2
        or relative.parts[0] != "tests"
        or relative.suffix != ".py"
    ):
        raise VerificationError(f"unsafe verification target: {tokens[2]!r}")
    target = repository.joinpath(*relative.parts)
    if not target.is_file():
        raise VerificationError(f"verification target does not exist: {tokens[2]!r}")
    return [sys.executable, "-m", "pytest", "-q", relative.as_posix()]


class LocalVerificationEngine:
    """Verify a published local Git change without trusting mutable UI state."""

    def verify(
        self,
        bundle: RepairBundle,
        change_receipt: ChangeReceipt,
    ) -> VerificationReceipt:
        if bundle.status not in {
            RepairStatus.PUBLISHED,
            RepairStatus.VERIFIED,
            RepairStatus.APPROVED,
            RepairStatus.APPLIED,
        }:
            raise VerificationError(
                f"verification requires a published repair revision, got {bundle.status.value}"
            )
        if change_receipt.provider != "LOCAL_GIT" or change_receipt.status != "COMMITTED":
            raise VerificationError("local verification requires a committed LOCAL_GIT receipt")
        if change_receipt.bundle_id != bundle.bundle_id:
            raise VerificationError("change receipt does not belong to this repair bundle")

        repository = Path(change_receipt.repository).resolve()
        if not repository.is_dir():
            raise VerificationError(f"repository does not exist: {repository}")
        if _git(repository, "rev-parse", "HEAD") != change_receipt.commit_sha:
            raise VerificationError("repository HEAD no longer matches the published commit")
        if _git(repository, "branch", "--show-current") != change_receipt.branch:
            raise VerificationError("repository branch no longer matches the publication receipt")
        source_tree_clean = not bool(_git(repository, "status", "--porcelain"))
        if not source_tree_clean:
            raise VerificationError("repository is dirty; verification would not be reproducible")
        commit_message = _git(repository, "show", "-s", "--format=%B", "HEAD")
        if f"SciGuard-Bundle: {bundle.bundle_id}" not in commit_message:
            raise VerificationError("published commit is not bound to the repair bundle")

        receipts: list[VerificationCheckReceipt] = []
        with tempfile.TemporaryDirectory(prefix="sciguard-verify-") as temporary:
            checkout = Path(temporary) / "checkout"
            _git(
                repository,
                "worktree",
                "add",
                "--quiet",
                "--detach",
                str(checkout),
                change_receipt.commit_sha,
            )
            try:
                for check in bundle.verification_checks:
                    command = _trusted_pytest_command(check.command, checkout)
                    started = time.monotonic()
                    result = subprocess.run(
                        command,
                        cwd=checkout,
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=120,
                    )
                    duration_ms = round((time.monotonic() - started) * 1000)
                    output = f"{result.stdout}\n{result.stderr}".strip()
                    status = (
                        CheckExecutionStatus.PASS
                        if result.returncode == 0
                        else CheckExecutionStatus.FAIL
                    )
                    output_sha256 = hashlib.sha256(output.encode("utf-8")).hexdigest()
                    result_sha256 = hashlib.sha256(
                        json.dumps(
                            {
                                "check_id": check.check_id,
                                "declared_command": check.command,
                                "executed_command": command,
                                "exit_code": result.returncode,
                                "output_sha256": output_sha256,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    receipts.append(
                        VerificationCheckReceipt(
                            check_id=check.check_id,
                            name=check.name,
                            status=status,
                            declared_command=check.command,
                            executed_command=command,
                            exit_code=result.returncode,
                            duration_ms=duration_ms,
                            output_sha256=output_sha256,
                            result_sha256=result_sha256,
                            output_excerpt=output[-800:],
                            evidence_ids=check.evidence_ids,
                        )
                    )
            finally:
                _git(
                    repository,
                    "worktree",
                    "remove",
                    "--force",
                    str(checkout),
                )

        overall = (
            CheckExecutionStatus.PASS
            if all(item.status is CheckExecutionStatus.PASS for item in receipts)
            else CheckExecutionStatus.FAIL
        )
        identity = {
            "bundle_id": bundle.bundle_id,
            "commit_sha": change_receipt.commit_sha,
            "checks": [
                {
                    "check_id": item.check_id,
                    "status": item.status.value,
                    "exit_code": item.exit_code,
                    "output_sha256": item.output_sha256,
                    "result_sha256": item.result_sha256,
                }
                for item in receipts
            ],
        }
        return VerificationReceipt(
            receipt_id=stable_evidence_id("verification-receipt", identity),
            provider="LOCAL_PROCESS",
            status=overall,
            bundle_id=bundle.bundle_id,
            repository=str(repository),
            branch=change_receipt.branch,
            commit_sha=change_receipt.commit_sha,
            source_tree_clean=source_tree_clean,
            checks=receipts,
            created_at=datetime.now(timezone.utc),
        )


def attach_verification_receipt(
    bundle: RepairBundle,
    receipt: VerificationReceipt,
) -> RepairBundle:
    """Create the verified immutable state only when every real check passed."""

    if bundle.status is not RepairStatus.PUBLISHED:
        raise ValueError("only a published bundle can receive verification")
    if receipt.bundle_id != bundle.bundle_id:
        raise ValueError("verification receipt does not belong to this repair bundle")
    if receipt.status is not CheckExecutionStatus.PASS:
        raise ValueError("a failed verification receipt cannot unlock approval")
    external = dict(bundle.external_action_receipt or {})
    if external.get("commit_sha") != receipt.commit_sha:
        raise ValueError("verification receipt commit does not match publication")
    if external.get("repository") != receipt.repository:
        raise ValueError("verification receipt repository does not match publication")
    if external.get("branch") != receipt.branch:
        raise ValueError("verification receipt branch does not match publication")
    expected_provider = {
        "GITHUB": "GITHUB_CHECK_RUNS",
        "LOCAL_GIT": "LOCAL_PROCESS",
    }.get(str(external.get("provider") or ""))
    if expected_provider is None or receipt.provider != expected_provider:
        raise ValueError("verification provider does not match the publication provider")
    declared = {check.check_id: check for check in bundle.verification_checks}
    observed = {check.check_id: check for check in receipt.checks}
    if set(declared) != set(observed):
        raise ValueError("verification receipt must cover exactly the declared check IDs")
    for check_id, expected in declared.items():
        actual = observed[check_id]
        if actual.status is not CheckExecutionStatus.PASS:
            raise ValueError(f"verification check did not pass: {check_id}")
        if actual.name != expected.name:
            raise ValueError(f"verification check name changed: {check_id}")
        if actual.declared_command != expected.command:
            raise ValueError(f"verification command changed: {check_id}")
        if actual.evidence_ids != expected.evidence_ids:
            raise ValueError(f"verification evidence changed: {check_id}")
    return RepairBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "status": RepairStatus.VERIFIED,
            "verification_receipt": receipt.model_dump(mode="python"),
        }
    )
