"""Strict incident lifecycle transitions and replay validation."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Iterable

from core.events import Event, EventActor, EventRecorder, EventType, validate_event_stream


class IncidentState(str, Enum):
    HEALTHY = "HEALTHY"
    DETECTED = "DETECTED"
    INVESTIGATING = "INVESTIGATING"
    AT_RISK = "AT_RISK"
    QUARANTINED = "QUARANTINED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RESOLVED = "RESOLVED"


ALLOWED_TRANSITIONS = frozenset(
    {
        (IncidentState.HEALTHY, IncidentState.DETECTED),
        (IncidentState.DETECTED, IncidentState.RESOLVED),
        (IncidentState.DETECTED, IncidentState.INVESTIGATING),
        (IncidentState.INVESTIGATING, IncidentState.AT_RISK),
        (IncidentState.INVESTIGATING, IncidentState.QUARANTINED),
        (IncidentState.INVESTIGATING, IncidentState.RESOLVED),
        (IncidentState.AT_RISK, IncidentState.QUARANTINED),
        (IncidentState.AT_RISK, IncidentState.RECOVERY_PENDING),
        (IncidentState.QUARANTINED, IncidentState.RECOVERY_PENDING),
        (IncidentState.RECOVERY_PENDING, IncidentState.AT_RISK),
        (IncidentState.RECOVERY_PENDING, IncidentState.QUARANTINED),
        (IncidentState.RECOVERY_PENDING, IncidentState.RESOLVED),
    }
)


def _assert_legal(source: IncidentState, target: IncidentState) -> None:
    if (source, target) not in ALLOWED_TRANSITIONS:
        raise ValueError(f"Illegal incident transition: {source.value} -> {target.value}")


class IncidentStateMachine:
    def __init__(
        self,
        recorder: EventRecorder,
        initial: IncidentState = IncidentState.HEALTHY,
    ) -> None:
        self.recorder = recorder
        self.state = initial

    def transition(
        self,
        target: IncidentState,
        *,
        actor: EventActor,
        summary: str | None = None,
        evidence_ids: Iterable[str] = (),
        duration_ms: int = 0,
        payload: dict | None = None,
    ) -> Event:
        source = self.state
        _assert_legal(source, target)
        transition_payload = dict(payload or {})
        transition_payload.update(from_state=source.value, to_state=target.value)
        event = self.recorder.emit(
            actor=actor,
            event_type=EventType.STATE_TRANSITIONED,
            summary=summary or f"Incident moved from {source.value} to {target.value}",
            evidence_ids=evidence_ids,
            duration_ms=duration_ms,
            payload=transition_payload,
        )
        self.state = target
        return event


def replay_state(
    events: Iterable[Event], initial: IncidentState = IncidentState.HEALTHY
) -> IncidentState:
    """Rebuild state while rejecting tampered or illegal transition events."""

    state = initial
    for event in validate_event_stream(events):
        if event.event_type is not EventType.STATE_TRANSITIONED:
            continue
        try:
            claimed_source = IncidentState(event.payload["from_state"])
            target = IncidentState(event.payload["to_state"])
        except (KeyError, ValueError) as exc:
            raise ValueError(f"invalid state transition payload in {event.event_id}") from exc
        if claimed_source is not state:
            raise ValueError(
                f"transition {event.event_id} claims from_state {claimed_source.value}, "
                f"but replay state is {state.value}"
            )
        _assert_legal(state, target)
        state = target
    return state


class IncidentRun:
    """Own one immutable event stream and its strictly validated lifecycle."""

    def __init__(
        self,
        incident_id: str,
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        self.recorder = EventRecorder(incident_id, on_event=on_event)
        self.machine = IncidentStateMachine(self.recorder)

    @property
    def incident_id(self) -> str:
        return self.recorder.incident_id

    @property
    def events(self) -> list[Event]:
        return self.recorder.events

    @property
    def state(self) -> IncidentState:
        return self.machine.state

    def start(self, symptom: str, *, payload: dict | None = None) -> None:
        if self.state is not IncidentState.HEALTHY or any(
            event.event_type is EventType.INCIDENT_CREATED for event in self.events
        ):
            raise ValueError("an incident run can only be started once from HEALTHY")
        event_payload = dict(payload or {})
        event_payload["symptom"] = symptom
        self.recorder.emit(
            actor=EventActor.SYSTEM,
            event_type=EventType.INCIDENT_CREATED,
            summary="Incident created from an escalated detection signal",
            payload=event_payload,
        )
        self.machine.transition(
            IncidentState.DETECTED,
            actor=EventActor.COORDINATOR,
            summary="Sentinel escalated the signal for investigation",
        )

    def transition(
        self,
        target: IncidentState,
        *,
        actor: EventActor,
        summary: str | None = None,
        evidence_ids: Iterable[str] = (),
        payload: dict | None = None,
    ) -> Event:
        return self.machine.transition(
            target,
            actor=actor,
            summary=summary,
            evidence_ids=evidence_ids,
            payload=payload,
        )

    def save_jsonl(self, path: str | Path) -> Path:
        return self.recorder.save_jsonl(path)

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "IncidentRun":
        recorder = EventRecorder.from_jsonl(path)
        instance = cls(recorder.incident_id)
        instance.recorder = recorder
        instance.machine = IncidentStateMachine(
            recorder,
            initial=replay_state(recorder.events),
        )
        return instance
