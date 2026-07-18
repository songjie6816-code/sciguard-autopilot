"""End-to-end SciGuard demo: Tg unit change -> impact analysis -> write-back.

Deterministic loop (no LLM):
  1. Read the incident's incoming snapshot.
  2. Read the "before" state (schema + units) live from DataHub.
  3. Detect changes.
  4. Walk DataHub lineage for the downstream impact cone.
  5. Score risk against the polymer domain profile.
  6. Build a remediation plan and Markdown report.
  7. Write trusted context back to DataHub: a model-at-risk tag and an incident
     summary on the affected model, plus the report to examples/outputs/.

Run from the repo root:  PYTHONPATH=. python examples/run_tg_unit_incident.py
"""

from __future__ import annotations

import json
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core import remediation
from core.change_detector import Snapshot, detect_changes
from core.lineage_analyzer import analyze_impact
from core.profiles import load_profile
from core.risk_engine import assess
from datahub_client import metadata_reader as reader
from datahub_client import metadata_writer as writer

ROOT = Path(__file__).resolve().parents[1]
INCIDENT = ROOT / "examples" / "incidents" / "tg_unit_change.json"
OUTPUT = ROOT / "examples" / "outputs" / "tg_unit_change_report.md"
PLATFORM = "polymer_rnd"
RISK_TAG = "urn:li:tag:sciguard:model-at-risk"


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env="PROD")


def main() -> None:
    incident = json.loads(INCIDENT.read_text())
    changed_name = incident["dataset"]
    changed_urn = _urn(changed_name)

    graph = reader.connect()

    # "before" from DataHub is the source of truth.
    before = Snapshot(
        fields={f["path"]: (f["nativeType"] or "") for f in reader.get_schema_fields(graph, changed_urn)},
        units=reader.get_units(graph, changed_urn),
    )
    if not before.fields:
        raise SystemExit(
            f"'{changed_name}' has no schema in DataHub ({changed_urn}). "
            "Run data/synthetic_polymer/ingest_to_datahub.py first; refusing to "
            "report an all-clear against an empty before-state."
        )
    after = Snapshot(**incident["after"])

    changes = detect_changes(before, after)
    print(f"[1] changes detected: {len(changes)}")
    for c in changes:
        print(f"      - {c.describe()}")

    affected = analyze_impact(graph, changed_urn)
    print(f"[2] downstream affected: {len(affected)}")

    profile = load_profile(incident.get("profile", "polymer"))
    assessment = assess(profile, changes, affected)
    print(f"[3] overall severity: {assessment.overall_severity.upper()}"
          f"  (actionable={assessment.is_actionable})")
    print(f"      owners to notify: {assessment.responsible_owners}")

    plan = remediation.build_plan(profile, assessment, changed_name)
    report = remediation.render_report(changed_name, assessment, plan)
    OUTPUT.write_text(report)
    print(f"[4] report written: {OUTPUT.relative_to(ROOT)}")

    # Write trusted context back to DataHub.
    if assessment.is_actionable:
        for target in plan.tag_targets:
            tags = writer.add_tags(graph, target, [RISK_TAG])
            writer.add_custom_properties(
                graph,
                target,
                {
                    "sciguard:status": "model-at-risk",
                    "sciguard:severity": assessment.overall_severity,
                    "sciguard:incident": incident["incident_id"],
                    "sciguard:reason": changes[0].describe() if changes else "",
                },
            )
            print(f"[5] write-back on {target.split(',')[-2]}: tags={tags}")
    else:
        print("[5] severity below threshold; no write-back")

    print("\n--- report preview ---")
    print(report)


if __name__ == "__main__":
    main()
