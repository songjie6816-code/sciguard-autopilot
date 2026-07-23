import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from core.events import (
    Event,
    EventActor,
    EventRecorder,
    EventType,
    load_events,
    validate_event_stream,
)


def test_event_enums_and_fields_match_frozen_contract() -> None:
    contract = json.loads(Path("evaluation/scenarios.json").read_text(encoding="utf-8"))[
        "contract"
    ]["event"]

    assert list(Event.model_fields) == contract["required_fields"]
    assert [actor.value for actor in EventActor] == contract["actors"]
    assert [event.value for event in EventType] == contract["event_types"]


def test_event_rejects_non_utc_time_negative_duration_and_duplicate_evidence() -> None:
    base = {
        "event_id": "inc-1:0000:INCIDENT_CREATED",
        "incident_id": "inc-1",
        "sequence": 0,
        "timestamp": datetime.now(timezone.utc),
        "actor": EventActor.SYSTEM,
        "event_type": EventType.INCIDENT_CREATED,
        "summary": "Incident opened",
        "evidence_ids": ["e-1"],
        "duration_ms": 0,
        "payload": {},
    }
    with pytest.raises(ValidationError):
        Event(**{**base, "timestamp": datetime.now()})
    with pytest.raises(ValidationError):
        Event(**{**base, "timestamp": datetime.now(timezone(timedelta(hours=8)))})
    with pytest.raises(ValidationError):
        Event(**{**base, "duration_ms": -1})
    with pytest.raises(ValidationError):
        Event(**{**base, "evidence_ids": ["e-1", "e-1"]})


def test_recorder_saves_and_replays_exact_event_order(tmp_path) -> None:
    recorder = EventRecorder("inc-1")
    fixed = datetime(2026, 7, 21, 0, 0, tzinfo=timezone.utc)
    first = recorder.emit(
        actor=EventActor.SYSTEM,
        event_type=EventType.INCIDENT_CREATED,
        summary="Incident opened",
        timestamp=fixed,
        payload={"symptom": "rank changed"},
    )
    second = recorder.emit(
        actor=EventActor.REALITY_CHECKER,
        event_type=EventType.EVIDENCE_OBSERVED,
        summary="Metadata drift observed",
        evidence_ids=["e-drift"],
        timestamp=fixed,
        duration_ms=3,
        payload={"change_count": 1},
    )

    assert first.sequence == 0
    assert second.sequence == 1
    assert first.event_id == "inc-1:0000:INCIDENT_CREATED"

    path = tmp_path / "incident.jsonl"
    recorder.save_jsonl(path)
    replayed = load_events(path)
    assert replayed == [first, second]
    assert EventRecorder.from_jsonl(path).events == [first, second]


def test_stream_validation_rejects_gaps_and_mixed_incidents() -> None:
    recorder = EventRecorder("inc-1")
    event = recorder.emit(
        actor=EventActor.SYSTEM,
        event_type=EventType.INCIDENT_CREATED,
        summary="Incident opened",
    )
    with pytest.raises(ValueError, match="contiguous"):
        validate_event_stream([event.model_copy(update={"sequence": 2})])
    with pytest.raises(ValueError, match="one incident"):
        validate_event_stream(
            [event, event.model_copy(update={"incident_id": "inc-2", "sequence": 1})]
        )
