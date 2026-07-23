import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _scenario_spec() -> dict:
    return json.loads((ROOT / "evaluation" / "scenarios.json").read_text())


def test_required_project_assets_exist() -> None:
    required = [
        "LICENSE",
        "README.md",
        ".env.example",
        "domain_profiles/generic.yaml",
        "domain_profiles/materials.yaml",
        "domain_profiles/polymer.yaml",
    ]
    assert all((ROOT / path).is_file() for path in required)


def test_wp0_protocol_contract_is_complete_and_unambiguous() -> None:
    contract = _scenario_spec()["contract"]
    event = contract["event"]

    assert contract["schema_version"] == "1.0"
    assert event["required_fields"] == list(event["fields"])
    assert len(event["event_types"]) == len(set(event["event_types"]))
    assert len(event["actors"]) == len(set(event["actors"]))
    assert contract["policy_decisions"] == ["HALT", "WARN", "ALLOW"]

    states = contract["incident_states"]
    assert states == [
        "HEALTHY",
        "DETECTED",
        "INVESTIGATING",
        "AT_RISK",
        "QUARANTINED",
        "RECOVERY_PENDING",
        "RESOLVED",
    ]
    assert len(states) == len(set(states))
    assert all(source in states and target in states for source, target in contract["transitions"])
    assert not any(source == "RESOLVED" for source, _ in contract["transitions"])


def test_wp0_flagship_ground_truth_freezes_selective_containment() -> None:
    spec = _scenario_spec()
    contract = spec["contract"]
    flagship = spec["flagship"]
    assets = {asset["name"]: asset for asset in flagship["assets"]}

    assert flagship["input"]["candidate_id"] == "P-204"
    assert flagship["input"]["rank_before"] == 18
    assert flagship["input"]["rank_after"] == 1
    assert flagship["root_cause"]["batch_id"] == "B042"
    assert flagship["root_cause"]["affected_rows"] == 187
    assert len(assets) == len(flagship["assets"])
    assert all(asset["owner"] for asset in assets.values())
    assert all(asset["criticality"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
               for asset in assets.values())
    assert all(asset["expected_decision"] in contract["policy_decisions"]
               for asset in assets.values())
    assert all(asset["expected_catalog_status"] in contract["catalog_statuses"]
               for asset in assets.values())
    assert all(set(asset["enforcement_actions"]) <= set(contract["enforcement_actions"])
               for asset in assets.values())
    assert set(flagship["ground_truth"]["affected"]) | set(
        flagship["ground_truth"]["unaffected"]
    ) == set(assets)
    assert not set(flagship["ground_truth"]["affected"]) & set(
        flagship["ground_truth"]["unaffected"]
    )

    expected_decisions = {
        "instrument_batch_B042": "HALT",
        "tg_prediction_model": "HALT",
        "candidate_ranking_report": "HALT",
        "exploratory_dashboard": "WARN",
        "molecular_weight_feature_table": "ALLOW",
        "durability_model": "ALLOW",
        "formulation_report": "ALLOW",
    }
    assert {name: assets[name]["expected_decision"] for name in expected_decisions} == (
        expected_decisions
    )
    assert set(flagship["ground_truth"]["unaffected"]) == {
        "molecular_weight_feature_table",
        "durability_model",
        "formulation_report",
    }
    assert "BLOCK_PUBLISH" in assets["candidate_ranking_report"]["enforcement_actions"]
    assert "QUARANTINE" in assets["instrument_batch_B042"]["enforcement_actions"]


def test_wp05_presentation_contract_freezes_cinematic_mvp() -> None:
    spec = _scenario_spec()
    contract = spec["contract"]
    presentation = spec["presentation"]
    panel_ids = [panel["id"] for panel in presentation["panels"]]
    beats = presentation["story_beats"]

    assert presentation["schema_version"] == "1.0"
    assert presentation["primary_surface"] == "NEXTJS_COMMAND_CENTER"
    assert presentation["fallback_surface"] == "STREAMLIT"
    assert presentation["modes"] == ["LIVE", "RECORDED_REPLAY"]
    assert panel_ids == [
        "incident_header",
        "rank_shock",
        "agent_timeline",
        "lineage_graph",
        "evidence_board",
        "policy_surface",
        "enforcement_console",
        "recovery_gate",
        "evaluation_theatre",
    ]
    assert len(panel_ids) == len(set(panel_ids))

    assert beats[0]["start_second"] == 0
    assert beats[-1]["end_second"] <= 170
    assert all(left["end_second"] == right["start_second"]
               for left, right in zip(beats, beats[1:]))
    known_event_types = set(contract["event"]["event_types"])
    assert all(set(beat["required_event_types"]) <= known_event_types for beat in beats)
    assert all(set(beat["panels"]) <= set(panel_ids) for beat in beats)

    truth = presentation["truth_rules"]
    assert truth["show_chain_of_thought"] is False
    assert truth["allow_fabricated_metrics"] is False
    assert truth["require_evidence_for_numbers"] is True
    assert truth["live_replay_badge_is_global"] is True
