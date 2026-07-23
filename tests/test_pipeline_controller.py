from pathlib import Path
import subprocess

from core.pipeline_controller import DryRunPipelineController, LocalPipelineController
from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)


def _plan() -> PolicyPlan:
    return PolicyPlan(
        incident_id="inc-control",
        decisions=[
            AssetPolicyDecision(
                urn="urn:ranking",
                name="candidate_ranking_report",
                role="decision_report",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[EnforcementAction.BLOCK_PUBLISH],
                reason_code="AFFECTED_DECISION_REPORT",
                evidence_ids=["e-unit"],
            ),
            AssetPolicyDecision(
                urn="urn:model",
                name="tg_prediction_model",
                role="model",
                criticality="CRITICAL",
                affected=True,
                decision=PolicyDecision.HALT,
                catalog_status=CatalogStatus.AT_RISK,
                actions=[EnforcementAction.BLOCK_EXECUTION],
                reason_code="AFFECTED_MODEL",
                evidence_ids=["e-unit"],
            ),
            AssetPolicyDecision(
                urn="urn:formulation",
                name="formulation_report",
                role="report",
                criticality="HIGH",
                affected=False,
                decision=PolicyDecision.ALLOW,
                catalog_status=CatalogStatus.HEALTHY,
                actions=[],
                reason_code="UNAFFECTED_BRANCH",
                evidence_ids=["e-unit"],
            ),
        ],
    )


def test_local_controller_really_blocks_tg_publish_but_allows_mw(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("candidate,rank\nP-204,1\n", encoding="utf-8")
    controller = LocalPipelineController(_plan())

    blocked_target = tmp_path / "candidate_report.csv"
    blocked = controller.publish("candidate_ranking_report", source, blocked_target)
    assert blocked.exit_code == 42
    assert blocked.incident_id == "inc-control"
    assert not blocked.executed
    assert not blocked_target.exists()

    allowed_target = tmp_path / "formulation_report.csv"
    allowed = controller.publish("formulation_report", source, allowed_target)
    assert allowed.exit_code == 0
    assert allowed.executed
    assert allowed_target.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_dry_run_never_writes_even_when_policy_would_allow(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("safe", encoding="utf-8")
    target = tmp_path / "target.csv"
    result = DryRunPipelineController(_plan()).publish("formulation_report", source, target)
    assert result.exit_code == 0
    assert not result.executed
    assert not result.would_block
    assert not target.exists()


def test_model_execution_callback_is_not_called_when_blocked() -> None:
    calls = []
    result = LocalPipelineController(_plan()).execute(
        "tg_prediction_model", lambda: calls.append("executed")
    )
    assert result.exit_code == 42
    assert calls == []


def test_blocked_publish_process_returns_nonzero_and_incident_id(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("candidate,rank\nP-204,1\n", encoding="utf-8")
    target = tmp_path / "published.csv"
    plan_path = tmp_path / "policy.json"
    plan_path.write_text(_plan().model_dump_json(), encoding="utf-8")
    completed = subprocess.run(
        [
            ".venv/bin/python3.11",
            "-m",
            "examples.publish_candidate_report",
            "--source",
            str(source),
            "--target",
            str(target),
            "--policy-plan",
            str(plan_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 42
    assert '"incident_id":"inc-control"' in completed.stdout
    assert not target.exists()
