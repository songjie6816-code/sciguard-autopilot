from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Any

import pytest

from core.change_provider import (
    ChangePublicationError,
    attach_change_receipt,
    default_branch,
)
from core.github_provider import (
    GitHubChangePublisher,
    GitHubResponse,
    PublicReadOnlyGitHubTransport,
)
from core.github_verification import GitHubCheckRunVerifier
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.repair import RepairStatus, create_unit_repair_bundle
from core.verification import (
    CheckExecutionStatus,
    VerificationError,
    attach_verification_receipt,
)

BASE_SHA = "1" * 40
BASE_TREE_SHA = "2" * 40
HEAD_SHA = "3" * 40
TREE_SHA = "4" * 40
MOVED_BASE_SHA = "9" * 40
ROOT = Path(__file__).parents[1]


def test_public_transport_is_fail_closed_for_writes() -> None:
    transport = PublicReadOnlyGitHubTransport()

    response = transport.request("POST", "/repos/acme/sciguard/pulls", {})

    assert response.status == 403
    assert response.data == {"message": "public evidence transport is read-only"}


def _bundle(*, target_repository: str = "https://github.com/acme/sciguard-sandbox"):
    return create_unit_repair_bundle(
        incident_id="inc-github-provider",
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
        target_repository=target_repository,
    )


