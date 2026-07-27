"""Signed, commit-bound approval receipts for high-risk scientific repairs.

This module deliberately separates cryptographic record integrity from identity
assurance. The bundled local authority signs demo review decisions so they
cannot be silently edited, while the receipt explicitly states that a real
SSO/OIDC integration is still required before production authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from core.events import stable_evidence_id
from core.repair import ApprovalStatus, RepairBundle, RepairStatus


class ApprovalError(RuntimeError):
    pass


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ApprovalReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_id: str
    bundle_id: str
    verification_receipt_id: str
    commit_sha: str
    approver_urn: str
    expected_approver_urn: str
    decision: ApprovalDecision
    note: str = Field(min_length=8, max_length=1000)
    identity_provider: str
    identity_assurance: str
    production_authorized: bool
    signing_key_id: str
    created_at: datetime
    evidence_ids: list[str]
    signature_sha256: str


def _signature_payload(receipt: ApprovalReceipt | dict[str, object]) -> bytes:
    if isinstance(receipt, ApprovalReceipt):
        payload = receipt.model_dump(mode="json", exclude={"signature_sha256"})
    else:
        payload = dict(receipt)
        payload.pop("signature_sha256", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class ApprovalAuthority:
    """Issue and verify approval receipts after an external identity check."""

    def __init__(
        self,
        signing_key: bytes,
        *,
        key_id: str = "sciguard-demo-v1",
        identity_provider: str = "SCIGUARD_LOCAL_REVIEW_SESSION",
        identity_assurance: str = "DEMO_SIGNED_NOT_SSO",
        production_authorized: bool = False,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("approval signing key must contain at least 32 bytes")
        self._signing_key = signing_key
        self.key_id = key_id
        self.identity_provider = identity_provider
        self.identity_assurance = identity_assurance
        self.production_authorized = production_authorized

    def record(
        self,
        bundle: RepairBundle,
        *,
        authenticated_approver_urn: str,
        decision: ApprovalDecision,
        note: str,
    ) -> ApprovalReceipt:
        if bundle.status is not RepairStatus.VERIFIED:
            raise ApprovalError(
                f"approval requires a VERIFIED bundle, got {bundle.status.value}"
            )
        if authenticated_approver_urn != bundle.approval.approver_urn:
            raise ApprovalError("authenticated reviewer is not the accountable approver")
        verification = bundle.verification_receipt or {}
        external = bundle.external_action_receipt or {}
        verification_id = str(verification.get("receipt_id", ""))
        commit_sha = str(verification.get("commit_sha", ""))
        if not verification_id or not commit_sha:
            raise ApprovalError("verified bundle is missing receipt identity")
        if external.get("commit_sha") != commit_sha:
            raise ApprovalError("approval cannot span different publication commits")
        note = note.strip()
        if len(note) < 8:
            raise ApprovalError("approval note must explain the review decision")

        created_at = datetime.now(timezone.utc)
        identity = {
            "bundle_id": bundle.bundle_id,
            "verification_receipt_id": verification_id,
            "commit_sha": commit_sha,
            "approver_urn": authenticated_approver_urn,
            "decision": decision.value,
            "created_at": created_at.isoformat(),
        }
        receipt_id = stable_evidence_id("approval-receipt", identity)
        evidence_ids = list(
            dict.fromkeys([*bundle.evidence_ids, verification_id, receipt_id])
        )
        unsigned: dict[str, object] = {
            "receipt_id": receipt_id,
            "bundle_id": bundle.bundle_id,
            "verification_receipt_id": verification_id,
            "commit_sha": commit_sha,
            "approver_urn": authenticated_approver_urn,
            "expected_approver_urn": bundle.approval.approver_urn,
            "decision": decision,
            "note": note,
            "identity_provider": self.identity_provider,
            "identity_assurance": self.identity_assurance,
            "production_authorized": self.production_authorized,
            "signing_key_id": self.key_id,
            "created_at": created_at,
            "evidence_ids": evidence_ids,
        }
        draft = ApprovalReceipt(**unsigned, signature_sha256="0" * 64)
        signature = hmac.new(
            self._signing_key,
            _signature_payload(draft),
            hashlib.sha256,
        ).hexdigest()
        return ApprovalReceipt(**unsigned, signature_sha256=signature)

    def verify(self, receipt: ApprovalReceipt) -> bool:
        if receipt.signing_key_id != self.key_id:
            return False
        expected = hmac.new(
            self._signing_key,
            _signature_payload(receipt),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, receipt.signature_sha256)


def attach_approval_receipt(
    bundle: RepairBundle,
    receipt: ApprovalReceipt,
    authority: ApprovalAuthority,
) -> RepairBundle:
    """Create an approved or rejected bundle after signature and binding checks."""

    if not authority.verify(receipt):
        raise ApprovalError("approval receipt signature is invalid")
    if bundle.status is not RepairStatus.VERIFIED:
        raise ApprovalError("only a verified bundle can receive approval")
    if receipt.bundle_id != bundle.bundle_id:
        raise ApprovalError("approval receipt does not belong to this repair bundle")
    verification = bundle.verification_receipt or {}
    if receipt.verification_receipt_id != verification.get("receipt_id"):
        raise ApprovalError("approval receipt targets a different verification result")
    if receipt.commit_sha != verification.get("commit_sha"):
        raise ApprovalError("approval receipt targets a different commit")
    if receipt.approver_urn != bundle.approval.approver_urn:
        raise ApprovalError("approval receipt was not issued to the accountable owner")

    approved = receipt.decision is ApprovalDecision.APPROVE
    gate_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    next_status = RepairStatus.APPROVED if approved else RepairStatus.REJECTED
    return RepairBundle.model_validate(
        {
            **bundle.model_dump(mode="python"),
            "status": next_status,
            "approval": {
                **bundle.approval.model_dump(mode="python"),
                "status": gate_status,
            },
            "approval_receipt": receipt.model_dump(mode="python"),
        }
    )
