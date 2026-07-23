"""Shared, deterministic models for the WP3 investigation workflow."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from core.events import stable_evidence_id


class EvidenceSource(str, Enum):
    DATAHUB_CATALOG = "DATAHUB_CATALOG"
    LOCAL_ARTIFACT = "LOCAL_ARTIFACT"


class HypothesisStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str
    source: EvidenceSource
    kind: str
    summary: str
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        *,
        source: EvidenceSource | str,
        kind: str,
        summary: str,
        payload: dict[str, Any],
    ) -> Evidence:
        source_value = EvidenceSource(source)
        identity = {"source": source_value.value, "kind": kind, "payload": payload}
        return cls(
            evidence_id=stable_evidence_id(kind.lower().replace("_", "-"), identity),
            source=source_value,
            kind=kind,
            summary=summary,
            payload=payload,
        )


class AssetContext(BaseModel):
    urn: str
    name: str
    degree: int = 0
    owners: list[str] = []
    tags: list[str] = []
    terms: list[str] = []
    properties: dict[str, str] = {}
    assertion_history: list[dict[str, Any]] = []
    assertions_supported: bool = True


class InvestigationResult(BaseModel):
    available: bool
    start_urn: str
    assets: list[AssetContext] = []
    suspect_sources: list[str] = []
    evidence: list[Evidence] = []
    degraded_reason: str | None = None


class RealityCheckResult(BaseModel):
    available: bool
    evidence: list[Evidence] = []
    degraded_reason: str | None = None


class Hypothesis(BaseModel):
    id: str
    claim: str
    assigned_actor: str
    investigation_contract: str
    required_evidence_kinds: list[str]


class InvestigationCase(BaseModel):
    incident_id: str
    signal_id: str | None = None
    signal_evidence_ids: list[str] = []
    symptom: str
    candidate_id: str
    rank_before: int
    rank_after: int
    pipeline_status: str
    start_asset_name: str
    hypotheses: list[Hypothesis]


class HypothesisResolution(BaseModel):
    hypothesis_id: str
    status: HypothesisStatus
    rationale: str
    evidence_ids: list[str]


class RootCause(BaseModel):
    batch_id: str
    instrument_firmware_before: str
    instrument_firmware_after: str
    expected_unit: str
    observed_units: list[str]
    normalization_version: str
    affected_rows: int
    explanation: str


class InvestigationReport(BaseModel):
    incident_id: str
    root_cause_confirmed: bool
    root_cause: RootCause | None
    resolutions: list[HypothesisResolution]
    degraded: bool = False
    degraded_reason: str | None = None
