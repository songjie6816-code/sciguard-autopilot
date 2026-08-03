"""Native DataHub Incident and Decision Log lifecycle for SciGuard."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from datahub.configuration.common import OperationalError
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.metadata.schema_classes import (
    AuditStampClass,
    DocumentContentsClass,
    DocumentInfoClass,
    DocumentSourceClass,
    DocumentSourceTypeClass,
    DocumentStateClass,
    DocumentStatusClass,
    IncidentAssigneeClass,
    IncidentInfoClass,
    IncidentNoteClass,
    IncidentNotesClass,
    IncidentNoteSourceClass,
    IncidentNoteSourceTypeClass,
    IncidentSourceClass,
    IncidentSourceTypeClass,
    IncidentStageClass,
    IncidentStateClass,
    IncidentStatusClass,
    IncidentTypeClass,
    RelatedAssetClass,
)
from datahub.metadata.urns import DocumentUrn, IncidentUrn
from pydantic import BaseModel, ConfigDict

from core.repair import RepairBundle

SCIGUARD_ACTOR = "urn:li:corpuser:sciguard"


class IncidentWriteReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    incident_urn: str
    state: str
    stage: str
    entity_count: int
    notes_written: bool
    notes_capability: str


class DecisionLogWriteReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_urn: str
    status: str
    related_asset_count: int
    content_sha256: str


def incident_urn(incident_id: str) -> str:
    return str(IncidentUrn(id=f"sciguard-{incident_id}"))


def decision_log_urn(incident_id: str) -> str:
    return str(DocumentUrn(id=f"sciguard-decision-log-{incident_id}"))


def _stamp() -> AuditStampClass:
    return AuditStampClass(
        time=round(datetime.now(timezone.utc).timestamp() * 1000),
        actor=SCIGUARD_ACTOR,
    )


def _emit(graph, urn: str, aspect) -> None:
    graph.emit(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))


def raise_incident(
    graph,
    *,
    incident_id: str,
    entities: list[str],
    assignee_urn: str,
    title: str,
    description: str,
    evidence_ids: list[str],
) -> IncidentWriteReceipt:
    """Create or refresh SciGuard's native active Incident without touching notes."""

    urn = incident_urn(incident_id)
    entities = list(dict.fromkeys(entities))
    stamp = _stamp()
    existing = graph.get_aspect(urn, IncidentInfoClass)
    created = existing.created if existing else stamp
    _emit(
        graph,
        urn,
        IncidentInfoClass(
            type=IncidentTypeClass.CUSTOM,
            customType="SCIENTIFIC_DECISION_INTEGRITY",
            entities=entities,
            status=IncidentStatusClass(
                state=IncidentStateClass.ACTIVE,
                stage=IncidentStageClass.WORK_IN_PROGRESS,
                lastUpdated=stamp,
                message="Selective containment active; repair review required.",
            ),
            created=created,
            title=title,
            description=(
                f"{description}\n\nSciGuard evidence: {', '.join(evidence_ids)}"
            ),
            priority=0,
            assignees=[IncidentAssigneeClass(actor=assignee_urn, assignedAt=stamp)],
            source=IncidentSourceClass(type=IncidentSourceTypeClass.MANUAL),
            startedAt=created.time,
        ),
    )
    notes_written = append_incident_note(
        graph,
        incident_id=incident_id,
        message=(
            "SciGuard opened selective containment with evidence "
            + ", ".join(evidence_ids)
        ),
    )
    return IncidentWriteReceipt(
        incident_urn=urn,
        state=IncidentStateClass.ACTIVE,
        stage=IncidentStageClass.WORK_IN_PROGRESS,
        entity_count=len(entities),
        notes_written=notes_written,
        notes_capability=(
            "INCIDENT_NOTES_ASPECT"
            if notes_written
            else "STATUS_MESSAGE_FALLBACK_SERVER_SCHEMA"
        ),
    )


def append_incident_note(graph, *, incident_id: str, message: str) -> bool:
    urn = incident_urn(incident_id)
    existing = graph.get_aspect(urn, IncidentNotesClass)
    notes = list(existing.notes or []) if existing else []
    if message in {note.message for note in notes}:
        return True
    notes.append(
        IncidentNoteClass(
            message=message,
            created=_stamp(),
            source=IncidentNoteSourceClass(
                sourceType=IncidentNoteSourceTypeClass.EXTERNAL,
                externalId=incident_id,
            ),
        )
    )
    try:
        _emit(graph, urn, IncidentNotesClass(notes=notes))
    except OperationalError as exc:
        if "Unknown aspect incidentNotes" not in str(exc):
            raise
        return False
    return True


