"""SciGuard demo UI.

A judge-facing walkthrough of the loop: pick a scientific-data change, watch
SciGuard read DataHub lineage to find every affected model and report, score the
risk against the domain profile, propose remediation, and write trusted context
back to the catalog. The with/without-DataHub panel shows why the lineage graph
is load-bearing.

Run:  PYTHONPATH=. streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
from datahub.emitter.mce_builder import make_dataset_urn

from core import remediation
from core.change_detector import Snapshot, detect_changes
from core.lineage_analyzer import analyze_impact, impact_via_search
from core.profiles import load_profile
from core.risk_engine import assess
from datahub_client import metadata_reader as reader
from datahub_client import metadata_writer as writer

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = json.loads((ROOT / "evaluation" / "scenarios.json").read_text())
PLATFORM = "polymer_rnd"
RISK_TAG = "urn:li:tag:sciguard:model-at-risk"
SEVERITY_STYLE = {
    "critical": ("🔴", "error"),
    "high": ("🟠", "warning"),
    "medium": ("🟡", "warning"),
    "low": ("🔵", "info"),
    "none": ("🟢", "success"),
}


def _urn(name: str) -> str:
    return make_dataset_urn(platform=PLATFORM, name=name, env="PROD")


@st.cache_resource
def graph():
    return reader.connect()


def describe_mutation(m: dict) -> str:
    op = m["op"]
    if op == "unit":
        return f"unit of `{m['field']}` set to **{m['to']}**"
    if op == "remove_field":
        return f"field `{m['field']}` **removed**"
    if op == "add_field":
        return f"field `{m['field']}` added ({m.get('to', 'string')})"
    if op == "type":
        return f"type of `{m['field']}` changed to {m['to']}"
    if op == "remove_unit":
        return f"unit of `{m['field']}` dropped"
    return json.dumps(m)


def apply_mutations(before: Snapshot, mutations: list[dict]) -> Snapshot:
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


st.set_page_config(page_title="SciGuard", page_icon="🧪", layout="wide")
st.title("🧪 SciGuard")
st.caption(
    "Scientific-data and ML trust agent. It uses DataHub lineage, ownership and "
    "governance to turn a silent upstream change into an accountable impact "
    "analysis and a write-back of trusted context."
)

try:
    g = graph()
except Exception as exc:  # noqa: BLE001
    st.error(f"Cannot reach DataHub GMS. Start the Quickstart first.\n\n{exc}")
    st.stop()

scenarios = SCENARIOS["scenarios"]
labels = {s["id"]: s for s in scenarios}
# Default to a mid-pipeline change so the with/without-DataHub contrast is visible
# (a change at the pipeline root is recoverable even by naive search).
ids = list(labels)
default_index = ids.index("tg-unit-cleaned") if "tg-unit-cleaned" in ids else 0
with st.sidebar:
    st.header("Incident")
    chosen_id = st.selectbox("Scenario", ids, index=default_index)
    sc = labels[chosen_id]
    st.markdown(f"**Change site:** `{sc['dataset']}`")
    for m in sc["mutations"]:
        st.markdown(f"- {describe_mutation(m)}")
    st.caption("Ground truth expected severity: " + sc["expected"]["severity"])

dataset = sc["dataset"]
changed_urn = _urn(dataset)

before = Snapshot(
    fields={f["path"]: (f["nativeType"] or "") for f in reader.get_schema_fields(g, changed_urn)},
    units=reader.get_units(g, changed_urn),
)
after = apply_mutations(before, sc["mutations"])
changes = detect_changes(before, after)
affected = analyze_impact(g, changed_urn)
profile = load_profile(sc["profile"])
assessment = assess(profile, changes, affected)
plan = remediation.build_plan(profile, assessment, dataset)

icon, box = SEVERITY_STYLE.get(assessment.overall_severity, ("", "info"))
getattr(st, box)(
    f"{icon} Overall risk: **{assessment.overall_severity.upper()}** "
    f"— {'actionable' if assessment.is_actionable else 'no action needed'}"
)

c1, c2 = st.columns(2)
with c1:
    st.subheader("1 · Detected change")
    if changes:
        for ch in changes:
            st.markdown(f"- {ch.describe()}")
    else:
        st.markdown("_no material change_")

    st.subheader("2 · Impact via DataHub lineage")
    if affected:
        st.dataframe(
            pd.DataFrame(
                [
                    {"hop": e.degree, "entity": e.name, "role": e.role,
                     "owners": ", ".join(e.owners)}
                    for e in affected
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.markdown("_no downstream entities_")

with c2:
    st.subheader("3 · Rules & owners")
    for f in assessment.findings:
        st.markdown(f"- {f.rationale}")
    if not assessment.findings:
        st.markdown("_no rule matched — this is a benign change_")
    st.markdown("**Owners to notify:** " + (", ".join(assessment.responsible_owners) or "none"))

    st.subheader("4 · Recommended remediation")
    for i, a in enumerate(plan.actions, 1):
        st.markdown(f"{i}. {a}")
    if not plan.actions:
        st.markdown("_none_")

st.divider()
st.subheader("Why DataHub — impact recall with vs without the lineage graph")
expected_cone = set(SCENARIOS["cones"][dataset]["affected"])
lineage_found = {e.name for e in affected}
search_found = set(impact_via_search(g, dataset, platform=PLATFORM))
a1, a2 = st.columns(2)
a1.metric(
    "WITH DataHub lineage",
    f"{len(lineage_found & expected_cone)}/{len(expected_cone)} affected found",
    help="Exact downstream cone, correct direction.",
)
a2.metric(
    "WITHOUT DataHub (catalog search)",
    f"{len(search_found & expected_cone)}/{len(expected_cone)} found",
    delta=f"{len(search_found - expected_cone)} false positives",
    delta_color="inverse",
    help="Search cannot tell direction: it also flags upstream/sibling datasets.",
)
if search_found - expected_cone:
    st.caption("Search false positives (not actually downstream): "
               + ", ".join(sorted(search_found - expected_cone)))

st.divider()
st.subheader("5 · Write trusted context back to DataHub")
if not assessment.is_actionable:
    st.info("Benign change — nothing to write back.")
elif not plan.tag_targets:
    st.info("No model in the impact cone to flag.")
else:
    targets = ", ".join(u.split(",")[-2] for u in plan.tag_targets)
    st.markdown(f"Will flag **{targets}** as `model-at-risk` and attach an incident summary.")
    if st.button("Write back to DataHub", type="primary"):
        for target in plan.tag_targets:
            writer.add_tags(g, target, [RISK_TAG])
            writer.add_custom_properties(
                g,
                target,
                {
                    "sciguard:status": "model-at-risk",
                    "sciguard:severity": assessment.overall_severity,
                    "sciguard:incident": sc["id"],
                    "sciguard:reason": changes[0].describe() if changes else "",
                },
            )
        st.success(f"Wrote model-at-risk tag + incident summary to: {targets}")
        st.caption("Open http://localhost:9002 and search the model to see the tag and properties.")
