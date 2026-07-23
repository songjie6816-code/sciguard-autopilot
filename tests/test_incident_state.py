import json
from pathlib import Path

import pytest

from core.events import EventActor, EventRecorder, EventType
from core.incident_state import (
    ALLOWED_TRANSITIONS,
    IncidentRun,
    IncidentState,
    IncidentStateMachine,
    replay_state,
)


def test_states_and_transitions_match_frozen_contract() -> None:
    contract = json.loads(Path("evaluation/scenarios.json").read_text(encoding="utf-8"))[
        "contract"
    ]
    assert [state.value for state in IncidentState] == contract["incident_states"]
    actual = {(source.value, target.value) for source, target in ALLOWED_TRANSITIONS}
    assert actual == {tuple(edge) for edge in contract["transitions"]}


def test_legal_risk_and_recovery_path_replays_to_same_state(tmp_path) -> None:
    recorder = EventRecorder("inc-risk")
    machine = IncidentStateMachine(recorder)
    for target, actor in (
        (IncidentState.DETECTED, EventActor.COORDINATOR),
        (IncidentState.INVESTIGATING, EventActor.SCIENTIFIC_INVESTIGATOR),
        (IncidentState.AT_RISK, EventActor.POLICY_GUARDIAN),
        (IncidentState.RECOVERY_PENDING, EventActor.RECOVERY_CONTROLLER),
        (IncidentState.RESOLVED, EventActor.RECOVERY_CONTROLLER),
    ):
        machine.transition(target, actor=actor)

    path = tmp_path / "risk.jsonl"
    recorder.save_jsonl(path)
    assert machine.state is IncidentState.RESOLVED
    assert replay_state(EventRecorder.from_jsonl(path).events) is IncidentState.RESOLVED


def test_quarantine_path_is_legal() -> None:
    recorder = EventRecorder("inc-quarantine")
    machine = IncidentStateMachine(recorder)
    machine.transition(IncidentState.DETECTED, actor=EventActor.COORDINATOR)
    machine.transition(IncidentState.INVESTIGATING, actor=EventActor.COORDINATOR)
    machine.transition(IncidentState.QUARANTINED, actor=EventActor.ENFORCER)
    machine.transition(IncidentState.RECOVERY_PENDING, actor=EventActor.RECOVERY_CONTROLLER)
    assert machine.state is IncidentState.RECOVERY_PENDING


def test_illegal_transition_fails_without_mutation_or_event() -> None:
    recorder = EventRecorder("inc-illegal")
    machine = IncidentStateMachine(recorder)
    before = list(recorder.events)

    with pytest.raises(ValueError, match="Illegal incident transition"):
        machine.transition(IncidentState.AT_RISK, actor=EventActor.POLICY_GUARDIAN)

    assert machine.state is IncidentState.HEALTHY
    assert recorder.events == before


def test_replay_rejects_tampered_from_state() -> None:
    recorder = EventRecorder("inc-tampered")
    machine = IncidentStateMachine(recorder)
    machine.transition(IncidentState.DETECTED, actor=EventActor.COORDINATOR)
    tampered = recorder.events[0].model_copy(
        update={"payload": {"from_state": "AT_RISK", "to_state": "DETECTED"}}
    )
    with pytest.raises(ValueError, match="claims from_state"):
        replay_state([tampered])


def test_incident_run_accepts_signal_events_then_starts_once_and_replays(tmp_path) -> None:
    run = IncidentRun("inc-signal")
    run.recorder.emit(
        actor=EventActor.SENTINEL,
        event_type=EventType.SIGNAL_DETECTED,
        summary="signal",
    )
    run.start("P-204 moved from rank 18 to rank 1", payload={"signal_id": "signal:1"})
    with pytest.raises(ValueError, match="only be started once"):
        run.start("duplicate")

    path = tmp_path / "incident.jsonl"
    run.save_jsonl(path)
    replay = IncidentRun.from_jsonl(path)
    assert replay.events == run.events
    assert replay.state is IncidentState.DETECTED
