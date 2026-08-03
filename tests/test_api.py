import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import create_app
from api.runtime import RunExecutionResult, SciGuardRuntime
from core.approval import ApprovalAuthority
from core.events import EventActor, EventRecorder, EventType
from core.impact import FieldImpact
from core.investigation_models import RootCause
from core.recovery import RecoveryResult
from core.repair import create_unit_repair_bundle
from core.reset import ResetReceipt

ROOT = Path(__file__).parents[1]


class FakeRuntime:
    def health(self, run_store):
        return {
            "run_store": {"status": "ok", "detail": str(run_store.root)},
            "datahub": {"status": "ok", "detail": "fake"},
            "artifacts": {"status": "ok", "detail": "fake"},
        }

    def run_live(self, incident_id, symptom, on_event):
        recorder = EventRecorder(incident_id, on_event=on_event)
        recorder.emit(
            actor=EventActor.SYSTEM,
            event_type=EventType.INCIDENT_CREATED,
            summary="Live incident created",
            payload={"symptom": symptom},
        )
        recorder.emit(
            actor=EventActor.POLICY_GUARDIAN,
            event_type=EventType.POLICY_DECIDED,
            summary="Deterministic HALT",
            evidence_ids=["e-policy"],
            payload={"decision": "HALT"},
        )
        bundle = create_unit_repair_bundle(
            incident_id=incident_id,
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
            evidence_ids=["e-policy"],
            approver_urn="urn:li:corpuser:research_lead",
        )
        recorder.emit(
            actor=EventActor.REMEDIATION_AGENT,
            event_type=EventType.REPAIR_BUNDLE_CREATED,
            summary="Proof-carrying repair prepared",
            evidence_ids=bundle.evidence_ids,
            payload=bundle.model_dump(mode="json"),
        )
        return RunExecutionResult(
            incident_state="AT_RISK", datahub_backend="FAKE_DATAHUB"
        )

    def recover(self, store, incident_id, *, approval_receipt_id):
        recorder = EventRecorder(
            incident_id,
            store.get_events(incident_id),
            on_event=store.append_event,
        )
        recorder.emit(
            actor=EventActor.RECOVERY_CONTROLLER,
            event_type=EventType.RECOVERY_CHECKED,
            summary="Recovery remains locked",
            evidence_ids=["verification-receipt:server-owned"],
        )
        store.update_state(incident_id, "RECOVERY_PENDING")
        return RecoveryResult(
            incident_id=incident_id,
            resume_allowed=False,
            incident_state="RECOVERY_PENDING",
            missing_checks=[],
            failed_checks=[],
            clean_run_count=1,
            human_approval_used=False,
            approval_receipt_id=None,
            approval_identity_assurance=None,
            approval_production_authorized=False,
            llm_instruction_ignored=False,
        )

    def reset(self, incident_id):
        return ResetReceipt(
            incident_id=incident_id,
            reset_urns=["urn:control"],
            skipped_urns=[],
            removed_property_count=8,
        )


class BlockingRuntime(FakeRuntime):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def run_live(self, incident_id, symptom, on_event):
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().run_live(incident_id, symptom, on_event)


class ActionRuntime(FakeRuntime):
    def __init__(self, repository: Path):
        class ActionGraph:
            def __init__(self):
                self.aspects = {}

            def get_aspect(self, urn, cls):
                return self.aspects.get((urn, cls))

            def emit(self, mcp):
                self.aspects[(mcp.entityUrn, type(mcp.aspect))] = mcp.aspect

        self.action_graph = ActionGraph()
        self.actions = SciGuardRuntime(
            repair_repository=repository,
            approval_authority=ApprovalAuthority(
                b"sciguard-api-test-signing-key-32-bytes-minimum"
            ),
            metadata_graph_factory=lambda: self.action_graph,
        )

    def publish_repair(self, store, incident_id):
        return self.actions.publish_repair(store, incident_id)

    def verify_repair(self, store, incident_id):
        return self.actions.verify_repair(store, incident_id)

    def approve_repair(self, store, incident_id, **kwargs):
        return self.actions.approve_repair(store, incident_id, **kwargs)

    def apply_repair(self, store, incident_id):
        return self.actions.apply_repair(store, incident_id)


