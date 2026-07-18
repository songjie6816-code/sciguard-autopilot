"""Run the labelled scenarios end-to-end and report quantitative metrics.

For each scenario we read the dataset's live "before" state from DataHub, apply
the scenario's mutation to get "after", run SciGuard's deterministic loop, and
compare against the hand-labelled ground truth.

Impact analysis is measured over the distinct change-site datasets (the cone
depends only on lineage, not on the mutation) with TWO real runs:
  - WITH DataHub: analyze_impact (lineage traversal)
  - WITHOUT DataHub: impact_via_search (catalog search, no lineage graph)
Both are executed against DataHub; neither number is hardcoded.

The harness GATES: main() exits non-zero if any headline metric regresses, so a
broken (e.g. over-broad) lineage analyzer fails the evaluation instead of
silently keeping a perfect-looking score.

Run from the repo root:  PYTHONPATH=. python evaluation/harness.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core import remediation
from core.change_detector import Snapshot, detect_changes
from core.lineage_analyzer import analyze_impact, impact_via_search
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

    # Per-scenario: detection, severity, false-alarm, latency, tag targeting.
    rows = []
    for sc in spec["scenarios"]:
        dataset, expected, cone = sc["dataset"], sc["expected"], cones[sc["dataset"]]
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
        rows.append({
            "id": sc["id"],
            "is_positive": expected["severity"] != "none",
            "detect_ok": detected == {tuple(x) for x in expected["changes"]},
            "severity_ok": assessment.overall_severity == expected["severity"],
            "actionable": assessment.is_actionable,
            "owner": counts(set(assessment.responsible_owners), set(cone["owners"])),
            "tag_ok": set(plan.tag_targets) == {_urn(n) for n in cone["tag_targets"]},
            "latency_ms": latency_ms,
        })

    # Impact analysis over the DISTINCT change sites (cone depends on lineage,
    # not on the mutation), each scored with two real runs.
    impact = []
    for dataset in {sc["dataset"] for sc in spec["scenarios"] if cones.get(sc["dataset"])}:
        expected = set(cones[dataset]["affected"])
        lineage_names = {e.name for e in analyze_impact(graph, _urn(dataset))}
        search_names = set(impact_via_search(graph, dataset, platform=PLATFORM))
        impact.append({
            "dataset": dataset,
            "expected": expected,
            "lineage": counts(lineage_names, expected),
            "lineage_exact": lineage_names == expected,
            "search": counts(search_names, expected),
            "search_exact": search_names == expected,
            "search_false_positives": sorted(search_names - expected),
        })

    return {"rows": rows, "impact": impact}


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def summarize(result: dict) -> str:
    rows, impact = result["rows"], result["impact"]
    pos = [r for r in rows if r["is_positive"]]
    neg = [r for r in rows if not r["is_positive"]]

    detect_ok = sum(r["detect_ok"] for r in rows)
    severity_ok = sum(r["severity_ok"] for r in rows)
    false_alarms = sum(r["actionable"] for r in neg)
    owner = aggregate([r["owner"] for r in pos])
    tag_ok = sum(r["tag_ok"] for r in pos)
    mean_latency = sum(r["latency_ms"] for r in rows) / len(rows)

    lineage = aggregate([i["lineage"] for i in impact])
    search = aggregate([i["search"] for i in impact])
    lineage_exact = sum(i["lineage_exact"] for i in impact)
    search_exact = sum(i["search_exact"] for i in impact)
    search_fps = sorted({fp for i in impact for fp in i["search_false_positives"]})

    lines = ["# SciGuard evaluation report", ""]
    lines.append(
        "> Controlled synthetic benchmark on hand-labelled scenarios. Both ablation "
        "arms are executed against DataHub (no number is hardcoded). Purpose: "
        "regression safety, false-alarm control, and a measured DataHub ablation."
    )
    lines.append("")
    lines.append(f"- scenarios: {len(rows)} ({len(pos)} actionable, {len(neg)} negative controls)")
    lines.append(f"- change detection accuracy: {_pct(detect_ok / len(rows))} ({detect_ok}/{len(rows)})")
    lines.append(f"- risk-severity accuracy: {_pct(severity_ok / len(rows))} ({severity_ok}/{len(rows)})")
    lines.append(f"- false-alarm rate on negatives: {_pct(false_alarms / len(neg))} ({false_alarms}/{len(neg)})")
    lines.append(f"- owner-notification precision/recall: {_pct(owner.precision)} / {_pct(owner.recall)}")
    lines.append(f"- model-at-risk tag targeting: {_pct(tag_ok / len(pos))} ({tag_ok}/{len(pos)})")
    lines.append("")
    lines.append(f"## Impact analysis over {len(impact)} distinct lineage cones")
    lines.append("| approach | precision | recall | F1 | exact cone |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| WITH DataHub lineage | {_pct(lineage.precision)} | {_pct(lineage.recall)} | "
        f"{_pct(lineage.f1)} | {lineage_exact}/{len(impact)} |"
    )
    lines.append(
        f"| WITHOUT DataHub (catalog search) | {_pct(search.precision)} | {_pct(search.recall)} | "
        f"{_pct(search.f1)} | {search_exact}/{len(impact)} |"
    )
    lines.append("")
    lines.append("The no-lineage search baseline cannot tell dependency direction, so it")
    lines.append(f"flags upstream/sibling datasets as affected (false positives: {search_fps or 'none'}).")
    lines.append("Only lineage recovers the exact downstream cone with correct direction.")
    lines.append("")
    lines.append(f"## Latency\n- mean per-scenario: {mean_latency:.1f} ms")
    lines.append("")
    lines.append("## Per-scenario")
    lines.append("| scenario | detect | severity | note |")
    lines.append("|---|---|---|---|")
    for r in rows:
        note = "negative control" if not r["is_positive"] else ""
        lines.append(
            f"| {r['id']} | {'ok' if r['detect_ok'] else 'MISS'} | "
            f"{'ok' if r['severity_ok'] else 'MISS'} | {note} |"
        )
    return "\n".join(lines) + "\n"


def gate(result: dict) -> list[str]:
    """Return a list of regression failures; empty means the evaluation passed."""
    rows, impact = result["rows"], result["impact"]
    pos = [r for r in rows if r["is_positive"]]
    failures = []
    # Guard against a vacuous pass: nothing evaluated must never read as success.
    if not pos:
        failures.append("no actionable scenarios were evaluated")
    if not impact:
        failures.append("no lineage cones were evaluated")
    if not all(r["detect_ok"] for r in rows):
        failures.append("change detection is not 100%")
    if not all(r["severity_ok"] for r in rows):
        failures.append("risk-severity is not 100%")
    if any(r["actionable"] for r in rows if not r["is_positive"]):
        failures.append("a negative control raised a false alarm")
    lineage = aggregate([i["lineage"] for i in impact])
    if lineage.precision < 1.0 or lineage.recall < 1.0:
        failures.append(
            f"lineage impact is not exact (precision {_pct(lineage.precision)}, "
            f"recall {_pct(lineage.recall)})"
        )
    if not all(i["lineage_exact"] for i in impact):
        failures.append("lineage did not recover an exact cone for every change site")
    owner = aggregate([r["owner"] for r in pos])
    if owner.precision < 1.0 or owner.recall < 1.0:
        failures.append(
            f"owner notification is not exact (precision {_pct(owner.precision)}, "
            f"recall {_pct(owner.recall)}) — notifies the wrong or too many owners"
        )
    if not all(r["tag_ok"] for r in pos):
        failures.append("model-at-risk tag targeting regressed on an actionable scenario")
    return failures


def main() -> None:
    result = run()
    report = summarize(result)
    REPORT.write_text(report)
    print(report)
    print(f"(written to {REPORT.relative_to(ROOT)})")

    failures = gate(result)
    if failures:
        print("\nEVALUATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nEVALUATION PASSED")


if __name__ == "__main__":
    main()
