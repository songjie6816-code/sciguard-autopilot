import json

import pytest

from api.run_store import (
    ActiveRunError,
    RunMode,
    RunStatus,
    RunStore,
    RunStoreIntegrityError,
)
from core.events import EventActor, EventRecorder, EventType


def _event(incident_id: str):
    return EventRecorder(incident_id).emit(
        actor=EventActor.SYSTEM,
        event_type=EventType.INCIDENT_CREATED,
        summary="Observed real run event",
    )


def test_run_store_isolates_incidents_and_enforces_one_active_run(tmp_path) -> None:
    store = RunStore(tmp_path / "runs", source_commit="abc123")
    manifest = store.start_run("inc-one")
    assert manifest.mode is RunMode.LIVE
    with pytest.raises(ActiveRunError, match="already running"):
        store.start_run("inc-two")

    store.append_event(_event("inc-one"))
    completed = store.finish_run(
        "inc-one", incident_state="AT_RISK", datahub_backend="DATAHUB_SDK"
    )
    assert completed.status is RunStatus.COMPLETED
    assert completed.event_count == 1
    assert store.get_events("inc-one")[0].summary == "Observed real run event"
    store.start_run("inc-two")


def test_manifest_detects_tampered_event_file(tmp_path) -> None:
    store = RunStore(tmp_path / "runs", source_commit="abc123")
    store.start_run("inc-tamper")
    store.append_event(_event("inc-tamper"))
    path = tmp_path / "runs" / "inc-tamper" / "events.jsonl"
    path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
    with pytest.raises(RunStoreIntegrityError, match="digest"):
        store.get_events("inc-tamper")


def test_replay_export_preserves_events_and_records_provenance(tmp_path) -> None:
    store = RunStore(
        tmp_path / "runs", source_commit="abc123", source_worktree_dirty=True
    )
    store.start_run("inc-replay")
    store.append_event(_event("inc-replay"))
    store.finish_run("inc-replay", incident_state="AT_RISK", datahub_backend="SDK")
    (tmp_path / "replays" / "inc-replay").mkdir(parents=True)

    replay = store.export_replay("inc-replay", tmp_path / "replays")
    replay_store = RunStore(tmp_path / "replays", source_commit="ignored")
    assert replay.mode is RunMode.RECORDED_REPLAY
    assert replay.source_commit == "abc123"
    assert replay.source_worktree_dirty is True
    assert replay.generated_at
    assert replay.validation.contiguous_sequence
    assert replay_store.get_events("inc-replay") == store.get_events("inc-replay")


def test_reset_deletes_only_explicit_terminal_incident_directory(tmp_path) -> None:
    store = RunStore(tmp_path / "runs", source_commit="abc123")
    store.start_run("inc-reset")
    store.finish_run("inc-reset", incident_state="DETECTED", datahub_backend="SDK")
    unrelated = tmp_path / "runs" / "do-not-touch.json"
    unrelated.write_text(json.dumps({"keep": True}), encoding="utf-8")

    store.delete_run("inc-reset")
    assert not (tmp_path / "runs" / "inc-reset").exists()
    assert unrelated.exists()


@pytest.mark.parametrize("incident_id", ["../escape", "/absolute", "bad id", ""])
def test_unsafe_incident_ids_are_rejected(tmp_path, incident_id) -> None:
    store = RunStore(tmp_path / "runs", source_commit="abc123")
    with pytest.raises(ValueError, match="safe characters"):
        store.start_run(incident_id)
