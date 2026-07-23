"""Minimal FastAPI surface: health, run, state, SSE, recovery, reset, replay."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.run_store import (
    ActiveRunError,
    RunManifest,
    RunMode,
    RunStatus,
    RunStore,
    RunStoreIntegrityError,
    current_source_commit,
    current_worktree_dirty,
)
from api.runtime import DEFAULT_SYMPTOM, SciGuardRuntime
from core.events import Event
from core.recovery import RecoveryCheck, RecoveryResult
from core.reset import ResetReceipt

ROOT = Path(__file__).resolve().parents[1]


class HealthResponse(BaseModel):
    status: str
    dependencies: dict[str, dict[str, str]]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str | None = Field(default=None, min_length=1, max_length=64)
    symptom: str = Field(default=DEFAULT_SYMPTOM, min_length=10, max_length=800)


class RunView(BaseModel):
    manifest: RunManifest
    state_url: str
    events_url: str


class EventFrame(BaseModel):
    mode: RunMode
    event: Event


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[RecoveryCheck] = Field(min_length=1, max_length=20)
    human_approved: bool = False


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: str = Field(min_length=1, max_length=64)


class ResetResponse(BaseModel):
    incident_id: str
    metadata: ResetReceipt
    run_files_deleted: bool


def _not_found(exc: FileNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _view(manifest: RunManifest, *, replay: bool = False) -> RunView:
    prefix = "/api/replays" if replay else "/api/runs"
    return RunView(
        manifest=manifest,
        state_url=f"{prefix}/{manifest.incident_id}",
        events_url=f"{prefix}/{manifest.incident_id}/events",
    )


def create_app(
    *,
    run_root: str | Path | None = None,
    replay_root: str | Path | None = None,
    runtime: Any | None = None,
    source_commit: str | None = None,
    source_worktree_dirty: bool | None = None,
) -> FastAPI:
    run_root = Path(run_root or os.environ.get("SCIGUARD_RUN_ROOT", ROOT / ".sciguard/runs"))
    replay_root = Path(
        replay_root or os.environ.get("SCIGUARD_REPLAY_ROOT", ROOT / "examples/replays")
    )
    commit = source_commit or current_source_commit(ROOT)
    dirty = (
        source_worktree_dirty
        if source_worktree_dirty is not None
        else current_worktree_dirty(ROOT)
    )
    run_store = RunStore(
        run_root,
        source_commit=commit,
        source_worktree_dirty=dirty,
    )
    replay_store = RunStore(
        replay_root,
        source_commit=commit,
        source_worktree_dirty=dirty,
    )
    runtime = runtime or SciGuardRuntime()

    app = FastAPI(
        title="SciGuard Event API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.run_store = run_store
    app.state.replay_store = replay_store
    app.state.runtime = runtime
    allowed_origins = os.environ.get(
        "SCIGUARD_UI_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.get("/healthz", response_model=HealthResponse)
    def healthz() -> HealthResponse:
        dependencies = runtime.health(run_store)
        overall = (
            "ok"
            if all(item.get("status") == "ok" for item in dependencies.values())
            else "degraded"
        )
        return HealthResponse(status=overall, dependencies=dependencies)

    @app.post("/api/runs", response_model=RunView, status_code=status.HTTP_202_ACCEPTED)
    def start_run(request: RunRequest) -> RunView:
        incident_id = request.incident_id or f"inc-{uuid.uuid4().hex[:12]}"
        try:
            manifest = run_store.start_run(incident_id)
        except (ActiveRunError, FileExistsError, ValueError) as exc:
            raise _conflict(exc) from exc

        def execute() -> None:
            try:
                result = runtime.run_live(
                    incident_id,
                    request.symptom,
                    run_store.append_event,
                )
                run_store.finish_run(
                    incident_id,
                    incident_state=result.incident_state,
                    datahub_backend=result.datahub_backend,
                )
            except Exception as exc:  # noqa: BLE001 - failure is persisted for UI/replay
                run_store.fail_run(incident_id, f"{type(exc).__name__}: {exc}")

        threading.Thread(
            target=execute,
            name=f"sciguard-{incident_id}",
            daemon=True,
        ).start()
        return _view(manifest)

    @app.get("/api/runs/{incident_id}", response_model=RunView)
    def get_run(incident_id: str) -> RunView:
        try:
            return _view(run_store.get_manifest(incident_id))
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(FileNotFoundError(str(exc))) from exc

    async def event_stream(
        request: Request,
        store: RunStore,
        incident_id: str,
        mode: RunMode,
        after_sequence: int,
    ):
        cursor = after_sequence
        idle_cycles = 0
        while True:
            if await request.is_disconnected():
                return
            try:
                manifest = store.get_manifest(incident_id)
                events = store.get_events(incident_id)
            except FileNotFoundError as exc:
                yield "event: error\ndata: " + json.dumps({"detail": str(exc)}) + "\n\n"
                return
            for event in events:
                if event.sequence <= cursor:
                    continue
                frame = EventFrame(mode=mode, event=event)
                yield (
                    f"id: {event.sequence}\n"
                    "event: sciguard-event\n"
                    f"data: {frame.model_dump_json()}\n\n"
                )
                cursor = event.sequence
                idle_cycles = 0
            if manifest.status in {RunStatus.COMPLETED, RunStatus.FAILED}:
                return
            idle_cycles += 1
            if idle_cycles >= 20:
                yield ": heartbeat\n\n"
                idle_cycles = 0
            await asyncio.sleep(0.05)

    @app.get("/api/runs/{incident_id}/events", response_class=StreamingResponse)
    def stream_live_events(
        request: Request,
        incident_id: str,
        after_sequence: int = Query(default=-1, ge=-1),
    ) -> StreamingResponse:
        try:
            run_store.get_manifest(incident_id)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(FileNotFoundError(str(exc))) from exc
        if after_sequence == -1 and request.headers.get("last-event-id"):
            try:
                after_sequence = int(request.headers["last-event-id"])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
        return StreamingResponse(
            event_stream(
                request,
                run_store,
                incident_id,
                RunMode.LIVE,
                after_sequence,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/runs/{incident_id}/recovery", response_model=RecoveryResult)
    def recover(incident_id: str, request: RecoveryRequest) -> RecoveryResult:
        try:
            manifest = run_store.get_manifest(incident_id)
            if manifest.status is not RunStatus.COMPLETED:
                raise ActiveRunError("recovery requires a completed live run")
            return runtime.recover(
                run_store,
                incident_id,
                request.checks,
                human_approved=request.human_approved,
            )
        except FileNotFoundError as exc:
            raise _not_found(exc) from exc
        except (ActiveRunError, LookupError, ValueError, RunStoreIntegrityError) as exc:
            raise _conflict(exc) from exc

    @app.post("/api/reset", response_model=ResetResponse)
    def reset(request: ResetRequest) -> ResetResponse:
        try:
            manifest = run_store.get_manifest(request.incident_id)
            if manifest.status is RunStatus.RUNNING:
                raise ActiveRunError("cannot reset an active run")
            receipt = runtime.reset(request.incident_id)
            run_store.delete_run(request.incident_id)
            return ResetResponse(
                incident_id=request.incident_id,
                metadata=receipt,
                run_files_deleted=True,
            )
        except FileNotFoundError as exc:
            raise _not_found(exc) from exc
        except (ActiveRunError, LookupError, ValueError) as exc:
            raise _conflict(exc) from exc

    @app.get("/api/replays/{incident_id}", response_model=RunView)
    def get_replay(incident_id: str) -> RunView:
        try:
            manifest = replay_store.get_manifest(incident_id)
            replay_store.get_events(incident_id)
            if manifest.mode is not RunMode.RECORDED_REPLAY:
                raise RunStoreIntegrityError("bundle is not labelled RECORDED_REPLAY")
            return _view(manifest, replay=True)
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(FileNotFoundError(str(exc))) from exc
        except RunStoreIntegrityError as exc:
            raise _conflict(exc) from exc

    @app.get("/api/replays/{incident_id}/events", response_class=StreamingResponse)
    def stream_replay_events(
        request: Request,
        incident_id: str,
        after_sequence: int = Query(default=-1, ge=-1),
    ) -> StreamingResponse:
        try:
            manifest = replay_store.get_manifest(incident_id)
            replay_store.get_events(incident_id)
            if manifest.mode is not RunMode.RECORDED_REPLAY:
                raise RunStoreIntegrityError("bundle is not labelled RECORDED_REPLAY")
        except (FileNotFoundError, ValueError) as exc:
            raise _not_found(FileNotFoundError(str(exc))) from exc
        except RunStoreIntegrityError as exc:
            raise _conflict(exc) from exc
        if after_sequence == -1 and request.headers.get("last-event-id"):
            try:
                after_sequence = int(request.headers["last-event-id"])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc
        return StreamingResponse(
            event_stream(
                request,
                replay_store,
                incident_id,
                RunMode.RECORDED_REPLAY,
                after_sequence,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
