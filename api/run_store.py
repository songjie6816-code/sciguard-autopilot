"""Incident-isolated, integrity-checked JSON/JSONL run persistence."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.events import Event, EventRecorder, load_events, validate_event_stream

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MANIFEST_NAME = "manifest.json"
EVENTS_NAME = "events.jsonl"


class RunMode(str, Enum):
    LIVE = "LIVE"
    RECORDED_REPLAY = "RECORDED_REPLAY"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EventValidation(BaseModel):
    event_schema: str = "core.events.Event@1"
    single_incident: bool = True
    contiguous_sequence: bool = True
    unique_event_ids: bool = True


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    incident_id: str
    mode: RunMode
    status: RunStatus
    incident_state: str
    datahub_backend: str
    source_commit: str
    source_worktree_dirty: bool
    generated_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    event_count: int = Field(ge=0)
    events_sha256: str
    validation: EventValidation
    source_run_id: str | None = None
    error: str | None = None


class ActiveRunError(RuntimeError):
    pass


class RunStoreIntegrityError(RuntimeError):
    pass


def current_source_commit(workspace: str | Path) -> str:
    override = os.environ.get("SCIGUARD_SOURCE_COMMIT")
    if override:
        return override.strip()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(workspace),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def current_worktree_dirty(workspace: str | Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=normal"],
            cwd=Path(workspace),
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return True


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    os.replace(temporary, path)


class RunStore:
    """Persist one directory per incident and enforce one active live run."""

    def __init__(
        self,
        root: str | Path,
        *,
        source_commit: str,
        source_worktree_dirty: bool = False,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.source_commit = source_commit
        self.source_worktree_dirty = source_worktree_dirty
        self._lock = threading.RLock()
        self._active_incident: str | None = None
        for manifest_path in self.root.glob(f"*/{MANIFEST_NAME}"):
            try:
                manifest = RunManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except ValueError:
                continue
            if manifest.mode is RunMode.LIVE and manifest.status is RunStatus.RUNNING:
                self._active_incident = manifest.incident_id
                break

    @staticmethod
    def validate_id(incident_id: str) -> str:
        if not _SAFE_ID.fullmatch(incident_id):
            raise ValueError(
                "incident_id must be 1-64 safe characters: letters, digits, dot, underscore, dash"
            )
        return incident_id

    def _directory(self, incident_id: str) -> Path:
        return self.root / self.validate_id(incident_id)

    def _manifest_path(self, incident_id: str) -> Path:
        return self._directory(incident_id) / MANIFEST_NAME

    def _events_path(self, incident_id: str) -> Path:
        return self._directory(incident_id) / EVENTS_NAME

    @staticmethod
    def _digest(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _write_manifest(self, manifest: RunManifest) -> None:
        _atomic_text(
            self._manifest_path(manifest.incident_id),
            manifest.model_dump_json(indent=2) + "\n",
        )

    def start_run(self, incident_id: str, *, datahub_backend: str = "PENDING") -> RunManifest:
        incident_id = self.validate_id(incident_id)
        with self._lock:
            if self._active_incident is not None:
                raise ActiveRunError(
                    f"incident {self._active_incident} is already running"
                )
            directory = self._directory(incident_id)
            if directory.exists():
                raise FileExistsError(f"incident already exists: {incident_id}")
            directory.mkdir(parents=True)
            _atomic_text(self._events_path(incident_id), "")
            now = datetime.now(timezone.utc)
            manifest = RunManifest(
                incident_id=incident_id,
                mode=RunMode.LIVE,
                status=RunStatus.RUNNING,
                incident_state="HEALTHY",
                datahub_backend=datahub_backend,
                source_commit=self.source_commit,
                source_worktree_dirty=self.source_worktree_dirty,
                generated_at=now,
                updated_at=now,
                event_count=0,
                events_sha256=self._digest(self._events_path(incident_id)),
                validation=EventValidation(),
            )
            self._write_manifest(manifest)
            self._active_incident = incident_id
            return manifest

    def get_manifest(self, incident_id: str) -> RunManifest:
        path = self._manifest_path(incident_id)
        if not path.is_file():
            raise FileNotFoundError(f"incident not found: {incident_id}")
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def get_events(self, incident_id: str) -> list[Event]:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            path = self._events_path(incident_id)
            if not path.is_file():
                raise RunStoreIntegrityError("event file is missing")
            digest = self._digest(path)
            if digest != manifest.events_sha256:
                raise RunStoreIntegrityError("event file digest does not match manifest")
            events = load_events(path)
            if len(events) != manifest.event_count:
                raise RunStoreIntegrityError("event count does not match manifest")
            return events

    def append_event(self, event: Event) -> None:
        with self._lock:
            manifest = self.get_manifest(event.incident_id)
            if manifest.mode is not RunMode.LIVE or manifest.status is RunStatus.FAILED:
                raise RunStoreIntegrityError("events cannot be appended to this run")
            events = self.get_events(event.incident_id)
            if event.sequence != len(events):
                raise RunStoreIntegrityError(
                    f"expected event sequence {len(events)}, got {event.sequence}"
                )
            EventRecorder(event.incident_id, [*events, event]).save_jsonl(
                self._events_path(event.incident_id)
            )
            now = datetime.now(timezone.utc)
            updated = manifest.model_copy(
                update={
                    "updated_at": now,
                    "event_count": len(events) + 1,
                    "events_sha256": self._digest(self._events_path(event.incident_id)),
                }
            )
            self._write_manifest(updated)

    def finish_run(
        self,
        incident_id: str,
        *,
        incident_state: str,
        datahub_backend: str,
    ) -> RunManifest:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            validate_event_stream(self.get_events(incident_id))
            now = datetime.now(timezone.utc)
            updated = manifest.model_copy(
                update={
                    "status": RunStatus.COMPLETED,
                    "incident_state": incident_state,
                    "datahub_backend": datahub_backend,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._write_manifest(updated)
            if self._active_incident == incident_id:
                self._active_incident = None
            return updated

    def fail_run(self, incident_id: str, error: str) -> RunManifest:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            now = datetime.now(timezone.utc)
            updated = manifest.model_copy(
                update={
                    "status": RunStatus.FAILED,
                    "updated_at": now,
                    "completed_at": now,
                    "error": error[:2_000],
                }
            )
            self._write_manifest(updated)
            if self._active_incident == incident_id:
                self._active_incident = None
            return updated

    def update_state(self, incident_id: str, incident_state: str) -> RunManifest:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            updated = manifest.model_copy(
                update={
                    "incident_state": incident_state,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._write_manifest(updated)
            return updated

    def export_replay(self, incident_id: str, destination_root: str | Path) -> RunManifest:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            events = self.get_events(incident_id)
            if manifest.status is not RunStatus.COMPLETED:
                raise ValueError("only completed live runs can be exported")
            destination = RunStore(
                destination_root,
                source_commit=manifest.source_commit,
                source_worktree_dirty=manifest.source_worktree_dirty,
            )
            replay_directory = destination._directory(incident_id)
            if replay_directory.exists() and any(replay_directory.iterdir()):
                raise FileExistsError(f"replay already exists: {incident_id}")
            replay_directory.mkdir(parents=True, exist_ok=True)
            EventRecorder(incident_id, events).save_jsonl(destination._events_path(incident_id))
            replay = manifest.model_copy(
                update={
                    "mode": RunMode.RECORDED_REPLAY,
                    "source_run_id": incident_id,
                    "events_sha256": destination._digest(
                        destination._events_path(incident_id)
                    ),
                }
            )
            destination._write_manifest(replay)
            return replay

    def delete_run(self, incident_id: str) -> None:
        with self._lock:
            manifest = self.get_manifest(incident_id)
            if manifest.status is RunStatus.RUNNING:
                raise ActiveRunError("cannot reset an active run")
            directory = self._directory(incident_id)
            for name in (MANIFEST_NAME, EVENTS_NAME):
                path = directory / name
                if path.exists():
                    path.unlink()
            directory.rmdir()
