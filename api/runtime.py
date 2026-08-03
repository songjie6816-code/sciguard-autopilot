"""Composition root for the real flagship run, recovery, health, and reset."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn
from pydantic import BaseModel

from api.run_store import RunStore
from core.application import (
    LocalStagingApplicator,
    RepairApplicator,
    attach_application_receipt,
)
from core.approval import (
    ApprovalAuthority,
    ApprovalDecision,
    ApprovalReceipt,
    attach_approval_receipt,
)
from core.change_provider import (
    ChangePublisher,
    ChangeReceipt,
    LocalGitChangePublisher,
    attach_change_receipt,
)
from core.coordinator import Coordinator
from core.enforcement import enforce
from core.events import Event, EventActor, EventRecorder, EventType, stable_evidence_id
from core.github_provider import GitHubChangePublisher, UrllibGitHubTransport
from core.github_verification import GitHubCheckRunVerifier
from core.impact import build_policy_contexts, trace_field_impact, trace_initial_scope
from core.incident_state import IncidentRun, IncidentState
from core.narration import NarrationService
from core.pipeline_controller import LocalPipelineController
from core.policy_engine import CatalogStatus, decide
from core.profiles import load_profile
from core.recovery import (
    CheckStatus,
    HumanApprovalEvidence,
    RecoveryCheck,
    RecoveryController,
    RecoveryResult,
)
from core.repair import (
    NativeMLDecisionContext,
    RepairBundle,
    RepairStatus,
    create_unit_repair_bundle,
)
from core.reset import ResetReceipt, reset_incident_metadata
from core.sentinel import (
    ChangeKind,
    Snapshot,
    assess,
    build_signal,
    decide_escalation,
    detect_changes,
)
from core.verification import (
    CheckExecutionStatus,
    LocalVerificationEngine,
    VerificationEngine,
    VerificationReceipt,
    attach_verification_receipt,
)
from datahub_client import metadata_reader
from datahub_client.backends import SdkReader, open_reader
from datahub_client.incident_writer import (
    decision_log_urn,
    incident_urn,
    raise_incident,
    update_incident_status,
    write_decision_log,
)

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

    def __init__(
        self,
        *,
        repair_repository: str | Path | None = None,
        repair_target_repository: str | None = None,
        repair_target_base_revision: str = "main",
        change_publisher: ChangePublisher | None = None,
        verification_engine: VerificationEngine | None = None,
        repair_applicator: RepairApplicator | None = None,
        deployment_root: str | Path | None = None,
        approval_authority: ApprovalAuthority | None = None,
        metadata_graph_factory: Callable[[], object] | None = None,
    ) -> None:
        configured_repository = repair_repository or os.environ.get(
            "SCIGUARD_REPAIR_REPOSITORY"
        )
        self.repair_repository = (
            Path(configured_repository).resolve() if configured_repository else None
        )
        self.change_publisher = change_publisher
        self.verification_engine = verification_engine
        self.repair_applicator = repair_applicator
        self.deployment_root = Path(
            deployment_root or ROOT / ".sciguard" / "deployments"
        ).resolve()
        self.repair_target_repository = repair_target_repository or (
            "https://github.com/songjie6816-code/sciguard-repair-sandbox"
        )
        self.repair_target_base_revision = repair_target_base_revision
        github_repository = os.environ.get("SCIGUARD_GITHUB_REPOSITORY")
        github_token = os.environ.get("SCIGUARD_GITHUB_TOKEN")
        if bool(github_repository) != bool(github_token):
            raise RuntimeError(
                "SCIGUARD_GITHUB_REPOSITORY and SCIGUARD_GITHUB_TOKEN "
                "must be configured together"
            )
        if github_repository and github_token:
            if self.change_publisher or self.verification_engine:
                raise RuntimeError(
                    "injected action adapters cannot be combined with GitHub environment config"
                )
            transport = UrllibGitHubTransport(token=github_token)
            self.change_publisher = GitHubChangePublisher(
                repository=github_repository,
                transport=transport,
            )
            self.verification_engine = GitHubCheckRunVerifier(
                repository=github_repository,
                transport=transport,
            )
            self.repair_target_repository = (
                f"https://github.com/{github_repository}"
            )
        elif (
            self.repair_repository is not None
            and repair_target_repository is None
            and change_publisher is None
        ):
            self.repair_target_repository = (
                f"local-git://{self.repair_repository.name}"
            )
        configured_key = os.environ.get("SCIGUARD_APPROVAL_SIGNING_KEY")
        self.approval_authority = approval_authority
        if self.approval_authority is None and configured_key:
            self.approval_authority = ApprovalAuthority(configured_key.encode("utf-8"))
        self.metadata_graph_factory = metadata_graph_factory or metadata_reader.connect

    @staticmethod
    def _latest_repair_bundle(store: RunStore, incident_id: str) -> RepairBundle:
        lifecycle_types = {
            EventType.REPAIR_BUNDLE_CREATED,
            EventType.REPAIR_PUBLISHED,
            EventType.REPAIR_VERIFIED,
            EventType.APPROVAL_RECORDED,
            EventType.REPAIR_APPLIED,
        }
        for event in reversed(store.get_events(incident_id)):
            if event.event_type in lifecycle_types:
                return RepairBundle.model_validate(event.payload)
        raise LookupError(f"no repair bundle recorded for {incident_id}")

    @staticmethod
    def _recorder(store: RunStore, incident_id: str) -> EventRecorder:
        return EventRecorder(
            incident_id,
            store.get_events(incident_id),
            on_event=store.append_event,
        )

    def _verifier_for(self, receipt: ChangeReceipt) -> VerificationEngine:
        verifier = self.verification_engine
        if verifier is None and receipt.provider == "LOCAL_GIT":
            verifier = LocalVerificationEngine()
        if verifier is None:
            raise RuntimeError(
                f"no verification engine configured for {receipt.provider}"
            )
        return verifier

    @staticmethod
    def _recovery_checks_from_receipt(
        verification: VerificationReceipt,
        required_check_ids: list[str],
    ) -> list[RecoveryCheck]:
        by_id = {check.check_id: check for check in verification.checks}
        missing = sorted(set(required_check_ids) - set(by_id))
        extra = sorted(set(by_id) - set(required_check_ids))
        if missing or extra:
            raise RuntimeError(
                "fresh verification does not match the locked recovery policy: "
                f"missing={missing}, extra={extra}"
            )
        return [
            RecoveryCheck(
                check_id=check_id,
                status=(
                    CheckStatus.PASS
                    if by_id[check_id].status is CheckExecutionStatus.PASS
                    else CheckStatus.FAIL
                ),
                evidence_ids=list(
                    dict.fromkeys(
                        [
                            verification.receipt_id,
                            by_id[check_id].result_sha256,
                            *by_id[check_id].evidence_ids,
                        ]
                    )
                ),
            )
            for check_id in required_check_ids
        ]

    def publish_repair(self, store: RunStore, incident_id: str) -> RepairBundle:
        """Create a real local branch/commit and persist the content-bound receipt."""

        publisher = self.change_publisher
        if publisher is None and self.repair_repository is not None:
            publisher = LocalGitChangePublisher(self.repair_repository)
        if publisher is None:
            raise RuntimeError(
                "repair publication is disabled; configure a local or GitHub provider"
            )
        proposal = self._latest_repair_bundle(store, incident_id)
        receipt = publisher.publish(proposal)
        published = attach_change_receipt(proposal, receipt)
        receipt_evidence = stable_evidence_id(
            "change-receipt", receipt.model_dump(mode="json")
        )
        decision_log = write_decision_log(
            self.metadata_graph_factory(),
            bundle=published,
            incident_state="QUARANTINED",
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.REMEDIATION_AGENT,
            event_type=EventType.REPAIR_PUBLISHED,
            summary=(
                (
                    f"GitHub pull request #{receipt.pull_request_number} opened "
                    f"for commit {receipt.commit_sha[:12]}"
                )
                if receipt.provider == "GITHUB"
                else (
                    f"Repair committed on {receipt.branch}; "
                    "no remote pull request claimed"
                )
            ),
            evidence_ids=list(
                dict.fromkeys([*proposal.evidence_ids, receipt_evidence])
            ),
            payload=published.model_dump(mode="json"),
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.REMEDIATION_AGENT,
            event_type=EventType.DECISION_LOG_WRITTEN,
            summary=(
                "DataHub Decision Log updated with the observed change-provider receipt"
            ),
            evidence_ids=[receipt_evidence, decision_log.content_sha256],
            payload=decision_log.model_dump(mode="json"),
        )
        return published

    def verify_repair(self, store: RunStore, incident_id: str) -> RepairBundle:
        """Execute every locked verification check against the published commit."""

        published = self._latest_repair_bundle(store, incident_id)
        if published.status is not RepairStatus.PUBLISHED:
            raise RuntimeError(
                f"repair must be PUBLISHED before verification, got {published.status.value}"
            )
        receipt = ChangeReceipt.model_validate(published.external_action_receipt)
        verifier = self._verifier_for(receipt)
        verification = verifier.verify(published, receipt)
        verified = attach_verification_receipt(published, verification)
        decision_log = write_decision_log(
            self.metadata_graph_factory(),
            bundle=verified,
            incident_state="QUARANTINED",
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.VERIFICATION_ENGINE,
            event_type=EventType.REPAIR_VERIFIED,
            summary=(
                f"{len(verification.checks)} / {len(verification.checks)} "
                "commit-bound verification checks passed"
            ),
            evidence_ids=list(
                dict.fromkeys([*published.evidence_ids, verification.receipt_id])
            ),
            duration_ms=sum(check.duration_ms for check in verification.checks),
            payload=verified.model_dump(mode="json"),
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.VERIFICATION_ENGINE,
            event_type=EventType.DECISION_LOG_WRITTEN,
            summary="DataHub Decision Log updated with commit-bound verification",
            evidence_ids=[verification.receipt_id, decision_log.content_sha256],
            payload=decision_log.model_dump(mode="json"),
        )
        return verified

    def approve_repair(
        self,
        store: RunStore,
        incident_id: str,
        *,
        reviewer_urn: str,
        decision: ApprovalDecision,
        note: str,
    ) -> RepairBundle:
        """Record a signed review decision without overstating demo identity assurance."""

        if self.approval_authority is None:
            raise RuntimeError(
                "repair approval is disabled; configure SCIGUARD_APPROVAL_SIGNING_KEY"
            )
        verified = self._latest_repair_bundle(store, incident_id)
        receipt = self.approval_authority.record(
            verified,
            authenticated_approver_urn=reviewer_urn,
            decision=decision,
            note=note,
        )
        reviewed = attach_approval_receipt(
            verified,
            receipt,
            self.approval_authority,
        )
        decision_log = write_decision_log(
            self.metadata_graph_factory(),
            bundle=reviewed,
            incident_state="QUARANTINED",
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.HUMAN_APPROVER,
            event_type=EventType.APPROVAL_RECORDED,
            summary=(
                f"Accountable owner {decision.value.lower()} decision recorded "
                f"with {receipt.identity_assurance} assurance"
            ),
            evidence_ids=receipt.evidence_ids,
            payload=reviewed.model_dump(mode="json"),
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.HUMAN_APPROVER,
            event_type=EventType.DECISION_LOG_WRITTEN,
            summary="DataHub Decision Log updated with the signed review receipt",
            evidence_ids=[receipt.receipt_id, decision_log.content_sha256],
            payload=decision_log.model_dump(mode="json"),
        )
        return reviewed

    def apply_repair(self, store: RunStore, incident_id: str) -> RepairBundle:
        """Materialize the approved exact revision into the configured environment."""

        approved = self._latest_repair_bundle(store, incident_id)
        if approved.status is not RepairStatus.APPROVED:
            raise RuntimeError(
                f"repair must be APPROVED before application, got {approved.status.value}"
            )
        applicator = self.repair_applicator
        if applicator is None and self.repair_repository is not None:
            applicator = LocalStagingApplicator(
                self.repair_repository,
                self.deployment_root,
            )
        if applicator is None:
            raise RuntimeError(
                "repair application is disabled; configure an exact-revision applicator"
            )
        receipt = applicator.apply(approved)
        applied = attach_application_receipt(approved, receipt)
        decision_log = write_decision_log(
            self.metadata_graph_factory(),
            bundle=applied,
            incident_state="QUARANTINED",
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.REMEDIATION_AGENT,
            event_type=EventType.REPAIR_APPLIED,
            summary=(
                f"Approved commit {receipt.commit_sha[:12]} applied to "
                f"{receipt.target_environment}"
            ),
            evidence_ids=list(
                dict.fromkeys([*applied.evidence_ids, receipt.receipt_id])
            ),
            payload=applied.model_dump(mode="json"),
        )
        self._recorder(store, incident_id).emit(
            actor=EventActor.REMEDIATION_AGENT,
            event_type=EventType.DECISION_LOG_WRITTEN,
            summary="DataHub Decision Log updated with the exact-revision application receipt",
            evidence_ids=[receipt.receipt_id, decision_log.content_sha256],
            payload=decision_log.model_dump(mode="json"),
        )
        return applied

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
            owners = backend.get_owners(CONTROL_URN)
            approver_identity = owners[0] if owners else "research_lead"
            approver_urn = (
                approver_identity
                if approver_identity.startswith("urn:")
                else f"urn:li:corpuser:{approver_identity}"
            )
            native_ml_context = []
            impacted_pairs = [
                *zip(impact.affected_urns, impact.affected_names, strict=True),
                *zip(impact.unaffected_urns, impact.unaffected_names, strict=True),
            ]
            for projection_urn, name in impacted_pairs:
                if not name.endswith("_model"):
                    continue
                context = metadata_reader.get_native_ml_model_context(
                    write_graph,
                    projection_urn,
                )
                custom_properties = context.pop("custom_properties")
                native_ml_context.append(
                    NativeMLDecisionContext(
                        **context,
                        criticality=custom_properties.get(
                            "sciguard:criticality", "UNKNOWN"
                        ),
                        expected_target_unit=custom_properties.get(
                            "sciguard:expected_target_unit"
                        ),
                        affected=projection_urn in impact.affected_urns,
                    )
                )
            incident_receipt = raise_incident(
                write_graph,
                incident_id=incident_id,
                entities=[
                    urn
                    for urn in [
                        *impact.affected_urns,
                        *impact.unaffected_urns,
                    ]
                    if urn.startswith("urn:li:dataset:")
                ],
                assignee_urn=approver_urn,
                title="Unsafe scientific candidate ranking",
                description=report.root_cause.explanation,
                evidence_ids=[impact_evidence, *root_evidence_ids],
            )
            incident_receipt_evidence = stable_evidence_id(
                "datahub-incident", incident_receipt.model_dump(mode="json")
            )
            run.recorder.emit(
                actor=EventActor.ENFORCER,
                event_type=EventType.DATAHUB_INCIDENT_WRITTEN,
                summary=(
                    "Native DataHub Incident raised across the affected and preserved "
                    "scientific decision cone"
                ),
                evidence_ids=[incident_receipt_evidence],
                payload=incident_receipt.model_dump(mode="json"),
            )
            repair_bundle = create_unit_repair_bundle(
                incident_id=incident_id,
                root_cause=report.root_cause,
                impact=impact,
                evidence_ids=[impact_evidence, *root_evidence_ids],
                approver_urn=approver_urn,
                native_ml_context=native_ml_context,
                datahub_incident_urn=incident_urn(incident_id),
                datahub_decision_log_urn=decision_log_urn(incident_id),
                target_repository=self.repair_target_repository,
                target_base_revision=self.repair_target_base_revision,
            )
            run.recorder.emit(
                actor=EventActor.REMEDIATION_AGENT,
                event_type=EventType.REPAIR_BUNDLE_CREATED,
                summary=(
                    "Proof-carrying unit repair prepared with contract, "
                    "scientific-regression, and safe-branch tests"
                ),
                evidence_ids=repair_bundle.evidence_ids,
                payload=repair_bundle.model_dump(mode="json"),
            )
            decision_log = write_decision_log(
                write_graph,
                bundle=repair_bundle,
                incident_state="INVESTIGATING",
            )
            decision_log_evidence = stable_evidence_id(
                "decision-log", decision_log.model_dump(mode="json")
            )
            run.recorder.emit(
                actor=EventActor.REMEDIATION_AGENT,
                event_type=EventType.DECISION_LOG_WRITTEN,
                summary=(
                    "Native DataHub Decision Log published and linked to every "
                    "affected, preserved, model, and deployment entity"
                ),
                evidence_ids=[decision_log_evidence],
                payload=decision_log.model_dump(mode="json"),
            )
            run.recorder.emit(
                actor=EventActor.POLICY_GUARDIAN,
                event_type=EventType.APPROVAL_REQUESTED,
                summary=(
                    "Critical scientific-decision repair locked pending "
                    "accountable-owner approval"
                ),
                evidence_ids=repair_bundle.approval.evidence_ids,
                payload=repair_bundle.approval.model_dump(mode="json"),
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
        *,
        approval_receipt_id: str | None,
    ) -> RecoveryResult:
        events = store.get_events(incident_id)
        recorder = EventRecorder(
            incident_id,
            events,
            on_event=store.append_event,
        )
        human_approval = None
        if approval_receipt_id:
            bundle = self._latest_repair_bundle(store, incident_id)
            if bundle.status not in {RepairStatus.APPROVED, RepairStatus.APPLIED}:
                raise RuntimeError(
                    "recovery approval requires an APPROVED or APPLIED repair bundle"
                )
            receipt = ApprovalReceipt.model_validate(bundle.approval_receipt)
            if receipt.receipt_id != approval_receipt_id:
                raise RuntimeError("recovery approval receipt does not match the repair")
            if self.approval_authority is None or not self.approval_authority.verify(receipt):
                raise RuntimeError("recovery approval receipt signature is invalid")
            if receipt.decision is not ApprovalDecision.APPROVE:
                raise RuntimeError("a rejected repair cannot authorize recovery")
            human_approval = HumanApprovalEvidence(
                receipt_id=receipt.receipt_id,
                approver_urn=receipt.approver_urn,
                identity_assurance=receipt.identity_assurance,
                production_authorized=receipt.production_authorized,
            )
        bundle = self._latest_repair_bundle(store, incident_id)
        if bundle.incident_id != incident_id:
            raise RuntimeError("repair bundle incident does not match the recovery route")
        if bundle.status is not RepairStatus.APPLIED:
            raise RuntimeError(
                "recovery requires an APPLIED repair revision"
            )
        change_receipt = ChangeReceipt.model_validate(
            bundle.external_action_receipt
        )
        fresh_verification = self._verifier_for(change_receipt).verify(
            bundle,
            change_receipt,
        )
        profile = load_profile("polymer")
        if profile.recovery_policy is None:
            raise RuntimeError("polymer profile has no recovery policy")
        checks = self._recovery_checks_from_receipt(
            fresh_verification,
            profile.recovery_policy.required_checks,
        )
        recorder.emit(
            actor=EventActor.VERIFICATION_ENGINE,
            event_type=EventType.RECOVERY_EVIDENCE_REFRESHED,
            summary=(
                "Fresh commit-bound recovery evidence read from "
                f"{fresh_verification.provider}"
            ),
            evidence_ids=list(
                dict.fromkeys(
                    [
                        fresh_verification.receipt_id,
                        *(
                            check.result_sha256
                            for check in fresh_verification.checks
                        ),
                    ]
                )
            ),
            duration_ms=sum(
                check.duration_ms for check in fresh_verification.checks
            ),
            payload=fresh_verification.model_dump(mode="json"),
        )
        graph = self.metadata_graph_factory()
        result = RecoveryController(
            graph,
            CONTROL_URN,
            profile,
            recorder=recorder,
        ).evaluate(
            checks,
            human_approval=human_approval,
            expected_incident_id=incident_id,
        )
        incident_receipt = update_incident_status(
            graph,
            incident_id=incident_id,
            resolved=result.resume_allowed,
            message=(
                "Recovery evidence accepted; scientific decision incident resolved."
                if result.resume_allowed
                else "Recovery remains locked pending clean scientific evidence."
            ),
            evidence_ids=[
                evidence_id
                for check in checks
                for evidence_id in check.evidence_ids
            ],
        )
        decision_log = write_decision_log(
            graph,
            bundle=bundle,
            incident_state=result.incident_state,
            recovery_result=result.model_dump(mode="json"),
            recovery_verification=fresh_verification.model_dump(mode="json"),
        )
        recorder.emit(
            actor=EventActor.RECOVERY_CONTROLLER,
            event_type=EventType.DATAHUB_INCIDENT_WRITTEN,
            summary=(
                "Native DataHub Incident resolved"
                if result.resume_allowed
                else "Native DataHub Incident remains active"
            ),
            evidence_ids=[
                stable_evidence_id(
                    "datahub-incident", incident_receipt.model_dump(mode="json")
                )
            ],
            payload=incident_receipt.model_dump(mode="json"),
        )
        recorder.emit(
            actor=EventActor.RECOVERY_CONTROLLER,
            event_type=EventType.DECISION_LOG_WRITTEN,
            summary="Native DataHub Decision Log updated with recovery evidence",
            evidence_ids=[
                stable_evidence_id(
                    "decision-log", decision_log.model_dump(mode="json")
                )
            ],
            payload=decision_log.model_dump(mode="json"),
        )
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
