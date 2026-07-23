"""Composition root for the real flagship run, recovery, health, and reset."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn
from pydantic import BaseModel

from api.run_store import RunStore
from core.coordinator import Coordinator
from core.enforcement import enforce
from core.events import Event, EventActor, EventRecorder, EventType, stable_evidence_id
from core.impact import build_policy_contexts, trace_field_impact, trace_initial_scope
from core.incident_state import IncidentRun, IncidentState
from core.narration import NarrationService
from core.pipeline_controller import LocalPipelineController
from core.policy_engine import CatalogStatus, decide
from core.profiles import load_profile
from core.recovery import RecoveryCheck, RecoveryController, RecoveryResult
from core.reset import ResetReceipt, reset_incident_metadata
from core.sentinel import (
    ChangeKind,
    Snapshot,
    assess,
    build_signal,
    decide_escalation,
    detect_changes,
)
from datahub_client import metadata_reader
from datahub_client.backends import SdkReader, open_reader

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "synthetic_polymer"
PLATFORM = "polymer_rnd"
ENV = "PROD"
SOURCE_URN = make_dataset_urn(PLATFORM, "raw_polymer_experiments", ENV)
BATCH_URN = make_dataset_urn(PLATFORM, "instrument_batch_B042", ENV)
CONTROL_URN = make_dataset_urn(PLATFORM, "candidate_ranking_report", ENV)
DEFAULT_SYMPTOM = (
    "Candidate P-204 moved from rank #18 to #1 after last night's batch. "
    "No pipeline failed. Investigate before the morning selection meeting."
)


class RunExecutionResult(BaseModel):
    incident_state: str
    datahub_backend: str


class SciGuardRuntime:
    """Single composition root: Sentinel detection through controlled recovery."""

    def run_live(
        self,
        incident_id: str,
        symptom: str,
        on_event: Callable[[Event], None],
    ) -> RunExecutionResult:
        run = IncidentRun(incident_id, on_event=on_event)
        backend = open_reader()
        write_graph = backend.graph if isinstance(backend, SdkReader) else metadata_reader.connect()
        backend_label = (
            "DATAHUB_SDK"
            if isinstance(backend, SdkReader)
            else "DATAHUB_MCP_CONTEXT_SDK_FIELD_LINEAGE_WRITE"
        )
        datahub_provenance = (
            {
                "required_component": "DATAHUB_SDK",
                "decision_inputs_via_sdk": [
                    "schema",
                    "units",
                    "dataset_lineage",
                    "fine_grained_lineage",
                    "ownership",
                    "governance_context",
                    "metadata_write_back",
                ],
            }
            if isinstance(backend, SdkReader)
            else backend.capability_receipt()
        )
        try:
            profile = load_profile("polymer")
            fields = {
                field["path"]: field.get("nativeType") or ""
                for field in backend.get_schema_fields(SOURCE_URN)
            }
            observed_units = backend.get_units(SOURCE_URN)
            batch_context = backend.get_asset_context(BATCH_URN)
            expected_unit = batch_context["properties"].get("expected_tg_unit")
            if not fields or not expected_unit:
                raise RuntimeError("Sentinel could not read the scientific contract")
            trusted_units = dict(observed_units)
            trusted_units["tg_value"] = expected_unit
            changes = detect_changes(
                Snapshot(fields=fields, units=trusted_units),
                Snapshot(fields=fields, units=observed_units),
            )
            initial_scope = trace_initial_scope(backend, SOURCE_URN)
            signal = build_signal(
                SOURCE_URN,
                assess(profile, changes, initial_scope),
            )
            escalation = decide_escalation(profile, signal)
            run.recorder.emit(
                actor=EventActor.SENTINEL,
                event_type=EventType.SIGNAL_DETECTED,
                summary=(
                    f"Sentinel detected {len(signal.changes)} scientific contract "
                    f"change(s) across {len(signal.initial_scope) + 1} review assets"
                ),
                evidence_ids=signal.evidence_ids,
                payload={
                    **signal.model_dump(mode="json"),
                    "datahub_context_provenance": datahub_provenance,
                    "decision_effect": (
                        "DataHub unit contract and directed lineage determine whether "
                        "the signal reaches the deterministic escalation gate"
                    ),
                },
            )
            run.recorder.emit(
                actor=EventActor.SENTINEL,
                event_type=EventType.ESCALATION_DECIDED,
                summary=(
                    "Decision-critical path reached; deep investigation required"
                    if escalation.escalate
                    else "Signal closed by deterministic escalation policy"
                ),
                evidence_ids=escalation.evidence_ids,
                payload=escalation.model_dump(mode="json"),
            )
            run.start(
                symptom,
                payload={
                    "signal_id": signal.signal_id,
                    "escalation_reason": escalation.reason_code,
                },
            )
            if not escalation.escalate:
                run.transition(
                    IncidentState.RESOLVED,
                    actor=EventActor.SENTINEL,
                    summary="Signal resolved without opening a controlled incident",
                    evidence_ids=escalation.evidence_ids,
                )
                return RunExecutionResult(
                    incident_state=IncidentState.RESOLVED.value,
                    datahub_backend=backend_label,
                )
            run.transition(
                IncidentState.INVESTIGATING,
                actor=EventActor.COORDINATOR,
                summary="Bounded flagship investigation started",
                evidence_ids=signal.evidence_ids,
            )
            coordinator = Coordinator(recorder=run.recorder)
            case = coordinator.open_case(incident_id, symptom, signal)
            report = coordinator.investigate_case(
                case,
                backend=backend,
                data_dir=DATA_DIR,
                platform=PLATFORM,
                env=ENV,
            )
            if not report.root_cause_confirmed or report.root_cause is None:
                raise RuntimeError("flagship evidence did not confirm the bounded root cause")

            source_fields = [
                change.field
                for change in signal.changes
                if change.kind is ChangeKind.UNIT_CHANGE
            ]
            impact = trace_field_impact(backend, SOURCE_URN, source_fields)
            impact_payload = {
                **impact.model_dump(mode="json"),
                "datahub_context_provenance": datahub_provenance,
                "decision_effect": (
                    "Fine-grained DataHub lineage defines the affected and preserved "
                    "cones consumed by deterministic policy"
                ),
            }
            impact_evidence = stable_evidence_id("field-impact", impact_payload)
            run.recorder.emit(
                actor=EventActor.SCIENTIFIC_INVESTIGATOR,
                event_type=EventType.IMPACT_MAPPED,
                summary=(
                    f"Field lineage selected {len(impact.affected_urns)} affected and "
                    f"{len(impact.unaffected_urns)} preserved assets"
                ),
                evidence_ids=[impact_evidence],
                payload=impact_payload,
            )
            contexts = build_policy_contexts(
                backend,
                impact,
                additional_affected_urns=[BATCH_URN],
            )
            root_evidence_ids = list(
                dict.fromkeys(
                    evidence_id
                    for resolution in report.resolutions
                    for evidence_id in resolution.evidence_ids
                )
            )
            plan = decide(
                profile,
                incident_id,
                contexts,
                root_cause_evidence_ids=root_evidence_ids,
                recorder=run.recorder,
            )
            narrative = NarrationService(client=None).run(
                case=case,
                report=report,
                plan=plan,
                events=run.events,
                extra_context={
                    "signal_id": signal.signal_id,
                    "escalation_reason": escalation.reason_code,
                },
            )
            run.recorder.emit(
                actor=EventActor.COORDINATOR,
                event_type=EventType.NOTIFICATION_RECORDED,
                summary="Evidence-linked incident narrative prepared",
                evidence_ids=root_evidence_ids,
                payload={
                    "source": narrative.source.value,
                    "public_summary": narrative.public_summary,
                    "prompt_sha256": narrative.prompt_snapshot.context_sha256,
                    "raw_data_rows": narrative.prompt_snapshot.raw_rows_included,
                    "policy_unchanged": narrative.policy_plan == plan,
                },
            )
            enforce(write_graph, plan, recorder=run.recorder)
            controller = LocalPipelineController(plan)
            publish_source = DATA_DIR / "candidate_ranking_after.csv"
            with tempfile.TemporaryDirectory(prefix=f"sciguard-{incident_id}-") as temp:
                output_dir = Path(temp)
                blocked_target = output_dir / "candidate_ranking_report.csv"
                blocked = controller.publish(
                    "candidate_ranking_report",
                    publish_source,
                    blocked_target,
                )
                if blocked.exit_code != 42 or blocked_target.exists():
                    raise RuntimeError("candidate report publish guard did not block")
                run.recorder.emit(
                    actor=EventActor.ENFORCER,
                    event_type=EventType.ENFORCEMENT_APPLIED,
                    summary="Local candidate ranking publication blocked with exit code 42",
                    evidence_ids=root_evidence_ids,
                    payload={
                        **blocked.model_dump(mode="json"),
                        "asset_name": "candidate_ranking_report",
                        "target_created": blocked_target.exists(),
                        "command": "publish candidate_ranking_report",
                    },
                )

                allowed_target = output_dir / "formulation_report.csv"
                allowed = controller.publish(
                    "formulation_report",
                    publish_source,
                    allowed_target,
                )
                if allowed.exit_code != 0 or not allowed_target.is_file():
                    raise RuntimeError("preserved formulation branch did not publish")
                run.recorder.emit(
                    actor=EventActor.ENFORCER,
                    event_type=EventType.ENFORCEMENT_APPLIED,
                    summary="Preserved formulation publication completed with exit code 0",
                    evidence_ids=root_evidence_ids,
                    payload={
                        **allowed.model_dump(mode="json"),
                        "asset_name": "formulation_report",
                        "target_created": allowed_target.is_file(),
                        "command": "publish formulation_report",
                    },
                )
            state = (
                IncidentState.QUARANTINED
                if any(
                    item.catalog_status is CatalogStatus.QUARANTINED
                    for item in plan.decisions
                )
                else IncidentState.AT_RISK
            )
            run.transition(
                state,
                actor=EventActor.ENFORCER,
                summary=f"Deterministic controls applied; incident is {state.value}",
                evidence_ids=root_evidence_ids,
            )
            return RunExecutionResult(
                incident_state=state.value,
                datahub_backend=backend_label,
            )
        finally:
            backend.close()

    def recover(
        self,
        store: RunStore,
        incident_id: str,
        checks: list[RecoveryCheck],
        *,
        human_approved: bool,
    ) -> RecoveryResult:
        events = store.get_events(incident_id)
        recorder = EventRecorder(
            incident_id,
            events,
            on_event=store.append_event,
        )
        graph = metadata_reader.connect()
        result = RecoveryController(
            graph,
            CONTROL_URN,
            load_profile("polymer"),
            recorder=recorder,
        ).evaluate(checks, human_approved=human_approved)
        store.update_state(incident_id, result.incident_state)
        return result

    def reset(self, incident_id: str) -> ResetReceipt:
        graph = metadata_reader.connect()
        return reset_incident_metadata(graph, CONTROL_URN, incident_id)

    @staticmethod
    def health(run_store: RunStore) -> dict[str, dict[str, str]]:
        dependencies: dict[str, dict[str, str]] = {
            "run_store": {
                "status": "ok" if os.access(run_store.root, os.W_OK) else "error",
                "detail": str(run_store.root),
            },
            "artifacts": {
                "status": "ok" if DATA_DIR.joinpath("raw_polymer_experiments.csv").is_file() else "error",
                "detail": str(DATA_DIR),
            },
        }
        try:
            graph = metadata_reader.connect()
            dependencies["datahub"] = {
                "status": "ok",
                "detail": str(graph.config.server),
            }
        except Exception as exc:  # noqa: BLE001 - health reports dependency degradation
            dependencies["datahub"] = {
                "status": "error",
                "detail": str(exc)[:300],
            }
        return dependencies
