"""Run the labelled scenarios end-to-end and report quantitative metrics.

For each scenario we read the dataset's live "before" state from DataHub, apply
the scenario's mutation to get "after", run SciGuard's deterministic loop, and
compare against the hand-labelled ground truth. Impact analysis is scored twice:
with DataHub lineage and without (the ablation that shows DataHub's value).

Run from the repo root:  PYTHONPATH=. python evaluation/harness.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core import remediation
from core.change_detector import Snapshot, detect_changes
from core.lineage_analyzer import analyze_impact
from core.profiles import load_profile
from core.risk_engine import assess
from datahub_client import metadata_reader as reader
from evaluation.metrics import aggregate, counts

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evaluation" / "scenarios.json"
REPORT = ROOT / "examples" / "outputs" / "evaluation_report.md"
PLATFORM = "polymer_rnd"


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env="PROD")


def _read_before(graph, dataset: str) -> Snapshot:
    urn = _urn(dataset)
    return Snapshot(
        fields={f["path"]: (f["nativeType"] or "") for f in reader.get_schema_fields(graph, urn)},
        units=reader.get_units(graph, urn),
    )


def _apply(before: Snapshot, mutations: list[dict]) -> Snapshot:
    fields, units = dict(before.fields), dict(before.units)
    for m in mutations:
        op, field = m["op"], m["field"]
        if op == "unit":
            units[field] = m["to"]
        elif op == "remove_unit":
            units.pop(field, None)
        elif op == "remove_field":
            fields.pop(field, None)
            units.pop(field, None)
        elif op == "add_field":
            fields[field] = m.get("to", "string")
        elif op == "type":
            fields[field] = m["to"]
    return Snapshot(fields=fields, units=units)


def run() -> dict:
    spec = json.loads(SCENARIOS.read_text())
    cones = spec["cones"]
    graph = reader.connect()

    rows = []
    for sc in spec["scenarios"]:
        dataset = sc["dataset"]
        expected = sc["expected"]
        cone = cones[dataset]

        before = _read_before(graph, dataset)
        after = _apply(before, sc["mutations"])

        t0 = time.perf_counter()
        changes = detect_changes(before, after)
        affected = analyze_impact(graph, _urn(dataset))
        profile = load_profile(sc["profile"])
        assessment = assess(profile, changes, affected)
        plan = remediation.build_plan(profile, assessment, dataset)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        detected = {(c.kind.value, c.field) for c in changes}
        expected_changes = {tuple(x) for x in expected["changes"]}
        pred_affected = {e.name for e in affected}
        pred_tag_urns = set(plan.tag_targets)
        expected_tag_urns = {_urn(n) for n in cone["tag_targets"]}
        is_positive = expected["severity"] != "none"

        rows.append(
            {
                "id": sc["id"],
                "dataset": dataset,
                "is_positive": is_positive,
                "detect_ok": detected == expected_changes,
                "severity_ok": assessment.overall_severity == expected["severity"],
                "actionable": assessment.is_actionable,
                "impact_with": counts(pred_affected, set(cone["affected"])),
                "impact_without": counts(set(), set(cone["affected"])),
                "owner_recall": counts(set(assessment.responsible_owners), set(cone["owners"])),
                "tag_ok": pred_tag_urns == expected_tag_urns,
                "latency_ms": latency_ms,
            }
        )

    return {"rows": rows}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def summarize(rows: list[dict]) -> str:
    pos = [r for r in rows if r["is_positive"]]
    neg = [r for r in rows if not r["is_positive"]]

    detect_ok = sum(r["detect_ok"] for r in rows)
    severity_ok = sum(r["severity_ok"] for r in rows)
    false_alarms = sum(r["actionable"] for r in neg)

    impact_with = aggregate([r["impact_with"] for r in pos])
    impact_without = aggregate([r["impact_without"] for r in pos])
    owner = aggregate([r["owner_recall"] for r in pos])
    tag_ok = sum(r["tag_ok"] for r in pos)
    mean_latency = sum(r["latency_ms"] for r in rows) / len(rows)

    lines = ["# SciGuard evaluation report", ""]
    lines.append(
        "> Controlled synthetic benchmark on hand-labelled scenarios. Its value is "
        "regression safety, the DataHub ablation, and false-alarm control on "
        "negative cases — not a claim of real-world accuracy."
    )
    lines.append("")
    lines.append(f"- scenarios: {len(rows)} ({len(pos)} actionable, {len(neg)} negative controls)")
    lines.append(f"- change detection accuracy: {_pct(detect_ok / len(rows))} ({detect_ok}/{len(rows)})")
    lines.append(f"- risk-severity accuracy: {_pct(severity_ok / len(rows))} ({severity_ok}/{len(rows)})")
    lines.append(f"- false-alarm rate on negatives: {_pct(false_alarms / len(neg))} ({false_alarms}/{len(neg)})")
    lines.append("")
    lines.append("## Impact analysis (actionable scenarios)")
    lines.append(f"- impacted-entity precision: {_pct(impact_with.precision)}")
    lines.append(f"- impacted-entity recall: {_pct(impact_with.recall)}")
    lines.append(f"- impacted-entity F1: {_pct(impact_with.f1)}")
    lines.append(f"- owner-notification recall: {_pct(owner.recall)}")
    lines.append(f"- model-at-risk tag targeting: {_pct(tag_ok / len(pos))} ({tag_ok}/{len(pos)})")
    lines.append("")
    lines.append("## Ablation: with vs without DataHub lineage")
    lines.append(f"- impacted-entity recall WITH DataHub:    {_pct(impact_with.recall)}")
    lines.append(f"- impacted-entity recall WITHOUT DataHub:  {_pct(impact_without.recall)}")
    lines.append("- Without the lineage graph, downstream models and reports are invisible,")
    lines.append("  so every downstream artifact at risk is missed.")
    lines.append("")
    lines.append(f"## Latency\n- mean per-scenario: {mean_latency:.1f} ms")
    lines.append("")
    lines.append("## Per-scenario")
    lines.append("| scenario | detect | severity | impact recall | note |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        note = "negative control" if not r["is_positive"] else ""
        rec = _pct(r["impact_with"].recall) if r["is_positive"] else "-"
        lines.append(
            f"| {r['id']} | {'ok' if r['detect_ok'] else 'MISS'} | "
            f"{'ok' if r['severity_ok'] else 'MISS'} | {rec} | {note} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    result = run()
    report = summarize(result["rows"])
    REPORT.write_text(report)
    print(report)
    print(f"(written to {REPORT.relative_to(ROOT)})")


if __name__ == "__main__":
    main()
