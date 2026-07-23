import json

from fastapi.testclient import TestClient

from api.main import create_app
from api.run_store import RunStore
from core.events import EventActor, EventRecorder, EventType
from tests.test_api import FakeRuntime


def _frames(response):
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_live_and_recorded_replay_have_event_parity_but_distinct_truth_labels(tmp_path) -> None:
    runs = RunStore(tmp_path / "runs", source_commit="source-commit")
    runs.start_run("inc-parity")
    recorder = EventRecorder("inc-parity", on_event=runs.append_event)
    recorder.emit(
        actor=EventActor.SYSTEM,
        event_type=EventType.INCIDENT_CREATED,
        summary="A real previously executed event",
    )
    recorder.emit(
        actor=EventActor.ENFORCER,
        event_type=EventType.ENFORCEMENT_APPLIED,
        summary="Real enforcement was applied",
        evidence_ids=["e-control"],
    )
    runs.finish_run("inc-parity", incident_state="AT_RISK", datahub_backend="SDK")
    runs.export_replay("inc-parity", tmp_path / "replays")

    app = create_app(
        run_root=tmp_path / "runs",
        replay_root=tmp_path / "replays",
        runtime=FakeRuntime(),
        source_commit="current-commit",
    )
    client = TestClient(app)
    live = _frames(client.get("/api/runs/inc-parity/events"))
    replay = _frames(client.get("/api/replays/inc-parity/events"))

    assert [frame["event"] for frame in live] == [frame["event"] for frame in replay]
    assert {frame["mode"] for frame in live} == {"LIVE"}
    assert {frame["mode"] for frame in replay} == {"RECORDED_REPLAY"}
    replay_manifest = client.get("/api/replays/inc-parity").json()["manifest"]
    assert replay_manifest["source_commit"] == "source-commit"
    assert replay_manifest["generated_at"]
    assert replay_manifest["validation"]["contiguous_sequence"] is True


def test_tampered_replay_is_rejected_before_rendering(tmp_path) -> None:
    runs = RunStore(tmp_path / "runs", source_commit="source-commit")
    runs.start_run("inc-tampered-replay")
    runs.finish_run(
        "inc-tampered-replay", incident_state="DETECTED", datahub_backend="SDK"
    )
    runs.export_replay("inc-tampered-replay", tmp_path / "replays")
    events = tmp_path / "replays" / "inc-tampered-replay" / "events.jsonl"
    events.write_text("{}\n", encoding="utf-8")
    client = TestClient(
        create_app(
            run_root=tmp_path / "runs",
            replay_root=tmp_path / "replays",
            runtime=FakeRuntime(),
            source_commit="current-commit",
        )
    )
    assert client.get("/api/replays/inc-tampered-replay").status_code == 409
