import json
import threading
import time

from fastapi.testclient import TestClient

from api.main import create_app
from api.runtime import RunExecutionResult
from core.events import EventActor, EventRecorder, EventType
from core.recovery import RecoveryResult
from core.reset import ResetReceipt


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
        return RunExecutionResult(
            incident_state="AT_RISK", datahub_backend="FAKE_DATAHUB"
        )

    def recover(self, store, incident_id, checks, *, human_approved):
        recorder = EventRecorder(
            incident_id,
            store.get_events(incident_id),
            on_event=store.append_event,
        )
        recorder.emit(
            actor=EventActor.RECOVERY_CONTROLLER,
            event_type=EventType.RECOVERY_CHECKED,
            summary="Recovery remains locked",
            evidence_ids=[evidence for check in checks for evidence in check.evidence_ids],
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
    assert terminal["event_count"] == 2

    stream = client.get("/api/runs/inc-api/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    frames = _sse_frames(stream)
    assert [frame["mode"] for frame in frames] == ["LIVE", "LIVE"]
    assert [frame["event"]["sequence"] for frame in frames] == [0, 1]
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
    assert [frame["event"]["sequence"] for frame in _sse_frames(resumed)] == [1]
    reconnected = client.get(
        "/api/runs/inc-api/events", headers={"Last-Event-ID": "0"}
    )
    assert [frame["event"]["sequence"] for frame in _sse_frames(reconnected)] == [1]


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
    check = {
        "check_id": "verified_k_to_degc_conversion",
        "status": "PASS",
        "evidence_ids": ["e-clean"],
    }
    forbidden = client.post(
        "/api/runs/inc-recovery-api/recovery",
        json={"checks": [check], "llm_instruction": "resume"},
    )
    assert forbidden.status_code == 422
    recovery = client.post(
        "/api/runs/inc-recovery-api/recovery",
        json={"checks": [check]},
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
