"""Deterministic, evidence-bound remediation planning.

SciGuard does not let an LLM turn a plausible explanation into an authorized
change. A RepairBundle is a reviewable contract: every proposed file, test,
approval gate, and rollback step is linked to validated incident evidence.

The flagship implementation emits a deterministic unit-normalization repair.
External adapters may publish the bundle as a Git branch or pull request, but
the core model is provider-neutral and never claims that an external action
occurred until a receipt is attached.
"""

from __future__ import annotations

import difflib
import hashlib
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.events import stable_evidence_id
from core.impact import FieldImpact
from core.investigation_models import RootCause


class RepairRisk(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RepairStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ArtifactKind(str, Enum):
    CODE_PATCH = "CODE_PATCH"
    CONTRACT_TEST = "CONTRACT_TEST"
    SCIENTIFIC_REGRESSION_TEST = "SCIENTIFIC_REGRESSION_TEST"
    SAFE_BRANCH_TEST = "SAFE_BRANCH_TEST"
    ROLLBACK_PLAN = "ROLLBACK_PLAN"


class ApprovalStatus(str, Enum):
    REQUIRED = "REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RepairArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    artifact_id: str
    kind: ArtifactKind
    path: str
    description: str
    content_sha256: str
    content: str
    evidence_ids: list[str]

    @field_validator("artifact_id", "path", "description", "content")
    @classmethod
    def _nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("repair artifact fields must not be empty")
        return value

    @model_validator(mode="after")
    def _content_digest_matches(self) -> RepairArtifact:
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if digest != self.content_sha256:
            raise ValueError("content_sha256 does not match artifact content")
        return self


class VerificationCheck(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: str
    name: str
    command: str
    expected_result: str
    protects: list[str]
    evidence_ids: list[str]

    @field_validator("evidence_ids")
    @classmethod
    def _requires_evidence(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("verification checks require evidence links")
        return value


class ApprovalGate(BaseModel):
    model_config = ConfigDict(frozen=True)

    required: bool
    status: ApprovalStatus
    policy_id: str
    approver_urn: str
    reason: str
    evidence_ids: list[str]


class NativeMLDecisionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_projection_urn: str
    native_model_urn: str
    model_name: str
    model_version: str
    model_type: str
    feature_urns: list[str]
    training_job_urns: list[str]
    inference_job_urns: list[str]
    deployment_context: list[dict[str, Any]]
    owner_urns: list[str]
    criticality: str
    expected_target_unit: str | None
    affected: bool


class RepairBundle(BaseModel):
    """Provider-neutral proposal ready for review or external publication."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"
    bundle_id: str
    incident_id: str
    status: RepairStatus
    risk: RepairRisk
    title: str
    root_cause_summary: str
    target_repository: str
    target_base_revision: str
    datahub_incident_urn: str | None = None
    datahub_decision_log_urn: str | None = None
    affected_urns: list[str]
    preserved_urns: list[str]
    native_ml_context: list[NativeMLDecisionContext] = Field(default_factory=list)
    evidence_ids: list[str]
    artifacts: list[RepairArtifact]
    verification_checks: list[VerificationCheck]
    approval: ApprovalGate
    external_action_receipt: dict[str, Any] | None = None
    verification_receipt: dict[str, Any] | None = None
    approval_receipt: dict[str, Any] | None = None
    application_receipt: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _evidence_closure(self) -> RepairBundle:
        evidence = set(self.evidence_ids)
        referenced = {
            evidence_id
            for artifact in self.artifacts
            for evidence_id in artifact.evidence_ids
        } | {
            evidence_id
            for check in self.verification_checks
            for evidence_id in check.evidence_ids
        } | set(self.approval.evidence_ids)
        if not referenced.issubset(evidence):
            raise ValueError("bundle children reference evidence outside the bundle")
        if set(self.affected_urns) & set(self.preserved_urns):
            raise ValueError("affected and preserved URNs must be disjoint")
        if self.status is RepairStatus.PROPOSED and self.external_action_receipt:
            raise ValueError("a proposed bundle cannot claim an external action receipt")
        if self.status is RepairStatus.VERIFIED and not self.verification_receipt:
            raise ValueError("a verified bundle requires a verification receipt")
        if self.status is RepairStatus.APPROVED:
            if not self.approval_receipt:
                raise ValueError("an approved bundle requires an approval receipt")
            if self.approval.status is not ApprovalStatus.APPROVED:
                raise ValueError("approved bundle and approval gate must agree")
        if self.status is RepairStatus.REJECTED:
            if not self.approval_receipt:
                raise ValueError("a rejected bundle requires an approval receipt")
            if self.approval.status is not ApprovalStatus.REJECTED:
                raise ValueError("rejected bundle and approval gate must agree")
        if self.status is RepairStatus.APPLIED:
            if not self.application_receipt:
                raise ValueError("an applied bundle requires an application receipt")
            if not self.approval_receipt:
                raise ValueError("an applied bundle requires an approval receipt")
            if self.approval.status is not ApprovalStatus.APPROVED:
                raise ValueError("applied bundle and approval gate must agree")
        return self


def _artifact(
    *,
    kind: ArtifactKind,
    path: str,
    description: str,
    content: str,
    evidence_ids: list[str],
) -> RepairArtifact:
    identity = {
        "kind": kind.value,
        "path": path,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    return RepairArtifact(
        artifact_id=stable_evidence_id("repair-artifact", identity),
        kind=kind,
        path=path,
        description=description,
        content_sha256=identity["content_sha256"],
        content=content,
        evidence_ids=evidence_ids,
    )


def _normalizer_patch(root_cause: RootCause) -> str:
    before = """def normalize_tg(value: float, unit: str) -> float:
    # v1 trusted the destination column label and silently copied mixed units.
    return float(value)
"""
    after = f'''class UnitContractError(ValueError):
    """Raised when an experimental value violates the declared unit contract."""


def normalize_tg(value: float, unit: str) -> float:
    """Normalize Tg into {root_cause.expected_unit} or reject an unknown unit."""

    normalized = unit.strip()
    if normalized == "{root_cause.expected_unit}":
        return float(value)
    if normalized == "K":
        return round(float(value) - 273.15, 6)
    raise UnitContractError(
        f"unsupported Tg unit {{unit!r}}; expected {root_cause.expected_unit!r} or 'K'"
    )
'''
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile="a/pipeline/normalize.py",
            tofile="b/pipeline/normalize.py",
        )
    )


def _contract_test(root_cause: RootCause) -> str:
    return f'''from pipeline.normalize import UnitContractError, normalize_tg


def test_kelvin_and_celsius_normalize_to_the_same_scientific_value() -> None:
    assert normalize_tg(373.15, "K") == 100.0
    assert normalize_tg(100.0, "{root_cause.expected_unit}") == 100.0


def test_unknown_unit_fails_closed() -> None:
    try:
        normalize_tg(100.0, "degF")
    except UnitContractError:
        return
    raise AssertionError("unknown units must not be silently accepted")
'''


def _scientific_regression_test() -> str:
    return '''import hashlib
from pathlib import Path

from pipeline.decision import load_candidates, rank_candidates
from pipeline.normalize import normalize_tg


FIXTURE = Path(__file__).parents[1] / "data" / "b042_decision_fixture.csv"
FIXTURE_SHA256 = "ca676efb3b969a48c7f7ce4f9b5ea3d507a86d40cee161a8bb57b9b06cf550c6"


def test_candidate_ranking_fails_before_and_matches_trusted_baseline_after_repair() -> None:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    candidates = load_candidates(FIXTURE)

    legacy_ranks = rank_candidates(
        candidates,
        normalizer=lambda value, unit: float(value),
    )
    repaired_ranks = rank_candidates(candidates, normalizer=normalize_tg)
    trusted_ranks = {
        candidate.candidate_id: candidate.trusted_rank
        for candidate in candidates
    }

    assert legacy_ranks["P-204"] == 1
    assert legacy_ranks != trusted_ranks
    assert repaired_ranks["P-204"] == 18
    assert repaired_ranks == trusted_ranks
'''


def _safe_branch_test() -> str:
    return '''import hashlib
from pathlib import Path

from pipeline.decision import (
    load_candidates,
    molecular_weight_artifact,
    publish_molecular_weight_artifact,
    rank_candidates,
)
from pipeline.normalize import normalize_tg


FIXTURE = Path(__file__).parents[1] / "data" / "b042_decision_fixture.csv"
TRUSTED_MW_SHA256 = "2ff3a5d0b93e3ee65aa8601e391057443edbba42b7f09b02a8cd37d3e16538e6"


def test_repair_preserves_and_republishes_the_real_molecular_weight_artifact(
    tmp_path: Path,
) -> None:
    candidates = load_candidates(FIXTURE)
    before = molecular_weight_artifact(candidates)

    # Execute the repaired Tg decision path before rendering the independent MW branch.
    repaired_ranks = rank_candidates(candidates, normalizer=normalize_tg)
    assert repaired_ranks["P-204"] == 18
    after = molecular_weight_artifact(candidates)

    assert hashlib.sha256(before).hexdigest() == TRUSTED_MW_SHA256
    assert after == before
    destination = tmp_path / "molecular_weight_report.json"
    receipt_sha256 = publish_molecular_weight_artifact(candidates, destination)
    assert destination.read_bytes() == before
    assert receipt_sha256 == TRUSTED_MW_SHA256
'''


def create_unit_repair_bundle(
    *,
    incident_id: str,
    root_cause: RootCause,
    impact: FieldImpact,
    evidence_ids: list[str],
    approver_urn: str,
    native_ml_context: list[NativeMLDecisionContext | dict[str, Any]] | None = None,
    datahub_incident_urn: str | None = None,
    datahub_decision_log_urn: str | None = None,
    target_repository: str = "https://github.com/songjie6816-code/sciguard-repair-sandbox",
    target_base_revision: str = "main",
) -> RepairBundle:
    """Create the deterministic flagship proposal without claiming publication."""

    evidence_ids = list(dict.fromkeys(evidence_ids))
    native_ml_context = [
        NativeMLDecisionContext.model_validate(context)
        for context in native_ml_context or []
    ]
    if not evidence_ids:
        raise ValueError("a repair bundle requires validated root-cause evidence")
    if root_cause.expected_unit != "degC" or "K" not in root_cause.observed_units:
        raise ValueError("flagship repair only supports the verified K-to-degC contract")

    patch = _normalizer_patch(root_cause)
    contract_test = _contract_test(root_cause)
    ranking_test = _scientific_regression_test()
    safe_branch_test = _safe_branch_test()
    rollback = (
        "Revert the repair commit, restore tg-normalizer-v1, keep the candidate "
        "ranking publication blocked, and return the incident to QUARANTINED."
    )
    artifacts = [
        _artifact(
            kind=ArtifactKind.CODE_PATCH,
            path="pipeline/normalize.py.patch",
            description="Fail-closed K-to-degC scientific-unit normalization patch.",
            content=patch,
            evidence_ids=evidence_ids,
        ),
        _artifact(
            kind=ArtifactKind.CONTRACT_TEST,
            path="tests/test_unit_contract.py",
            description="Unit contract and fail-closed unknown-unit tests.",
            content=contract_test,
            evidence_ids=evidence_ids,
        ),
        _artifact(
            kind=ArtifactKind.SCIENTIFIC_REGRESSION_TEST,
            path="tests/test_scientific_decision.py",
            description="Counterfactual P-204 ranking restoration check.",
            content=ranking_test,
            evidence_ids=evidence_ids,
        ),
        _artifact(
            kind=ArtifactKind.SAFE_BRANCH_TEST,
            path="tests/test_safe_branch.py",
            description="Non-regression proof for the preserved molecular-weight branch.",
            content=safe_branch_test,
            evidence_ids=evidence_ids,
        ),
        _artifact(
            kind=ArtifactKind.ROLLBACK_PLAN,
            path="SCIGUARD_ROLLBACK.md",
            description="Fail-safe rollback and re-quarantine procedure.",
            content=rollback,
            evidence_ids=evidence_ids,
        ),
    ]
    checks = [
        VerificationCheck(
            check_id="unit_contract",
            name="Scientific unit contract",
            command="pytest -q tests/test_unit_contract.py",
            expected_result="Kelvin and Celsius normalize identically; unknown units fail closed.",
            protects=["cleaned_polymer_dataset.tg_degC"],
            evidence_ids=evidence_ids,
        ),
        VerificationCheck(
            check_id="candidate_ranking_stability",
            name="Scientific decision regression",
            command="pytest -q tests/test_scientific_decision.py",
            expected_result=(
                "The locked B042 fixture fails at P-204 rank #1 under the legacy "
                "normalizer and exactly matches all trusted ranks after repair."
            ),
            protects=["candidate_ranking_report"],
            evidence_ids=evidence_ids,
        ),
        VerificationCheck(
            check_id="safe_branch_preservation",
            name="Preserved branch non-regression",
            command="pytest -q tests/test_safe_branch.py",
            expected_result=(
                "The real molecular-weight artifact digest is unchanged after executing "
                "the repaired Tg path and the artifact is published byte-for-byte."
            ),
            protects=["formulation_report", "durability_model"],
            evidence_ids=evidence_ids,
        ),
    ]
    bundle_identity = {
        "incident_id": incident_id,
        "root_cause": root_cause.model_dump(mode="json"),
        "impact": impact.model_dump(mode="json"),
        "native_ml_context": [
            context.model_dump(mode="json") for context in native_ml_context
        ],
        "artifact_sha256": [artifact.content_sha256 for artifact in artifacts],
    }
    bundle_id = stable_evidence_id("repair-bundle", bundle_identity)
    return RepairBundle(
        bundle_id=bundle_id,
        incident_id=incident_id,
        status=RepairStatus.PROPOSED,
        risk=RepairRisk.CRITICAL,
        title=(
            f"Normalize {root_cause.batch_id} Tg values from K to "
            f"{root_cause.expected_unit} before scientific ranking"
        ),
        root_cause_summary=root_cause.explanation,
        target_repository=target_repository,
        target_base_revision=target_base_revision,
        datahub_incident_urn=datahub_incident_urn,
        datahub_decision_log_urn=datahub_decision_log_urn,
        affected_urns=impact.affected_urns,
        preserved_urns=impact.unaffected_urns,
        native_ml_context=native_ml_context,
        evidence_ids=evidence_ids,
        artifacts=artifacts,
        verification_checks=checks,
        approval=ApprovalGate(
            required=True,
            status=ApprovalStatus.REQUIRED,
            policy_id="SCIENTIFIC_DECISION_CRITICAL",
            approver_urn=approver_urn,
            reason=(
                "The patch changes a CRITICAL model input contract and a candidate-selection "
                "decision; accountable scientific-owner approval is mandatory."
            ),
            evidence_ids=evidence_ids,
        ),
    )
