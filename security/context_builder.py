"""Build a small, sanitized metadata-only prompt and auditable snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from core.events import Event
from core.investigation_models import AssetContext, InvestigationCase, InvestigationReport
from core.policy_engine import PolicyPlan
from security.redactor import RedactionResult, Redactor

_UNTRUSTED_AUTHORITY_KEYS = {
    "action", "actions", "allow", "catalog_status", "decision", "enforcement",
    "policy", "policy_decision", "resume", "status_override",
}


class BoundedMetadataContext(BaseModel):
    incident: dict[str, Any]
    root_cause: dict[str, Any] | None
    hypotheses: list[dict[str, Any]]
    policy: list[dict[str, Any]]
    assets: list[dict[str, Any]]
    events: list[dict[str, Any]]
    evidence_ids: list[str]
    extra_context: dict[str, Any]
    raw_rows_included: int = Field(default=0, frozen=True)
    authority: str = (
        "Narrative only. Deterministic policy owns HALT/ALLOW; recovery gate owns RESUME."
    )


class ContextBuildResult(BaseModel):
    context: BoundedMetadataContext
    redactions: RedactionResult
    max_prompt_chars: int

    def render_prompt(self, output_schema: dict[str, Any] | None = None) -> str:
        instructions = (
            "You are SciGuard's bounded scientific-incident narrator. Use only the supplied "
            "metadata and evidence IDs. Do not infer raw rows, reveal secrets, change policy "
            "actions, authorize RESUME, or request non-read-only tools. Return JSON matching "
            "the provided output schema.\n\nOUTPUT_SCHEMA:\n"
        )
        schema = json.dumps(
            output_schema or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        body = json.dumps(
            self.context.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        prompt = instructions + schema + "\n\nSANITIZED_METADATA_CONTEXT:\n" + body
        if len(prompt) <= self.max_prompt_chars:
            return prompt
        marker = "\n[CONTEXT_TRUNCATED]"
        return prompt[: self.max_prompt_chars - len(marker)] + marker


class PromptSnapshot(BaseModel):
    snapshot_id: str
    created_at: datetime
    sanitized_prompt: str
    context_sha256: str
    redaction_counts: dict[str, int]
    raw_rows_included: int


class BoundedContextBuilder:
    def __init__(
        self,
        *,
        max_assets: int = 12,
        max_events: int = 30,
        max_prompt_chars: int = 12_000,
    ) -> None:
        if max_assets < 1 or max_events < 1:
            raise ValueError("metadata context limits must be positive")
        if max_prompt_chars < 256:
            raise ValueError("max_prompt_chars must be at least 256")
        self.max_assets = max_assets
        self.max_events = max_events
        self.max_prompt_chars = max_prompt_chars

    def build(
        self,
        *,
        case: InvestigationCase,
        report: InvestigationReport,
        plan: PolicyPlan,
        assets: list[AssetContext] | None = None,
        events: list[Event] | None = None,
        extra_context: dict[str, Any] | None = None,
    ) -> ContextBuildResult:
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for resolution in report.resolutions
                for evidence_id in resolution.evidence_ids
            )
        )
        safe_extra = {
            key: value
            for key, value in (extra_context or {}).items()
            if key.lower() not in _UNTRUSTED_AUTHORITY_KEYS
        }
        raw_context = {
            "incident": {
                "incident_id": case.incident_id,
                "symptom": case.symptom,
                "candidate_id": case.candidate_id,
                "rank_before": case.rank_before,
                "rank_after": case.rank_after,
                "pipeline_status": case.pipeline_status,
            },
            "root_cause": report.root_cause.model_dump(mode="json") if report.root_cause else None,
            "hypotheses": [item.model_dump(mode="json") for item in report.resolutions],
            "policy": [
                {
                    "name": item.name,
                    "role": item.role,
                    "affected": item.affected,
                    "decision": item.decision.value,
                    "catalog_status": item.catalog_status.value,
                    "actions": [action.value for action in item.actions],
                    "reason_code": item.reason_code,
                    "evidence_ids": item.evidence_ids,
                }
                for item in plan.decisions[: self.max_assets]
            ],
            "assets": [
                {
                    "name": item.name,
                    "degree": item.degree,
                    "owners": item.owners,
                    "tags": item.tags,
                    "terms": item.terms,
                    "model_version": item.properties.get("model_version"),
                    "code_version": item.properties.get("code_version"),
                    "assertion_run_count": len(item.assertion_history),
                    "assertions_supported": item.assertions_supported,
                }
                for item in (assets or [])[: self.max_assets]
            ],
            "events": [
                {
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "actor": event.actor.value,
                    "event_type": event.event_type.value,
                    "summary": event.summary,
                    "evidence_ids": event.evidence_ids,
                    "duration_ms": event.duration_ms,
                }
                for event in (events or [])[-self.max_events :]
            ],
            "evidence_ids": evidence_ids,
            "extra_context": safe_extra,
            "raw_rows_included": 0,
            "authority": (
                "Narrative only. Deterministic policy owns HALT/ALLOW; recovery gate owns RESUME."
            ),
        }
        redactions = Redactor().redact(raw_context)
        context = BoundedMetadataContext.model_validate(redactions.value)
        return ContextBuildResult(
            context=context,
            redactions=redactions,
            max_prompt_chars=self.max_prompt_chars,
        )


def make_prompt_snapshot(
    result: ContextBuildResult,
    output_schema: dict[str, Any] | None = None,
) -> PromptSnapshot:
    prompt = result.render_prompt(output_schema)
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return PromptSnapshot(
        snapshot_id=f"prompt:{digest[:16]}",
        created_at=datetime.now(timezone.utc),
        sanitized_prompt=prompt,
        context_sha256=digest,
        redaction_counts=result.redactions.counts,
        raw_rows_included=result.context.raw_rows_included,
    )


def save_prompt_snapshot(
    path: str | Path,
    result: ContextBuildResult,
    output_schema: dict[str, Any] | None = None,
) -> PromptSnapshot:
    snapshot = make_prompt_snapshot(result, output_schema)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(snapshot.model_dump_json(indent=2))
        handle.write("\n")
    os.replace(temporary, destination)
    return snapshot
