import pytest
from datahub.emitter.mce_builder import make_dataset_urn

from core.coordinator import Coordinator, EvidencePendingError, HypothesisStatus
from core.events import EventActor, EventRecorder, EventType
from core.investigation_models import Evidence, InvestigationResult, RealityCheckResult
from data.synthetic_polymer import generate


SYMPTOM = (
    "Candidate P-204 moved from rank #18 to #1 after last night's batch. "
    "No pipeline failed. Investigate before the morning selection meeting."
)


def _evidence(source: str, kind: str, payload: dict) -> Evidence:
    return Evidence.create(source=source, kind=kind, summary=kind, payload=payload)


def _catalog(*, available: bool = True) -> InvestigationResult:
    if not available:
        return InvestigationResult(
            available=False,
            start_urn="urn:report",
            evidence=[
                _evidence(
                    "DATAHUB_CATALOG",
                    "DATAHUB_UNAVAILABLE",
                    {"error": "DataHub unavailable"},
                )
            ],
            degraded_reason="DataHub unavailable",
        )
    return InvestigationResult(
        available=True,
        start_urn="urn:report",
        assets=[],
        suspect_sources=["instrument_batch_B042"],
        evidence=[
            _evidence(
                "DATAHUB_CATALOG",
                "UPSTREAM_LINEAGE",
                {
                    "asset_names": [
                        "candidate_ranking_report",
                        "tg_prediction_model",
                        "raw_polymer_experiments",
                        "instrument_batch_B042",
                    ],
                    "suspect_sources": ["instrument_batch_B042"],
                },
            ),
            _evidence(
                "DATAHUB_CATALOG",
                "MODEL_RELEASE_CONTEXT",
                {"model_version": "tg-gbr-v3", "code_version": "ranker-2026.07"},
            ),
        ],
    )


def _reality() -> RealityCheckResult:
    return RealityCheckResult(
        available=True,
        evidence=[
            _evidence(
                "LOCAL_ARTIFACT",
                "TRUSTED_RELEASE_BASELINE",
                {"model_version": "tg-gbr-v3", "code_version": "ranker-2026.07"},
            ),
            _evidence(
                "LOCAL_ARTIFACT",
                "UNIT_FIRMWARE_CONTRACT",
                {
                    "contract_passed": False,
                    "affected_rows": 187,
                    "affected_batches": ["B042"],
                    "trusted_firmware": ["v4.1"],
                    "current_firmware": ["v4.2"],
                    "observed_units": ["degC", "K"],
                    "expected_unit": "degC",
                    "normalization_versions": ["tg-normalizer-v1"],
                },
            ),
            _evidence(
                "LOCAL_ARTIFACT",
                "RANK_BASELINE_COMPARISON",
                {
                    "candidate_id": "P-204",
                    "rank_before": 18,
                    "rank_after": 1,
                    "pipeline_status": "SUCCESS",
                },
            ),
            _evidence(
                "LOCAL_ARTIFACT",
                "EXPERIMENTAL_VALUE_CHECK",
                {
                    "candidate_true_delta_degc": 0.0,
                    "all_converted_values_match_baseline": True,
                },
            ),
        ],
    )


def test_coordinator_opens_three_distinct_contracts_from_symptom_only() -> None:
    recorder = EventRecorder("inc-coordinate")
    case = Coordinator(recorder=recorder).open_case("inc-coordinate", SYMPTOM)
    assert case.candidate_id == "P-204"
    assert (case.rank_before, case.rank_after) == (18, 1)
    assert [hypothesis.id for hypothesis in case.hypotheses] == ["H1", "H2", "H3"]
    assert len({h.investigation_contract for h in case.hypotheses}) == 3
    assert [event.event_type for event in recorder.events] == [
        EventType.HYPOTHESIS_PROPOSED,
        EventType.HYPOTHESIS_PROPOSED,
        EventType.HYPOTHESIS_PROPOSED,
    ]


def test_coordinator_cannot_resolve_before_both_evidence_classes_return() -> None:
    coordinator = Coordinator()
    case = coordinator.open_case("inc-pending", SYMPTOM)
    with pytest.raises(EvidencePendingError):
        coordinator.resolve(case, catalog=None, reality=_reality())
    with pytest.raises(EvidencePendingError):
        coordinator.resolve(case, catalog=_catalog(), reality=None)


def test_coordinator_resolves_flagship_only_by_combining_independent_evidence() -> None:
    recorder = EventRecorder("inc-resolve")
    coordinator = Coordinator(recorder=recorder)
    case = coordinator.open_case("inc-resolve", SYMPTOM)
    report = coordinator.resolve(case, catalog=_catalog(), reality=_reality())

    assert {item.hypothesis_id: item.status for item in report.resolutions} == {
        "H1": HypothesisStatus.REJECTED,
        "H2": HypothesisStatus.CONFIRMED,
        "H3": HypothesisStatus.REJECTED,
    }
    assert report.root_cause_confirmed
    assert report.root_cause.batch_id == "B042"
    assert report.root_cause.affected_rows == 187
    assert all(item.evidence_ids for item in report.resolutions)
    resolved_events = [
        event for event in recorder.events if event.event_type is EventType.HYPOTHESIS_RESOLVED
    ]
    assert len(resolved_events) == 3
    assert all(event.actor is EventActor.COORDINATOR for event in resolved_events)


def test_no_datahub_never_fabricates_lineage_or_confirms_root_cause() -> None:
    coordinator = Coordinator()
    case = coordinator.open_case("inc-degraded", SYMPTOM)
    report = coordinator.resolve(case, catalog=_catalog(available=False), reality=_reality())
    assert report.degraded
    assert not report.root_cause_confirmed
    assert report.root_cause is None
    assert all(item.status is HypothesisStatus.INCONCLUSIVE for item in report.resolutions)
    assert all(item.evidence_ids for item in report.resolutions)
    assert "DataHub unavailable" in report.degraded_reason


class FlagshipCatalog:
    def get_all_upstream(self, urn):
        names = [
            "tg_prediction_model",
            "tg_feature_table",
            "cleaned_polymer_dataset",
            "raw_polymer_experiments",
            "instrument_batch_B042",
        ]
        return [
            type("Hit", (), {"urn": make_dataset_urn("polymer_rnd", name, "PROD"), "degree": i})
            for i, name in enumerate(names, 1)
        ]

    def get_asset_context(self, urn):
        name = urn.rsplit(",", 2)[-2]
        properties = {"entity_role": "dataset"}
        if name == "tg_prediction_model":
            properties.update(
                entity_role="model",
                model_version="tg-gbr-v3",
                code_version="ranker-2026.07",
            )
        if name == "instrument_batch_B042":
            properties.update(entity_role="source_batch", instrument_firmware="v4.2")
        return {
            "urn": urn,
            "name": name,
            "owners": ["owner"],
            "tags": ["urn:li:tag:synthetic"],
            "terms": [],
            "properties": properties,
            "assertion_history": [],
            "assertions_supported": True,
        }


def test_only_symptom_input_drives_full_bounded_investigation(tmp_path) -> None:
    generate.build(tmp_path)
    recorder = EventRecorder("inc-full")
    report = Coordinator(recorder=recorder).run_investigation(
        "inc-full", SYMPTOM, backend=FlagshipCatalog(), data_dir=tmp_path
    )

    assert report.root_cause_confirmed
    assert report.root_cause.batch_id == "B042"
    assert {event.actor for event in recorder.events} >= {
        EventActor.COORDINATOR,
        EventActor.SCIENTIFIC_INVESTIGATOR,
        EventActor.REALITY_CHECKER,
    }
