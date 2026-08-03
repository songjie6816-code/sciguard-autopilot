"""Read and bind GitHub Check Runs to a published repair commit."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlparse

from core.change_provider import ChangeReceipt
from core.events import stable_evidence_id
from core.github_provider import GitHubTransport
from core.repair import RepairBundle, RepairStatus
from core.verification import (
    CheckExecutionStatus,
    VerificationCheckReceipt,
    VerificationError,
    VerificationReceipt,
)

DEFAULT_CHECK_NAMES = {
    "unit_contract": "scientific-unit-contract",
    "candidate_ranking_stability": "scientific-decision-regression",
    "safe_branch_preservation": "preserved-branch-non-regression",
}


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise VerificationError("GitHub Check Run has an invalid timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise VerificationError("GitHub Check Run has an invalid timestamp") from exc


class GitHubCheckRunVerifier:
    """Trust only a named GitHub Actions workflow on the exact PR revision."""

    def __init__(
        self,
        *,
        repository: str,
        transport: GitHubTransport,
        check_names: dict[str, str] | None = None,
        trusted_app_slug: str = "github-actions",
        trusted_app_id: int | None = 15368,
        trusted_workflow_path: str = ".github/workflows/sciguard-repair.yml",
        trusted_workflow_id: int | None = None,
    ) -> None:
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",
            repository,
        ):
            raise ValueError("GitHub repository must be in owner/name form")
        self.repository = repository
        self.transport = transport
        self.check_names = dict(check_names or DEFAULT_CHECK_NAMES)
        if (
            not self.check_names
            or any(not key or not value for key, value in self.check_names.items())
            or len(set(self.check_names.values())) != len(self.check_names)
        ):
            raise ValueError("GitHub Check Run names must be nonempty and unique")
        if not re.fullmatch(r"[A-Za-z0-9-]+", trusted_app_slug):
            raise ValueError("trusted GitHub App slug is invalid")
        if trusted_app_id is not None and trusted_app_id <= 0:
            raise ValueError("trusted GitHub App ID must be positive")
        if not re.fullmatch(
            r"\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml",
            trusted_workflow_path,
        ):
            raise ValueError("trusted GitHub workflow path is invalid")
        if trusted_workflow_id is not None and trusted_workflow_id <= 0:
            raise ValueError("trusted GitHub workflow ID must be positive")
        self.trusted_app_slug = trusted_app_slug
        self.trusted_app_id = trusted_app_id
        self.trusted_workflow_path = trusted_workflow_path
        self.trusted_workflow_id = trusted_workflow_id

    def _request(self, path: str, label: str) -> dict[str, Any]:
        response = self.transport.request("GET", path)
        if response.status != 200 or not isinstance(response.data, dict):
            raise VerificationError(f"GitHub {label} request returned {response.status}")
        return response.data

    def _assert_publication_still_exact(
        self,
        change_receipt: ChangeReceipt,
    ) -> None:
        """Re-read mutable refs and PR state before accepting CI evidence."""

        branch_ref = self._request(
            (f"/repos/{self.repository}/git/ref/heads/{quote(change_receipt.branch, safe='')}"),
            "repair branch",
        )
        branch_object = branch_ref.get("object")
        branch_object = branch_object if isinstance(branch_object, dict) else {}
        if (
            branch_object.get("type") != "commit"
            or branch_object.get("sha") != change_receipt.commit_sha
        ):
            raise VerificationError("GitHub repair branch no longer matches the published commit")
        base_ref = self._request(
            (
                f"/repos/{self.repository}/git/ref/heads/"
                f"{quote(change_receipt.base_revision, safe='')}"
            ),
            "base branch",
        )
        base_object = base_ref.get("object")
        base_object = base_object if isinstance(base_object, dict) else {}
        if (
            base_object.get("type") != "commit"
            or base_object.get("sha") != change_receipt.base_commit_sha
        ):
            raise VerificationError(
                "GitHub base branch moved after publication; rebase and re-verify"
            )
        if not isinstance(change_receipt.pull_request_number, int):
            raise VerificationError("publication receipt has no pull request number")
        pull = self._request(
            (f"/repos/{self.repository}/pulls/{change_receipt.pull_request_number}"),
            "pull request",
        )
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
            or head.get("sha") != change_receipt.commit_sha
            or head.get("ref") != change_receipt.branch
            or head_repo.get("full_name") != self.repository
            or base.get("sha") != change_receipt.base_commit_sha
            or base.get("ref") != change_receipt.base_revision
            or base_repo.get("full_name") != self.repository
        ):
            raise VerificationError("GitHub pull request no longer matches the publication receipt")

    def _workflow_provenance(
        self,
        observed: dict[str, Any],
        change_receipt: ChangeReceipt,
        cache: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        def exact_pull_binding(items: Any) -> bool:
            if not isinstance(items, list):
                return False
            matching: list[dict[str, Any]] = [
                item
                for item in items
                if isinstance(item, dict)
                and item.get("number") == change_receipt.pull_request_number
            ]
            if len(matching) != 1:
                return False
            head = matching[0].get("head")
            base = matching[0].get("base")
            head = head if isinstance(head, dict) else {}
            base = base if isinstance(base, dict) else {}
            return (
                head.get("sha") == change_receipt.commit_sha
                and head.get("ref") == change_receipt.branch
                and base.get("sha") == change_receipt.base_commit_sha
                and base.get("ref") == change_receipt.base_revision
            )

        app = observed.get("app")
        if (
            not isinstance(app, dict)
            or app.get("slug") != self.trusted_app_slug
            or (self.trusted_app_id is not None and app.get("id") != self.trusted_app_id)
        ):
            raise VerificationError(f"untrusted GitHub App produced Check Run {observed.get('id')}")
        app_id = app.get("id")
        if not isinstance(app_id, int):
            raise VerificationError("GitHub Check Run App has no stable numeric ID")

        suite = observed.get("check_suite")
        if not isinstance(suite, dict) or not isinstance(suite.get("id"), int):
            raise VerificationError("GitHub Check Run is not bound to an exact check suite")
        check_suite_id = int(suite["id"])
        if not exact_pull_binding(observed.get("pull_requests")):
            raise VerificationError("GitHub Check Run is not bound to the exact pull request")

        details_url = observed.get("details_url")
        if not isinstance(details_url, str):
            raise VerificationError("GitHub Check Run has no details URL")
        parsed = urlparse(details_url)
        match = re.fullmatch(
            (
                rf"/{re.escape(self.repository)}/actions/runs/"
                r"([1-9][0-9]*)(?:/job/[1-9][0-9]*)?"
            ),
            parsed.path.rstrip("/"),
        )
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.query
            or parsed.fragment
            or not match
        ):
            raise VerificationError(
                "GitHub Check Run details URL is outside the trusted repository"
            )
        workflow_run_id = int(match.group(1))
        workflow = cache.get(workflow_run_id)
        if workflow is None:
            workflow = self._request(
                (f"/repos/{self.repository}/actions/runs/{workflow_run_id}"),
                "workflow run",
            )
            cache[workflow_run_id] = workflow

        workflow_path = str(workflow.get("path") or "").split("@", 1)[0]
        workflow_id = workflow.get("workflow_id")
        run_attempt = workflow.get("run_attempt")
        expected_run_url = f"https://github.com/{self.repository}/actions/runs/{workflow_run_id}"
        terminal_conclusions = {
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
        repository = workflow.get("repository")
        head_repository = workflow.get("head_repository")
        repository = repository if isinstance(repository, dict) else {}
        head_repository = head_repository if isinstance(head_repository, dict) else {}
        if (
            workflow.get("id") != workflow_run_id
            or workflow.get("check_suite_id") != check_suite_id
            or workflow.get("head_sha") != change_receipt.commit_sha
            or workflow.get("head_branch") != change_receipt.branch
            or workflow.get("event") != "pull_request"
            or workflow.get("status") != "completed"
            or workflow.get("conclusion") not in terminal_conclusions
            or repository.get("full_name") != self.repository
            or head_repository.get("full_name") != self.repository
            or workflow.get("html_url") != expected_run_url
            or workflow_path != self.trusted_workflow_path
            or not isinstance(workflow_id, int)
            or (self.trusted_workflow_id is not None and workflow_id != self.trusted_workflow_id)
            or not isinstance(run_attempt, int)
            or run_attempt <= 0
            or not exact_pull_binding(workflow.get("pull_requests"))
        ):
            raise VerificationError("GitHub Check Run lacks trusted workflow provenance")
        return {
            "external_app_id": app_id,
            "external_app_slug": self.trusted_app_slug,
            "check_suite_id": check_suite_id,
            "workflow_run_id": workflow_run_id,
            "workflow_run_attempt": run_attempt,
            "workflow_id": workflow_id,
            "workflow_path": workflow_path,
            "workflow_url": expected_run_url,
            "workflow_conclusion": workflow["conclusion"],
        }

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
            raise VerificationError("GitHub verification requires a published repair revision")
        if change_receipt.provider != "GITHUB" or change_receipt.status != "PULL_REQUEST_OPEN":
            raise VerificationError(
                "GitHub verification requires a pull-request publication receipt"
            )
        if change_receipt.bundle_id != bundle.bundle_id:
            raise VerificationError("change receipt does not belong to this bundle")
        if change_receipt.repository != f"https://github.com/{self.repository}":
            raise VerificationError("verification repository does not match publication")
        if not re.fullmatch(r"[0-9a-f]{40}", change_receipt.commit_sha):
            raise VerificationError("publication receipt has an invalid commit SHA")
        if not re.fullmatch(
            r"[0-9a-f]{40}",
            str(change_receipt.base_commit_sha or ""),
        ):
            raise VerificationError("publication receipt has an invalid base SHA")
        self._assert_publication_still_exact(change_receipt)

        response = self.transport.request(
            "GET",
            (
                f"/repos/{self.repository}/commits/{change_receipt.commit_sha}"
                "/check-runs?filter=latest&per_page=100"
            ),
        )
        if response.status != 200 or not isinstance(response.data, dict):
            raise VerificationError(f"GitHub Check Runs request returned {response.status}")
        check_runs = response.data.get("check_runs")
        if not isinstance(check_runs, list):
            raise VerificationError("GitHub Check Runs response is malformed")

        receipts: list[VerificationCheckReceipt] = []
        completed_times: list[datetime] = []
        workflow_cache: dict[int, dict[str, Any]] = {}
        used_check_run_ids: set[int] = set()
        for check in bundle.verification_checks:
            external_name = self.check_names.get(check.check_id)
            if not external_name:
                raise VerificationError(f"no GitHub Check Run is configured for {check.check_id}")
            candidates = [
                item
                for item in check_runs
                if isinstance(item, dict)
                and item.get("name") == external_name
                and item.get("head_sha") == change_receipt.commit_sha
                and isinstance(item.get("id"), int)
            ]
            if not candidates:
                raise VerificationError(f"required GitHub Check Run is missing: {external_name}")
            observed = max(candidates, key=lambda item: int(item["id"]))
            if int(observed["id"]) in used_check_run_ids:
                raise VerificationError(
                    "one GitHub Check Run cannot satisfy multiple required checks"
                )
            used_check_run_ids.add(int(observed["id"]))
            provenance = self._workflow_provenance(
                observed,
                change_receipt,
                workflow_cache,
            )
            status = (
                CheckExecutionStatus.PASS
                if observed.get("status") == "completed"
                and observed.get("conclusion") == "success"
                and provenance["workflow_conclusion"] == "success"
                else CheckExecutionStatus.FAIL
            )
            started_at = _timestamp(observed.get("started_at"))
            completed_at = _timestamp(observed.get("completed_at"))
            if started_at is None or completed_at is None or completed_at < started_at:
                raise VerificationError("GitHub Check Run has an invalid execution interval")
            completed_times.append(completed_at)
            duration_ms = round((completed_at - started_at).total_seconds() * 1000)
            canonical: dict[str, Any] = {
                "id": observed["id"],
                "name": external_name,
                "status": observed.get("status"),
                "conclusion": observed.get("conclusion"),
                "head_sha": observed.get("head_sha"),
                "details_url": observed.get("details_url"),
                "started_at": observed.get("started_at"),
                "completed_at": observed.get("completed_at"),
                "app_id": provenance["external_app_id"],
                "app_slug": provenance["external_app_slug"],
                "check_suite_id": provenance["check_suite_id"],
                "workflow_run_id": provenance["workflow_run_id"],
                "workflow_run_attempt": provenance["workflow_run_attempt"],
                "workflow_id": provenance["workflow_id"],
                "workflow_path": provenance["workflow_path"],
                "workflow_conclusion": provenance["workflow_conclusion"],
            }
            encoded = json.dumps(
                canonical,
                sort_keys=True,
                separators=(",", ":"),
            )
            output_sha256 = hashlib.sha256(encoded.encode()).hexdigest()
            result_sha256 = hashlib.sha256(
                json.dumps(
                    {
                        "check_id": check.check_id,
                        "external_run_id": observed["id"],
                        "head_sha": change_receipt.commit_sha,
                        "output_sha256": output_sha256,
                        "workflow_run_id": provenance["workflow_run_id"],
                        "workflow_run_attempt": provenance["workflow_run_attempt"],
                        "workflow_id": provenance["workflow_id"],
                        "workflow_path": provenance["workflow_path"],
                        "workflow_conclusion": provenance["workflow_conclusion"],
                        "check_suite_id": provenance["check_suite_id"],
                        "external_app_id": provenance["external_app_id"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            receipts.append(
                VerificationCheckReceipt(
                    check_id=check.check_id,
                    name=check.name,
                    status=status,
                    declared_command=check.command,
                    executed_command=[],
                    exit_code=0 if status is CheckExecutionStatus.PASS else 1,
                    duration_ms=duration_ms,
                    output_sha256=output_sha256,
                    result_sha256=result_sha256,
                    output_excerpt=(
                        f"GitHub Check Run {observed['id']} · "
                        f"{observed.get('status')} / {observed.get('conclusion')}"
                    ),
                    evidence_ids=check.evidence_ids,
                    details_url=observed.get("details_url"),
                    external_run_id=observed["id"],
                    external_app_id=provenance["external_app_id"],
                    external_app_slug=provenance["external_app_slug"],
                    check_suite_id=provenance["check_suite_id"],
                    workflow_run_id=provenance["workflow_run_id"],
                    workflow_run_attempt=provenance["workflow_run_attempt"],
                    workflow_id=provenance["workflow_id"],
                    workflow_path=provenance["workflow_path"],
                    workflow_conclusion=provenance["workflow_conclusion"],
                )
            )

        overall = (
            CheckExecutionStatus.PASS
            if all(item.status is CheckExecutionStatus.PASS for item in receipts)
            else CheckExecutionStatus.FAIL
        )
        identity = {
            "bundle_id": bundle.bundle_id,
            "commit_sha": change_receipt.commit_sha,
            "provider": "GITHUB_CHECK_RUNS",
            "checks": [
                {
                    "check_id": item.check_id,
                    "external_run_id": item.external_run_id,
                    "status": item.status.value,
                    "output_sha256": item.output_sha256,
                    "result_sha256": item.result_sha256,
                    "external_app_id": item.external_app_id,
                    "check_suite_id": item.check_suite_id,
                    "workflow_run_id": item.workflow_run_id,
                    "workflow_run_attempt": item.workflow_run_attempt,
                    "workflow_id": item.workflow_id,
                    "workflow_path": item.workflow_path,
                    "workflow_conclusion": item.workflow_conclusion,
                }
                for item in receipts
            ],
        }
        return VerificationReceipt(
            receipt_id=stable_evidence_id("verification-receipt", identity),
            provider="GITHUB_CHECK_RUNS",
            status=overall,
            bundle_id=bundle.bundle_id,
            repository=change_receipt.repository,
            branch=change_receipt.branch,
            commit_sha=change_receipt.commit_sha,
            source_tree_clean=None,
            checks=receipts,
            created_at=max(completed_times) if completed_times else datetime.now(timezone.utc),
        )
