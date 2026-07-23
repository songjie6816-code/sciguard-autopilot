"""Publish through the real LocalPipelineController.

By default control state is loaded from DataHub. ``--policy-plan`` is an explicit
offline/test path; it applies the same controller and is never presented as live DataHub.
Blocked publication exits with code 42 and prints the incident ID as JSON.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from datahub.emitter.mce_builder import make_dataset_urn

from core.pipeline_controller import LocalPipelineController
from core.policy_engine import PolicyPlan
from datahub_client.metadata_reader import connect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", default="candidate_ranking_report")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--policy-plan", type=Path)
    args = parser.parse_args(argv)

    if args.policy_plan:
        plan = PolicyPlan.model_validate_json(args.policy_plan.read_text(encoding="utf-8"))
        controller = LocalPipelineController(plan)
    else:
        graph = connect()
        urn = make_dataset_urn("polymer_rnd", args.asset, "PROD")
        controller = LocalPipelineController.from_datahub(graph, urn)

    result = controller.publish(args.asset, args.source, args.target)
    print(result.model_dump_json())
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
