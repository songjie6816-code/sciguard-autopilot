"""Run the labelled scenarios end-to-end and report quantitative metrics.

For each scenario we read the dataset's live "before" state from DataHub, apply
the scenario's mutation to get "after", run SciGuard's deterministic loop, and
compare against the hand-labelled ground truth.

Impact analysis is measured over the distinct change-site datasets (the cone
depends only on lineage, not on the mutation) with THREE real arms:
  - WITH DataHub: trace_initial_scope (lineage traversal)
  - SEARCH-ONLY DataHub: impact_via_search (catalog search, no lineage graph)
  - NO DataHub: an explicit zero-context abstention with no catalog object or call
The first two are executed against DataHub. The third proves what remains when the
context graph is prohibited; no number is hardcoded.

The harness GATES: main() exits non-zero if any headline metric regresses, so a
    broken (e.g. over-broad) impact mapper fails the evaluation instead of
silently keeping a perfect-looking score.

Run from the repo root:  PYTHONPATH=. python evaluation/harness.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core.impact import impact_via_search, trace_initial_scope
from core.profiles import load_profile
from core.sentinel import Snapshot, assess, detect_changes
from datahub_client import metadata_reader as reader
from datahub_client.backends import SdkReader
from evaluation.metrics import PRF, aggregate, counts

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "evaluation" / "scenarios.json"
GOLDEN_REPORT = ROOT / "examples" / "outputs" / "evaluation_report.md"
GOLDEN_JSON_REPORT = ROOT / "examples" / "outputs" / "evaluation_report.json"
PUBLIC_JSON_REPORT = ROOT / "web" / "public" / "evidence" / "evaluation_report.json"
DEFAULT_REPORT = ROOT / "evaluation" / "outputs" / "evaluation_report.md"
DEFAULT_JSON_REPORT = ROOT / "evaluation" / "outputs" / "evaluation_report.json"
DEFAULT_PERFORMANCE_REPORT = ROOT / "evaluation" / "outputs" / "evaluation_performance.md"
PLATFORM = "polymer_rnd"


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env="PROD")


def _read_before(backend, dataset: str) -> Snapshot:
    urn = _urn(dataset)
    return Snapshot(
        fields={f["path"]: (f["nativeType"] or "") for f in backend.get_schema_fields(urn)},
        units=backend.get_units(urn),
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


def impact_without_datahub() -> set[str]:
    """Return an explicit abstention; this arm has no backend object to call."""

    return set()


def run() -> dict:
    spec = json.loads(SCENARIOS.read_text())
    cones = spec["cones"]
    backend = SdkReader(reader.connect())

    # Per-scenario: detection, severity, false-alarm, latency, control targeting.
    rows = []
    for sc in spec["scenarios"]:
        dataset, expected, cone = sc["dataset"], sc["expected"], cones[sc["dataset"]]
        before = _read_before(backend, dataset)
        after = _apply(before, sc["mutations"])

        t0 = time.perf_counter()
        changes = detect_changes(before, after)
        affected = trace_initial_scope(backend, _urn(dataset))
        profile = load_profile(sc["profile"])
        assessment = assess(profile, changes, affected)
        control_targets = {item.urn for item in assessment.affected if item.role == "model"}
        latency_ms = (time.perf_counter() - t0) * 1000.0

        detected = {(c.kind.value, c.field) for c in changes}
        rows.append(
            {
                "id": sc["id"],
                "is_positive": expected["severity"] != "none",
                "detect_ok": detected == {tuple(x) for x in expected["changes"]},
                "severity_ok": assessment.overall_severity == expected["severity"],
                "actionable": assessment.is_actionable,
                "owner": counts(set(assessment.responsible_owners), set(cone["owners"])),
                "control_ok": control_targets == {_urn(n) for n in cone["control_targets"]},
                "latency_ms": latency_ms,
            }
        )

    # Impact analysis over the DISTINCT change sites (cone depends on lineage,
    # not on the mutation), each scored with two real runs.
    impact = []
    for dataset in {sc["dataset"] for sc in spec["scenarios"] if cones.get(sc["dataset"])}:
        expected = set(cones[dataset]["affected"])
        lineage_names = {e.name for e in trace_initial_scope(backend, _urn(dataset))}
        search_names = set(impact_via_search(backend, dataset, platform=PLATFORM))
        no_datahub_names = impact_without_datahub()
        impact.append(
            {
                "dataset": dataset,
                "expected": expected,
                "lineage": counts(lineage_names, expected),
                "lineage_exact": lineage_names == expected,
                "search": counts(search_names, expected),
                "search_exact": search_names == expected,
                "search_false_positives": sorted(search_names - expected),
                "no_datahub": counts(no_datahub_names, expected),
                "no_datahub_exact": no_datahub_names == expected,
                "no_datahub_predictions": len(no_datahub_names),
                "no_datahub_call_count": 0,
            }
        )

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
    control_ok = sum(r["control_ok"] for r in pos)
    lineage = aggregate([i["lineage"] for i in impact])
    search = aggregate([i["search"] for i in impact])
    lineage_exact = sum(i["lineage_exact"] for i in impact)
    search_exact = sum(i["search_exact"] for i in impact)
    no_datahub = aggregate([i["no_datahub"] for i in impact])
    no_datahub_exact = sum(i["no_datahub_exact"] for i in impact)
    no_datahub_predictions = sum(i["no_datahub_predictions"] for i in impact)
    search_fps = sorted({fp for i in impact for fp in i["search_false_positives"]})

    lines = ["# SciGuard evaluation report", ""]
    lines.append(
        "> Controlled synthetic benchmark on hand-labelled scenarios. Lineage and "
        "search-only arms execute against DataHub; the no-DataHub arm receives no "
        "backend and explicitly abstains. No number is hardcoded."
    )
    lines.append("")
    lines.append(f"- scenarios: {len(rows)} ({len(pos)} actionable, {len(neg)} negative controls)")
    lines.append(
        f"- change detection accuracy: {_pct(detect_ok / len(rows))} ({detect_ok}/{len(rows)})"
    )
    lines.append(
        f"- risk-severity accuracy: {_pct(severity_ok / len(rows))} ({severity_ok}/{len(rows)})"
    )
    lines.append(
        f"- false-alarm rate on negatives: {_pct(false_alarms / len(neg))} ({false_alarms}/{len(neg)})"
    )
    lines.append(
        f"- owner-notification precision/recall: {_pct(owner.precision)} / {_pct(owner.recall)}"
    )
    lines.append(
        f"- model control targeting: {_pct(control_ok / len(pos))} ({control_ok}/{len(pos)})"
    )
    lines.append("")
    lines.append(f"## Impact analysis over {len(impact)} distinct lineage cones")
    lines.append("| approach | precision | recall | F1 | exact cone |")
    lines.append("|---|---|---|---|---|")
    lines.append(
        f"| WITH DataHub lineage | {_pct(lineage.precision)} | {_pct(lineage.recall)} | "
        f"{_pct(lineage.f1)} | {lineage_exact}/{len(impact)} |"
    )
    lines.append(
        f"| SEARCH-ONLY DataHub (without lineage) | {_pct(search.precision)} | "
        f"{_pct(search.recall)} | "
        f"{_pct(search.f1)} | {search_exact}/{len(impact)} |"
    )
    lines.append(
        f"| NO DataHub (zero-context abstention) | N/A ({no_datahub_predictions} predictions) | "
        f"{_pct(no_datahub.recall)} | {_pct(no_datahub.f1)} | "
        f"{no_datahub_exact}/{len(impact)} |"
    )
    lines.append("")
    lines.append("The no-lineage search baseline cannot tell dependency direction, so it")
    lines.append(
        f"flags upstream/sibling datasets as affected (false positives: {search_fps or 'none'})."
    )
    lines.append("Only lineage recovers the exact downstream cone with correct direction.")
    lines.append(
        "With DataHub access prohibited, SciGuard has no defensible dependency or owner "
        "context and abstains rather than inventing an impact cone."
    )
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


def summarize_performance(result: dict) -> str:
    """Render timing separately so the deterministic golden remains stable."""

    rows = result["rows"]
    mean_latency = sum(r["latency_ms"] for r in rows) / len(rows)
    lines = [
        "# SciGuard evaluation performance sample",
        "",
        (
            "> NON-DETERMINISTIC: wall-clock timings vary by machine, load, and DataHub state. "
            "This file is never used as a correctness gate or curated golden."
        ),
        "",
        f"- scenarios: {len(rows)}",
        f"- mean per-scenario: {mean_latency:.1f} ms",
        "",
        "| scenario | latency (ms) |",
        "|---|---:|",
    ]
    lines.extend(f"| {row['id']} | {row['latency_ms']:.1f} |" for row in rows)
    return "\n".join(lines) + "\n"


def machine_report(result: dict) -> dict:
    """Return the deterministic, UI-consumable form of the gated evaluation."""

    rows, impact = result["rows"], result["impact"]
    positive = [row for row in rows if row["is_positive"]]
    negative = [row for row in rows if not row["is_positive"]]
    lineage = aggregate([item["lineage"] for item in impact])
    search = aggregate([item["search"] for item in impact])
    no_datahub = aggregate([item["no_datahub"] for item in impact])
    owner = aggregate([row["owner"] for row in positive])
    failures = gate(result)

    def metric(raw: PRF) -> dict:
        return {
            **raw.model_dump(mode="json"),
            "precision": round(raw.precision, 10),
            "recall": round(raw.recall, 10),
            "f1": round(raw.f1, 10),
        }

    return {
        "schema_version": 1,
        "capture_type": "CONTROLLED_DATAHUB_ABLATION",
        "benchmark": {
            "scenario_count": len(rows),
            "actionable_count": len(positive),
            "negative_control_count": len(negative),
            "distinct_lineage_cones": len(impact),
            "scenario_spec_sha256": hashlib.sha256(SCENARIOS.read_bytes()).hexdigest(),
        },
        "headline": {
            "change_detection_accuracy": sum(row["detect_ok"] for row in rows) / len(rows),
            "risk_severity_accuracy": sum(row["severity_ok"] for row in rows) / len(rows),
            "false_alarm_rate": sum(row["actionable"] for row in negative) / len(negative),
            "owner_notification": metric(owner),
            "model_control_accuracy": sum(row["control_ok"] for row in positive) / len(positive),
        },
        "impact_arms": [
            {
                "id": "full-lineage",
                "label": "WITH DATAHUB LINEAGE",
                **metric(lineage),
                "exact_cones": sum(item["lineage_exact"] for item in impact),
                "total_cones": len(impact),
                "datahub_calls_permitted": True,
                "lineage_permitted": True,
                "status": "VERIFIED",
            },
            {
                "id": "search-only",
                "label": "SEARCH-ONLY DATAHUB",
                **metric(search),
                "exact_cones": sum(item["search_exact"] for item in impact),
                "total_cones": len(impact),
                "datahub_calls_permitted": True,
                "lineage_permitted": False,
                "status": "INCOMPLETE CONTEXT",
            },
            {
                "id": "no-datahub",
                "label": "NO DATAHUB",
                **metric(no_datahub),
                "precision": None,
                "exact_cones": sum(item["no_datahub_exact"] for item in impact),
                "total_cones": len(impact),
                "predictions": sum(item["no_datahub_predictions"] for item in impact),
                "datahub_call_count": sum(item["no_datahub_call_count"] for item in impact),
                "datahub_calls_permitted": False,
                "lineage_permitted": False,
                "status": "MEASURED ABSTENTION",
            },
        ],
        "scenario_results": [
            {
                "id": row["id"],
                "is_positive": row["is_positive"],
                "detect_ok": row["detect_ok"],
                "severity_ok": row["severity_ok"],
                "actionable": row["actionable"],
                "owner": metric(row["owner"]),
                "control_ok": row["control_ok"],
            }
            for row in rows
        ],
        "gate": {
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
        },
    }


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
    if not all(r["control_ok"] for r in pos):
        failures.append("model control targeting regressed on an actionable scenario")
    return failures


def _output_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORT),
        help="deterministic report destination (default: ignored evaluation/outputs)",
    )
    parser.add_argument(
        "--performance-output",
        default=str(DEFAULT_PERFORMANCE_REPORT),
        help="non-deterministic timing report destination",
    )
    parser.add_argument(
        "--json-output",
        default=str(DEFAULT_JSON_REPORT),
        help="deterministic machine-readable report destination",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="explicitly refresh examples/outputs/evaluation_report.md",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    result = run()
    report = summarize(result)
    output = _output_path(args.output)
    json_output = _output_path(args.json_output)
    performance_output = _output_path(args.performance_output)
    if output.resolve() == GOLDEN_REPORT.resolve() and not args.update_golden:
        raise SystemExit("Refusing to overwrite the curated golden without --update-golden")

    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    performance_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    raw_machine_report = json.dumps(machine_report(result), indent=2, sort_keys=True) + "\n"
    json_output.write_text(raw_machine_report, encoding="utf-8")
    performance_output.write_text(
        summarize_performance(result),
        encoding="utf-8",
    )
    if args.update_golden:
        GOLDEN_REPORT.write_text(report, encoding="utf-8")
        GOLDEN_JSON_REPORT.write_text(raw_machine_report, encoding="utf-8")
        PUBLIC_JSON_REPORT.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_JSON_REPORT.write_text(raw_machine_report, encoding="utf-8")

    print(report)
    print(f"(deterministic report written to {_display_path(output)})")
    print(f"(machine report written to {_display_path(json_output)})")
    print(f"(non-deterministic performance sample written to {_display_path(performance_output)})")
    if args.update_golden:
        print(f"(curated golden updated at {_display_path(GOLDEN_REPORT)})")

    failures = gate(result)
    if failures:
        print("\nEVALUATION FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nEVALUATION PASSED")


if __name__ == "__main__":
    main()
