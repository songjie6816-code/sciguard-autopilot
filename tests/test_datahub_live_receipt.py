import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_curated_live_datahub_receipt_proves_native_entities_and_lifecycle() -> None:
    receipt_path = ROOT / "examples/outputs/datahub_live_receipt.json"
    web_path = ROOT / "web/public/evidence/datahub_live_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert receipt["capture_type"] == "LIVE_DATAHUB_END_TO_END_CLOSURE"
    assert receipt["incident_id"] == "inc-sciguard-b042-unit-contract"
    assert receipt["source_worktree_dirty"] is False
    assert receipt["public_projection"]["canonical_single_run"] is True
    assert receipt["public_projection"]["decision_fields_redacted"] is False
    assert receipt["server_version"] == "v1.5.0.6"
    assert receipt["cli_version"] == "1.6.0.15"
    assert receipt["all_verified"] is True
    assert receipt["entity_count"] == 19
    assert receipt["entity_counts"] == {
        "DataProcessInstance": 4,
        "MLFeature": 7,
        "MLFeatureTable": 2,
        "MLModel": 2,
        "MLModelDeployment": 2,
        "MLModelGroup": 2,
    }
    assert len(receipt["native_model_context"]) == 2
    assert {item["affected"] for item in receipt["native_model_context"]} == {
        True,
        False,
    }
    assert receipt["incident_lifecycle"]["readback_state"] == "RESOLVED"
    assert receipt["incident_lifecycle"]["readback_stage"] == "FIXED"
    assert receipt["incident_lifecycle"]["resolved"]["notes_written"] is False
    assert receipt["incident_lifecycle"]["resolved"]["notes_capability"] == (
        "STATUS_MESSAGE_FALLBACK_SERVER_SCHEMA"
    )
    assert receipt["decision_log_lifecycle"]["readback_state"] == "PUBLISHED"
    assert receipt["decision_log_lifecycle"]["related_asset_count"] == 11
    lifecycle = receipt["repair_lifecycle"]
    assert lifecycle["status"] == "APPLIED"
    assert lifecycle["change_provider"] == "GITHUB"
    assert lifecycle["remote_pull_request_claimed"] is True
    assert lifecycle["identity_assurance"] == "DEMO_SIGNED_NOT_SSO"
    assert lifecycle["approval_production_authorized"] is False
    assert lifecycle["application_environment"] == "SCIGUARD_SYNTHETIC_STAGING"
    assert lifecycle["application_production_authorized"] is False
    assert len(lifecycle["recovery_verification_receipts"]) == 2
    assert [result["clean_run_count"] for result in lifecycle["recovery_results"]] == [
        1,
        2,
    ]
    assert lifecycle["recovery_results"][0]["resume_allowed"] is False
    assert lifecycle["recovery_results"][1]["resume_allowed"] is True
    assert set(
        receipt["decision_log_lifecycle"]["required_receipts_present"]
    ) == {
        "commit_sha",
        "verification_receipt_id",
        "approval_receipt_id",
        "application_receipt_id",
        "recovery_verification_receipt_id",
    }
    assert web_path.read_bytes() == receipt_path.read_bytes()