class FakeGitHub:
    def __init__(self) -> None:
        self.branch_created = False
        self.branch_head_sha = HEAD_SHA
        self.base_sha = BASE_SHA
        self.base_lookup_count = 0
        self.move_base_on_lookup: int | None = None
        self.commit_message: str | None = None
        self.commit_parent_sha = BASE_SHA
        self.pull: dict[str, Any] | None = None
        self.blob_contents: list[str] = []
        self.blobs: dict[str, str] = {}
        self.tree_entries: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []
        self.check_runs: list[dict[str, Any]] = []
        self.workflow_overrides: dict[int, dict[str, Any]] = {}
        self.fail_pull_before_create_once = False
        self.lose_pull_response_once = False
        self.lose_ref_response_once = False
        self.pull_base_sha: str | None = None
        self.compare_file_sha_overrides: dict[str, str] = {}

    @staticmethod
    def _blob_sha(content: str) -> str:
        payload = content.encode()
        return hashlib.sha1(
            f"blob {len(payload)}\0".encode() + payload,
            usedforsecurity=False,
        ).hexdigest()

    def _pull_payload(self, body: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": 17,
            "state": "open",
            "html_url": "https://github.com/acme/sciguard-sandbox/pull/17",
            "created_at": "2026-07-27T00:00:00Z",
            "body": body["body"],
            "head": {
                "sha": self.branch_head_sha,
                "ref": body["head"],
                "repo": {"full_name": "acme/sciguard-sandbox"},
            },
            "base": {
                "sha": self.pull_base_sha or self.base_sha,
                "ref": body["base"],
                "repo": {"full_name": "acme/sciguard-sandbox"},
            },
        }

    def _workflow(self, run_id: int) -> dict[str, Any]:
        related = [
            check
            for check in self.check_runs
            if f"/actions/runs/{run_id}/" in str(check.get("details_url"))
        ]
        if not related:
            return {}
        observed = related[0]
        latest_by_name: dict[str, dict[str, Any]] = {}
        for check in related:
            name = str(check["name"])
            previous = latest_by_name.get(name)
            if previous is None or int(check["id"]) > int(previous["id"]):
                latest_by_name[name] = check
        workflow_conclusion = (
            "success"
            if all(
                check.get("conclusion") == "success"
                for check in latest_by_name.values()
            )
            else "failure"
        )
        workflow = {
            "id": run_id,
            "workflow_id": 77,
            "run_attempt": 1,
            "check_suite_id": observed["check_suite"]["id"],
            "head_sha": observed["head_sha"],
            "head_branch": next(
                (str(self.pull["head"]["ref"]) for _ in [0] if self.pull is not None),
                "sciguard/unknown",
            ),
            "event": "pull_request",
            "status": "completed",
            "conclusion": workflow_conclusion,
            "path": ".github/workflows/sciguard-repair.yml",
            "html_url": (f"https://github.com/acme/sciguard-sandbox/actions/runs/{run_id}"),
            "repository": {"full_name": "acme/sciguard-sandbox"},
            "head_repository": {"full_name": "acme/sciguard-sandbox"},
            "pull_requests": observed["pull_requests"],
        }
        workflow.update(self.workflow_overrides.get(run_id, {}))
        return workflow

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> GitHubResponse:
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/heads/sciguard%2F" in path:
            if not self.branch_created:
                return GitHubResponse(404, {"message": "Not Found"})
            return GitHubResponse(
                200,
                {"object": {"type": "commit", "sha": self.branch_head_sha}},
            )
        if method == "GET" and path.endswith("/git/ref/heads/main"):
            self.base_lookup_count += 1
            if (
                self.move_base_on_lookup is not None
                and self.base_lookup_count >= self.move_base_on_lookup
            ):
                self.base_sha = MOVED_BASE_SHA
            return GitHubResponse(
                200,
                {"object": {"type": "commit", "sha": self.base_sha}},
            )
        if method == "GET" and path.endswith(
            (f"/git/commits/{BASE_SHA}", f"/git/commits/{MOVED_BASE_SHA}")
        ):
            return GitHubResponse(200, {"tree": {"sha": BASE_TREE_SHA}})
        if method == "GET" and path.endswith(f"/git/commits/{self.branch_head_sha}"):
            return GitHubResponse(
                200,
                {
                    "message": self.commit_message,
                    "tree": {"sha": TREE_SHA},
                    "parents": [{"sha": self.commit_parent_sha}],
                },
            )
        if method == "GET" and "/contents/pipeline/normalize.py?" in path:
            source = (
                "def normalize_tg(value: float, unit: str) -> float:\n"
                "    # v1 trusted the destination column label and silently copied mixed units.\n"
                "    return float(value)\n"
            )
            return GitHubResponse(
                200,
                {
                    "encoding": "base64",
                    "content": base64.b64encode(source.encode()).decode(),
                },
            )
        if method == "POST" and path.endswith("/git/blobs"):
            assert body is not None
            decoded = base64.b64decode(body["content"]).decode()
            self.blob_contents.append(decoded)
            blob_sha = self._blob_sha(decoded)
            self.blobs[blob_sha] = decoded
            return GitHubResponse(201, {"sha": blob_sha})
        if method == "POST" and path.endswith("/git/trees"):
            assert body is not None
            assert body["base_tree"] == BASE_TREE_SHA
            self.tree_entries = body["tree"]
            return GitHubResponse(201, {"sha": TREE_SHA})
        if method == "POST" and path.endswith("/git/commits"):
            assert body is not None
            assert body["tree"] == TREE_SHA
            assert body["parents"] == [BASE_SHA]
            assert "SciGuard-Bundle:" in body["message"]
            self.commit_message = body["message"]
            self.commit_parent_sha = body["parents"][0]
            return GitHubResponse(201, {"sha": HEAD_SHA})
        if method == "POST" and path.endswith("/git/refs"):
            assert body is not None
            assert body["ref"].startswith("refs/heads/sciguard/")
            assert body["sha"] == HEAD_SHA
            self.branch_created = True
            if self.lose_ref_response_once:
                self.lose_ref_response_once = False
                return GitHubResponse(503, {"message": "upstream timeout"})
            return GitHubResponse(201, {"ref": body["ref"]})
        if method == "POST" and path.endswith("/pulls"):
            assert body is not None
            assert "SciGuard-Bundle:" in body["body"]
            if self.fail_pull_before_create_once:
                self.fail_pull_before_create_once = False
                return GitHubResponse(503, {"message": "temporary outage"})
            self.pull = self._pull_payload(body)
            if self.lose_pull_response_once:
                self.lose_pull_response_once = False
                return GitHubResponse(503, {"message": "upstream timeout"})
            return GitHubResponse(201, self.pull)
        if method == "GET" and "/pulls?state=all" in path:
            return GitHubResponse(200, [self.pull] if self.pull else [])
        if method == "GET" and path.endswith("/pulls/17"):
            return GitHubResponse(
                200,
                self.pull or {"message": "Not Found"},
            )
        if method == "GET" and "/compare/" in path:
            files = [
                {
                    "filename": entry["path"],
                    "status": "modified" if entry["path"] == "pipeline/normalize.py" else "added",
                    "sha": self.compare_file_sha_overrides.get(
                        entry["path"],
                        entry["sha"],
                    ),
                }
                for entry in self.tree_entries
            ]
            return GitHubResponse(
                200,
                {
                    "status": "ahead",
                    "ahead_by": 1,
                    "behind_by": 0,
                    "total_commits": 1,
                    "commits": [{"sha": self.branch_head_sha}],
                    "files": files,
                },
            )
        if method == "GET" and path.endswith("/check-runs?filter=latest&per_page=100"):
            return GitHubResponse(
                200,
                {"total_count": len(self.check_runs), "check_runs": self.check_runs},
            )
        if method == "GET" and "/actions/runs/" in path:
            run_id = int(path.rsplit("/", 1)[-1])
            workflow = self._workflow(run_id)
            return GitHubResponse(200 if workflow else 404, workflow)
        raise AssertionError(f"unexpected GitHub call: {method} {path}")


