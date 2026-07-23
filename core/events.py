"""Auditable incident events and JSONL persistence.

This module is deliberately independent of the detector, lineage, policy, and
write-back implementations.  It records what those components observed or did
without changing their deterministic results.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from collections.abc import Callable
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventActor(str, Enum):
    SYSTEM = "SYSTEM"
    SENTINEL = "SENTINEL"
    COORDINATOR = "COORDINATOR"
    SCIENTIFIC_INVESTIGATOR = "SCIENTIFIC_INVESTIGATOR"
    REALITY_CHECKER = "REALITY_CHECKER"
    POLICY_GUARDIAN = "POLICY_GUARDIAN"
    ENFORCER = "ENFORCER"
    RECOVERY_CONTROLLER = "RECOVERY_CONTROLLER"


class EventType(str, Enum):
    SIGNAL_DETECTED = "SIGNAL_DETECTED"
    ESCALATION_DECIDED = "ESCALATION_DECIDED"
    INCIDENT_CREATED = "INCIDENT_CREATED"
    STATE_TRANSITIONED = "STATE_TRANSITIONED"
    HYPOTHESIS_PROPOSED = "HYPOTHESIS_PROPOSED"
    EVIDENCE_OBSERVED = "EVIDENCE_OBSERVED"
    HYPOTHESIS_RESOLVED = "HYPOTHESIS_RESOLVED"
    IMPACT_MAPPED = "IMPACT_MAPPED"
    POLICY_DECIDED = "POLICY_DECIDED"
    ENFORCEMENT_APPLIED = "ENFORCEMENT_APPLIED"
    NOTIFICATION_RECORDED = "NOTIFICATION_RECORDED"
    RECOVERY_CHECKED = "RECOVERY_CHECKED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"


class Event(BaseModel):
    """One immutable fact in an incident's append-only event stream."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    incident_id: str
    sequence: int = Field(ge=0)
    timestamp: datetime
    actor: EventActor
    event_type: EventType
    summary: str
    evidence_ids: list[str]
    duration_ms: int = Field(ge=0)
    payload: dict[str, Any]

    @field_validator("event_id", "incident_id", "summary")
    @classmethod
    def _nonempty_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("timestamp")
    @classmethod
    def _utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("timestamp must be timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @field_validator("evidence_ids")
    @classmethod
    def _unique_evidence_ids(cls, value: list[str]) -> list[str]:
        if any(not evidence_id.strip() for evidence_id in value):
            raise ValueError("evidence IDs must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("evidence IDs must be unique")
        return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def stable_evidence_id(kind: str, payload: Any) -> str:
    """Return a content-derived evidence ID suitable for cross-event links."""

    canonical = json.dumps(
        _jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


def validate_event_stream(events: Iterable[Event]) -> list[Event]:
    """Validate the ordering and identity invariants of one incident stream."""

    stream = list(events)
    if not stream:
        return stream
    incident_ids = {event.incident_id for event in stream}
    if len(incident_ids) != 1:
        raise ValueError("an event stream must contain exactly one incident")
    expected = list(range(len(stream)))
    actual = [event.sequence for event in stream]
    if actual != expected:
        raise ValueError(f"event sequence must be contiguous from zero: {actual}")
    event_ids = [event.event_id for event in stream]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("event IDs must be unique")
    return stream


def load_events(path: str | Path) -> list[Event]:
    """Load and validate one JSONL incident stream."""

    source = Path(path)
    events: list[Event] = []
    for line_number, raw_line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            events.append(Event.model_validate_json(raw_line))
        except ValueError as exc:
            raise ValueError(f"invalid event on JSONL line {line_number}: {exc}") from exc
    return validate_event_stream(events)


class EventRecorder:
    """Append-only recorder that assigns deterministic sequence-based IDs."""

    def __init__(
        self,
        incident_id: str,
        events: Iterable[Event] = (),
        on_event: Callable[[Event], None] | None = None,
    ) -> None:
        if not incident_id.strip():
            raise ValueError("incident_id must not be empty")
        self.incident_id = incident_id.strip()
        self._events = validate_event_stream(events)
        if self._events and self._events[0].incident_id != self.incident_id:
            raise ValueError("loaded events do not match recorder incident_id")
        self._on_event = on_event

    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def emit(
        self,
        *,
        actor: EventActor,
        event_type: EventType,
        summary: str,
        evidence_ids: Iterable[str] = (),
        duration_ms: int = 0,
        payload: dict[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> Event:
        sequence = len(self._events)
        event = Event(
            event_id=f"{self.incident_id}:{sequence:04d}:{event_type.value}",
            incident_id=self.incident_id,
            sequence=sequence,
            timestamp=timestamp or datetime.now(timezone.utc),
            actor=actor,
            event_type=event_type,
            summary=summary,
            evidence_ids=list(evidence_ids),
            duration_ms=duration_ms,
            payload=_jsonable(payload or {}),
        )
        self._events.append(event)
        if self._on_event is not None:
            self._on_event(event)
        return event

    def save_jsonl(self, path: str | Path) -> Path:
        """Atomically persist the stream so a partial write is never replayed."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        validate_event_stream(self._events)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            for event in self._events:
                handle.write(event.model_dump_json())
                handle.write("\n")
        os.replace(temporary, destination)
        return destination

    @classmethod
    def from_jsonl(cls, path: str | Path) -> EventRecorder:
        events = load_events(path)
        if not events:
            raise ValueError("cannot create an incident recorder from an empty stream")
        return cls(events[0].incident_id, events)
