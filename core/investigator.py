"""DataHub-only reverse-lineage investigation worker."""

from __future__ import annotations

from time import perf_counter_ns

from core.events import EventActor, EventRecorder, EventType
from core.investigation_models import AssetContext, Evidence, InvestigationResult


class ScientificInvestigator:
    """Inspect catalog evidence without reading local scientific data artifacts."""

    def __init__(self, backend, recorder: EventRecorder | None = None) -> None:
        self.backend = backend
        self.recorder = recorder

    def investigate(self, report_urn: str) -> InvestigationResult:
        start = perf_counter_ns()
        try:
            upstream = self.backend.get_all_upstream(report_urn)
            ordered = [(report_urn, 0), *((hit.urn, hit.degree) for hit in upstream)]
            assets = []
            seen: set[str] = set()
            for urn, degree in ordered:
                if urn in seen:
                    continue
                seen.add(urn)
                context = dict(self.backend.get_asset_context(urn))
                context["degree"] = degree
                assets.append(AssetContext.model_validate(context))
        except Exception as exc:  # noqa: BLE001 - boundary must degrade explicitly
            evidence = Evidence.create(
                source="DATAHUB_CATALOG",
                kind="DATAHUB_UNAVAILABLE",
                summary="DataHub context could not be read",
                payload={"error_type": type(exc).__name__, "error": str(exc)},
            )
            self._emit_observation([evidence], start, "DataHub investigation degraded")
            return InvestigationResult(
                available=False,
                start_urn=report_urn,
                evidence=[evidence],
                degraded_reason=f"DataHub context unavailable: {type(exc).__name__}: {exc}",
            )

        suspects = [
            asset.name
            for asset in assets
            if asset.properties.get("entity_role") == "source_batch"
            or asset.name.startswith("instrument_batch_")
        ]
        model = next((asset for asset in assets if asset.properties.get("entity_role") == "model"), None)
        if model is None:
            model = next((asset for asset in assets if "model" in asset.name), None)

        evidence = [
            Evidence.create(
                source="DATAHUB_CATALOG",
                kind="UPSTREAM_LINEAGE",
                summary=f"Reverse lineage reached {len(assets) - 1} upstream assets",
                payload={
                    "start_urn": report_urn,
                    "asset_names": [asset.name for asset in assets],
                    "degrees": {asset.name: asset.degree for asset in assets},
                    "suspect_sources": suspects,
                },
            ),
            Evidence.create(
                source="DATAHUB_CATALOG",
                kind="MODEL_RELEASE_CONTEXT",
                summary="Read current model and code release metadata from DataHub",
                payload={
                    "model_urn": model.urn if model else None,
                    "model_version": model.properties.get("model_version") if model else None,
                    "code_version": model.properties.get("code_version") if model else None,
                },
            ),
            Evidence.create(
                source="DATAHUB_CATALOG",
                kind="CATALOG_GOVERNANCE_CONTEXT",
                summary="Read owners, tags, terms, and assertion history for traced assets",
                payload={
                    "assets": [
                        {
                            "name": asset.name,
                            "owners": asset.owners,
                            "tags": asset.tags,
                            "terms": asset.terms,
                            "assertion_history": asset.assertion_history,
                            "assertions_supported": asset.assertions_supported,
                        }
                        for asset in assets
                    ]
                },
            ),
        ]
        self._emit_observation(evidence, start, "DataHub investigation completed")
        return InvestigationResult(
            available=True,
            start_urn=report_urn,
            assets=assets,
            suspect_sources=suspects,
            evidence=evidence,
        )

    def _emit_observation(
        self, evidence: list[Evidence], start_ns: int, summary: str
    ) -> None:
        if not self.recorder:
            return
        self.recorder.emit(
            actor=EventActor.SCIENTIFIC_INVESTIGATOR,
            event_type=EventType.EVIDENCE_OBSERVED,
            summary=summary,
            evidence_ids=[item.evidence_id for item in evidence],
            duration_ms=max(0, (perf_counter_ns() - start_ns) // 1_000_000),
            payload={"evidence": [item.model_dump(mode="json") for item in evidence]},
        )