def test_github_publisher_creates_idempotent_commit_and_pull_request() -> None:
    transport = FakeGitHub()
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )

    receipt = publisher.publish(_bundle())
    repeated = publisher.publish(_bundle())
    published = attach_change_receipt(_bundle(), receipt)

    assert receipt == repeated
    assert receipt.provider == "GITHUB"
    assert receipt.status == "PULL_REQUEST_OPEN"
    assert receipt.base_commit_sha == BASE_SHA
    assert receipt.commit_sha == HEAD_SHA
    assert receipt.pull_request_number == 17
    assert receipt.remote_url == "https://github.com/acme/sciguard-sandbox/pull/17"
    assert published.status is RepairStatus.PUBLISHED
    assert any("class UnitContractError" in content for content in transport.blob_contents)
    assert {entry["path"] for entry in transport.tree_entries} == set(receipt.changed_files)
    assert len(transport.tree_entries) == 5
    assert sum(path.endswith("/pulls") for _, path in transport.calls) == 1


def test_github_publisher_resumes_branch_after_pr_creation_failure() -> None:
    transport = FakeGitHub()
    transport.fail_pull_before_create_once = True
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )

    with pytest.raises(ChangePublicationError, match="returned 503"):
        publisher.publish(_bundle())

    assert transport.branch_created
    assert transport.pull is None
    assert sum(path.endswith("/git/commits") for _, path in transport.calls) == 1
    assert sum(path.endswith("/git/refs") for _, path in transport.calls) == 1

    recovered = publisher.publish(_bundle())

    assert recovered.commit_sha == HEAD_SHA
    assert recovered.pull_request_number == 17
    assert sum(path.endswith("/git/commits") for _, path in transport.calls) == 1
    assert sum(path.endswith("/git/refs") for _, path in transport.calls) == 1
    assert sum(path.endswith("/pulls") for _, path in transport.calls) == 2


def test_github_publisher_recovers_unknown_success_pr_response() -> None:
    transport = FakeGitHub()
    transport.lose_pull_response_once = True

    receipt = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).publish(_bundle())

    assert receipt.pull_request_number == 17
    assert sum(path.endswith("/pulls") for _, path in transport.calls) == 1
    assert any("/pulls?state=all" in path for _, path in transport.calls)


def test_github_publisher_recovers_unknown_success_ref_response() -> None:
    transport = FakeGitHub()
    transport.lose_ref_response_once = True

    receipt = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).publish(_bundle())

    assert receipt.commit_sha == HEAD_SHA
    assert transport.branch_created
    assert sum(path.endswith("/git/refs") for _, path in transport.calls) == 1
    assert sum(path.endswith("/pulls") for _, path in transport.calls) == 1


@pytest.mark.parametrize("move_on_lookup", [2, 3])
def test_github_publisher_detects_base_branch_toctou_before_public_ref(
    move_on_lookup: int,
) -> None:
    transport = FakeGitHub()
    transport.move_base_on_lookup = move_on_lookup

    with pytest.raises(ChangePublicationError, match="base branch moved"):
        GitHubChangePublisher(
            repository="acme/sciguard-sandbox",
            transport=transport,
        ).publish(_bundle())

    assert not transport.branch_created
    assert not any(path.endswith("/git/refs") for _, path in transport.calls)
    assert not any(path.endswith("/pulls") for _, path in transport.calls)


def test_github_publisher_rejects_pr_created_against_moved_base() -> None:
    transport = FakeGitHub()
    transport.pull_base_sha = MOVED_BASE_SHA

    with pytest.raises(ChangePublicationError, match="exact repair revision"):
        GitHubChangePublisher(
            repository="acme/sciguard-sandbox",
            transport=transport,
        ).publish(_bundle())

    assert transport.branch_created
    assert transport.pull is not None