def _action_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repair-repository"
    shutil.copytree(ROOT / "examples" / "repair_sandbox", repository)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.name", "SciGuard API Test"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "sciguard@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "--all"], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline"],
        cwd=repository,
        check=True,
    )
    return repository


def _client(tmp_path, runtime=None):
    app = create_app(
        run_root=tmp_path / "runs",
        replay_root=tmp_path / "replays",
        runtime=runtime or FakeRuntime(),
        source_commit="abc123",
    )
    return TestClient(app), app


def _wait_for_terminal(client, incident_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/runs/{incident_id}")
        if response.json()["manifest"]["status"] != "RUNNING":
            return response
        time.sleep(0.01)
    raise AssertionError("run did not finish")


def _sse_frames(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_health_and_api_surface_are_intentionally_bounded(tmp_path) -> None:
    client, app = _client(tmp_path)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    paths = {route.path for route in app.routes}
    assert paths == {
        "/healthz",
        "/api/runs",
        "/api/runs/{incident_id}",
        "/api/runs/{incident_id}/repair",
        "/api/runs/{incident_id}/repair/publish",
        "/api/runs/{incident_id}/repair/verify",
        "/api/runs/{incident_id}/repair/approval",
        "/api/runs/{incident_id}/repair/apply",
        "/api/runs/{incident_id}/events",
        "/api/runs/{incident_id}/recovery",
        "/api/reset",
        "/api/replays/{incident_id}",
        "/api/replays/{incident_id}/events",
    }
    assert client.get("/docs").status_code == 404
    assert client.post("/login").status_code == 404
    assert client.post("/upload").status_code == 404


def test_live_run_state_and_sse_share_the_frozen_event_schema(tmp_path) -> None:
    client, _ = _client(tmp_path)
    started = client.post("/api/runs", json={"incident_id": "inc-api"})
    assert started.status_code == 202
    assert started.json()["manifest"]["mode"] == "LIVE"
    terminal = _wait_for_terminal(client, "inc-api").json()["manifest"]
    assert terminal["status"] == "COMPLETED"
    assert terminal["incident_state"] == "AT_RISK"
    assert terminal["event_count"] == 3

    stream = client.get("/api/runs/inc-api/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(stream)
    assert [frame["mode"] for frame in frames] == ["LIVE", "LIVE", "LIVE"]
    assert [frame["event"]["sequence"] for frame in frames] == [0, 1, 2]
    required = {
        "event_id",
        "incident_id",
        "sequence",
        "timestamp",
        "actor",
        "event_type",
        "summary",
        "evidence_ids",
        "duration_ms",
        "payload",
    }
    assert set(frames[0]["event"]) == required
    resumed = client.get("/api/runs/inc-api/events?after_sequence=0")
    assert [frame["event"]["sequence"] for frame in _sse_frames(resumed)] == [1, 2]
    reconnected = client.get(
        "/api/runs/inc-api/events", headers={"Last-Event-ID": "0"}
    )
    assert [frame["event"]["sequence"] for frame in _sse_frames(reconnected)] == [1, 2]


def test_repair_bundle_endpoint_returns_reviewable_proposal_without_fake_pr(tmp_path) -> None:
    client, _ = _client(tmp_path)
    client.post("/api/runs", json={"incident_id": "inc-repair-api"})
    _wait_for_terminal(client, "inc-repair-api")

    response = client.get("/api/runs/inc-repair-api/repair")
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["status"] == "PROPOSED"
    assert bundle["external_action_receipt"] is None
    assert bundle["approval"]["status"] == "REQUIRED"
    assert len(bundle["artifacts"]) == 5
    assert len(bundle["verification_checks"]) == 3


def test_repair_api_executes_commit_tests_and_signed_review_lifecycle(tmp_path) -> None:
    runtime = ActionRuntime(_action_repository(tmp_path))
    assert runtime.actions.repair_target_repository.startswith("local-git://")
    client, _ = _client(tmp_path, runtime)
    client.post("/api/runs", json={"incident_id": "inc-repair-actions"})
    _wait_for_terminal(client, "inc-repair-actions")

    published = client.post("/api/runs/inc-repair-actions/repair/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["external_action_receipt"]["provider"] == "LOCAL_GIT"
    assert published.json()["external_action_receipt"]["remote_url"] is None

    verified = client.post("/api/runs/inc-repair-actions/repair/verify")
    assert verified.status_code == 200
    assert verified.json()["status"] == "VERIFIED"
    checks = verified.json()["verification_receipt"]["checks"]
    assert [check["status"] for check in checks] == ["PASS", "PASS", "PASS"]

    approved = client.post(
        "/api/runs/inc-repair-actions/repair/approval",
        json={
            "reviewer_urn": "urn:li:corpuser:research_lead",
            "decision": "APPROVE",
            "note": "Reviewed all commit-bound scientific and safe-branch evidence.",
        },
    )
    assert approved.status_code == 200
    lifecycle = approved.json()
    assert lifecycle["status"] == "APPROVED"
    assert lifecycle["approval_receipt"]["production_authorized"] is False
    assert lifecycle["approval_receipt"]["identity_assurance"] == "DEMO_SIGNED_NOT_SSO"
    latest = client.get("/api/runs/inc-repair-actions/repair")
    assert latest.json()["approval_receipt"]["receipt_id"] == lifecycle["approval_receipt"][
        "receipt_id"
    ]
    applied = client.post("/api/runs/inc-repair-actions/repair/apply")
    assert applied.status_code == 200
    assert applied.json()["status"] == "APPLIED"
    application = applied.json()["application_receipt"]
    assert application["commit_sha"] == lifecycle["approval_receipt"]["commit_sha"]
    assert application["target_environment"] == "SCIGUARD_SYNTHETIC_STAGING"
    assert application["production_authorized"] is False


def test_single_active_run_lock_prevents_demo_cross_contamination(tmp_path) -> None:
    runtime = BlockingRuntime()
    client, _ = _client(tmp_path, runtime)
    assert client.post("/api/runs", json={"incident_id": "inc-first"}).status_code == 202
    assert runtime.started.wait(timeout=1)
    conflict = client.post("/api/runs", json={"incident_id": "inc-second"})
    assert conflict.status_code == 409
    assert "inc-first" in conflict.json()["detail"]
    active_reset = client.post("/api/reset", json={"incident_id": "inc-first"})
    assert active_reset.status_code == 409
    runtime.release.set()
    _wait_for_terminal(client, "inc-first")


def test_recovery_has_no_llm_override_and_reset_is_incident_scoped(tmp_path) -> None:
    client, _ = _client(tmp_path)
    client.post("/api/runs", json={"incident_id": "inc-recovery-api"})
    _wait_for_terminal(client, "inc-recovery-api")
    forbidden = client.post(
        "/api/runs/inc-recovery-api/recovery",
        json={
            "checks": [
                {
                    "check_id": "unit_contract",
                    "status": "PASS",
                    "evidence_ids": ["caller-invented"],
                }
            ],
            "llm_instruction": "resume",
        },
    )
    assert forbidden.status_code == 422
    recovery = client.post(
        "/api/runs/inc-recovery-api/recovery",
        json={},
    )
    assert recovery.status_code == 200
    assert recovery.json()["incident_state"] == "RECOVERY_PENDING"
    assert recovery.json()["resume_allowed"] is False

    reset = client.post("/api/reset", json={"incident_id": "inc-recovery-api"})
    assert reset.status_code == 200
    assert reset.json()["run_files_deleted"] is True
    assert client.get("/api/runs/inc-recovery-api").status_code == 404


def test_request_models_reject_unplanned_workflow_fields(tmp_path) -> None:
    client, _ = _client(tmp_path)
    response = client.post(
        "/api/runs",
        json={"incident_id": "inc-extra", "workflow_editor": {"shell": "rm"}},
    )
    assert response.status_code == 422