def update_incident_status(
    graph,
    *,
    incident_id: str,
    resolved: bool,
    message: str,
    evidence_ids: list[str],
) -> IncidentWriteReceipt:
    """Update only the native Incident status while preserving its full info aspect."""

    urn = incident_urn(incident_id)
    existing = graph.get_aspect(urn, IncidentInfoClass)
    if existing is None:
        raise LookupError(f"native DataHub Incident is missing: {urn}")
    state = IncidentStateClass.RESOLVED if resolved else IncidentStateClass.ACTIVE
    stage = (
        IncidentStageClass.FIXED
        if resolved
        else IncidentStageClass.WORK_IN_PROGRESS
    )
    existing.status = IncidentStatusClass(
        state=state,
        stage=stage,
        lastUpdated=_stamp(),
        message=message,
    )
    _emit(graph, urn, existing)
    notes_written = append_incident_note(
        graph,
        incident_id=incident_id,
        message=f"{message} Evidence: {', '.join(evidence_ids)}",
    )
    return IncidentWriteReceipt(
        incident_urn=urn,
        state=state,
        stage=stage,
        entity_count=len(existing.entities),
        notes_written=notes_written,
        notes_capability=(
            "INCIDENT_NOTES_ASPECT"
            if notes_written
            else "STATUS_MESSAGE_FALLBACK_SERVER_SCHEMA"
        ),
    )


def _decision_log_markdown(
    bundle: RepairBundle,
    incident_state: str,
    *,
    recovery_result: dict[str, object] | None = None,
    recovery_verification: dict[str, object] | None = None,
) -> str:
    native_lines = [
        (
            f"- {'AFFECTED' if context.affected else 'PRESERVED'}: "
            f"`{context.model_name}` `{context.model_version}` "
            f"({len(context.feature_urns)} features, "
            f"{len(context.deployment_context)} deployment)"
        )
        for context in bundle.native_ml_context
    ] or ["- Native ML context was not present in this capture."]
    check_lines = [
        f"- `{check.check_id}`: {check.expected_result}"
        for check in bundle.verification_checks
    ]
    change = bundle.external_action_receipt or {}
    verification = bundle.verification_receipt or {}
    approval = bundle.approval_receipt or {}
    application = bundle.application_receipt or {}
    observed_check_lines = [
        (
            f"- `{check.get('check_id')}`: {check.get('status')} · "
            f"result `{check.get('result_sha256')}`"
            + (
                f" · [details]({check.get('details_url')})"
                if check.get("details_url")
                else ""
            )
        )
        for check in verification.get("checks", [])
        if isinstance(check, dict)
    ]
    recovery_check_lines = [
        (
            f"- `{check.get('check_id')}`: {check.get('status')} · "
            f"result `{check.get('result_sha256')}`"
        )
        for check in (recovery_verification or {}).get("checks", [])
        if isinstance(check, dict)
    ]
    return "\n".join(
        [
            f"# SciGuard Decision Log · {bundle.incident_id}",
            "",
            f"**Incident state:** {incident_state}",
            f"**Repair state:** {bundle.status.value}",
            f"**Risk:** {bundle.risk.value}",
            "",
            "## Root cause",
            "",
            bundle.root_cause_summary,
            "",
            "## Decision cone",
            "",
            f"- Affected assets: {len(bundle.affected_urns)}",
            f"- Preserved assets: {len(bundle.preserved_urns)}",
            "",
            "## Native Production ML context",
            "",
            *native_lines,
            "",
            "## Proof-carrying repair",
            "",
            f"- Bundle: `{bundle.bundle_id}`",
            f"- Artifacts: {len(bundle.artifacts)}",
            *check_lines,
            f"- Approval: {bundle.approval.status.value} · `{bundle.approval.approver_urn}`",
            "",
            "## Observed change receipt",
            "",
            (
                f"- Provider: `{change.get('provider')}` · status `{change.get('status')}`"
                if change
                else "- No change provider has acted on this proposal."
            ),
            *(
                [
                    f"- Commit: `{change.get('commit_sha')}`",
                    f"- Base: `{change.get('base_commit_sha')}`",
                    f"- Branch: `{change.get('branch')}`",
                    f"- Remote URL: {change.get('remote_url') or 'not created'}",
                ]
                if change
                else []
            ),
            "",
            "## Commit-bound verification",
            "",
            (
                f"- Receipt: `{verification.get('receipt_id')}` · "
                f"{verification.get('provider')} · {verification.get('status')}"
                if verification
                else "- Verification has not run."
            ),
            *observed_check_lines,
            "",
            "## Owner review",
            "",
            (
                f"- Receipt: `{approval.get('receipt_id')}` · "
                f"{approval.get('decision')} by `{approval.get('approver_urn')}`"
                if approval
                else "- Accountable-owner review has not been recorded."
            ),
            *(
                [
                    f"- Identity assurance: `{approval.get('identity_assurance')}`",
                    (
                        "- Production authorized: "
                        f"`{str(bool(approval.get('production_authorized'))).lower()}`"
                    ),
                    f"- Signature: `{approval.get('signature_sha256')}`",
                ]
                if approval
                else []
            ),
            "",
            "## Applied revision",
            "",
            (
                f"- Receipt: `{application.get('receipt_id')}` · "
                f"{application.get('provider')} · {application.get('status')}"
                if application
                else "- The approved revision has not been applied."
            ),
            *(
                [
                    f"- Commit: `{application.get('commit_sha')}`",
                    f"- Environment: `{application.get('target_environment')}`",
                    f"- Deployment: `{application.get('deployment_id')}`",
                    (
                        "- Production authorized: "
                        f"`{str(bool(application.get('production_authorized'))).lower()}`"
                    ),
                ]
                if application
                else []
            ),
            "",
            "## Recovery",
            "",
            (
                f"- State: `{recovery_result.get('incident_state')}` · "
                f"resume `{str(bool(recovery_result.get('resume_allowed'))).lower()}` · "
                f"clean runs `{recovery_result.get('clean_run_count')}`"
                if recovery_result
                else "- Recovery has not been evaluated."
            ),
            *(
                [
                    (
                        "- Fresh verification: "
                        f"`{recovery_verification.get('receipt_id')}` · "
                        f"commit `{recovery_verification.get('commit_sha')}`"
                    ),
                    *recovery_check_lines,
                ]
                if recovery_verification
                else []
            ),
            "",
            "## Evidence closure",
            "",
            *[f"- `{evidence_id}`" for evidence_id in bundle.evidence_ids],
        ]
    )


