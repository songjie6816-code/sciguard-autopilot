"""DataHub impact analysis at two deliberate levels of precision.

Sentinel uses dataset-level lineage to create a conservative initial review
scope. The investigation later follows fine-grained field lineage to prove the
affected branch and preserve unrelated work.
"""

from __future__ import annotations

from datahub.emitter.mce_builder import make_schema_field_urn
from pydantic import BaseModel

from core.policy_engine import AssetPolicyContext


class AffectedEntity(BaseModel):
    urn: str
    name: str | None
    role: str
    degree: int
    owners: list[str] = []


class FieldImpact(BaseModel):
    source_urn: str
    source_fields: list[str]
    affected_urns: list[str]
    affected_names: list[str]
    unaffected_urns: list[str]
    unaffected_names: list[str]
    tainted_field_urns: list[str]


def _infer_role(entity_type: str | None, name: str | None) -> str:
    entity = (entity_type or "").upper()
    normalized = (name or "").lower()
    if "MLMODEL" in entity or "model" in normalized:
        return "model"
    if "candidate" in normalized or "ranking" in normalized:
        return "decision_report"
    if entity in {"DASHBOARD", "CHART"} or "dashboard" in normalized:
        return "dashboard"
    if "report" in normalized:
        return "report"
    return "dataset"


def trace_initial_scope(backend, changed_urn: str) -> list[AffectedEntity]:
    """Return the conservative downstream review scope used by Sentinel."""

    return [
        AffectedEntity(
            urn=hit.urn,
            name=hit.name,
            role=_infer_role(hit.entity_type, hit.name),
            degree=hit.degree,
            owners=backend.get_owners(hit.urn),
        )
        for hit in backend.get_all_downstream(changed_urn)
    ]


def impact_via_search(
    backend,
    changed_name: str,
    platform: str | None = None,
) -> list[str]:
    """Search-only ablation with no lineage direction or hop information."""

    return [
        hit.name
        for hit in backend.search_datasets(query=changed_name, count=100)
        if hit.name
        and hit.name != changed_name
        and (platform is None or hit.platform == platform)
    ]


def trace_field_impact(
    backend,
    source_urn: str,
    source_fields: list[str],
) -> FieldImpact:
    """Follow only fine-grained edges fed by the contaminated source fields."""

    downstream = backend.get_all_downstream(source_urn)
    tainted = {make_schema_field_urn(source_urn, field) for field in source_fields}
    affected_urns = [source_urn]
    source_name = source_urn.rsplit(",", 2)[-2]
    affected_names = [source_name]
    unaffected_urns: list[str] = []
    unaffected_names: list[str] = []

    for hit in sorted(downstream, key=lambda item: item.degree):
        edges = backend.get_fine_grained_lineage(hit.urn)
        propagated = {
            downstream_field
            for upstream_field, downstream_field in edges
            if upstream_field in tainted
        }
        if propagated:
            tainted.update(propagated)
            affected_urns.append(hit.urn)
            affected_names.append(hit.name or hit.urn)
        else:
            unaffected_urns.append(hit.urn)
            unaffected_names.append(hit.name or hit.urn)
    return FieldImpact(
        source_urn=source_urn,
        source_fields=source_fields,
        affected_urns=affected_urns,
        affected_names=affected_names,
        unaffected_urns=unaffected_urns,
        unaffected_names=unaffected_names,
        tainted_field_urns=sorted(tainted),
    )


def build_policy_contexts(
    backend,
    impact: FieldImpact,
    additional_affected_urns: list[str] | None = None,
) -> list[AssetPolicyContext]:
    """Turn proven field impact plus live catalog properties into policy inputs."""

    affected = set(impact.affected_urns) | set(additional_affected_urns or [])
    urns = list(
        dict.fromkeys(
            [
                *impact.affected_urns,
                *impact.unaffected_urns,
                *(additional_affected_urns or []),
            ]
        )
    )
    contexts = []
    for urn in urns:
        context = backend.get_asset_context(urn)
        properties = context["properties"]
        contexts.append(
            AssetPolicyContext(
                urn=urn,
                name=context["name"],
                role=properties.get("entity_role", "dataset"),
                criticality=properties.get("sciguard:criticality", "UNKNOWN"),
                affected=urn in affected,
            )
        )
    return contexts
