"""Exact-revision application boundary for an approved SciGuard repair."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from core.events import stable_evidence_id
from core.repair import RepairBundle, RepairStatus


class ApplicationError(RuntimeError):
    pass


class ApplicationReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    provider: str
    status: str
    bundle_id: str
    commit_sha: str
    target_environment: str
    deployment_id: str
    source_tree_sha256: str
    production_authorized: bool
    applied_at: datetime


class RepairApplicator(Protocol):
    def apply(self, bundle: RepairBundle) -> ApplicationReceipt: ...


def _git_bytes(repository: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout).decode("utf-8", errors="replace").strip()
        raise ApplicationError(f"git {' '.join(args)} failed: {detail}") from exc


def _git_text(repository: Path, *args: str) -> str:
    return _git_bytes(repository, *args).decode("utf-8").strip()


def _safe_member(member: tarfile.TarInfo) -> PurePosixPath:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ApplicationError(f"unsafe application archive path: {member.name!r}")
    if not (member.isdir() or member.isfile()):
        raise ApplicationError(
            f"application archive contains a non-regular entry: {member.name!r}"
        )
    return path


def _tree_digest(files: dict[str, bytes]) -> str:
    canonical = [
        {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(files.items())
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class LocalStagingApplicator:
    """Materialize the approved Git tree into an isolated synthetic staging release."""

    def __init__(
        self,
        repository: str | Path,
        deployment_root: str | Path,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.deployment_root = Path(deployment_root).resolve()
        if not self.repository.is_dir():
            raise ApplicationError(f"repository does not exist: {self.repository}")
        self.deployment_root.mkdir(parents=True, exist_ok=True)

    def apply(self, bundle: RepairBundle) -> ApplicationReceipt:
        if bundle.status is not RepairStatus.APPROVED:
            raise ApplicationError("application requires an APPROVED repair bundle")
        change = bundle.external_action_receipt or {}
        approval = bundle.approval_receipt or {}
        commit_sha = str(change.get("commit_sha", ""))
        if (
            not commit_sha
            or approval.get("commit_sha") != commit_sha
            or (bundle.verification_receipt or {}).get("commit_sha") != commit_sha
        ):
            raise ApplicationError(
                "application commit is not bound to change, verification, and approval"
            )
        if _git_text(self.repository, "rev-parse", "HEAD") != commit_sha:
            raise ApplicationError("repository HEAD does not match the approved commit")
        if _git_text(self.repository, "status", "--porcelain"):
            raise ApplicationError("repository must be clean before application")

        archive = _git_bytes(self.repository, "archive", "--format=tar", commit_sha)
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            for member in tar.getmembers():
                path = _safe_member(member)
                if member.isfile():
                    extracted = tar.extractfile(member)
                    if extracted is None:
                        raise ApplicationError(
                            f"could not read application archive file: {path}"
                        )
                    files[path.as_posix()] = extracted.read()
        source_tree_sha256 = _tree_digest(files)
        identity = {
            "bundle_id": bundle.bundle_id,
            "commit_sha": commit_sha,
            "source_tree_sha256": source_tree_sha256,
            "target_environment": "SCIGUARD_SYNTHETIC_STAGING",
        }
        deployment_id = stable_evidence_id("staging-deployment", identity)
        receipt_path = self.deployment_root / f"{deployment_id.replace(':', '-')}.json"
        release_path = self.deployment_root / deployment_id.replace(":", "-")
        if receipt_path.is_file() and release_path.is_dir():
            receipt = ApplicationReceipt.model_validate_json(
                receipt_path.read_text(encoding="utf-8")
            )
            if (
                receipt.bundle_id != bundle.bundle_id
                or receipt.commit_sha != commit_sha
                or receipt.source_tree_sha256 != source_tree_sha256
            ):
                raise ApplicationError("existing staging receipt does not match the repair")
            observed_files = {
                path.relative_to(release_path).as_posix(): path.read_bytes()
                for path in release_path.rglob("*")
                if path.is_file()
            }
            if _tree_digest(observed_files) != source_tree_sha256:
                raise ApplicationError("existing staging release has been modified")
            return receipt
        if receipt_path.exists() or release_path.exists():
            raise ApplicationError("partial staging application requires operator review")

        with tempfile.TemporaryDirectory(
            prefix="sciguard-apply-",
            dir=self.deployment_root,
        ) as temporary:
            temporary_root = Path(temporary)
            for relative, content in files.items():
                destination = temporary_root.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            os.replace(temporary_root, release_path)

        applied_at = datetime.now(timezone.utc)
        receipt = ApplicationReceipt(
            receipt_id=stable_evidence_id(
                "application-receipt",
                {**identity, "deployment_id": deployment_id},
            ),
            provider="LOCAL_STAGING",
            status="APPLIED",
            bundle_id=bundle.bundle_id,
            commit_sha=commit_sha,
            target_environment="SCIGUARD_SYNTHETIC_STAGING",
            deployment_id=deployment_id,
            source_tree_sha256=source_tree_sha256,
            production_authorized=False,
            applied_at=applied_at,
        )
        receipt_path.write_text(
            receipt.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
        return receipt


def attach_application_receipt(
    bundle: RepairBundle,
    receipt: ApplicationReceipt,
) -> RepairBundle:
    if bundle.status is not RepairStatus.APPROVED:
        raise ApplicationError("only an approved bundle can be applied")
    if receipt.bundle_id != bundle.bundle_id:
        raise ApplicationError("application receipt does not belong to this bundle")
    expected_commit = (bundle.approval_receipt or {}).get("commit_sha")
    if receipt.commit_sha != expected_commit:
        raise ApplicationError("application receipt targets a different commit")
    if receipt.status != "APPLIED":
        raise ApplicationError("application receipt did not observe an applied revision")
    return RepairBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "status": RepairStatus.APPLIED,
            "application_receipt": receipt.model_dump(mode="python"),
        }
    )
