"""Independent row-level checks over trusted and current synthetic artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from time import perf_counter_ns

from core.events import EventActor, EventRecorder, EventType
from core.investigation_models import Evidence, InvestigationCase, RealityCheckResult


def _read_csv(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row[key]: row for row in csv.DictReader(handle)}


class RealityChecker:
    """Validate scientific facts without calling or trusting the DataHub worker."""

    REQUIRED = (
        "trusted_polymer_baseline.csv",
        "raw_polymer_experiments.csv",
        "candidate_ranking_before.csv",
        "candidate_ranking_after.csv",
        "trusted_release_manifest.json",
    )

    def __init__(self, data_dir: str | Path, recorder: EventRecorder | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.recorder = recorder

    def check(self, case: InvestigationCase) -> RealityCheckResult:
        start = perf_counter_ns()
        missing = [name for name in self.REQUIRED if not (self.data_dir / name).is_file()]
        if missing:
            evidence = Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="ARTIFACTS_UNAVAILABLE",
                summary="Required trusted/current artifacts are missing",
                payload={"missing": missing},
            )
            self._emit_observation([evidence], start, "Reality check degraded")
            return RealityCheckResult(
                available=False,
                evidence=[evidence],
                degraded_reason=f"missing trusted/current artifacts: {', '.join(missing)}",
            )
        try:
            baseline = _read_csv(self.data_dir / "trusted_polymer_baseline.csv", "sample_id")
            current = _read_csv(self.data_dir / "raw_polymer_experiments.csv", "sample_id")
            before = _read_csv(self.data_dir / "candidate_ranking_before.csv", "candidate_id")
            after = _read_csv(self.data_dir / "candidate_ranking_after.csv", "candidate_id")
            manifest = json.loads(
                (self.data_dir / "trusted_release_manifest.json").read_text(encoding="utf-8")
            )
            if case.candidate_id not in before or case.candidate_id not in after:
                raise ValueError(f"candidate {case.candidate_id} is absent from ranking artifacts")
        except (OSError, ValueError, KeyError) as exc:
            evidence = Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="ARTIFACT_VALIDATION_FAILED",
                summary="Trusted/current artifacts could not be validated",
                payload={"error_type": type(exc).__name__, "error": str(exc)},
            )
            self._emit_observation([evidence], start, "Reality check degraded")
            return RealityCheckResult(
                available=False,
                evidence=[evidence],
                degraded_reason=f"artifact validation failed: {type(exc).__name__}: {exc}",
            )

        current_rank = after[case.candidate_id]
        trusted_rank = before[case.candidate_id]
        rank_payload = {
            "candidate_id": case.candidate_id,
            "rank_before": int(trusted_rank["rank"]),
            "rank_after": int(current_rank["rank"]),
            "pipeline_status": current_rank["pipeline_status"],
            "symptom_matches_artifacts": (
                int(trusted_rank["rank"]) == case.rank_before
                and int(current_rank["rank"]) == case.rank_after
            ),
        }

        drifted = [
            row
            for sample_id, row in current.items()
            if sample_id in baseline and row["tg_unit"] != baseline[sample_id]["tg_unit"]
        ]
        affected_ids = {row["sample_id"] for row in drifted}
        expected_unit = manifest["scientific_contract"]["expected_tg_unit"]
        units = {row["tg_unit"] for row in current.values()}
        unit_payload = {
            "contract_passed": not drifted,
            "affected_rows": len(drifted),
            "affected_batches": sorted({row["batch_id"] for row in drifted}),
            "expected_unit": expected_unit,
            "observed_units": [expected_unit, *sorted(units - {expected_unit})],
            "trusted_firmware": sorted(
                {baseline[sample_id]["instrument_firmware"] for sample_id in affected_ids}
            ),
            "current_firmware": sorted({row["instrument_firmware"] for row in drifted}),
            "normalization_versions": sorted({row["normalization_version"] for row in drifted}),
        }

        deltas: dict[str, float] = {}
        for sample_id in affected_ids:
            row = current[sample_id]
            converted = float(row["tg_value"]) - 273.15 if row["tg_unit"] == "K" else float(
                row["tg_value"]
            )
            deltas[sample_id] = round(converted - float(baseline[sample_id]["tg_value"]), 6)
        experiment_payload = {
            "checked_rows": len(deltas),
            "all_converted_values_match_baseline": all(abs(delta) <= 1e-6 for delta in deltas.values()),
            "candidate_true_delta_degc": deltas.get(case.candidate_id),
        }
        release_payload = dict(manifest["trusted_release"])

        evidence = [
            Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="RANK_BASELINE_COMPARISON",
                summary=f"Verified {case.candidate_id} rank against trusted and current outputs",
                payload=rank_payload,
            ),
            Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="UNIT_FIRMWARE_CONTRACT",
                summary=f"Found {len(drifted)} rows violating the Tg unit contract",
                payload=unit_payload,
            ),
            Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="EXPERIMENTAL_VALUE_CHECK",
                summary="Converted current measurements to the trusted scientific unit",
                payload=experiment_payload,
            ),
            Evidence.create(
                source="LOCAL_ARTIFACT",
                kind="TRUSTED_RELEASE_BASELINE",
                summary="Loaded independently versioned trusted release manifest",
                payload=release_payload,
            ),
        ]
        self._emit_observation(evidence, start, "Independent reality checks completed")
        return RealityCheckResult(available=True, evidence=evidence)

    def _emit_observation(
        self, evidence: list[Evidence], start_ns: int, summary: str
    ) -> None:
        if not self.recorder:
            return
        self.recorder.emit(
            actor=EventActor.REALITY_CHECKER,
            event_type=EventType.EVIDENCE_OBSERVED,
            summary=summary,
            evidence_ids=[item.evidence_id for item in evidence],
            duration_ms=max(0, (perf_counter_ns() - start_ns) // 1_000_000),
            payload={"evidence": [item.model_dump(mode="json") for item in evidence]},
        )
