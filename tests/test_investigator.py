from types import SimpleNamespace

from core.events import EventActor, EventRecorder, EventType
from core.investigator import ScientificInvestigator


class FakeCatalog:
    def get_all_upstream(self, urn):
        return [
            SimpleNamespace(urn="urn:model", name="tg_prediction_model", degree=1),
            SimpleNamespace(urn="urn:raw", name="raw_polymer_experiments", degree=3),
            SimpleNamespace(urn="urn:batch", name="instrument_batch_B042", degree=4),
        ]

    def get_asset_context(self, urn):
        names = {
            "urn:report": "candidate_ranking_report",
            "urn:model": "tg_prediction_model",
            "urn:raw": "raw_polymer_experiments",
            "urn:batch": "instrument_batch_B042",
        }
        properties = {}
        if urn == "urn:model":
            properties = {"model_version": "tg-gbr-v3", "code_version": "ranker-2026.07"}
        if urn == "urn:batch":
            properties = {"batch_id": "B042", "instrument_firmware": "v4.2"}
        return {
            "urn": urn,
            "name": names[urn],
            "owners": ["owner"],
            "tags": ["urn:li:tag:synthetic"],
            "terms": [],
            "properties": properties,
            "assertion_history": [],
            "assertions_supported": True,
        }


def test_investigator_traces_report_back_to_batch_and_reads_governance() -> None:
    recorder = EventRecorder("inc-investigate")
    result = ScientificInvestigator(FakeCatalog(), recorder).investigate("urn:report")

    assert result.available
    assert [asset.name for asset in result.assets] == [
        "candidate_ranking_report",
        "tg_prediction_model",
        "raw_polymer_experiments",
        "instrument_batch_B042",
    ]
    assert result.suspect_sources == ["instrument_batch_B042"]
    model = next(asset for asset in result.assets if asset.name == "tg_prediction_model")
    assert model.properties["model_version"] == "tg-gbr-v3"
    assert model.owners == ["owner"]
    assert model.tags
    assert model.terms == []
    assert model.assertion_history == []
    assert {e.kind for e in result.evidence} == {
        "UPSTREAM_LINEAGE",
        "MODEL_RELEASE_CONTEXT",
        "CATALOG_GOVERNANCE_CONTEXT",
    }
    assert all(e.source == "DATAHUB_CATALOG" for e in result.evidence)
    assert recorder.events[-1].actor is EventActor.SCIENTIFIC_INVESTIGATOR
    assert recorder.events[-1].event_type is EventType.EVIDENCE_OBSERVED


class BrokenCatalog:
    def get_all_upstream(self, urn):
        raise ConnectionError("DataHub is offline")


def test_investigator_returns_explicit_degraded_result_without_datahub() -> None:
    result = ScientificInvestigator(BrokenCatalog()).investigate("urn:report")
    assert not result.available
    assert result.assets == []
    assert [item.kind for item in result.evidence] == ["DATAHUB_UNAVAILABLE"]
    assert "DataHub" in result.degraded_reason
    assert "offline" in result.degraded_reason