def write_decision_log(
    graph,
    *,
    bundle: RepairBundle,
    incident_state: str,
    recovery_result: dict[str, object] | None = None,
    recovery_verification: dict[str, object] | None = None,
) -> DecisionLogWriteReceipt:
    """Publish a native DataHub Document linked to every decision-cone entity."""

    urn = decision_log_urn(bundle.incident_id)
    existing = graph.get_aspect(urn, DocumentInfoClass)
    now = _stamp()
    created = existing.created if existing else now
    content = _decision_log_markdown(
        bundle,
        incident_state,
        recovery_result=recovery_result,
        recovery_verification=recovery_verification,
    )
    candidate_related_urns = list(
        dict.fromkeys(
            [
                *bundle.affected_urns,
                *bundle.preserved_urns,
                *(
                    context.native_model_urn
                    for context in bundle.native_ml_context
                ),
            ]
        )
    )
    # DataHub GMS 1.5 rejects DataProcessInstance and MLModelDeployment URNs
    # in DocumentInfo.relatedAssets. Preserve those links in custom properties
    # while using every destination type accepted by the native aspect.
    unsupported_related_asset_prefixes = (
        "urn:li:dataProcessInstance:",
        "urn:li:mlModelDeployment:",
    )
    unsupported_related_urns = [
        asset
        for asset in candidate_related_urns
        if asset.startswith(unsupported_related_asset_prefixes)
    ]
    related_urns = [
        asset
        for asset in candidate_related_urns
        if asset not in unsupported_related_urns
    ]
    _emit(
        graph,
        urn,
        DocumentInfoClass(
            status=DocumentStatusClass(state=DocumentStateClass.PUBLISHED),
            contents=DocumentContentsClass(text=content),
            created=created,
            lastModified=now,
            title=f"SciGuard Decision Log · {bundle.incident_id}",
            source=DocumentSourceClass(
                sourceType=DocumentSourceTypeClass.NATIVE,
                externalId=bundle.bundle_id,
            ),
            relatedAssets=[RelatedAssetClass(asset=asset) for asset in related_urns],
            customProperties={
                "sciguard:incident_id": bundle.incident_id,
                "sciguard:repair_bundle_id": bundle.bundle_id,
                "sciguard:repair_status": bundle.status.value,
                "sciguard:incident_state": incident_state,
                "sciguard:evidence_ids": ",".join(bundle.evidence_ids),
                "sciguard:change_commit_sha": str(
                    (bundle.external_action_receipt or {}).get("commit_sha", "")
                ),
                "sciguard:verification_receipt_id": str(
                    (bundle.verification_receipt or {}).get("receipt_id", "")
                ),
                "sciguard:approval_receipt_id": str(
                    (bundle.approval_receipt or {}).get("receipt_id", "")
                ),
                "sciguard:application_receipt_id": str(
                    (bundle.application_receipt or {}).get("receipt_id", "")
                ),
                "sciguard:application_environment": str(
                    (bundle.application_receipt or {}).get(
                        "target_environment", ""
                    )
                ),
                "sciguard:recovery_verification_receipt_id": str(
                    (recovery_verification or {}).get("receipt_id", "")
                ),
                "sciguard:recovery_resume_allowed": str(
                    bool((recovery_result or {}).get("resume_allowed"))
                ).lower(),
                "sciguard:native_deployment_urns": ",".join(
                    str(deployment["urn"])
                    for context in bundle.native_ml_context
                    for deployment in context.deployment_context
                ),
                "sciguard:server_unsupported_related_asset_urns": ",".join(
                    unsupported_related_urns
                ),
            },
        ),
    )
    return DecisionLogWriteReceipt(
        document_urn=urn,
        status=DocumentStateClass.PUBLISHED,
        related_asset_count=len(related_urns),
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
