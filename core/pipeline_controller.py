"""Bounded local execution controls backed by deterministic policy decisions."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from datahub.metadata.schema_classes import DatasetPropertiesClass
from pydantic import BaseModel

from core.policy_engine import (
    AssetPolicyDecision,
    CatalogStatus,
    EnforcementAction,
    PolicyDecision,
    PolicyPlan,
)

BLOCKED_EXIT_CODE = 42


class PipelineResult(BaseModel):
    asset_name: str
    operation: str
    executed: bool
    would_block: bool
    exit_code: int
    incident_id: str | None
    message: str


class LocalPipelineController:
    """Actually block or execute local model/report operations only."""

    def __init__(self, plan: PolicyPlan) -> None:
        self.plan = plan
        self._decisions = {item.name: item for item in plan.decisions}

    def decision_for(self, asset_name: str) -> AssetPolicyDecision:
        try:
            return self._decisions[asset_name]
        except KeyError as exc:
            raise KeyError(f"no policy decision exists for asset '{asset_name}'") from exc

    def publish(self, asset_name: str, source: str | Path, target: str | Path) -> PipelineResult:
        decision = self.decision_for(asset_name)
        blocked = EnforcementAction.BLOCK_PUBLISH in decision.actions
        if blocked:
            return PipelineResult(
                asset_name=asset_name,
                operation="PUBLISH",
                executed=False,
                would_block=True,
                exit_code=BLOCKED_EXIT_CODE,
                incident_id=self.plan.incident_id,
                message=f"BLOCKED by SciGuard incident {self.plan.incident_id}",
            )
        source_path, target_path = Path(source), Path(target)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target_path)
        return PipelineResult(
            asset_name=asset_name,
            operation="PUBLISH",
            executed=True,
            would_block=False,
            exit_code=0,
            incident_id=self.plan.incident_id,
            message="Published by LocalPipelineController",
        )

    def execute(self, asset_name: str, operation: Callable[[], None]) -> PipelineResult:
        decision = self.decision_for(asset_name)
        blocked = EnforcementAction.BLOCK_EXECUTION in decision.actions
        if blocked:
            return PipelineResult(
                asset_name=asset_name,
                operation="EXECUTE",
                executed=False,
                would_block=True,
                exit_code=BLOCKED_EXIT_CODE,
                incident_id=self.plan.incident_id,
                message=f"BLOCKED by SciGuard incident {self.plan.incident_id}",
            )
        operation()
        return PipelineResult(
            asset_name=asset_name,
            operation="EXECUTE",
            executed=True,
            would_block=False,
            exit_code=0,
            incident_id=self.plan.incident_id,
            message="Executed by LocalPipelineController",
        )

    @classmethod
    def from_datahub(cls, graph, urn: str) -> LocalPipelineController:
        """Start a fresh controller from persisted DataHub control state."""

        aspect = graph.get_aspect(urn, DatasetPropertiesClass)
        if aspect is None:
            raise LookupError(f"no DataHub properties found for {urn}")
        props = dict(aspect.customProperties or {})
        required = {
            "sciguard:incident_id",
            "sciguard:policy_decision",
            "sciguard:catalog_status",
            "sciguard:enforcement_actions",
        }
        missing = required - props.keys()
        if missing:
            raise LookupError(f"DataHub control state is incomplete: {sorted(missing)}")
        name = aspect.name or urn
        decision = AssetPolicyDecision(
            urn=urn,
            name=name,
            role=props.get("entity_role", "unknown"),
            criticality=props.get("sciguard:criticality", "UNKNOWN"),
            affected=props["sciguard:catalog_status"] not in {"HEALTHY", "RESOLVED"},
            decision=PolicyDecision(props["sciguard:policy_decision"]),
            catalog_status=CatalogStatus(props["sciguard:catalog_status"]),
            actions=[
                EnforcementAction(action)
                for action in json.loads(props["sciguard:enforcement_actions"])
            ],
            reason_code=props.get("sciguard:reason_code", "PERSISTED_CONTROL_STATE"),
            evidence_ids=json.loads(props.get("sciguard:evidence_ids", "[]")),
        )
        return cls(
            PolicyPlan(incident_id=props["sciguard:incident_id"], decisions=[decision])
        )


class DryRunPipelineController(LocalPipelineController):
    """Evaluate the same controls but never execute or block a process."""

    def publish(self, asset_name: str, source: str | Path, target: str | Path) -> PipelineResult:
        decision = self.decision_for(asset_name)
        would_block = EnforcementAction.BLOCK_PUBLISH in decision.actions
        return PipelineResult(
            asset_name=asset_name,
            operation="PUBLISH_DRY_RUN",
            executed=False,
            would_block=would_block,
            exit_code=0,
            incident_id=self.plan.incident_id,
            message=("Would block publish" if would_block else "Would allow publish"),
        )

    def execute(self, asset_name: str, operation: Callable[[], None]) -> PipelineResult:
        decision = self.decision_for(asset_name)
        would_block = EnforcementAction.BLOCK_EXECUTION in decision.actions
        return PipelineResult(
            asset_name=asset_name,
            operation="EXECUTE_DRY_RUN",
            executed=False,
            would_block=would_block,
            exit_code=0,
            incident_id=self.plan.incident_id,
            message=("Would block execution" if would_block else "Would allow execution"),
        )
