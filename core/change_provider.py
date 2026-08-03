"""Safe publication boundary for proof-carrying repairs.

The core planner produces a provider-neutral RepairBundle. This module is the
first real action adapter: it applies the bundle to an explicit local Git
repository, creates a branch and commit, and returns a content-bound receipt.
It never claims to have opened a remote pull request.

A future GitHub adapter must implement the same receipt semantics and add a
verified remote URL; the local adapter exists so branch creation, patch
application, idempotency, path safety, and failure rollback are testable now.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from core.repair import ArtifactKind, RepairBundle, RepairStatus
from core.unified_patch import apply_unified_patch


class ChangePublicationError(RuntimeError):
    pass


class ChangeReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    status: str
    bundle_id: str
    repository: str
    base_revision: str
    base_commit_sha: str | None = None
    branch: str
    commit_sha: str
    changed_files: list[str]
    created_at: datetime
    remote_url: str | None = None
    pull_request_number: int | None = None


class ChangePublisher(Protocol):
    def publish(
        self,
        bundle: RepairBundle,
        *,
        branch: str | None = None,
    ) -> ChangeReceipt: ...


def _run(
    repository: Path,
    args: list[str],
    *,
    input_text: str | None = None,
) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            input=input_text,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise ChangePublicationError(f"git {' '.join(args)} failed: {detail}") from exc
    return result.stdout.strip()


def safe_relative_path(raw_path: str) -> Path:
    posix = PurePosixPath(raw_path)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise ChangePublicationError(f"unsafe repair artifact path: {raw_path!r}")
    return Path(*posix.parts)


def default_branch(bundle: RepairBundle) -> str:
    suffix = re.sub(r"[^a-z0-9-]+", "-", bundle.incident_id.lower()).strip("-")
    return f"sciguard/{suffix}-{bundle.bundle_id.rsplit(':', 1)[-1][:8]}"


class LocalGitChangePublisher:
    """Apply one locked proposal to one explicit, clean local repository."""

    def __init__(self, repository: str | Path) -> None:
        self.repository = Path(repository).resolve()
        if not self.repository.is_dir():
            raise ChangePublicationError(f"repository does not exist: {self.repository}")
        if _run(self.repository, ["rev-parse", "--is-inside-work-tree"]) != "true":
            raise ChangePublicationError(f"not a Git work tree: {self.repository}")

    def _receipt_for_existing(
        self,
        bundle: RepairBundle,
        branch: str,
    ) -> ChangeReceipt | None:
        branch_ref = f"refs/heads/{branch}"
        try:
            commit_sha = _run(self.repository, ["rev-parse", "--verify", branch_ref])
        except ChangePublicationError:
            return None
        message = _run(self.repository, ["show", "-s", "--format=%B", commit_sha])
        if f"SciGuard-Bundle: {bundle.bundle_id}" not in message:
            raise ChangePublicationError(
                f"branch {branch!r} exists but is not bound to {bundle.bundle_id}"
            )
        parent_line = _run(
            self.repository,
            ["rev-list", "--parents", "-n", "1", commit_sha],
        ).split()
        if len(parent_line) != 2:
            raise ChangePublicationError(
                "repair commit must have exactly one immutable base parent"
            )
        base_commit_sha = parent_line[1]
        changed_files = _run(
            self.repository,
            [
                "diff",
                "--name-only",
                f"{base_commit_sha}..{commit_sha}",
            ],
        ).splitlines()
        expected_files = self._materialize_expected_files(
            bundle,
            base_commit_sha,
        )
        if sorted(path for path in changed_files if path) != sorted(expected_files):
            raise ChangePublicationError(
                "existing repair commit changed an unexpected file set"
            )
        for path, expected_content in expected_files.items():
            observed = _run(self.repository, ["show", f"{commit_sha}:{path}"])
            if observed + ("\n" if expected_content.endswith("\n") else "") != expected_content:
                raise ChangePublicationError(
                    f"existing repair content does not match the bundle: {path}"
                )
        authored_at = _run(
            self.repository, ["show", "-s", "--format=%aI", commit_sha]
        )
        return ChangeReceipt(
            provider="LOCAL_GIT",
            status="COMMITTED",
            bundle_id=bundle.bundle_id,
            repository=str(self.repository),
            base_revision=bundle.target_base_revision,
            base_commit_sha=base_commit_sha,
            branch=branch,
            commit_sha=commit_sha,
            changed_files=sorted(path for path in changed_files if path),
            created_at=datetime.fromisoformat(authored_at).astimezone(timezone.utc),
        )

    def _materialize_expected_files(
        self,
        bundle: RepairBundle,
        base_commit_sha: str,
    ) -> dict[str, str]:
        files: dict[str, str] = {}
        for artifact in bundle.artifacts:
            if artifact.kind is not ArtifactKind.CODE_PATCH:
                path = safe_relative_path(artifact.path).as_posix()
                files[path] = artifact.content
                continue
            header_lines = artifact.content.splitlines()
            if len(header_lines) < 2:
                raise ChangePublicationError("code patch is missing file headers")
            raw_path = (
                header_lines[1]
                .removeprefix("+++ ")
                .split("\t", 1)[0]
                .removeprefix("b/")
            )
            path = safe_relative_path(raw_path).as_posix()
            try:
                original = _run(
                    self.repository,
                    ["show", f"{base_commit_sha}:{path}"],
                )
                if original:
                    original += "\n"
                applied = apply_unified_patch(original, artifact.content)
            except (ChangePublicationError, ValueError) as exc:
                raise ChangePublicationError(
                    f"could not materialize expected repair content for {path}: {exc}"
                ) from exc
            if applied.path != path:
                raise ChangePublicationError("patch target changed during materialization")
            files[path] = applied.content
        return files

    def _safe_destination(self, relative: Path) -> Path:
        destination = self.repository / relative
        try:
            destination.resolve(strict=False).relative_to(self.repository)
        except ValueError as exc:
            raise ChangePublicationError(
                f"repair artifact resolves outside the repository: {relative}"
            ) from exc
        cursor = self.repository
        for part in relative.parts:
            cursor = cursor / part
            if cursor.exists() and cursor.is_symlink():
                raise ChangePublicationError(
                    f"repair artifact traverses a symlink: {relative}"
                )
        return destination

    def publish(
        self,
        bundle: RepairBundle,
        *,
        branch: str | None = None,
    ) -> ChangeReceipt:
        if bundle.status is not RepairStatus.PROPOSED:
            raise ChangePublicationError(
                f"only a PROPOSED bundle can be published, got {bundle.status.value}"
            )
        if bundle.external_action_receipt is not None:
            raise ChangePublicationError("bundle already contains an external action receipt")
        branch = branch or default_branch(bundle)
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch) or branch.startswith(("/", "-")):
            raise ChangePublicationError(f"unsafe branch name: {branch!r}")

        existing = self._receipt_for_existing(bundle, branch)
        if existing:
            return existing

        if _run(self.repository, ["status", "--porcelain"]):
            raise ChangePublicationError("repair repository must be clean before publication")
        base_commit = _run(
            self.repository, ["rev-parse", "--verify", bundle.target_base_revision]
        )
        _run(self.repository, ["checkout", "--quiet", "-b", branch, base_commit])
        try:
            for artifact in bundle.artifacts:
                if artifact.kind is ArtifactKind.CODE_PATCH:
                    _run(self.repository, ["apply", "--check", "-"], input_text=artifact.content)
                    _run(self.repository, ["apply", "-"], input_text=artifact.content)
                    continue
                path = self._safe_destination(safe_relative_path(artifact.path))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(artifact.content, encoding="utf-8")

            changed = _run(self.repository, ["status", "--porcelain"])
            if not changed:
                raise ChangePublicationError("repair bundle produced no repository changes")
            _run(self.repository, ["add", "--all"])
            message = (
                f"fix(sciguard): {bundle.title}\n\n"
                f"SciGuard-Incident: {bundle.incident_id}\n"
                f"SciGuard-Bundle: {bundle.bundle_id}\n"
                f"SciGuard-Evidence: {','.join(bundle.evidence_ids)}"
            )
            _run(self.repository, ["commit", "--quiet", "-m", message])
            commit_sha = _run(self.repository, ["rev-parse", "HEAD"])
            changed_files = _run(
                self.repository,
                ["diff", "--name-only", f"{base_commit}..{commit_sha}"],
            ).splitlines()
            authored_at = _run(
                self.repository, ["show", "-s", "--format=%aI", commit_sha]
            )
            return ChangeReceipt(
                provider="LOCAL_GIT",
                status="COMMITTED",
                bundle_id=bundle.bundle_id,
                repository=str(self.repository),
                base_revision=bundle.target_base_revision,
                base_commit_sha=base_commit,
                branch=branch,
                commit_sha=commit_sha,
                changed_files=sorted(path for path in changed_files if path),
                created_at=datetime.fromisoformat(authored_at).astimezone(timezone.utc),
            )
        except Exception:
            _run(self.repository, ["reset", "--hard", "--quiet", base_commit])
            _run(self.repository, ["checkout", "--quiet", bundle.target_base_revision])
            _run(self.repository, ["branch", "-D", branch])
            raise


def attach_change_receipt(
    bundle: RepairBundle,
    receipt: ChangeReceipt,
) -> RepairBundle:
    """Bind an observed change receipt to a new immutable bundle state."""

    if receipt.bundle_id != bundle.bundle_id:
        raise ValueError("change receipt does not belong to this repair bundle")
    return RepairBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "status": RepairStatus.PUBLISHED,
            "external_action_receipt": receipt.model_dump(mode="python"),
        }
    )
