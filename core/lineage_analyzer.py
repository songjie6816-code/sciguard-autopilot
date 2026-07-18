"""Resolve multi-hop impact using DataHub lineage context.

Given the dataset where a change occurred, walk the downstream cone and attach
each affected entity's owner and inferred role (model / report / dataset). This
is the step that only DataHub can make reliable: without the lineage graph, a
change on a raw table cannot be connected to the model and report it silently
breaks.
"""

from __future__ import annotations

from pydantic import BaseModel

from datahub_client import metadata_reader as reader


class AffectedEntity(BaseModel):
    urn: str
    name: str | None
    role: str            # "model" | "report" | "dataset"
    degree: int          # hops from the change site
    owners: list[str] = []


def _infer_role(entity_type: str | None, name: str | None) -> str:
    """Prefer DataHub's authoritative entity type; fall back to the name.

    Once real mlModel/dashboard entities exist, the type decides; while the demo
    models everything as datasets, the name still distinguishes model vs report.
    """
    et = (entity_type or "").upper()
    if "MLMODEL" in et:
        return "model"
    if et in {"DASHBOARD", "CHART"}:
        return "report"
    n = (name or "").lower()
    if "model" in n:
        return "model"
    if any(k in n for k in ("report", "ranking", "candidate")):
        return "report"
    return "dataset"


def analyze_impact(graph, changed_urn: str) -> list[AffectedEntity]:
    """Return every downstream entity affected by a change at `changed_urn`,
    ordered by lineage distance and annotated with role and owners."""
    affected: list[AffectedEntity] = []
    for hit in reader.get_all_downstream(graph, changed_urn):
        affected.append(
            AffectedEntity(
                urn=hit.urn,
                name=hit.name,
                role=_infer_role(hit.entity_type, hit.name),
                degree=hit.degree,
                owners=reader.get_owners(graph, hit.urn),
            )
        )
    return affected