def test_existing_branch_content_tamper_fails_closed() -> None:
    transport = FakeGitHub()
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )
    receipt = publisher.publish(_bundle())
    transport.compare_file_sha_overrides[receipt.changed_files[0]] = "f" * 40

    with pytest.raises(ChangePublicationError, match="content does not match"):
        publisher.publish(_bundle())


def test_github_publisher_rejects_target_mismatch_before_remote_mutation() -> None:
    transport = FakeGitHub()
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )

    with pytest.raises(ChangePublicationError, match="does not match"):
        publisher.publish(_bundle(target_repository="https://github.com/acme/other"))

    assert transport.calls == []


def test_existing_unbound_branch_fails_closed() -> None:
    transport = FakeGitHub()
    transport.branch_created = True
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )

    with pytest.raises(ChangePublicationError, match="not bound"):
        publisher.publish(_bundle())


def _check_run(
    run_id: int,
    name: str,
    *,
    conclusion: str = "success",
    head_sha: str = HEAD_SHA,
    app_slug: str = "github-actions",
    workflow_run_id: int | None = None,
    check_suite_id: int | None = None,
) -> dict[str, Any]:
    repair_branch = default_branch(_bundle())
    workflow_run_id = workflow_run_id or run_id
    check_suite_id = check_suite_id or 1000 + run_id
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "app": {"id": 15368, "slug": app_slug},
        # GitHub's list-check-runs payload embeds the suite ID; the workflow
        # run lookup supplies the authoritative suite-to-head binding.
        "check_suite": {"id": check_suite_id},
        "pull_requests": [
            {
                "number": 17,
                "head": {"sha": head_sha, "ref": repair_branch},
                "base": {"sha": BASE_SHA, "ref": "main"},
            }
        ],
        "status": "completed",
        "conclusion": conclusion,
        "details_url": (
            "https://github.com/acme/sciguard-sandbox/actions/runs/"
            f"{workflow_run_id}/job/{2000 + run_id}"
        ),
        "started_at": "2026-07-27T00:00:00Z",
        "completed_at": "2026-07-27T00:00:03Z",
    }


def test_github_check_runs_bind_three_remote_results_to_exact_commit() -> None:
    transport = FakeGitHub()
    publisher = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )
    proposal = _bundle()
    change = publisher.publish(proposal)
    published = attach_change_receipt(proposal, change)
    transport.check_runs = [
        _check_run(
            9,
            "scientific-unit-contract",
            conclusion="failure",
            workflow_run_id=700,
            check_suite_id=1700,
        ),
        _check_run(
            10,
            "scientific-unit-contract",
            workflow_run_id=700,
            check_suite_id=1700,
        ),
        _check_run(
            11,
            "scientific-decision-regression",
            workflow_run_id=700,
            check_suite_id=1700,
        ),
        _check_run(
            12,
            "preserved-branch-non-regression",
            workflow_run_id=700,
            check_suite_id=1700,
        ),
    ]

    receipt = GitHubCheckRunVerifier(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).verify(published, change)
    verified = attach_verification_receipt(published, receipt)

    assert receipt.provider == "GITHUB_CHECK_RUNS"
    assert receipt.status is CheckExecutionStatus.PASS
    assert receipt.source_tree_clean is None
    assert [check.external_run_id for check in receipt.checks] == [10, 11, 12]
    assert all(check.details_url.startswith("https://github.com/") for check in receipt.checks)
    assert all(check.duration_ms == 3000 for check in receipt.checks)
    assert len({check.result_sha256 for check in receipt.checks}) == 3
    assert {check.external_app_id for check in receipt.checks} == {15368}
    assert {check.external_app_slug for check in receipt.checks} == {"github-actions"}
    assert {check.workflow_id for check in receipt.checks} == {77}
    assert {check.workflow_run_id for check in receipt.checks} == {700}
    assert {check.workflow_run_attempt for check in receipt.checks} == {1}
    assert {check.workflow_path for check in receipt.checks} == {
        ".github/workflows/sciguard-repair.yml"
    }
    assert {check.workflow_conclusion for check in receipt.checks} == {"success"}
    assert {check.check_suite_id for check in receipt.checks} == {1700}
    assert verified.status is RepairStatus.VERIFIED


def test_github_verification_model_requires_complete_provider_provenance() -> None:
    transport, change, published = _published_with_checks()
    receipt = GitHubCheckRunVerifier(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).verify(published, change)
    payload = receipt.model_dump(mode="python")
    payload["checks"][0]["workflow_run_id"] = None

    with pytest.raises(ValueError, match="complete provider provenance"):
        receipt.__class__.model_validate(payload)


