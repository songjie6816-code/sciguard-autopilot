from core.coordinator import Coordinator
from core.events import EventActor, EventRecorder, EventType
from core.reality_checker import RealityChecker
from data.synthetic_polymer import generate


SYMPTOM = (
    "Candidate P-204 moved from rank #18 to #1 after last night's batch. "
    "No pipeline failed. Investigate before the morning selection meeting."
)


def test_reality_checker_finds_exact_unit_firmware_drift(tmp_path) -> None:
    generate.build(tmp_path)
    case = Coordinator().open_case("inc-reality", SYMPTOM)
    recorder = EventRecorder("inc-reality-events")
    result = RealityChecker(tmp_path, recorder).check(case)

    assert result.available
    evidence = {item.kind: item for item in result.evidence}
    rank = evidence["RANK_BASELINE_COMPARISON"].payload
    unit = evidence["UNIT_FIRMWARE_CONTRACT"].payload
    experiment = evidence["EXPERIMENTAL_VALUE_CHECK"].payload
    release = evidence["TRUSTED_RELEASE_BASELINE"].payload

    assert rank["candidate_id"] == "P-204"
    assert (rank["rank_before"], rank["rank_after"]) == (18, 1)
    assert rank["pipeline_status"] == "SUCCESS"
    assert unit["contract_passed"] is False
    assert unit["affected_rows"] == 187
    assert unit["affected_batches"] == ["B042"]
    assert unit["trusted_firmware"] == ["v4.1"]
    assert unit["current_firmware"] == ["v4.2"]
    assert experiment["candidate_true_delta_degc"] == 0.0
    assert experiment["all_converted_values_match_baseline"] is True
    assert release["model_version"] == "tg-gbr-v3"
    assert recorder.events[-1].actor is EventActor.REALITY_CHECKER
    assert recorder.events[-1].event_type is EventType.EVIDENCE_OBSERVED


def test_reality_checker_missing_artifacts_is_explicitly_degraded(tmp_path) -> None:
    case = Coordinator().open_case("inc-missing", SYMPTOM)
    result = RealityChecker(tmp_path).check(case)
    assert not result.available
    assert [item.kind for item in result.evidence] == ["ARTIFACTS_UNAVAILABLE"]
    assert "missing" in result.degraded_reason.lower()
