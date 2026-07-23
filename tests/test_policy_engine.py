import json
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core.policy_engine import AssetPolicyContext, PolicyDecision, decide
from core.profiles import load_profile


def test_flagship_policy_matches_all_frozen_asset_decisions() -> None:
    flagship = json.loads(Path("evaluation/scenarios.json").read_text(encoding="utf-8"))[
        "flagship"
    ]
    affected = set(flagship["ground_truth"]["affected"])
    assets = [
        AssetPolicyContext(
            urn=make_dataset_urn("polymer_rnd", asset["name"], "PROD"),
            name=asset["name"],
            role=asset["role"],
            criticality=asset["criticality"],
            affected=asset["name"] in affected,
        )
        for asset in flagship["assets"]
    ]

    plan = decide(
        load_profile("polymer"),
        "inc-policy",
        assets,
        root_cause_evidence_ids=["e-lineage", "e-unit"],
    )
    actual = {item.name: item for item in plan.decisions}
    assert {name: item.decision.value for name, item in actual.items()} == {
        asset["name"]: asset["expected_decision"] for asset in flagship["assets"]
    }
    assert {name: item.catalog_status.value for name, item in actual.items()} == {
        asset["name"]: asset["expected_catalog_status"] for asset in flagship["assets"]
    }
    assert {name: [action.value for action in item.actions] for name, item in actual.items()} == {
        asset["name"]: asset["enforcement_actions"] for asset in flagship["assets"]
    }
    assert actual["candidate_ranking_report"].decision is PolicyDecision.HALT
    assert actual["formulation_report"].decision is PolicyDecision.ALLOW
    assert all(item.evidence_ids == ["e-lineage", "e-unit"] for item in plan.decisions)


def test_unaffected_assets_are_allowed_regardless_of_criticality() -> None:
    plan = decide(
        load_profile("polymer"),
        "inc-safe",
        [
            AssetPolicyContext(
                urn="urn:safe", name="safe_model", role="model", criticality="CRITICAL",
                affected=False
            )
        ],
        root_cause_evidence_ids=["e-safe"],
    )
    assert plan.decisions[0].decision is PolicyDecision.ALLOW
    assert plan.decisions[0].actions == []
