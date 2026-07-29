import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
INCIDENT = "inc-sciguard-b042-unit-contract"


def test_canonical_repair_capture_closes_one_incident_and_is_honestly_bounded() -> None:
    replay = ROOT / "examples" / "replays" / INCIDENT
    web_replay = ROOT / "web" / "public" / "replays" / INCIDENT
    raw_events = (replay / "events.jsonl").read_bytes()
    raw_bundle = (replay / "repair-bundle.json").read_bytes()
    manifest = json.loads((replay / "repair-manifest.json").read_text())
    bundle = json.loads(raw_bundle)

    assert hashlib.sha256(raw_events).hexdigest() == manifest["source_events_sha256"]
    assert hashlib.sha256(raw_bundle).hexdigest() == manifest["repair_bundle_sha256"]
    replay_manifest = json.loads((replay / "manifest.json").read_text())
    datahub_receipt_path = ROOT / "examples" / "outputs" / "datahub_live_receipt.json"
    evaluation_report_path = ROOT / "examples" / "outputs" / "evaluation_report.json"
    github_receipt_path = ROOT / "examples" / "outputs" / "github_live_evidence.json"
    datahub_receipt = json.loads(datahub_receipt_path.read_text())
    github_receipt = json.loads(github_receipt_path.read_text())
    events = [
        json.loads(line)
        for line in raw_events.decode("utf-8").splitlines()
        if line
    ]

    assert manifest["capture_type"] == "RECORDED_DATAHUB_END_TO_END"
    assert manifest["canonical_single_run"] is True
    assert manifest["source_incident_id"] == INCIDENT
    assert manifest["clean_run_count"] == 2
    assert replay_manifest["incident_id"] == INCIDENT
    assert replay_manifest["incident_state"] == "RESOLVED"
    assert replay_manifest["source_worktree_dirty"] is False
    assert manifest["source_worktree_dirty"] is False
    assert datahub_receipt["source_worktree_dirty"] is False
    assert {
        replay_manifest["source_commit"],
        manifest["source_commit"],
        datahub_receipt["source_commit"],
    } == {manifest["source_commit"]}
    assert hashlib.sha256(datahub_receipt_path.read_bytes()).hexdigest() == (
        manifest["datahub_native_receipt_sha256"]
    )
    assert hashlib.sha256(evaluation_report_path.read_bytes()).hexdigest() == (
        manifest["evaluation_report_sha256"]
    )
    assert hashlib.sha256(github_receipt_path.read_bytes()).hexdigest() == (
        manifest["github_live_evidence_sha256"]
    )
    assert replay_manifest["event_count"] == len(events) == 55
    assert {event["incident_id"] for event in events} == {INCIDENT}
    assert sum(
        event["event_type"] == "RECOVERY_EVIDENCE_REFRESHED" for event in events
    ) == 2
    assert any(event["event_type"] == "REPAIR_APPLIED" for event in events)
    assert any(event["event_type"] == "INCIDENT_RESOLVED" for event in events)
    published_event = next(
        event for event in events if event["event_type"] == "REPAIR_PUBLISHED"
    )
    assert published_event["payload"]["external_action_receipt"]["provider"] == "GITHUB"
    assert published_event["payload"]["external_action_receipt"]["pull_request_number"] == 2
    assert bundle["status"] == "APPLIED"
    assert bundle["external_action_receipt"]["provider"] == "GITHUB"
    assert bundle["external_action_receipt"]["remote_url"].startswith(
        "https://github.com/songjie6816-code/sciguard-repair-sandbox/pull/"
    )
    assert bundle["external_action_receipt"]["pull_request_number"] > 1
    assert bundle["external_action_receipt"]["repository"] == (
        "https://github.com/songjie6816-code/sciguard-repair-sandbox"
    )
    assert bundle["verification_receipt"]["commit_sha"] == (
        bundle["external_action_receipt"]["commit_sha"]
    )
    assert [check["status"] for check in bundle["verification_receipt"]["checks"]] == [
        "PASS",
        "PASS",
        "PASS",
    ]
    assert bundle["approval_receipt"]["identity_assurance"] == "DEMO_SIGNED_NOT_SSO"
    assert bundle["approval_receipt"]["production_authorized"] is False
    assert bundle["application_receipt"]["status"] == "APPLIED"
    assert bundle["application_receipt"]["target_environment"] == (
        "SCIGUARD_SYNTHETIC_STAGING"
    )
    assert bundle["application_receipt"]["production_authorized"] is False
    assert bundle["application_receipt"]["commit_sha"] == (
        bundle["external_action_receipt"]["commit_sha"]
    )
    assert bundle["linked_capture"]["canonical_single_run"] is True
    assert bundle["linked_capture"]["source_incident_id"] == INCIDENT
    assert bundle["linked_capture"]["change_provider"] == "GITHUB"
    assert bundle["linked_capture"]["remote_pull_request_claimed"] is True
    assert bundle["linked_capture"]["github_live_evidence_sha256"] == (
        manifest["github_live_evidence_sha256"]
    )
    assert github_receipt["incident_id"] == INCIDENT
    assert github_receipt["bundle_id"] == bundle["bundle_id"]
    assert github_receipt["pull_request"]["number"] == 2
    assert github_receipt["pull_request"]["head_sha"] == (
        bundle["external_action_receipt"]["commit_sha"]
    )
    assert github_receipt["verification_receipt"]["receipt_id"] == (
        bundle["verification_receipt"]["receipt_id"]
    )
    assert github_receipt["approval_binding"]["receipt_id"] == (
        bundle["approval_receipt"]["receipt_id"]
    )
    assert set(github_receipt["canonical_bindings"].values()) == {
        INCIDENT,
        bundle["bundle_id"],
        bundle["external_action_receipt"]["commit_sha"],
    }
    assert (web_replay / "repair-bundle.json").read_bytes() == raw_bundle
    assert (web_replay / "repair-manifest.json").read_bytes() == (
        replay / "repair-manifest.json"
    ).read_bytes()
