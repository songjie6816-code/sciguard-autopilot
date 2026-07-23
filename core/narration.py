"""Optional, sanitized narration after deterministic policy has been frozen."""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.events import Event
from core.investigation_models import AssetContext, InvestigationCase, InvestigationReport
from core.policy_engine import PolicyPlan
from security.context_builder import (
    BoundedContextBuilder,
    PromptSnapshot,
    make_prompt_snapshot,
    save_prompt_snapshot,
)
from security.policy_gate import PolicyViolation, ReadOnlyToolExecutor, ToolRequest
from security.redactor import Redactor


class HypothesisNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(min_length=1, max_length=64)
    note: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(max_length=30)


class ProposedHypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1_000)
    evidence_needed: list[str] = Field(max_length=10)


class LLMNarrativeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    internal_report: str = Field(min_length=1, max_length=8_000)
    public_summary: str = Field(min_length=1, max_length=2_000)
    hypothesis_notes: list[HypothesisNote] = Field(max_length=10)
    proposed_hypotheses: list[ProposedHypothesis] = Field(
        default_factory=list,
        max_length=3,
    )
    tool_requests: list[ToolRequest] = Field(max_length=10)
    cited_evidence_ids: list[str] = Field(max_length=50)


class NarrativeSource(str, Enum):
    LLM = "LLM"
    DETERMINISTIC_FALLBACK = "DETERMINISTIC_FALLBACK"


class NarrativeResult(BaseModel):
    source: NarrativeSource
    internal_report: str
    public_summary: str
    policy_plan: PolicyPlan
    prompt_snapshot: PromptSnapshot
    hypothesis_notes: list[HypothesisNote] = Field(default_factory=list)
    proposed_hypotheses: list[ProposedHypothesis] = Field(default_factory=list)
    approved_tool_requests: list[ToolRequest] = Field(default_factory=list)
    fallback_reason: str | None = None


def deterministic_narrative(
    report: InvestigationReport,
    plan: PolicyPlan,
) -> tuple[str, str]:
    root = report.root_cause
    if root:
        cause = (
            f"Batch {root.batch_id}: firmware {root.instrument_firmware_before} -> "
            f"{root.instrument_firmware_after}; {root.affected_rows} rows violated the "
            f"{root.expected_unit} unit contract under {root.normalization_version}."
        )
    else:
        cause = "Root cause is not confirmed; required evidence remains incomplete."
    hypotheses = "; ".join(
        f"{item.hypothesis_id}={item.status.value} ({item.rationale})"
        for item in report.resolutions
    )
    decisions = "; ".join(
        f"{item.name}={item.decision.value}/{item.catalog_status.value}"
        for item in plan.decisions
    )
    internal = f"{cause}\nHypotheses: {hypotheses}\nDeterministic policy: {decisions}"
    halted = [item.name for item in plan.decisions if item.decision.value == "HALT"]
    allowed = [item.name for item in plan.decisions if item.decision.value == "ALLOW"]
    public = (
        "A synthetic scientific-data unit incident was detected and independently "
        f"verified. Containment halted {len(halted)} affected decision-critical "
        f"asset(s) while {len(allowed)} unaffected asset(s) remained available. "
        "Recovery is controlled by deterministic evidence checks."
    )
    return internal, public


class NarrationService:
    """Validate one optional provider; never grant action or recovery authority."""

    def __init__(
        self,
        *,
        client: Callable[[str], str] | None,
        context_builder: BoundedContextBuilder | None = None,
        tool_executor: ReadOnlyToolExecutor | None = None,
    ) -> None:
        self.client = client
        self.context_builder = context_builder or BoundedContextBuilder()
        self.tool_executor = tool_executor

    def run(
        self,
        *,
        case: InvestigationCase,
        report: InvestigationReport,
        plan: PolicyPlan,
        assets: list[AssetContext] | None = None,
        events: list[Event] | None = None,
        extra_context: dict[str, Any] | None = None,
        snapshot_path: str | Path | None = None,
    ) -> NarrativeResult:
        context = self.context_builder.build(
            case=case,
            report=report,
            plan=plan,
            assets=assets,
            events=events,
            extra_context=extra_context,
        )
        output_schema = LLMNarrativeOutput.model_json_schema()
        snapshot = (
            save_prompt_snapshot(snapshot_path, context, output_schema)
            if snapshot_path
            else make_prompt_snapshot(context, output_schema)
        )
        if self.client is None:
            return self._fallback(report, plan, snapshot, "LLM provider not configured")

        try:
            raw = self.client(snapshot.sanitized_prompt)
            output = LLMNarrativeOutput.model_validate_json(raw)
            available_evidence = set(context.context.evidence_ids)
            cited = set(output.cited_evidence_ids)
            cited.update(
                evidence_id
                for note in output.hypothesis_notes
                for evidence_id in note.evidence_ids
            )
            if not cited <= available_evidence:
                raise ValueError(
                    f"LLM cited unknown evidence IDs: {sorted(cited - available_evidence)}"
                )
            known_hypotheses = {item.id for item in case.hypotheses}
            unknown_hypotheses = {
                item.hypothesis_id for item in output.hypothesis_notes
            } - known_hypotheses
            if unknown_hypotheses:
                raise ValueError(
                    f"LLM referenced unknown hypotheses: {sorted(unknown_hypotheses)}"
                )
            if output.tool_requests and self.tool_executor is None:
                raise PolicyViolation(
                    "tool requests exist but no read-only executor is registered"
                )
            for request in output.tool_requests:
                self.tool_executor.validate(request)
        except ValidationError as exc:
            return self._fallback(
                report,
                plan,
                snapshot,
                f"LLM output validation failed: {exc}",
            )
        except PolicyViolation as exc:
            return self._fallback(
                report,
                plan,
                snapshot,
                f"LLM tool request rejected: {exc}",
            )
        except Exception as exc:  # noqa: BLE001 - providers always fail closed
            return self._fallback(
                report,
                plan,
                snapshot,
                f"LLM provider/output failed: {exc}",
            )

        sanitized = Redactor().redact(
            {
                "internal_report": output.internal_report,
                "public_summary": output.public_summary,
            }
        ).value
        return NarrativeResult(
            source=NarrativeSource.LLM,
            internal_report=sanitized["internal_report"],
            public_summary=sanitized["public_summary"],
            policy_plan=plan,
            prompt_snapshot=snapshot,
            hypothesis_notes=output.hypothesis_notes,
            proposed_hypotheses=output.proposed_hypotheses,
            approved_tool_requests=output.tool_requests,
        )

    @staticmethod
    def _fallback(
        report: InvestigationReport,
        plan: PolicyPlan,
        snapshot: PromptSnapshot,
        reason: str,
    ) -> NarrativeResult:
        internal, public = deterministic_narrative(report, plan)
        sanitized = Redactor().redact(
            {"internal_report": internal, "public_summary": public}
        ).value
        return NarrativeResult(
            source=NarrativeSource.DETERMINISTIC_FALLBACK,
            internal_report=sanitized["internal_report"],
            public_summary=sanitized["public_summary"],
            policy_plan=plan,
            prompt_snapshot=snapshot,
            hypothesis_notes=[
                HypothesisNote(
                    hypothesis_id=item.hypothesis_id,
                    note=item.rationale,
                    evidence_ids=item.evidence_ids,
                )
                for item in report.resolutions
            ],
            fallback_reason=reason,
        )
