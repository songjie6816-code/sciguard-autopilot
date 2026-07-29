"""GitHub publication adapter for proof-carrying repairs.

The adapter uses GitHub's Git Data and Pull Requests APIs so it can create a
reviewable branch without mutating the SciGuard process worktree. Every remote
receipt is bound to the requested base commit, generated tree, head commit,
bundle marker, and pull-request URL. A transport interface keeps the network
boundary adversarially testable and prevents unit tests from creating remote
state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import certifi

from core.change_provider import (
    ChangePublicationError,
    ChangeReceipt,
    default_branch,
    safe_relative_path,
)
from core.repair import ArtifactKind, RepairBundle, RepairStatus
from core.unified_patch import apply_unified_patch


@dataclass(frozen=True)
class GitHubResponse:
    status: int
    data: Any


class GitHubTransport(Protocol):
    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> GitHubResponse: ...


class UrllibGitHubTransport:
    """Minimal token-authenticated transport with sanitized failures."""

    def __init__(
        self,
        *,
        token: str,
        api_base: str = "https://api.github.com",
        timeout_seconds: float = 20,
    ) -> None:
        if not token.strip():
            raise ValueError("GitHub token must not be empty")
        if not api_base.startswith("https://"):
            raise ValueError("GitHub API base must use HTTPS")
        self._token = token
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._tls_context = ssl.create_default_context(cafile=certifi.where())

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> GitHubResponse:
        payload = (
            json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
        )
        request = Request(
            f"{self._api_base}{path}",
            method=method,
            data=payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "sciguard-proof-carrying-repair",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(
                request,
                timeout=self._timeout_seconds,
                context=self._tls_context,
            ) as response:
                raw = response.read()
                return GitHubResponse(
                    status=response.status,
                    data=json.loads(raw) if raw else {},
                )
        except HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                detail = {}
            return GitHubResponse(status=exc.code, data=detail)


class PublicReadOnlyGitHubTransport:
    """Read public GitHub evidence without creating or storing a credential."""

    def __init__(
        self,
        *,
        api_base: str = "https://api.github.com",
        timeout_seconds: float = 20,
    ) -> None:
        if not api_base.startswith("https://"):
            raise ValueError("GitHub API base must use HTTPS")
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._tls_context = ssl.create_default_context(cafile=certifi.where())

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> GitHubResponse:
        if method != "GET" or body is not None:
            return GitHubResponse(
                status=403,
                data={"message": "public evidence transport is read-only"},
            )
        request = Request(
            f"{self._api_base}{path}",
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "sciguard-public-evidence-verifier",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urlopen(
                request,
                timeout=self._timeout_seconds,
                context=self._tls_context,
            ) as response:
                raw = response.read()
                return GitHubResponse(
                    status=response.status,
                    data=json.loads(raw) if raw else {},
                )
        except HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                detail = {}
            return GitHubResponse(status=exc.code, data=detail)


def _safe_branch(branch: str) -> str:
    if (
        not re.fullmatch(r"[A-Za-z0-9._/-]+", branch)
        or branch.startswith(("/", "-", "."))
        or branch.endswith(("/", ".", ".lock"))
        or ".." in branch
        or "@{" in branch
        or "//" in branch
    ):
        raise ChangePublicationError(f"unsafe GitHub branch name: {branch!r}")
    return branch


def _git_blob_sha(content: str) -> str:
    """Return the SHA-1 GitHub exposes for a UTF-8 blob."""

    payload = content.encode("utf-8")
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


class GitHubChangePublisher:
    """Create one idempotent GitHub branch, commit, and pull request."""

    def __init__(
        self,
        *,
        repository: str,
        transport: GitHubTransport,
        base_branch: str = "main",
    ) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            repository,
        ):
            raise ValueError("GitHub repository must be in owner/name form")
        self.repository = repository
        self.owner = repository.split("/", 1)[0]
        self.transport = transport
        self.base_branch = _safe_branch(base_branch)
        self._prefix = f"/repos/{repository}"

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        expected: set[int] | None = None,
    ) -> Any:
        response = self.transport.request(method, path, body)
        expected_statuses = expected or {200}
        if response.status not in expected_statuses:
            message = response.data.get("message") if isinstance(response.data, dict) else None
            detail = f": {message}" if message else ""
            raise ChangePublicationError(
                f"GitHub API {method} {path} returned {response.status}{detail}"
            )
        return response.data

    def _get_ref(self, branch: str) -> tuple[int, dict[str, Any]]:
        response = self.transport.request(
            "GET",
            f"{self._prefix}/git/ref/heads/{quote(branch, safe='')}",
        )
        if response.status not in {200, 404}:
            raise ChangePublicationError(f"GitHub branch lookup returned {response.status}")
        if response.status == 200 and not isinstance(response.data, dict):
            raise ChangePublicationError("GitHub branch lookup is malformed")
        return response.status, response.data if isinstance(response.data, dict) else {}

    @staticmethod
    def _response_error(
        method: str,
        path: str,
        response: GitHubResponse,
    ) -> ChangePublicationError:
        message = response.data.get("message") if isinstance(response.data, dict) else None
        detail = f": {message}" if message else ""
        return ChangePublicationError(
            f"GitHub API {method} {path} returned {response.status}{detail}"
        )

    def _assert_base_unchanged(self, expected_sha: str) -> None:
        status, ref = self._get_ref(self.base_branch)
        ref_object = ref.get("object")
        ref_object = ref_object if isinstance(ref_object, dict) else {}
        observed_sha = str(ref_object.get("sha", ""))
        if status != 200 or ref_object.get("type") != "commit" or observed_sha != expected_sha:
            raise ChangePublicationError(
                "GitHub base branch moved during publication; refusing to publish a stale repair"
            )

    @staticmethod
    def _commit_markers(bundle: RepairBundle) -> set[str]:
        return {
            f"SciGuard-Incident: {bundle.incident_id}",
            f"SciGuard-Bundle: {bundle.bundle_id}",
            f"SciGuard-Evidence: {','.join(bundle.evidence_ids)}",
        }

    def _validate_existing_branch(
        self,
        bundle: RepairBundle,
        branch: str,
        head_sha: str,
    ) -> tuple[str, list[str]]:
        """Prove an existing branch is the exact interrupted SciGuard mutation."""

        commit = self._request(
            "GET",
            f"{self._prefix}/git/commits/{head_sha}",
        )
        if not isinstance(commit, dict):
            raise ChangePublicationError("GitHub commit response is malformed")
        parents = commit.get("parents")
        if not isinstance(parents, list) or len(parents) != 1 or not isinstance(parents[0], dict):
            raise ChangePublicationError(
                "existing GitHub branch is not a single-parent repair commit"
            )
        base_sha = str(parents[0].get("sha") or "")
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise ChangePublicationError("existing GitHub branch has an invalid parent SHA")
        message_lines = set(str(commit.get("message") or "").splitlines())
        if not self._commit_markers(bundle).issubset(message_lines):
            raise ChangePublicationError(
                "existing GitHub branch commit is not bound to this repair bundle"
            )
        self._assert_base_unchanged(base_sha)

        files = self._materialize_files(bundle, base_sha)
        comparison = self._request(
            "GET",
            f"{self._prefix}/compare/{base_sha}...{head_sha}",
        )
        if not isinstance(comparison, dict):
            raise ChangePublicationError("GitHub comparison response is malformed")
        compared_commits = comparison.get("commits")
        compared_files = comparison.get("files")
        if (
            comparison.get("status") != "ahead"
            or comparison.get("ahead_by") != 1
            or comparison.get("behind_by") != 0
            or comparison.get("total_commits") != 1
            or not isinstance(compared_commits, list)
            or any(not isinstance(item, dict) for item in compared_commits)
            or [str(item.get("sha") or "") for item in compared_commits] != [head_sha]
            or not isinstance(compared_files, list)
        ):
            raise ChangePublicationError(
                "existing GitHub branch history is not the exact repair revision"
            )
        observed_files: dict[str, dict[str, Any]] = {}
        for item in compared_files:
            if not isinstance(item, dict):
                raise ChangePublicationError("GitHub comparison returned a malformed file entry")
            filename = str(item.get("filename") or "")
            if filename in observed_files:
                raise ChangePublicationError("GitHub comparison returned duplicate file entries")
            observed_files[filename] = item
        if set(observed_files) != set(files):
            raise ChangePublicationError(
                "existing GitHub branch changed files outside the repair bundle"
            )
        for path, expected_content in files.items():
            observed = observed_files[path]
            if observed.get("status") not in {"added", "modified"} or observed.get(
                "sha"
            ) != _git_blob_sha(expected_content):
                raise ChangePublicationError(
                    f"existing GitHub branch content does not match repair artifact: {path}"
                )
        return base_sha, sorted(files)

    def _pulls_for_branch(self, branch: str) -> list[dict[str, Any]]:
        pulls = self._request(
            "GET",
            (f"{self._prefix}/pulls?state=all&head={quote(f'{self.owner}:{branch}', safe='')}"),
        )
        if not isinstance(pulls, list) or any(not isinstance(pull, dict) for pull in pulls):
            raise ChangePublicationError("GitHub pull request list is malformed")
        return pulls

    def _validate_pull(
        self,
        *,
        bundle: RepairBundle,
        branch: str,
        base_sha: str,
        head_sha: str,
        pull: dict[str, Any],
    ) -> None:
        marker = f"SciGuard-Bundle: {bundle.bundle_id}"
        expected_url_prefix = f"https://github.com/{self.repository}/pull/"
        head = pull.get("head")
        base = pull.get("base")
        head = head if isinstance(head, dict) else {}
        base = base if isinstance(base, dict) else {}
        head_repo = head.get("repo")
        base_repo = base.get("repo")
        head_repo = head_repo if isinstance(head_repo, dict) else {}
        base_repo = base_repo if isinstance(base_repo, dict) else {}
        if (
            pull.get("state") != "open"
            or marker not in str(pull.get("body") or "")
            or str(head.get("sha") or "") != head_sha
            or str(head.get("ref") or "") != branch
            or str(head_repo.get("full_name") or "") != self.repository
            or str(base.get("sha") or "") != base_sha
            or str(base.get("ref") or "") != self.base_branch
            or str(base_repo.get("full_name") or "") != self.repository
            or not str(pull.get("html_url") or "").startswith(expected_url_prefix)
        ):
            raise ChangePublicationError(
                "GitHub pull request is not bound to the exact repair revision"
            )

    def _pull_body(self, bundle: RepairBundle) -> str:
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

    def _create_pull_recoverably(
        self,
        *,
        bundle: RepairBundle,
        branch: str,
        base_sha: str,
        head_sha: str,
    ) -> dict[str, Any]:
        """Create the missing PR, probing state if the response was ambiguous."""

        self._assert_base_unchanged(base_sha)
        path = f"{self._prefix}/pulls"
        response = self.transport.request(
            "POST",
            path,
            {
                "title": f"[SciGuard] {bundle.title}",
                "head": branch,
                "base": self.base_branch,
                "body": self._pull_body(bundle),
                "maintainer_can_modify": False,
            },
        )
        if response.status == 201 and isinstance(response.data, dict):
            pull = response.data
        else:
            # A timeout/5xx may be an unknown-success response. Re-read remote
            # state before failing so a retry cannot strand a valid branch.
            pulls = self._pulls_for_branch(branch)
            marker = f"SciGuard-Bundle: {bundle.bundle_id}"
            recovered = []
            for candidate in pulls:
                candidate_head = candidate.get("head")
                candidate_head = candidate_head if isinstance(candidate_head, dict) else {}
                if (
                    marker in str(candidate.get("body") or "")
                    and str(candidate_head.get("sha") or "") == head_sha
                ):
                    recovered.append(candidate)
            if len(recovered) != 1:
                raise self._response_error("POST", path, response)
            pull = recovered[0]
        self._validate_pull(
            bundle=bundle,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            pull=pull,
        )
        return pull

    def _existing_receipt(
        self,
        bundle: RepairBundle,
        branch: str,
        ref: dict[str, Any],
    ) -> ChangeReceipt:
        ref_object = ref.get("object")
        ref_object = ref_object if isinstance(ref_object, dict) else {}
        head_sha = str(ref_object.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", head_sha):
            raise ChangePublicationError("existing GitHub branch has an invalid head SHA")
        if ref_object.get("type") != "commit":
            raise ChangePublicationError("existing GitHub branch does not reference a commit")
        base_sha, changed_files = self._validate_existing_branch(
            bundle,
            branch,
            head_sha,
        )
        pulls = self._pulls_for_branch(branch)
        marker = f"SciGuard-Bundle: {bundle.bundle_id}"
        matching = []
        for pull in pulls:
            pull_head = pull.get("head")
            pull_head = pull_head if isinstance(pull_head, dict) else {}
            if (
                marker in str(pull.get("body") or "")
                and str(pull_head.get("sha") or "") == head_sha
            ):
                matching.append(pull)
        if len(matching) > 1 or (not matching and pulls):
            raise ChangePublicationError(
                "existing branch is not bound to exactly one SciGuard pull request"
            )
        pull = (
            matching[0]
            if matching
            else self._create_pull_recoverably(
                bundle=bundle,
                branch=branch,
                base_sha=base_sha,
                head_sha=head_sha,
            )
        )
        self._validate_pull(
            bundle=bundle,
            branch=branch,
            base_sha=base_sha,
            head_sha=head_sha,
            pull=pull,
        )
        return self._receipt(
            bundle=bundle,
            branch=branch,
            base_sha=base_sha,
            commit_sha=head_sha,
            changed_files=changed_files,
            pull=pull,
        )

    @staticmethod
    def _artifact_paths(bundle: RepairBundle) -> list[str]:
        paths = []
        for artifact in bundle.artifacts:
            if artifact.kind is ArtifactKind.CODE_PATCH:
                lines = artifact.content.splitlines()
                if len(lines) < 2:
                    raise ChangePublicationError("code patch is missing file headers")
                raw = lines[1].removeprefix("+++ ").split("\t", 1)[0].removeprefix("b/")
                paths.append(safe_relative_path(raw).as_posix())
            else:
                paths.append(safe_relative_path(artifact.path).as_posix())
        return sorted(dict.fromkeys(paths))

    def _materialize_files(
        self,
        bundle: RepairBundle,
        base_sha: str,
    ) -> dict[str, str]:
        files: dict[str, str] = {}
        for artifact in bundle.artifacts:
            if artifact.kind is not ArtifactKind.CODE_PATCH:
                files[safe_relative_path(artifact.path).as_posix()] = artifact.content
                continue
            header_lines = artifact.content.splitlines()
            if len(header_lines) < 2:
                raise ChangePublicationError("code patch is missing file headers")
            target = header_lines[1].removeprefix("+++ ").split("\t", 1)[0].removeprefix("b/")
            target = safe_relative_path(target).as_posix()
            encoded_target = quote(target, safe="/")
            content_response = self._request(
                "GET",
                f"{self._prefix}/contents/{encoded_target}?ref={quote(base_sha, safe='')}",
            )
            if not isinstance(content_response, dict):
                raise ChangePublicationError(f"GitHub content response is malformed for {target}")
            if content_response.get("encoding") != "base64":
                raise ChangePublicationError(f"GitHub did not return base64 content for {target}")
            try:
                original = base64.b64decode(
                    str(content_response["content"]).replace("\n", ""),
                    validate=True,
                ).decode("utf-8")
                applied = apply_unified_patch(original, artifact.content)
            except (KeyError, UnicodeDecodeError, ValueError) as exc:
                raise ChangePublicationError(
                    f"could not safely materialize {target}: {exc}"
                ) from exc
            if applied.path != target:
                raise ChangePublicationError("patch target changed during materialization")
            files[target] = applied.content
        return files

    def _receipt(
        self,
        *,
        bundle: RepairBundle,
        branch: str,
        base_sha: str,
        commit_sha: str,
        changed_files: list[str],
        pull: dict[str, Any],
    ) -> ChangeReceipt:
        remote_url = str(pull.get("html_url") or "")
        number = pull.get("number")
        if (
            remote_url != f"https://github.com/{self.repository}/pull/{number}"
            or not isinstance(number, int)
            or not re.fullmatch(r"[0-9a-f]{40}", commit_sha)
            or not re.fullmatch(r"[0-9a-f]{40}", base_sha)
        ):
            raise ChangePublicationError("GitHub pull request response is incomplete")
        try:
            created_at = datetime.fromisoformat(
                str(pull["created_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (KeyError, ValueError) as exc:
            raise ChangePublicationError(
                "GitHub pull request has an invalid creation timestamp"
            ) from exc
        return ChangeReceipt(
            provider="GITHUB",
            status="PULL_REQUEST_OPEN",
            bundle_id=bundle.bundle_id,
            repository=f"https://github.com/{self.repository}",
            base_revision=self.base_branch,
            base_commit_sha=base_sha,
            branch=branch,
            commit_sha=commit_sha,
            changed_files=changed_files,
            created_at=created_at,
            remote_url=remote_url,
            pull_request_number=number,
        )

    def publish(
        self,
        bundle: RepairBundle,
        *,
        branch: str | None = None,
    ) -> ChangeReceipt:
        if bundle.status is not RepairStatus.PROPOSED:
            raise ChangePublicationError("GitHub publication requires a PROPOSED bundle")
        if bundle.external_action_receipt is not None:
            raise ChangePublicationError("bundle already contains an external action receipt")
        expected_repository = f"https://github.com/{self.repository}"
        if bundle.target_repository.rstrip("/") != expected_repository:
            raise ChangePublicationError(
                "configured GitHub repository does not match the repair target"
            )
        if bundle.target_base_revision != self.base_branch:
            raise ChangePublicationError(
                "configured GitHub base branch does not match the repair target"
            )
        branch = _safe_branch(branch or default_branch(bundle))

        existing_status, existing_ref = self._get_ref(branch)
        if existing_status == 200:
            return self._existing_receipt(bundle, branch, existing_ref)

        base_ref = self._request(
            "GET",
            f"{self._prefix}/git/ref/heads/{quote(self.base_branch, safe='')}",
        )
        if not isinstance(base_ref, dict):
            raise ChangePublicationError("GitHub base branch response is malformed")
        base_ref_object = base_ref.get("object")
        base_ref_object = base_ref_object if isinstance(base_ref_object, dict) else {}
        base_sha = str(base_ref_object.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", base_sha):
            raise ChangePublicationError("GitHub base branch has an invalid commit SHA")
        base_commit = self._request(
            "GET",
            f"{self._prefix}/git/commits/{base_sha}",
        )
        if not isinstance(base_commit, dict):
            raise ChangePublicationError("GitHub base commit response is malformed")
        base_tree = base_commit.get("tree")
        base_tree = base_tree if isinstance(base_tree, dict) else {}
        base_tree_sha = str(base_tree.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", base_tree_sha):
            raise ChangePublicationError("GitHub base commit has an invalid tree SHA")

        files = self._materialize_files(bundle, base_sha)
        # Keep the public mutation boundary closed until all source reads have
        # completed against one immutable base revision.
        self._assert_base_unchanged(base_sha)
        entries = []
        for path, content in sorted(files.items()):
            blob = self._request(
                "POST",
                f"{self._prefix}/git/blobs",
                {
                    "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                    "encoding": "base64",
                },
                expected={201},
            )
            if not isinstance(blob, dict):
                raise ChangePublicationError("GitHub blob response is malformed")
            blob_sha = str(blob.get("sha", ""))
            if not re.fullmatch(r"[0-9a-f]{40}", blob_sha):
                raise ChangePublicationError("GitHub blob response has an invalid SHA")
            entries.append({"path": path, "mode": "100644", "type": "blob", "sha": blob_sha})

        tree = self._request(
            "POST",
            f"{self._prefix}/git/trees",
            {"base_tree": base_tree_sha, "tree": entries},
            expected={201},
        )
        if not isinstance(tree, dict):
            raise ChangePublicationError("GitHub tree response is malformed")
        tree_sha = str(tree.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", tree_sha):
            raise ChangePublicationError("GitHub tree response has an invalid SHA")
        message = (
            f"fix(sciguard): {bundle.title}\n\n"
            f"SciGuard-Incident: {bundle.incident_id}\n"
            f"SciGuard-Bundle: {bundle.bundle_id}\n"
            f"SciGuard-Evidence: {','.join(bundle.evidence_ids)}"
        )
        commit = self._request(
            "POST",
            f"{self._prefix}/git/commits",
            {"message": message, "tree": tree_sha, "parents": [base_sha]},
            expected={201},
        )
        if not isinstance(commit, dict):
            raise ChangePublicationError("GitHub commit response is malformed")
        commit_sha = str(commit.get("sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise ChangePublicationError("GitHub commit response has an invalid SHA")
        self._assert_base_unchanged(base_sha)
        ref_path = f"{self._prefix}/git/refs"
        ref_response = self.transport.request(
            "POST",
            ref_path,
            {"ref": f"refs/heads/{branch}", "sha": commit_sha},
        )
        ref_status, ref = self._get_ref(branch)
        if ref_status != 200:
            raise self._response_error("POST", ref_path, ref_response)
        ref_object = ref.get("object")
        ref_object = ref_object if isinstance(ref_object, dict) else {}
        observed_head = str(ref_object.get("sha") or "")
        if observed_head != commit_sha:
            raise ChangePublicationError(
                "GitHub repair branch was concurrently created at another commit"
            )
        return self._existing_receipt(bundle, branch, ref)
