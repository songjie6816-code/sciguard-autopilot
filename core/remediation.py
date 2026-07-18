"""Build deterministic remediation plans and a human-readable incident report.

The plan is assembled from the matched rules' remediation steps plus the
lineage-derived list of affected models, reports and owners. A Markdown report
is rendered for `examples/outputs/` and for write-back into DataHub.
"""

from __future__ import annotations

from pydantic import BaseModel

from core.profiles import Profile
from core.risk_engine import RiskAssessment


class RemediationPlan(BaseModel):
    incident_title: str
    severity: str
    actions: list[str] = []
    tag_targets: list[str] = []      # entity urns to flag model-at-risk
    notify_owners: list[str] = []


def build_plan(profile: Profile, assessment: RiskAssessment, changed_name: str) -> RemediationPlan:
    actions: list[str] = []
    for finding in assessment.findings:
        rule = next((r for r in profile.rules if r.id == finding.rule_id), None)
        steps = rule.remediation if rule else []
        for step in steps:
            if step not in actions:
                actions.append(step)

    models_and_reports = [e for e in assessment.affected if e.role in ("model", "report")]
    tag_targets = [e.urn for e in assessment.affected if e.role == "model"]

    if models_and_reports:
        names = ", ".join(e.name or e.urn for e in models_and_reports)
        actions.append(f"Revalidate downstream artifacts before use: {names}")

    return RemediationPlan(
        incident_title=f"Risk on '{changed_name}': {assessment.overall_severity.upper()}",
        severity=assessment.overall_severity,
        actions=actions,
        tag_targets=tag_targets,
        notify_owners=assessment.responsible_owners,
    )


def render_report(
    changed_name: str,
    assessment: RiskAssessment,
    plan: RemediationPlan,
) -> str:
    """Render a Markdown incident report."""
    lines: list[str] = []
    lines.append(f"# SciGuard incident: {plan.incident_title}")
    lines.append("")
    lines.append(f"- **Change site:** `{changed_name}`")
    lines.append(f"- **Overall severity:** {assessment.overall_severity.upper()}")
    lines.append(f"- **Owners to notify:** {', '.join(plan.notify_owners) or 'none'}")
    lines.append("")

    lines.append("## Detected changes and rules")
    for f in assessment.findings:
        lines.append(f"- {f.rationale}")
        if f.accepted_units:
            lines.append(f"  - accepted units: {', '.join(f.accepted_units)}")
    if not assessment.findings:
        lines.append("- no rule-matched changes")
    lines.append("")

    lines.append("## Affected downstream (via DataHub lineage)")
    for e in assessment.affected:
        owners = ", ".join(e.owners) or "unowned"
        lines.append(f"- hop {e.degree}: `{e.name}` [{e.role}] — owner: {owners}")
    if not assessment.affected:
        lines.append("- none")
    lines.append("")

    lines.append("## Recommended remediation")
    for i, a in enumerate(plan.actions, 1):
        lines.append(f"{i}. {a}")
    lines.append("")
    return "\n".join(lines)