def test_github_check_runs_fail_closed_on_missing_or_failed_result() -> None:
    transport = FakeGitHub()
    proposal = _bundle()
    change = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).publish(proposal)
    published = attach_change_receipt(proposal, change)
    verifier = GitHubCheckRunVerifier(
        repository="acme/sciguard-sandbox",
        transport=transport,
    )

    transport.check_runs = [
        _check_run(20, "scientific-unit-contract"),
        _check_run(21, "scientific-decision-regression"),
    ]
    with pytest.raises(VerificationError, match="missing"):
        verifier.verify(published, change)

    transport.check_runs.append(
        _check_run(
            22,
            "preserved-branch-non-regression",
            conclusion="failure",
        )
    )
    failed = verifier.verify(published, change)
    assert failed.status is CheckExecutionStatus.FAIL
    with pytest.raises(ValueError, match="failed"):
        attach_verification_receipt(published, failed)


def _published_with_checks() -> tuple[FakeGitHub, Any, Any]:
    transport = FakeGitHub()
    proposal = _bundle()
    change = GitHubChangePublisher(
        repository="acme/sciguard-sandbox",
        transport=transport,
    ).publish(proposal)
    published = attach_change_receipt(proposal, change)
    transport.check_runs = [
        _check_run(30, "scientific-unit-contract"),
        _check_run(31, "scientific-decision-regression"),
        _check_run(32, "preserved-branch-non-regression"),
    ]
    return transport, change, published


def test_github_check_runs_reject_spoofed_app_identity() -> None:
    transport, change, published = _published_with_checks()
    transport.check_runs[0]["app"] = {"id": 999, "slug": "github-actions"}

    with pytest.raises(VerificationError, match="untrusted GitHub App"):
        GitHubCheckRunVerifier(
            repository="acme/sciguard-sandbox",
            transport=transport,
        ).verify(published, change)


@pytest.mark.parametrize(
    ("override", "value"),
    [
        ("path", ".github/workflows/untrusted.yml"),
        ("event", "pull_request_target"),
        ("check_suite_id", 999999),
        ("head_sha", "8" * 40),
        ("head_branch", "attacker/branch"),
        ("workflow_id", 999),
        ("run_attempt", 0),
        ("pull_requests", [{"number": 999}]),
    ],
)
def test_github_check_runs_reject_wrong_workflow_provenance(
    override: str,
    value: Any,
) -> None:
    transport, change, published = _published_with_checks()
    transport.workflow_overrides[30] = {override: value}
    verifier_options = {"trusted_workflow_id": 77} if override == "workflow_id" else {}

    with pytest.raises(VerificationError, match="workflow provenance"):
        GitHubCheckRunVerifier(
            repository="acme/sciguard-sandbox",
            transport=transport,
            **verifier_options,
        ).verify(published, change)


@pytest.mark.parametrize("mutation", ["branch", "base", "pull"])
def test_github_check_runs_revalidate_mutable_publication_state(
    mutation: str,
) -> None:
    transport, change, published = _published_with_checks()
    if mutation == "branch":
        transport.branch_head_sha = "8" * 40
    elif mutation == "base":
        transport.base_sha = MOVED_BASE_SHA
    else:
        assert transport.pull is not None
        transport.pull["state"] = "closed"

    with pytest.raises(
        VerificationError,
        match="no longer matches|base branch moved",
    ):
        GitHubCheckRunVerifier(
            repository="acme/sciguard-sandbox",
            transport=transport,
        ).verify(published, change)


def test_github_check_runs_reject_external_details_url() -> None:
    transport, change, published = _published_with_checks()
    transport.check_runs[0]["details_url"] = (
        "https://evil.example/acme/sciguard-sandbox/actions/runs/30/job/2030"
    )

    with pytest.raises(VerificationError, match="outside the trusted repository"):
        GitHubCheckRunVerifier(
            repository="acme/sciguard-sandbox",
            transport=transport,
        ).verify(published, change)


def test_repair_sandbox_workflow_exposes_exact_read_only_check_names() -> None:
    workflow = (
        ROOT / "examples" / "repair_sandbox" / ".github" / "workflows" / "sciguard-repair.yml"
    ).read_text(encoding="utf-8")

    assert "contents: read" in workflow
    assert "scientific-unit-contract" in workflow
    assert "scientific-decision-regression" in workflow
    assert "preserved-branch-non-regression" in workflow
    assert "pull_request_target" not in workflow
    assert "secrets." not in workflow
